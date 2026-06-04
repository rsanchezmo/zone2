"""Garmin intraday-volatility probe — does each per-day metric keep changing
through the day, or does it settle once (computed overnight)?

This answers the question behind the sync optimization: which metrics are worth
force-refetching on the 6h auto-sync (intraday) vs. fetch-once-then-skip (stable).

How it works
------------
Each run fetches TODAY's payload for every per-day metric, then diffs it against
the most recent earlier snapshot from the SAME calendar day and reports what
changed. Run it 2-3 times across a day (e.g. morning, midday, evening) and the
final run prints a verdict per metric:

    INTRADAY     numeric fields changed between runs        -> force-refetch today
    NOISE-ONLY   only timestamp-ish strings changed         -> treat as STABLE
    STABLE       byte-identical across every run today       -> fetch-once, skip

Snapshots are saved under .strava/garmin/probe/<metric>/<date>T<HHMMSS>.json so
the diff survives across separate process runs.

Usage (run the SAME command at 2-3 points in one day):
    python scripts/garmin_intraday_probe.py
    python scripts/garmin_intraday_probe.py --date 2026-06-04   # pin a day
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
TOKEN_DIR = REPO_ROOT / ".strava" / "garmin"
PROBE_DIR = TOKEN_DIR / "probe"

os.environ.setdefault("GARMINTOKENS", str(TOKEN_DIR))
load_dotenv(REPO_ROOT / ".env")

try:
    from garminconnect import Garmin  # noqa: E402
except ImportError:
    print("ERROR: `garminconnect` not installed. Run: poetry add garminconnect curl-cffi")
    sys.exit(1)

# The 10 per-day metrics the real sync fetches (strava/garmin_client.py).
# training_readiness is special-cased: the API returns a list of intraday
# snapshots, so it's intraday by construction — we still probe it to confirm.
METRICS_PER_DAY: list[tuple[str, callable]] = [
    ("user_summary",       lambda c, d: c.get_user_summary(d)),
    ("sleep",              lambda c, d: c.get_sleep_data(d)),
    ("hrv",                lambda c, d: c.get_hrv_data(d)),
    ("training_readiness", lambda c, d: c.get_training_readiness(d)),
    ("training_status",    lambda c, d: c.get_training_status(d)),
    ("stress",             lambda c, d: c.get_stress_data(d)),
    ("heart_rates",        lambda c, d: c.get_heart_rates(d)),
    ("spo2",               lambda c, d: c.get_spo2_data(d)),
    ("respiration",        lambda c, d: c.get_respiration_data(d)),
    ("intensity_minutes",  lambda c, d: c.get_intensity_minutes_data(d)),
]

# Substrings that mark a key as a server/sync timestamp rather than real data.
# Changes confined to these are "noise" — the underlying metric didn't move.
_TIMESTAMP_HINTS = ("timestamp", "lastupdated", "lastsync", "uploaded", "fetchtime")


def _is_timestamp_key(key: str) -> bool:
    k = key.lower()
    return any(h in k for h in _TIMESTAMP_HINTS)


def _diff(old, new, path: str = "") -> list[tuple[str, str, object, object]]:
    """Recursive diff. Returns (kind, path, old_val, new_val) where kind is
    'num' (numeric field moved), 'ts' (timestamp-ish key) or 'other'."""
    out: list[tuple[str, str, object, object]] = []
    if isinstance(old, dict) and isinstance(new, dict):
        for k in sorted(set(old) | set(new)):
            child = f"{path}.{k}" if path else k
            if k not in old or k not in new:
                kind = "ts" if _is_timestamp_key(k) else "other"
                out.append((kind, child, old.get(k, "<absent>"), new.get(k, "<absent>")))
            else:
                out.extend(_diff(old[k], new[k], child))
    elif isinstance(old, list) and isinstance(new, list):
        if len(old) != len(new):
            out.append(("other", f"{path}[len]", len(old), len(new)))
        for i in range(min(len(old), len(new))):
            out.extend(_diff(old[i], new[i], f"{path}[{i}]"))
    elif old != new:
        leaf = path.rsplit(".", 1)[-1].split("[", 1)[0]
        if _is_timestamp_key(leaf):
            kind = "ts"
        elif isinstance(old, (int, float)) and isinstance(new, (int, float)):
            kind = "num"
        else:
            kind = "other"
        out.append((kind, path, old, new))
    return out


def _snapshots_for(metric: str, day: str) -> list[Path]:
    d = PROBE_DIR / metric
    if not d.exists():
        return []
    return sorted(d.glob(f"{day}T*.json"))


def _classify(diffs: list[tuple]) -> str:
    if not diffs:
        return "STABLE"
    kinds = {k for k, *_ in diffs}
    if "num" in kinds or "other" in kinds:
        return "INTRADAY"
    return "NOISE-ONLY"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat(),
                        help="Day to probe (ISO, default today).")
    parser.add_argument("--sleep-ms", type=int, default=300)
    parser.add_argument("--max-diffs", type=int, default=6,
                        help="Max changed fields to print per metric.")
    args = parser.parse_args()

    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    if not email or not password:
        print("ERROR: GARMIN_EMAIL and GARMIN_PASSWORD must be set in .env")
        return 1

    day = args.date
    now = datetime.now()
    stamp = now.strftime("%Y-%m-%dT%H%M%S")
    print(f"Logging in as {email} (cached token: {TOKEN_DIR}) ...")
    client = Garmin(email, password, prompt_mfa=lambda: input("Garmin MFA code: ").strip())
    try:
        client.login(str(TOKEN_DIR))
    except Exception as e:
        print(f"Login failed: {e}")
        return 2
    print(f"Logged in. Probing {len(METRICS_PER_DAY)} metrics for {day} at {now:%H:%M:%S}\n")

    verdicts: dict[str, str] = {}
    for metric, fn in METRICS_PER_DAY:
        prev_paths = _snapshots_for(metric, day)
        try:
            payload = fn(client, day)
        except Exception as e:
            print(f"  {metric:20} FETCH FAILED: {type(e).__name__}: {e}")
            time.sleep(args.sleep_ms / 1000)
            continue

        # save this snapshot
        out_dir = PROBE_DIR / metric
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{stamp}.json").write_text(json.dumps(payload, indent=2, default=str))

        if not prev_paths:
            print(f"  {metric:20} baseline saved (no earlier snapshot today)")
            verdicts[metric] = "BASELINE"
            time.sleep(args.sleep_ms / 1000)
            continue

        prev = json.loads(prev_paths[-1].read_text())
        prev_when = prev_paths[-1].stem.split("T", 1)[-1]
        diffs = _diff(prev, payload)
        verdict = _classify(diffs)
        verdicts[metric] = verdict
        nums = sum(1 for k, *_ in diffs if k == "num")
        print(f"  {metric:20} {verdict:10} vs {prev_when}  "
              f"({len(diffs)} fields changed, {nums} numeric)")
        for kind, p, ov, nv in diffs[:args.max_diffs]:
            tag = {"num": "#", "ts": "t", "other": "*"}[kind]
            print(f"      {tag} {p}: {ov!r} -> {nv!r}")
        if len(diffs) > args.max_diffs:
            print(f"      ... +{len(diffs) - args.max_diffs} more")
        time.sleep(args.sleep_ms / 1000)

    print("\n=== Verdict (this run vs previous snapshot today) ===")
    print("  INTRADAY  -> force-refetch on auto-sync   "
          "NOISE-ONLY/STABLE -> fetch once, then skip\n")
    for metric, _ in METRICS_PER_DAY:
        v = verdicts.get(metric, "?")
        print(f"  {metric:20} {v}")
    print("\nRun this again later today to populate the diff. "
          f"Snapshots: {PROBE_DIR.relative_to(REPO_ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())

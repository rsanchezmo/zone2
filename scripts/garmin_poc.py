"""Garmin Connect POC — fetch one day (or --days N) of every candidate metric
and dump payloads to .strava/garmin/poc/<metric>/<date>.json for inspection.

Throwaway: this is for validating which methods return real data on the
user's watch before designing the real integration.

Usage:
    python scripts/garmin_poc.py            # yesterday only
    python scripts/garmin_poc.py --days 7   # last 7 days
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
TOKEN_DIR = REPO_ROOT / ".strava" / "garmin"
DUMP_DIR = TOKEN_DIR / "poc"

# Point garminconnect's token cache into the existing workdir before importing
# the lib so it picks up the env var on first use.
os.environ.setdefault("GARMINTOKENS", str(TOKEN_DIR))

load_dotenv(REPO_ROOT / ".env")

try:
    from garminconnect import Garmin  # noqa: E402
except ImportError:
    print("ERROR: `garminconnect` not installed. Run: poetry add garminconnect curl-cffi")
    sys.exit(1)


# (label, callable). Each callable takes (client, iso_date) and returns the raw payload.
METRICS: list[tuple[str, callable]] = [
    ("user_summary",       lambda c, d: c.get_user_summary(d)),
    ("stats_and_body",     lambda c, d: c.get_stats_and_body(d)),
    ("heart_rates",        lambda c, d: c.get_heart_rates(d)),
    ("rhr_day",            lambda c, d: c.get_rhr_day(d)),
    ("sleep",              lambda c, d: c.get_sleep_data(d)),
    ("stress",             lambda c, d: c.get_stress_data(d)),
    ("all_day_stress",     lambda c, d: c.get_all_day_stress(d)),
    ("body_battery",       lambda c, d: c.get_body_battery(d, d)),
    ("body_battery_events", lambda c, d: c.get_body_battery_events(d)),
    ("hrv",                lambda c, d: c.get_hrv_data(d)),
    ("training_readiness", lambda c, d: c.get_training_readiness(d)),
    ("training_status",    lambda c, d: c.get_training_status(d)),
    ("spo2",               lambda c, d: c.get_spo2_data(d)),
    ("respiration",        lambda c, d: c.get_respiration_data(d)),
    ("steps_intraday",     lambda c, d: c.get_steps_data(d)),
    ("daily_steps",        lambda c, d: c.get_daily_steps(d, d)),
    ("floors",             lambda c, d: c.get_floors(d)),
    ("intensity_minutes",  lambda c, d: c.get_intensity_minutes_data(d)),
    ("body_composition",   lambda c, d: c.get_body_composition(d, d)),
    ("max_metrics",        lambda c, d: c.get_max_metrics(d)),
]


def summarize(payload) -> str:
    """One-line description of a payload for the terminal."""
    if payload is None:
        return "None"
    if isinstance(payload, list):
        if not payload:
            return "[] (empty)"
        first = payload[0]
        if isinstance(first, dict):
            return f"list[{len(payload)}] dicts, first keys: {sorted(first.keys())[:8]}"
        return f"list[{len(payload)}] {type(first).__name__}s, sample: {first!r}"
    if isinstance(payload, dict):
        keys = sorted(payload.keys())
        return f"dict, {len(keys)} keys: {keys[:10]}{'...' if len(keys) > 10 else ''}"
    return f"{type(payload).__name__}: {payload!r}"


def dump(payload, metric: str, cdate: str) -> Path:
    out_dir = DUMP_DIR / metric
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{cdate}.json"
    with out.open("w") as f:
        json.dump(payload, f, indent=2, default=str)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=1,
                        help="How many days back from yesterday to fetch (default 1).")
    parser.add_argument("--sleep-ms", type=int, default=300,
                        help="Delay between API calls in ms (default 300).")
    args = parser.parse_args()

    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    if not email or not password:
        print("ERROR: GARMIN_EMAIL and GARMIN_PASSWORD must be set in .env")
        return 1

    TOKEN_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Logging in as {email} ... (MFA prompt on first run; cached afterwards)")
    client = Garmin(email, password, prompt_mfa=lambda: input("Garmin MFA code: ").strip())
    try:
        client.login(str(TOKEN_DIR))
    except Exception as e:
        print(f"Login failed: {e}")
        return 2
    print("Logged in.\n")

    # Iterate from oldest to newest so the JSON file timestamps make sense
    today = date.today()
    dates = [(today - timedelta(days=i)).isoformat() for i in range(args.days, 0, -1)]
    print(f"Fetching {len(METRICS)} metrics for {len(dates)} day(s): {dates[0]} ... {dates[-1]}\n")

    overall_t0 = time.monotonic()
    results: dict[str, dict[str, str]] = {}

    for cdate in dates:
        print(f"=== {cdate} ===")
        per_day = {}
        for metric, fn in METRICS:
            t0 = time.monotonic()
            try:
                payload = fn(client, cdate)
                elapsed = time.monotonic() - t0
                summary = summarize(payload)
                path = dump(payload, metric, cdate)
                per_day[metric] = f"OK ({elapsed*1000:.0f}ms) — {summary}"
                print(f"  {metric:22} {elapsed*1000:5.0f}ms  {summary}")
                print(f"  {' ':22}        -> {path.relative_to(REPO_ROOT)}")
            except Exception as e:
                elapsed = time.monotonic() - t0
                per_day[metric] = f"FAIL ({elapsed*1000:.0f}ms) — {type(e).__name__}: {e}"
                print(f"  {metric:22} {elapsed*1000:5.0f}ms  FAIL: {type(e).__name__}: {e}")
            time.sleep(args.sleep_ms / 1000)
        results[cdate] = per_day
        print()

    total = time.monotonic() - overall_t0
    print(f"Done in {total:.1f}s. Payloads under {DUMP_DIR.relative_to(REPO_ROOT)}/")

    # Quick verdict: which metrics worked at least once?
    print("\n=== Per-metric verdict (across all days) ===")
    for metric, _ in METRICS:
        statuses = [results[d][metric] for d in dates]
        n_ok = sum(1 for s in statuses if s.startswith("OK"))
        verdict = "WORKS" if n_ok == len(dates) else ("PARTIAL" if n_ok else "FAILS")
        print(f"  {metric:22} {verdict:8} ({n_ok}/{len(dates)} days)")

    return 0


if __name__ == "__main__":
    sys.exit(main())

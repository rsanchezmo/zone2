"""iCalendar (RFC 5545) feed builder for training sessions and race events.

The feed is subscribed to by Google Calendar / Apple Calendar so planned
sessions appear on the user's phone — and from there on a paired Garmin
watch via its Calendar glance.

All events are all-day (VALUE=DATE) since sessions and races in this app
are day-scoped.
"""
from __future__ import annotations

import json
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

import aiosqlite

from backend.config import settings
from backend.services.zones import get_setting, set_setting

FEED_TOKEN_KEY = "calendar_feed_token"
LAST_FETCH_KEY = "calendar_feed_last_fetched_at"
PRODID = "-//z2//Calendar Feed//EN"


def is_env_managed() -> bool:
    """True when STRAVA_WEB_CALENDAR_FEED_TOKEN is set. In that case the
    token is pinned via env and UI rotation is disabled."""
    return bool(settings.calendar_feed_token)


async def get_or_create_token(db: aiosqlite.Connection) -> str:
    """Return the active feed token. If the env var is set, it wins and
    the DB is untouched. Otherwise lazily generate and persist one."""
    if settings.calendar_feed_token:
        return settings.calendar_feed_token
    token = await get_setting(db, FEED_TOKEN_KEY)
    if token:
        return token
    token = secrets.token_urlsafe(32)
    await set_setting(db, FEED_TOKEN_KEY, token)
    return token


async def rotate_token(db: aiosqlite.Connection) -> str:
    """Generate and persist a new DB token. Caller must ensure the env
    override is not active — see `is_env_managed()`."""
    token = secrets.token_urlsafe(32)
    await set_setting(db, FEED_TOKEN_KEY, token)
    return token


async def record_fetch(db: aiosqlite.Connection) -> None:
    """Stamp the last successful feed fetch so the UI can show whether a
    subscriber (usually Google) is actively polling."""
    await set_setting(db, LAST_FETCH_KEY, datetime.now(timezone.utc).isoformat())


async def get_last_fetched_at(db: aiosqlite.Connection) -> str | None:
    return await get_setting(db, LAST_FETCH_KEY)


def _escape_text(value: str) -> str:
    # RFC 5545 §3.3.11 TEXT escaping.
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold(line: str) -> str:
    # RFC 5545 §3.1: lines > 75 octets must be folded with CRLF + leading space.
    if len(line.encode("utf-8")) <= 75:
        return line
    out: list[str] = []
    remaining = line
    first = True
    while remaining:
        limit = 75 if first else 74
        encoded = remaining.encode("utf-8")
        if len(encoded) <= limit:
            out.append(remaining)
            break
        cut = limit
        while cut > 0 and (encoded[cut] & 0xC0) == 0x80:
            cut -= 1
        chunk = encoded[:cut].decode("utf-8")
        out.append(chunk)
        remaining = remaining[len(chunk):]
        first = False
    return "\r\n ".join(out)


def _date_compact(yyyy_mm_dd: str) -> str:
    return yyyy_mm_dd.replace("-", "")


def _next_day_compact(yyyy_mm_dd: str) -> str:
    d = date.fromisoformat(yyyy_mm_dd)
    return (d + timedelta(days=1)).strftime("%Y%m%d")


def _session_summary(session: dict) -> str:
    sport = session.get("sport_type") or "Session"
    dist = session.get("planned_distance_km")
    dur = session.get("planned_duration_mins")
    intensity = session.get("planned_intensity")
    bits = [f"[PLAN] {sport}"]
    if dist:
        bits.append(f"{dist:g}km")
    elif dur:
        bits.append(f"{int(dur)}min")
    if intensity:
        bits.append(f"({intensity})")
    return " ".join(bits)


_SEGMENT_TYPE_LABELS = {
    "warmup": "Warmup",
    "work": "Work",
    "recovery": "Recovery",
    "cooldown": "Cooldown",
    "rest": "Rest",
}


def _format_distance_km(km: float) -> str:
    return f"{km:g} km" if km >= 1 else f"{int(round(km * 1000))} m"


def _parse_segments(raw) -> list[dict] | None:
    if not raw:
        return None
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, list) and parsed else None
    return None


def _format_segment(seg: dict) -> str:
    type_key = seg.get("type") or ""
    label = _SEGMENT_TYPE_LABELS.get(type_key, type_key.capitalize() or "Segment")

    qty: str | None = None
    dist = seg.get("distance_km")
    dur = seg.get("duration_mins")
    if dist:
        qty = _format_distance_km(float(dist))
    elif dur:
        qty = f"{float(dur):g} min"

    targets: list[str] = []
    pmin = seg.get("target_pace_min")
    pmax = seg.get("target_pace_max")
    if pmin and pmax:
        targets.append(f"pace {pmin:.2f}–{pmax:.2f}")
    elif pmin:
        targets.append(f"pace {pmin:.2f}")
    if seg.get("target_hr_zone"):
        targets.append(f"Z{seg['target_hr_zone']}")

    body = label + (f" {qty}" if qty else "")
    if targets:
        body += " @ " + ", ".join(targets)

    reps = seg.get("repetitions") or 1
    line = f"{int(reps)}× {body}" if reps and reps > 1 else body

    rec_dur = seg.get("recovery_duration_mins")
    rec_dist = seg.get("recovery_distance_km")
    if rec_dur:
        line += f" (recovery {float(rec_dur):g} min)"
    elif rec_dist:
        line += f" (recovery {_format_distance_km(float(rec_dist))})"

    if seg.get("label"):
        line += f" — {seg['label']}"

    return line


def _session_description(session: dict) -> str:
    lines: list[str] = []

    title = session.get("title")
    if title:
        lines.append(str(title))

    if session.get("description"):
        lines.append(str(session["description"]))

    segments = _parse_segments(session.get("segments"))
    if segments:
        if lines:
            lines.append("")
        lines.append("Plan:")
        for seg in segments:
            lines.append(f"• {_format_segment(seg)}")

    # Skip the top-level "Planned:" line when segments are present — the
    # planned distance is auto-derived from segments and would just repeat.
    if not segments:
        plan_bits: list[str] = []
        if session.get("planned_distance_km"):
            plan_bits.append(f"{session['planned_distance_km']:g} km")
        if session.get("planned_duration_mins"):
            plan_bits.append(f"{int(session['planned_duration_mins'])} min")
        if plan_bits:
            lines.append("Planned: " + " · ".join(plan_bits))

    tgt: list[str] = []
    if session.get("target_avg_pace"):
        tgt.append(f"pace {session['target_avg_pace']:.2f}")
    pmin = session.get("target_pace_min")
    pmax = session.get("target_pace_max")
    if pmin and pmax:
        tgt.append(f"pace {pmin:.2f}–{pmax:.2f}")
    if session.get("target_hr_zone"):
        tgt.append(f"Z{session['target_hr_zone']}")
    if tgt:
        lines.append("Target: " + ", ".join(tgt))

    return "\n".join(lines)


def _race_summary(race: dict) -> str:
    name = race.get("name") or "Race"
    return f"[RACE] {name}"


def _race_description(race: dict) -> str:
    parts: list[str] = []
    if race.get("description"):
        parts.append(str(race["description"]))
    meta: list[str] = []
    if race.get("distance_km"):
        meta.append(f"{race['distance_km']:g} km")
    if race.get("location"):
        meta.append(str(race["location"]))
    if meta:
        parts.append(" · ".join(meta))
    return "\n".join(parts)


def _event_lines(
    uid: str,
    dtstamp: str,
    date_str: str,
    summary: str,
    description: str | None,
    url: str | None = None,
) -> list[str]:
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART;VALUE=DATE:{_date_compact(date_str)}",
        f"DTEND;VALUE=DATE:{_next_day_compact(date_str)}",
        f"SUMMARY:{_escape_text(summary)}",
        "TRANSP:TRANSPARENT",
    ]
    if description:
        lines.append(f"DESCRIPTION:{_escape_text(description)}")
    if url:
        lines.append(f"URL:{_escape_text(url)}")
    lines.append("END:VEVENT")
    return lines


def build_ics(sessions: Iterable[dict], races: Iterable[dict]) -> str:
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:z2 — Training Plan",
        "X-WR-TIMEZONE:UTC",
    ]
    for s in sessions:
        if not s.get("date"):
            continue
        lines.extend(_event_lines(
            uid=f"session-{s['id']}@zone2",
            dtstamp=dtstamp,
            date_str=s["date"],
            summary=_session_summary(s),
            description=_session_description(s) or None,
        ))
    for r in races:
        if not r.get("date"):
            continue
        lines.extend(_event_lines(
            uid=f"race-{r['id']}@zone2",
            dtstamp=dtstamp,
            date_str=r["date"],
            summary=_race_summary(r),
            description=_race_description(r) or None,
            url=r.get("url"),
        ))
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"

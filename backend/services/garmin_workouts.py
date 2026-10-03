"""Planned runs on the watch: each running session from today on with segments
or a pace or HR target becomes a Garmin Connect workout scheduled on its day,
which the watch offers that morning. An edit replaces the workout and a delete
removes it; sessions in the past are left as they are."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import date
from enum import StrEnum
from typing import Any

import aiosqlite

from backend.db import connect_db, row_dict
from backend.services.calendar_feed import format_distance_km, format_target_pace, session_description
from backend.services.zones import get_setting
from zone2.core import Zone2
from zone2.garmin_client import GarminClient

logger = logging.getLogger(__name__)

SETTING_KEY = "garmin_send_workouts"
RUNNING_SPORTS = frozenset({"Run", "TrailRun", "VirtualRun"})
# Garmin's pace targets are ranges, so a single pace gets this much either side
PACE_BAND_S = 5
NAME_MAX = 60
ERROR_MAX = 200

# Garmin's step type ids for z2's segment types
_STEP_TYPES = {"warmup": (1, "warmup"), "cooldown": (2, "cooldown"), "work": (3, "interval"),
               "recovery": (4, "recovery"), "rest": (5, "rest")}
_RUNNING = {"sportTypeId": 1, "sportTypeKey": "running"}


class SyncState(StrEnum):
    PENDING = "pending"  # a change for Garmin is queued (send, replace or remove)
    SYNCED = "synced"    # on the Garmin calendar as planned
    FAILED = "failed"    # the last change failed; retried after each Garmin sync


# One Garmin change at a time, so a quick second edit can't send a session twice
_lock = asyncio.Lock()


# ── Workout JSON ─────────────────────────────────────────────────────────

def _end(km: float | None, mins: float | None) -> dict[str, Any]:
    if km:
        return {"endCondition": {"conditionTypeId": 3, "conditionTypeKey": "distance"}, "endConditionValue": km * 1000}
    if mins:
        return {"endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"}, "endConditionValue": mins * 60}
    return {"endCondition": {"conditionTypeId": 1, "conditionTypeKey": "lap.button"}}


def _target(pace_min: float | None, pace_max: float | None, hr_zone: int | None) -> dict[str, Any]:
    """Paces in min/km; Garmin wants speeds, the faster bound first."""
    paces = [p for p in (pace_min, pace_max) if p]
    if paces:
        fast, slow = min(paces), max(paces)
        if fast == slow:
            fast, slow = fast - PACE_BAND_S / 60, slow + PACE_BAND_S / 60
        return {"targetType": {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone"},
                "targetValueOne": round(1000 / (fast * 60), 4), "targetValueTwo": round(1000 / (slow * 60), 4)}
    if hr_zone:
        return {"targetType": {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone"},
                "zoneNumber": int(hr_zone)}
    return {"targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}}


def _step(kind: str, km: float | None, mins: float | None, target: dict[str, Any]) -> dict[str, Any]:
    type_id, key = _STEP_TYPES.get(kind, _STEP_TYPES["work"])
    return {"type": "ExecutableStepDTO", "stepType": {"stepTypeId": type_id, "stepTypeKey": key},
            **_end(km, mins), **target}


def _segment_step(seg: dict[str, Any]) -> dict[str, Any]:
    step = _step(seg.get("type") or "work", seg.get("distance_km"), seg.get("duration_mins"),
                 _target(seg.get("target_pace_min"), seg.get("target_pace_max"), seg.get("target_hr_zone")))
    reps = int(seg.get("repetitions") or 1)
    if reps <= 1:
        return step
    steps = [step]
    if seg.get("recovery_distance_km") or seg.get("recovery_duration_mins"):
        steps.append(_step("recovery", seg.get("recovery_distance_km"), seg.get("recovery_duration_mins"),
                           _target(None, None, None)))
    return {"type": "RepeatGroupDTO", "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat"},
            "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations"},
            "endConditionValue": reps, "numberOfIterations": reps, "smartRepeat": False,
            # The last rep runs into the next segment, not another recovery
            "skipLastRestStep": True, "workoutSteps": steps}


def _number(steps: list[dict[str, Any]], order: int = 0) -> int:
    """Garmin numbers steps depth-first, a repeat group before its own steps."""
    for step in steps:
        order += 1
        step["stepOrder"] = order
        order = _number(step.get("workoutSteps") or [], order)
    return order


def workout_name(session: dict[str, Any]) -> str:
    """The session's own description, else its main set: '5×1 km @ 4:00 /km', '10 km Z2'."""
    if session.get("description"):
        return session["description"][:NAME_MAX]
    main = next((s for s in session.get("segments") or [] if s.get("type") == "work"), None)
    if main:
        reps = int(main.get("repetitions") or 1)
        km, mins, zone = main.get("distance_km"), main.get("duration_mins"), main.get("target_hr_zone")
        pace = main.get("target_pace_min") or main.get("target_pace_max")
    else:
        reps = 1
        km, mins, zone = session.get("planned_distance_km"), session.get("planned_duration_mins"), session.get("target_hr_zone")
        pace = session.get("target_avg_pace") or session.get("target_pace_min") or session.get("target_pace_max")
    amount = format_distance_km(km) if km else f"{mins:g} min" if mins else ""
    name = f"{reps}×{amount}" if reps > 1 else amount
    if pace:
        name += f" @ {format_target_pace(session.get('sport_type'), pace)}"
    elif zone:
        name += f" Z{zone}"
    return name.strip() or session.get("title") or "Run"


def build_workout(session: dict[str, Any]) -> dict[str, Any] | None:
    """The session as a Garmin running workout, or None when it isn't one to
    send. Segments carry their own targets; the session's targets apply when
    it has no segments, and without segments it needs a pace or HR target."""
    if session.get("sport_type") not in RUNNING_SPORTS:
        return None
    segments = [s for s in session.get("segments") or [] if isinstance(s, dict)]
    if segments:
        steps = [_segment_step(s) for s in segments]
    else:
        pace_min, pace_max = session.get("target_pace_min"), session.get("target_pace_max")
        if not (pace_min or pace_max):
            pace_min = pace_max = session.get("target_avg_pace")
        if not (pace_min or pace_max or session.get("target_hr_zone")):
            return None
        steps = [_step("work", session.get("planned_distance_km"), session.get("planned_duration_mins"),
                       _target(pace_min, pace_max, session.get("target_hr_zone")))]
    _number(steps)
    return {"workoutName": workout_name(session), "description": session_description(session) or None,
            "sportType": _RUNNING,
            "workoutSegments": [{"segmentOrder": 1, "sportType": _RUNNING, "workoutSteps": steps}]}


# ── Keeping Garmin in step ───────────────────────────────────────────────

async def is_enabled(z2: Zone2, db: aiosqlite.Connection) -> bool:
    """Garmin is configured and the Profile switch is on (it is by default)."""
    return bool(z2.garmin_client.email) and (await get_setting(db, SETTING_KEY)) != "0"


def _wanted(session: dict[str, Any], enabled: bool, today: str) -> tuple[dict[str, Any], str] | None:
    """The workout the session should have on Garmin and its fingerprint, or None for none."""
    if not enabled or session["date"] < today:
        return None
    workout = build_workout(session)
    if workout is None:
        return None
    return workout, hashlib.sha1(json.dumps([workout, session["date"]], sort_keys=True).encode()).hexdigest()


def needs_sync(session: dict[str, Any], enabled: bool, today: str) -> bool:
    wanted = _wanted(session, enabled, today)
    if wanted is None:
        return session.get("garmin_workout_id") is not None
    return session.get("garmin_sync_state") != SyncState.SYNCED or session.get("garmin_sync_hash") != wanted[1]


async def _save(db: aiosqlite.Connection, session_id: int, workout_id: int | None, fingerprint: str | None,
                state: SyncState | None, error: str | None) -> bool:
    """Store the outcome; False when the session was deleted meanwhile."""
    cur = await db.execute(
        "UPDATE training_sessions SET garmin_workout_id = ?, garmin_sync_hash = ?, garmin_sync_state = ?, "
        "garmin_sync_error = ? WHERE id = ?",
        (workout_id, fingerprint, state, error, session_id),
    )
    await db.commit()
    return cur.rowcount > 0


async def _delete(client: GarminClient, workout_id: int) -> None:
    try:
        await asyncio.to_thread(client.delete_workout, workout_id)
    except Exception as e:
        logger.warning("Deleting Garmin workout %s failed: %s: %s", workout_id, type(e).__name__, e)


async def _apply(db: aiosqlite.Connection, client: GarminClient, session: dict[str, Any],
                 enabled: bool, today: str) -> None:
    """Replace the session's Garmin workout with the one it should have (or none)."""
    wanted = _wanted(session, enabled, today)
    workout_id = session.get("garmin_workout_id")
    try:
        if workout_id is not None:
            await asyncio.to_thread(client.delete_workout, workout_id)
            workout_id = None
        if wanted is not None:
            workout_id = await asyncio.to_thread(client.upload_workout, wanted[0])
            await asyncio.to_thread(client.schedule_workout, workout_id, session["date"])
    except Exception as e:
        logger.warning("Garmin workout for session %s failed: %s: %s", session["id"], type(e).__name__, e)
        if not await _save(db, session["id"], workout_id, None, SyncState.FAILED, str(e)[:ERROR_MAX]) \
                and workout_id is not None:
            await _delete(client, workout_id)
        return
    if wanted is None:
        await _save(db, session["id"], None, None, None, None)
    elif not await _save(db, session["id"], workout_id, wanted[1], SyncState.SYNCED, None):
        await _delete(client, workout_id)


async def mark_pending(z2: Zone2, db: aiosqlite.Connection, session: dict[str, Any],
                       previous_date: str | None = None) -> bool:
    """Mark the session pending when its Garmin workout needs a change, and
    say whether it does. A session that was and stays in the past is left alone."""
    today = date.today().isoformat()
    if max(session["date"], previous_date or session["date"]) < today:
        return False
    if not needs_sync(session, await is_enabled(z2, db), today):
        return False
    await db.execute("UPDATE training_sessions SET garmin_sync_state = ? WHERE id = ?",
                     (SyncState.PENDING, session["id"]))
    await db.commit()
    return True


async def sync_session(z2: Zone2, session_id: int) -> None:
    """Bring one session's Garmin workout in line with it, after `mark_pending`
    said it needs it. It re-reads the session, so the latest edit wins."""
    async with _lock, connect_db() as db:
        row = await (await db.execute("SELECT * FROM training_sessions WHERE id = ?", (session_id,))).fetchone()
        if row is None:
            return
        session = row_dict(row, json_cols=("segments",))
        today = date.today().isoformat()
        enabled = await is_enabled(z2, db)
        if needs_sync(session, enabled, today):
            await _apply(db, z2.garmin_client, session, enabled, today)


async def remove_workout(z2: Zone2, workout_id: int) -> None:
    """Delete the workout of a session deleted from the calendar."""
    async with _lock:
        await _delete(z2.garmin_client, workout_id)


async def mark_pending_upcoming(z2: Zone2, db: aiosqlite.Connection) -> None:
    """Mark every session from today on whose workout needs a change, before a `reconcile`."""
    today = date.today().isoformat()
    enabled = await is_enabled(z2, db)
    rows = await (await db.execute("SELECT * FROM training_sessions WHERE date >= ?", (today,))).fetchall()
    ids = [r["id"] for r in rows if needs_sync(row_dict(r, json_cols=("segments",)), enabled, today)]
    await db.executemany("UPDATE training_sessions SET garmin_sync_state = ? WHERE id = ?",
                         [(SyncState.PENDING, i) for i in ids])
    await db.commit()


async def reconcile(z2: Zone2) -> None:
    """Send what's missing, replace what changed, retry what failed and remove
    what's no longer wanted, for every session from today on. Runs after each
    Garmin sync and when the Profile switch flips."""
    client = z2.garmin_client
    if not client.email:
        return
    async with _lock, connect_db() as db:
        today = date.today().isoformat()
        enabled = await is_enabled(z2, db)
        rows = await (await db.execute("SELECT * FROM training_sessions WHERE date >= ? ORDER BY date",
                                       (today,))).fetchall()
        due = [s for s in (row_dict(r, json_cols=("segments",)) for r in rows) if needs_sync(s, enabled, today)]
        if not due:
            return
        # One login attempt for the lot, rather than one per session
        if not await asyncio.to_thread(client.ensure_logged_in):
            error = (client.last_error or "Garmin Connect is not connected")[:ERROR_MAX]
            for s in due:
                await _save(db, s["id"], s.get("garmin_workout_id"), None, SyncState.FAILED, error)
            return
        for s in due:
            await _apply(db, client, s, enabled, today)
        logger.info("Garmin workouts reconciled: %d session(s) updated", len(due))

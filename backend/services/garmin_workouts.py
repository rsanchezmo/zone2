"""Structured runs on the watch.

Library: every saved run workout (the Workouts page) has a copy in the Garmin
Connect library under its name, so the watch can start it any day. Editing it
updates the copy in place; deleting it deletes the copy, and with it every
Garmin calendar entry of it (Garmin's rule).

Calendar: a running session planned from a saved workout, from today on, gets
an entry on the Garmin calendar on its day, which the watch offers that
morning. Moving the session moves the entry and deleting it removes the entry,
keeping the workout. Past entries stay as history.

z2 only touches what it created: the copies of its saved workouts and the
entries it added. Workouts and entries made in Garmin Connect are left alone."""
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
from zone2.garmin_client import GarminClient, GarminNotFound
from zone2.utils import convert_speed

logger = logging.getLogger(__name__)

SETTING_KEY = "garmin_send_workouts"
RUNNING_SPORTS = frozenset({"Run", "TrailRun", "VirtualRun"})
# Garmin's pace targets are ranges, so a single pace gets this much either side
PACE_BAND_S = 5
ERROR_MAX = 200

# Garmin's step type ids for z2's segment types
_STEP_TYPES = {"warmup": (1, "warmup"), "cooldown": (2, "cooldown"), "work": (3, "interval"),
               "recovery": (4, "recovery"), "rest": (5, "rest")}
_RUNNING = {"sportTypeId": 1, "sportTypeKey": "running"}


class SyncState(StrEnum):
    PENDING = "pending"  # a change for Garmin is queued
    SYNCED = "synced"    # on Garmin as planned
    FAILED = "failed"    # the last change failed; retried after each Garmin sync


# One Garmin change at a time, so a quick second edit can't add a session twice
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
    """Its main set: '5×1 km @ 4:00 /km', '10 km Z2'."""
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
    return name.strip() or session.get("sport_type") or "Run"


def segment_steps(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Segments as Garmin workout steps, which is also what makes two workouts
    the same (whatever the sport)."""
    steps = [_segment_step(s) for s in segments if isinstance(s, dict)]
    _number(steps)
    return steps


def steps_hash(steps: list[dict[str, Any]]) -> str:
    return hashlib.sha1(json.dumps(steps, sort_keys=True).encode()).hexdigest()


# ── Reading Garmin's workouts back ───────────────────────────────────────

# Garmin's sports and step types as z2's ("main" is a swim's main set)
GARMIN_SPORTS = {"running": "Run", "cycling": "Ride", "swimming": "Swim", "walking": "Walk", "hiking": "Hike",
                 "strength_training": "WeightTraining"}
_SEGMENT_TYPES = {"warmup": "warmup", "cooldown": "cooldown", "interval": "work", "main": "work",
                  "recovery": "recovery", "rest": "rest"}


def _amount(step: dict[str, Any]) -> dict[str, float]:
    """A step's end as a distance or a duration; an open (lap button) end has neither."""
    key = (step.get("endCondition") or {}).get("conditionTypeKey")
    value = step.get("endConditionValue") or 0
    if not value:
        return {}
    if key in ("time", "fixed.rest"):
        return {"duration_mins": round(value / 60, 2)}
    # Swim steps keep their distance on a lap-button end
    if key in ("distance", "lap.button"):
        return {"distance_km": round(value / 1000, 3)}
    return {}


def _targets(step: dict[str, Any], sport_type: str) -> dict[str, float]:
    """Pace or speed targets in the unit z2 stores for the sport, or the HR zone."""
    key = (step.get("targetType") or {}).get("workoutTargetTypeKey")
    if key in ("pace.zone", "speed.zone"):
        values = sorted(round(convert_speed(v, sport_type)[0], 3) for v in (step.get("targetValueOne"), step.get("targetValueTwo")) if v)
        return {"target_pace_min": values[0], "target_pace_max": values[-1]} if values else {}
    if key == "heart.rate.zone" and step.get("zoneNumber"):
        return {"target_hr_zone": int(step["zoneNumber"])}
    return {}


def _step_segments(steps: list[dict[str, Any]], sport_type: str) -> list[dict[str, Any]]:
    segments = []
    for step in steps:
        if step.get("type") != "RepeatGroupDTO":
            kind = _SEGMENT_TYPES.get(step["stepType"]["stepTypeKey"], "work")
            segments.append({"type": kind, **_amount(step), **_targets(step, sport_type), "repetitions": 1})
            continue
        reps = int(step.get("numberOfIterations") or 1)
        inner = step.get("workoutSteps") or []
        kinds = [_SEGMENT_TYPES.get(s["stepType"]["stepTypeKey"]) if s.get("type") != "RepeatGroupDTO" else None
                 for s in inner]
        if kinds in (["work"], ["work", "recovery"], ["work", "rest"]):
            work = {**_step_segments(inner[:1], sport_type)[0], "repetitions": reps}
            if len(inner) == 2:
                recovery = _amount(inner[1])
                work.update(recovery_duration_mins=recovery.get("duration_mins"),
                            recovery_distance_km=recovery.get("distance_km"))
            segments.append(work)
        else:
            # Richer sets (several work steps, nested repeats) unrolled, so the summary stays true
            segments.extend(_step_segments(inner, sport_type) * reps)
    return segments


def garmin_segments(workout: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """A Garmin workout's sport and steps as z2's sport type and segments."""
    sport_key = (workout.get("sportType") or {}).get("sportTypeKey") or ""
    sport_type = GARMIN_SPORTS.get(sport_key, sport_key.replace("_", " ").title())
    steps = [s for seg in workout.get("workoutSegments") or [] for s in seg.get("workoutSteps") or []]
    return sport_type, _step_segments(steps, sport_type)


def _error(e: Exception) -> str:
    return str(e)[:ERROR_MAX]


# ── Library: saved run workouts ──────────────────────────────────────────

async def is_enabled(z2: Zone2, db: aiosqlite.Connection) -> bool:
    """Garmin is configured and the Profile switch is on (it is by default)."""
    return bool(z2.garmin_client.email) and (await get_setting(db, SETTING_KEY)) != "0"


def is_run_workout(template: dict[str, Any]) -> bool:
    return template["sport_type"] in RUNNING_SPORTS and bool(template.get("segments"))


def library_workout(template: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """The saved workout as Garmin workout JSON, and a fingerprint of it."""
    workout = {
        "workoutName": template["name"],
        "description": session_description({"sport_type": template["sport_type"], "segments": template["segments"],
                                            "description": template.get("description")}) or None,
        "sportType": _RUNNING,
        "workoutSegments": [{"segmentOrder": 1, "sportType": _RUNNING,
                             "workoutSteps": segment_steps(template["segments"])}],
    }
    return workout, hashlib.sha1(json.dumps(workout, sort_keys=True).encode()).hexdigest()


def library_state(template: dict[str, Any], enabled: bool) -> SyncState | None:
    """Whether the saved workout's Garmin copy is up to date (None: not one to copy)."""
    if not enabled or not is_run_workout(template):
        return None
    if template.get("garmin_workout_id") and template.get("garmin_sync_hash") == library_workout(template)[1]:
        return SyncState.SYNCED
    return SyncState.FAILED if template.get("garmin_sync_error") else SyncState.PENDING


async def _templates(db: aiosqlite.Connection, where: str = "1", params: tuple = ()) -> list[dict[str, Any]]:
    rows = await (await db.execute(f"SELECT * FROM workout_templates WHERE {where}", params)).fetchall()
    return [row_dict(r, json_cols=("segments",)) for r in rows]


async def _forget_copy(db: aiosqlite.Connection, workout_id: int) -> None:
    """A copy deleted in Garmin Connect, and its calendar entries with it."""
    await db.execute("DELETE FROM garmin_workout_schedules WHERE workout_id = ?", (workout_id,))
    await db.execute("UPDATE workout_templates SET garmin_workout_id = NULL, garmin_sync_hash = NULL "
                     "WHERE garmin_workout_id = ?", (workout_id,))
    await db.commit()


async def _push_template(db: aiosqlite.Connection, client: GarminClient, template: dict[str, Any]) -> int:
    """Upload the saved workout's copy, or update it in place; returns its Garmin id."""
    workout, fingerprint = library_workout(template)
    workout_id = template.get("garmin_workout_id")
    if workout_id is not None and template.get("garmin_sync_hash") != fingerprint:
        try:
            await asyncio.to_thread(client.update_workout, workout_id, workout)
        except GarminNotFound:
            await _forget_copy(db, workout_id)
            workout_id = None
    if workout_id is None:
        workout_id = await asyncio.to_thread(client.upload_workout, workout)
    await db.execute("UPDATE workout_templates SET garmin_workout_id = ?, garmin_sync_hash = ?, garmin_sync_error = NULL "
                     "WHERE id = ?", (workout_id, fingerprint, template["id"]))
    await db.commit()
    return workout_id


async def _sync_library(db: aiosqlite.Connection, client: GarminClient, enabled: bool) -> None:
    """Upload or update every saved run workout whose copy isn't current."""
    for t in await _templates(db):
        if library_state(t, enabled) in (None, SyncState.SYNCED):
            continue
        try:
            await _push_template(db, client, t)
        except Exception as e:
            logger.warning("Garmin copy of workout %r failed: %s: %s", t["name"], type(e).__name__, e)
            await db.execute("UPDATE workout_templates SET garmin_sync_error = ? WHERE id = ?", (_error(e), t["id"]))
            await db.commit()


async def sync_library(z2: Zone2) -> None:
    """Bring the Garmin copies in line with the saved workouts (after one changes)."""
    if not z2.garmin_client.email:
        return
    async with _lock, connect_db() as db:
        await _sync_library(db, z2.garmin_client, await is_enabled(z2, db))


async def delete_copy(z2: Zone2, workout_id: int) -> None:
    """Delete a deleted saved workout's Garmin copy, which takes its calendar entries with it."""
    async with _lock, connect_db() as db:
        try:
            await asyncio.to_thread(z2.garmin_client.delete_workout, workout_id)
        except Exception as e:
            logger.warning("Deleting Garmin workout %s failed: %s: %s", workout_id, type(e).__name__, e)
            return
        await db.execute("DELETE FROM garmin_workout_schedules WHERE workout_id = ?", (workout_id,))
        await db.commit()


# ── Calendar: planned sessions ───────────────────────────────────────────

async def _entries(db: aiosqlite.Connection, session_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Each session's Garmin calendar entry."""
    if not session_ids:
        return {}
    rows = await (await db.execute(
        "SELECT * FROM garmin_workout_schedules "
        f"WHERE session_id IN ({', '.join('?' * len(session_ids))})", session_ids,
    )).fetchall()
    return {r["session_id"]: dict(r) for r in rows}


def _wanted(session: dict[str, Any], template: dict[str, Any] | None, enabled: bool) -> dict[str, Any] | None:
    """The saved workout the session's entry should be of, or None for no entry."""
    if not enabled or template is None or session.get("sport_type") not in RUNNING_SPORTS or not is_run_workout(template):
        return None
    return template


def needs_sync(session: dict[str, Any], entry: dict[str, Any] | None, template: dict[str, Any] | None,
               enabled: bool) -> bool:
    wanted = _wanted(session, template, enabled)
    if wanted is None:
        return entry is not None
    return (session.get("garmin_sync_state") != SyncState.SYNCED or entry is None
            or entry["date"] != session["date"] or entry["workout_id"] != wanted.get("garmin_workout_id"))


async def _set_state(db: aiosqlite.Connection, session_id: int, state: SyncState | None, error: str | None) -> None:
    await db.execute("UPDATE training_sessions SET garmin_sync_state = ?, garmin_sync_error = ? WHERE id = ?",
                     (state, error, session_id))
    await db.commit()


async def _unschedule(db: aiosqlite.Connection, client: GarminClient, schedule_id: int) -> None:
    await asyncio.to_thread(client.unschedule_workout, schedule_id)
    await db.execute("DELETE FROM garmin_workout_schedules WHERE schedule_id = ?", (schedule_id,))
    await db.commit()


async def _schedule(db: aiosqlite.Connection, client: GarminClient, session: dict[str, Any],
                    template: dict[str, Any]) -> None:
    """Add the session's entry, on its saved workout's copy (uploaded first when missing or stale)."""
    if library_state(template, True) is not SyncState.SYNCED:
        template = {**template, "garmin_workout_id": await _push_template(db, client, template)}
    try:
        schedule_id = await asyncio.to_thread(client.schedule_workout, template["garmin_workout_id"], session["date"])
    except GarminNotFound:
        await _forget_copy(db, template["garmin_workout_id"])
        workout_id = await _push_template(db, client, {**template, "garmin_workout_id": None})
        template = {**template, "garmin_workout_id": workout_id}
        schedule_id = await asyncio.to_thread(client.schedule_workout, workout_id, session["date"])
    await db.execute("INSERT INTO garmin_workout_schedules (schedule_id, workout_id, date, session_id) VALUES (?, ?, ?, ?)",
                     (schedule_id, template["garmin_workout_id"], session["date"], session["id"]))
    await db.commit()


async def _apply(db: aiosqlite.Connection, client: GarminClient, session: dict[str, Any],
                 entry: dict[str, Any] | None, template: dict[str, Any] | None, enabled: bool) -> None:
    """Replace the session's entry with the one it should have (or none)."""
    wanted = _wanted(session, template, enabled)
    try:
        if entry is not None:
            await _unschedule(db, client, entry["schedule_id"])
        if wanted is not None:
            await _schedule(db, client, session, wanted)
    except Exception as e:
        logger.warning("Garmin entry for session %s failed: %s: %s", session["id"], type(e).__name__, e)
        await _set_state(db, session["id"], SyncState.FAILED, _error(e))
        return
    await _set_state(db, session["id"], SyncState.SYNCED if wanted else None, None)


async def _session_context(db: aiosqlite.Connection, session: dict[str, Any]) -> tuple[dict | None, dict | None]:
    """The session's current entry and its saved workout."""
    entry = (await _entries(db, [session["id"]])).get(session["id"])
    template = None
    if session.get("workout_template_id"):
        template = next(iter(await _templates(db, "id = ?", (session["workout_template_id"],))), None)
    return entry, template


async def mark_pending(z2: Zone2, db: aiosqlite.Connection, session: dict[str, Any],
                       previous_date: str | None = None) -> bool:
    """Mark the session pending when its entry needs a change, and say whether
    it does. A session that was and stays in the past is left alone."""
    if max(session["date"], previous_date or session["date"]) < date.today().isoformat():
        return False
    entry, template = await _session_context(db, session)
    if not needs_sync(session, entry, template, await is_enabled(z2, db)):
        return False
    await _set_state(db, session["id"], SyncState.PENDING, None)
    return True


async def sync_session(z2: Zone2, session_id: int) -> None:
    """Bring one session's entry in line with it, after `mark_pending` said it
    needs it. It re-reads the session, so the latest edit wins."""
    async with _lock, connect_db() as db:
        row = await (await db.execute("SELECT * FROM training_sessions WHERE id = ?", (session_id,))).fetchone()
        if row is None:
            return
        session = row_dict(row, json_cols=("segments",))
        entry, template = await _session_context(db, session)
        enabled = await is_enabled(z2, db)
        if needs_sync(session, entry, template, enabled):
            await _apply(db, z2.garmin_client, session, entry, template, enabled)


async def forget_session(z2: Zone2, session_id: int) -> None:
    """After a session is deleted: its past entry stays on Garmin as history and
    an upcoming one is removed; the workout stays. Runs after any change still
    in flight for it, so nothing it adds is left behind."""
    async with _lock, connect_db() as db:
        await db.execute("UPDATE garmin_workout_schedules SET session_id = NULL WHERE session_id = ? AND date < ?",
                         (session_id, date.today().isoformat()))
        await db.commit()
        rows = await (await db.execute("SELECT schedule_id FROM garmin_workout_schedules WHERE session_id = ?",
                                       (session_id,))).fetchall()
        for r in rows:
            try:
                await _unschedule(db, z2.garmin_client, r["schedule_id"])
            except Exception as e:
                logger.warning("Removing Garmin entry %s failed: %s: %s", r["schedule_id"], type(e).__name__, e)


async def _due(db: aiosqlite.Connection, enabled: bool) -> list[tuple[dict, dict | None, dict | None]]:
    """Sessions from today on whose entry needs a change, with their entry and saved workout."""
    rows = await (await db.execute("SELECT * FROM training_sessions WHERE date >= ? ORDER BY date",
                                   (date.today().isoformat(),))).fetchall()
    sessions = [row_dict(r, json_cols=("segments",)) for r in rows]
    entries = await _entries(db, [s["id"] for s in sessions])
    templates = {t["id"]: t for t in await _templates(db)}
    due = []
    for s in sessions:
        entry, template = entries.get(s["id"]), templates.get(s.get("workout_template_id"))
        if needs_sync(s, entry, template, enabled):
            due.append((s, entry, template))
    return due


async def mark_due_pending(z2: Zone2, db: aiosqlite.Connection) -> None:
    """Mark every upcoming session whose entry needs a change, before a `reconcile`."""
    due = await _due(db, await is_enabled(z2, db))
    await db.executemany("UPDATE training_sessions SET garmin_sync_state = ?, garmin_sync_error = NULL WHERE id = ?",
                         [(SyncState.PENDING, s["id"]) for s, _, _ in due])
    await db.commit()


async def reconcile(z2: Zone2) -> None:
    """Copy what the library is missing, then add what's missing on the
    calendar, move what changed, retry what failed and remove what's no longer
    wanted, from today on. Runs after each Garmin sync and when the Profile
    switch flips; with it off, upcoming entries are removed and the copies kept."""
    client = z2.garmin_client
    if not client.email:
        return
    async with _lock, connect_db() as db:
        enabled = await is_enabled(z2, db)
        stale = [t for t in await _templates(db) if library_state(t, enabled) not in (None, SyncState.SYNCED)]
        due = await _due(db, enabled)
        if not stale and not due:
            return
        # One login attempt for the lot, rather than one per change
        if not await asyncio.to_thread(client.ensure_logged_in):
            error = (client.last_error or "Garmin Connect is not connected")[:ERROR_MAX]
            for s, _, _ in due:
                await _set_state(db, s["id"], SyncState.FAILED, error)
            return
        await _sync_library(db, client, enabled)
        due = await _due(db, enabled)  # copies may have changed ids
        for s, entry, template in due:
            await _apply(db, client, s, entry, template, enabled)
        logger.info("Garmin workouts reconciled: %d copies, %d entries", len(stale), len(due))

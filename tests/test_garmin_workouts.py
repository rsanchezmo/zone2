"""Saved workouts as Garmin workout steps, and back."""
import pytest

from backend.services.calendar_feed import format_distance_km, format_target_pace
from backend.services.garmin_workouts import (
    SyncState, _end, _step, _target, garmin_segments, library_state, library_workout, needs_sync, segment_steps,
    steps_hash, workout_name,
)

INTERVALS = [
    {"type": "warmup", "duration_mins": 15, "target_hr_zone": 2},
    {"type": "work", "distance_km": 1.0, "repetitions": 5, "target_pace_min": 3.95, "target_pace_max": 4.05,
     "recovery_duration_mins": 2},
    {"type": "cooldown", "distance_km": 2.0},
]


def as_garmin_workout(segments: list[dict], sport_key: str = "running") -> dict:
    return {"sportType": {"sportTypeKey": sport_key}, "workoutSegments": [{"workoutSteps": segment_steps(segments)}]}


def test_a_single_pace_becomes_a_band_of_speeds_faster_first():
    target = _target(4.0, None, None)
    assert target["targetType"]["workoutTargetTypeKey"] == "pace.zone"
    # 5 s either side of 4:00 /km, as m/s
    assert target["targetValueOne"] == pytest.approx(1000 / 235, abs=1e-4)
    assert target["targetValueTwo"] == pytest.approx(1000 / 245, abs=1e-4)
    assert _target(None, None, 3) == {"targetType": {"workoutTargetTypeId": 4,
                                                     "workoutTargetTypeKey": "heart.rate.zone"}, "zoneNumber": 3}


def test_step_end_conditions():
    assert _end(1.5, 10)["endConditionValue"] == 1500   # distance wins
    assert _end(None, 10) == {"endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
                              "endConditionValue": 600}
    assert _end(None, None) == {"endCondition": {"conditionTypeId": 1, "conditionTypeKey": "lap.button"}}


def test_steps_are_numbered_depth_first():
    steps = segment_steps(INTERVALS)
    assert [s["type"] for s in steps] == ["ExecutableStepDTO", "RepeatGroupDTO", "ExecutableStepDTO"]
    repeat = steps[1]
    assert repeat["numberOfIterations"] == 5 and repeat["skipLastRestStep"]
    assert [s["stepType"]["stepTypeKey"] for s in repeat["workoutSteps"]] == ["interval", "recovery"]
    assert [steps[0]["stepOrder"], repeat["stepOrder"], *(s["stepOrder"] for s in repeat["workoutSteps"]),
            steps[2]["stepOrder"]] == [1, 2, 3, 4, 5]


def test_segments_round_trip_through_garmin():
    sport_type, segments = garmin_segments(as_garmin_workout(INTERVALS))
    assert sport_type == "Run"
    assert segments == [
        {"type": "warmup", "duration_mins": 15.0, "target_hr_zone": 2, "repetitions": 1},
        {"type": "work", "distance_km": 1.0, "target_pace_min": 3.95, "target_pace_max": 4.05, "repetitions": 5,
         "recovery_duration_mins": 2.0, "recovery_distance_km": None},
        {"type": "cooldown", "distance_km": 2.0, "repetitions": 1},
    ]


def test_richer_repeats_are_unrolled():
    no_target = _target(None, None, None)
    workout = {"sportType": {"sportTypeKey": "running"}, "workoutSegments": [{"workoutSteps": [{
        "type": "RepeatGroupDTO", "numberOfIterations": 3,
        "workoutSteps": [_step("work", 0.4, None, no_target), _step("work", 0.2, None, no_target)],
    }]}]}
    _, segments = garmin_segments(workout)
    assert [s["distance_km"] for s in segments] == [0.4, 0.2] * 3


def test_swim_steps_keep_their_distance_on_a_lap_button_end():
    step = {"type": "ExecutableStepDTO", "stepType": {"stepTypeKey": "main"},
            "endCondition": {"conditionTypeKey": "lap.button"}, "endConditionValue": 100}
    workout = {"sportType": {"sportTypeKey": "swimming"}, "workoutSegments": [{"workoutSteps": [step]}]}
    assert garmin_segments(workout) == ("Swim", [{"type": "work", "distance_km": 0.1, "repetitions": 1}])


def test_steps_hash_identifies_the_same_steps():
    reordered = [{k: seg[k] for k in reversed(list(seg))} for seg in INTERVALS]
    assert steps_hash(segment_steps(reordered)) == steps_hash(segment_steps(INTERVALS))
    longer = [*INTERVALS[:2], {"type": "cooldown", "distance_km": 3.0}]
    assert steps_hash(segment_steps(longer)) != steps_hash(segment_steps(INTERVALS))


def test_workout_name():
    main_set = [{"type": "warmup", "distance_km": 2},
                {"type": "work", "distance_km": 1, "repetitions": 5, "target_pace_min": 4.0}]
    assert workout_name({"sport_type": "Run", "segments": main_set}) == "5×1 km @ 4:00 /km"
    assert workout_name({"sport_type": "Run", "planned_distance_km": 10, "target_hr_zone": 2}) == "10 km Z2"
    assert workout_name({"sport_type": "Run", "planned_duration_mins": 45}) == "45 min"
    assert workout_name({"sport_type": "Run"}) == "Run"


def test_target_formatting():
    assert format_target_pace("Run", 4.9999) == "5:00 /km"
    assert format_target_pace("Run", 4.5, 4.0) == "4:00–4:30 /km"
    assert format_target_pace("Swim", 1.75) == "1:45 /100m"
    assert format_target_pace("Ride", 30, 35) == "30–35 km/h"
    assert (format_distance_km(0.4), format_distance_km(10)) == ("400 m", "10 km")


# ── Sync decisions ───────────────────────────────────────────────────────

TEMPLATE = {"id": 1, "name": "5×1 km", "sport_type": "Run", "segments": INTERVALS, "garmin_workout_id": 77}
SESSION = {"id": 9, "sport_type": "Run", "date": "2026-11-20", "garmin_sync_state": SyncState.SYNCED}
ENTRY = {"date": "2026-11-20", "workout_id": 77}


def test_needs_sync():
    assert not needs_sync(SESSION, ENTRY, TEMPLATE, True)                       # on Garmin as planned
    assert needs_sync({**SESSION, "date": "2026-11-21"}, ENTRY, TEMPLATE, True)  # moved
    assert needs_sync(SESSION, None, TEMPLATE, True)                            # entry missing
    assert needs_sync(SESSION, ENTRY, TEMPLATE, False)                          # switched off: remove it
    assert not needs_sync({**SESSION, "sport_type": "Ride"}, None, TEMPLATE, True)


def test_library_state():
    synced = {**TEMPLATE, "garmin_sync_hash": library_workout(TEMPLATE)[1]}
    assert library_state(synced, enabled=True) == SyncState.SYNCED
    assert library_state({**synced, "segments": INTERVALS[:2]}, enabled=True) == SyncState.PENDING
    assert library_state({**synced, "garmin_sync_hash": "old", "garmin_sync_error": "boom"}, True) == SyncState.FAILED
    assert library_state(synced, enabled=False) is None
    assert library_state({**synced, "sport_type": "Ride"}, enabled=True) is None

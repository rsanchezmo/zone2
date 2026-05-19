"""Execution scoring engine for training sessions.

Pure functions — no DB or framework dependencies.

Stream/point shape: columnar dict (`{time: [...], distance: [...], heartrate: [...], velocity_smooth: [...], ...}`).
A "slice" is the same shape with shorter arrays. Helpers `_len`, `_get`, and
`_slice` keep the call sites readable.
"""

from __future__ import annotations

from strava.strava_utils import convert_speed, get_sport_category
from strava.streams_store import slice_streams as _slice, stream_length as _len


def match_activity(
    session: dict,
    activities_on_day: list[dict],
) -> dict | None:
    """Match a session to the best activity on the same day.

    1. Filter by sport_type (exact match).
    2. If multiple: sort by closest planned_distance_km (if set),
       else planned_duration_mins, else first.
    3. Return best match or None.
    """
    sport = session.get("sport_type", "")
    candidates = [a for a in activities_on_day if a.get("sport_type") == sport]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    planned_dist = session.get("planned_distance_km")
    planned_dur = session.get("planned_duration_mins")

    if planned_dist is not None:
        candidates.sort(key=lambda a: abs((a.get("distance_km") or 0) - planned_dist))
    elif planned_dur is not None:
        candidates.sort(key=lambda a: abs((a.get("moving_time") or 0) / 60 - planned_dur))

    return candidates[0]


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _get(streams: dict, key: str, i: int, default=0):
    """Indexed access into a columnar stream channel, with default for
    missing channel / missing value / out-of-bounds index."""
    arr = streams.get(key)
    if arr is None or i >= len(arr):
        return default
    v = arr[i]
    return default if v is None else v


def _score_distance(target_km: float, actual_km: float) -> dict:
    if target_km <= 0:
        return {"target": target_km, "actual": actual_km, "score": 0, "unit": "km"}
    score = _clamp(100 - abs(1 - actual_km / target_km) * 100)
    return {"target": target_km, "actual": round(actual_km, 2), "score": round(score), "unit": "km"}


def _score_duration(target_mins: float, actual_mins: float) -> dict:
    if target_mins <= 0:
        return {"target": target_mins, "actual": actual_mins, "score": 0, "unit": "min"}
    score = _clamp(100 - abs(1 - actual_mins / target_mins) * 100)
    return {"target": target_mins, "actual": round(actual_mins, 1), "score": round(score), "unit": "min"}


def _pace_penalty(deviation: float, unit: str) -> float:
    """Convert a fractional deviation to a score penalty.

    For pace-based sports (min/km, min/100m) the penalty is steeper (×2)
    because small numeric differences represent large real-world gaps.
    For speed-based sports (km/h) the linear 1:1 mapping is fine.
    """
    if unit in ("min/km", "min/100m"):
        return deviation * 200
    return deviation * 100


def _score_pace(
    target_min: float | None,
    target_max: float | None,
    actual_pace: float,
    unit: str,
) -> dict:
    """Score pace/speed against a target range (either or both sides optional)."""
    result = {
        "target_min": target_min,
        "target_max": target_max,
        "actual": round(actual_pace, 2),
        "score": 0,
        "unit": unit,
    }

    if target_min is not None and target_max is not None:
        lo = min(target_min, target_max)
        hi = max(target_min, target_max)
        range_width = hi - lo if hi > lo else 1.0

        if lo <= actual_pace <= hi:
            result["score"] = 100
        else:
            overshoot = min(abs(actual_pace - lo), abs(actual_pace - hi))
            deviation = overshoot / range_width
            result["score"] = round(_clamp(100 - _pace_penalty(deviation, unit)))

    elif target_min is not None:
        if actual_pace >= target_min:
            result["score"] = 100
        else:
            ref = target_min if target_min != 0 else 1.0
            deviation = abs(actual_pace - target_min) / ref
            result["score"] = round(_clamp(100 - _pace_penalty(deviation, unit)))

    elif target_max is not None:
        if actual_pace <= target_max:
            result["score"] = 100
        else:
            ref = target_max if target_max != 0 else 1.0
            deviation = abs(actual_pace - target_max) / ref
            result["score"] = round(_clamp(100 - _pace_penalty(deviation, unit)))

    return result


def _compute_hr_zone_pct(
    streams: dict,
    target_zone: int,
    hr_zones: list[dict],
) -> float | None:
    """Percentage of time spent in target HR zone from a columnar stream slice."""
    if not streams or not hr_zones or target_zone < 1 or target_zone > len(hr_zones):
        return None

    zone = hr_zones[target_zone - 1]
    zone_min = zone.get("min", 0)
    zone_max = zone.get("max", 999)

    hr_col = streams.get("heartrate") or []
    hr_points = [hr for hr in hr_col if hr]
    if not hr_points:
        return None

    in_zone = sum(1 for hr in hr_points if zone_min <= hr <= zone_max)
    return round(in_zone / len(hr_points) * 100, 1)


def _score_hr_zone(target_pct: float, actual_pct: float) -> dict:
    if target_pct <= 0:
        return {"target_pct": target_pct, "actual_pct": actual_pct, "score": 0}
    score = _clamp(actual_pct / target_pct * 100)
    return {"target_pct": target_pct, "actual_pct": actual_pct, "score": round(score)}


def _advance_by_distance(streams: dict, pos: int, distance_m: float) -> tuple[dict, int]:
    """Walk streams from pos, collecting points until distance_m is covered.

    Uses the cumulative 'distance' channel. Returns (points_slice, new_pos).
    """
    n = _len(streams)
    if pos >= n:
        return _slice(streams, pos, pos), pos
    start_dist = _get(streams, "distance", pos)
    i = pos
    while i < n:
        current_dist = _get(streams, "distance", i) - start_dist
        if current_dist >= distance_m:
            i += 1
            break
        i += 1
    return _slice(streams, pos, i), i


def _advance_by_duration(streams: dict, pos: int, duration_s: float) -> tuple[dict, int]:
    """Walk streams from pos, collecting points until duration_s is covered.

    Returns (points_slice, new_pos).
    """
    n = _len(streams)
    if pos >= n:
        return _slice(streams, pos, pos), pos
    start_time = _get(streams, "time", pos)
    i = pos
    while i < n:
        elapsed = _get(streams, "time", i) - start_time
        if elapsed >= duration_s:
            i += 1
            break
        i += 1
    return _slice(streams, pos, i), i


def _merge_nearby_fast_phases(
    phases: list[dict],
    streams: dict,
    max_gap_seconds: float = 15,
) -> list[dict]:
    """Merge fast phases separated by short non-fast gaps."""
    if not phases:
        return phases

    fast_indices = [i for i, p in enumerate(phases) if p["phase"] == "fast"]
    if len(fast_indices) < 2:
        return phases

    merge_groups: list[list[int]] = [[fast_indices[0]]]
    for k in range(1, len(fast_indices)):
        prev_fi = fast_indices[k - 1]
        curr_fi = fast_indices[k]
        prev_phase = phases[prev_fi]
        curr_phase = phases[curr_fi]
        gap_s = (_get(streams, "time", curr_phase["i_start"])
                 - _get(streams, "time", prev_phase["i_end"]))
        if gap_s <= max_gap_seconds:
            merge_groups[-1].append(curr_fi)
        else:
            merge_groups.append([curr_fi])

    merged_fast = {}
    skip_indices = set()
    for group in merge_groups:
        first = phases[group[0]]
        last = phases[group[-1]]
        merged_phase = _build_phase(streams, "fast", first["i_start"], last["i_end"])
        merged_fast[group[0]] = merged_phase
        for fi in group[1:]:
            skip_indices.add(fi)
        for fi_a, fi_b in zip(group, group[1:]):
            for mid in range(fi_a + 1, fi_b):
                skip_indices.add(mid)

    result: list[dict] = []
    for i, p in enumerate(phases):
        if i in skip_indices:
            continue
        if i in merged_fast:
            result.append(merged_fast[i])
        else:
            result.append(p)

    return result


def _detect_velocity_phases(
    streams: dict,
    fast_threshold: float = 4.0,
    slow_threshold: float = 2.5,
    min_points: int = 3,
    max_merge_gap_seconds: float = 15,
) -> list[dict]:
    """Detect fast/slow/moderate phases from velocity_smooth data.

    Returns list of phase dicts:
      {phase: "fast"|"slow"|"moderate", i_start, i_end, distance_m, duration_s}
    """
    n = _len(streams)
    if n < min_points * 2:
        return []

    vel = streams.get("velocity_smooth") or []
    phases: list[dict] = []
    current_phase = None
    phase_start = 0

    for i in range(n):
        v = vel[i] if i < len(vel) and vel[i] is not None else 0
        if v > fast_threshold:
            phase = "fast"
        elif v < slow_threshold:
            phase = "slow"
        else:
            phase = "moderate"

        if phase != current_phase:
            if current_phase is not None and i - phase_start >= min_points:
                phases.append(_build_phase(streams, current_phase, phase_start, i - 1))
            current_phase = phase
            phase_start = i

    if current_phase is not None and n - phase_start >= min_points:
        phases.append(_build_phase(streams, current_phase, phase_start, n - 1))

    phases = _merge_nearby_fast_phases(phases, streams, max_merge_gap_seconds)

    return phases


def _build_phase(streams: dict, phase: str, i_start: int, i_end: int) -> dict:
    return {
        "phase": phase,
        "i_start": i_start,
        "i_end": i_end,
        "distance_m": _get(streams, "distance", i_end) - _get(streams, "distance", i_start),
        "duration_s": _get(streams, "time", i_end) - _get(streams, "time", i_start),
    }


def _has_rep_work_segments(segments: list[dict]) -> bool:
    """Check if any segment has repetitions > 1 (interval workout)."""
    return any((s.get("repetitions") or 1) > 1 for s in segments)


def _compute_fast_threshold(streams: dict) -> tuple[float, float]:
    """Compute adaptive fast/slow thresholds from the velocity distribution."""
    vel_col = streams.get("velocity_smooth") or []
    velocities = sorted(v for v in vel_col if v is not None and v > 0.5)
    if len(velocities) < 20:
        return 4.0, 2.5

    mid = len(velocities) // 2
    slow_median = velocities[mid // 2]
    fast_median = velocities[mid + mid // 2]

    if fast_median <= slow_median * 1.2:
        return 4.0, 2.5

    midpoint = (slow_median + fast_median) / 2
    return midpoint + 0.2, midpoint - 0.2


def _slice_intervals_by_velocity(
    streams: dict,
    segments: list[dict],
) -> list[dict] | None:
    """Slice an interval workout by detecting fast/slow velocity phases."""
    work_idx = None
    work_seg = None
    for i, seg in enumerate(segments):
        if (seg.get("repetitions") or 1) > 1:
            work_idx = i
            work_seg = seg
            break
    if work_seg is None:
        return None

    reps = work_seg.get("repetitions", 1)
    fast_thresh, slow_thresh = _compute_fast_threshold(streams)

    target_dist_m = (work_seg.get("distance_km") or 0) * 1000
    if target_dist_m > 0 and fast_thresh > 0:
        expected_rep_s = target_dist_m / fast_thresh
        max_merge_gap = max(15, min(expected_rep_s * 0.15, 90))
    else:
        max_merge_gap = 15

    phases = _detect_velocity_phases(
        streams, fast_thresh, slow_thresh,
        max_merge_gap_seconds=max_merge_gap,
    )

    fast_phases = [p for p in phases if p["phase"] == "fast"]

    target_dist = (work_seg.get("distance_km") or 0) * 1000
    target_dur = (work_seg.get("duration_mins") or 0) * 60
    min_dist = target_dist * 0.3 if target_dist > 0 else 0
    min_dur = max(target_dur * 0.3, 5)
    fast_phases = [
        p for p in fast_phases
        if p["distance_m"] >= min_dist and p["duration_s"] >= min_dur
    ]

    if len(fast_phases) < reps:
        return None

    if target_dist > 0:
        fast_phases.sort(key=lambda p: abs(p["distance_m"] - target_dist))
        matched_fast = sorted(fast_phases[:reps], key=lambda p: p["i_start"])
    else:
        matched_fast = fast_phases[:reps]

    slices = []

    # --- Pre-work segments (warmup etc.) ---
    work_start_idx = matched_fast[0]["i_start"]
    pos = 0
    for seg_idx in range(work_idx):
        seg = segments[seg_idx]
        dist_m = (seg.get("distance_km") or 0) * 1000
        dur_s = (seg.get("duration_mins") or 0) * 60

        if dist_m > 0:
            points, pos = _advance_by_distance(streams, pos, dist_m)
        elif dur_s > 0:
            points, pos = _advance_by_duration(streams, pos, dur_s)
        else:
            points = _slice(streams, pos, work_start_idx)
            pos = work_start_idx

        slices.append({
            "segment_idx": seg_idx,
            "segment": seg,
            "is_recovery": False,
            "rep": 1,
            "points": points,
        })

    # --- Work reps + recovery ---
    for rep_i, fast_phase in enumerate(matched_fast):
        work_points = _slice(streams, fast_phase["i_start"], fast_phase["i_end"] + 1)
        slices.append({
            "segment_idx": work_idx,
            "segment": work_seg,
            "is_recovery": False,
            "rep": rep_i + 1,
            "points": work_points,
        })

        if rep_i < len(matched_fast) - 1:
            rec_start = fast_phase["i_end"] + 1
            rec_end = matched_fast[rep_i + 1]["i_start"]
            rec_points = _slice(streams, rec_start, rec_end)
            if _len(rec_points):
                rec_segment = {
                    "type": "recovery",
                    "distance_km": work_seg.get("recovery_distance_km"),
                    "duration_mins": work_seg.get("recovery_duration_mins"),
                }
                slices.append({
                    "segment_idx": work_idx,
                    "segment": rec_segment,
                    "is_recovery": True,
                    "rep": rep_i + 1,
                    "points": rec_points,
                })

    # --- Post-work segments (cooldown etc.) ---
    pos = matched_fast[-1]["i_end"] + 1
    n = _len(streams)

    for seg_idx in range(work_idx + 1, len(segments)):
        seg = segments[seg_idx]
        dist_m = (seg.get("distance_km") or 0) * 1000
        dur_s = (seg.get("duration_mins") or 0) * 60

        if dist_m > 0:
            points, pos = _advance_by_distance(streams, pos, dist_m)
        elif dur_s > 0:
            points, pos = _advance_by_duration(streams, pos, dur_s)
        else:
            points = _slice(streams, pos, n)
            pos = n

        slices.append({
            "segment_idx": seg_idx,
            "segment": seg,
            "is_recovery": False,
            "rep": 1,
            "points": points,
        })

    return slices


def slice_streams_by_segments(
    streams: dict,
    segments: list[dict],
    sport_type: str = "",
) -> list[dict]:
    """Slice stream data into segments for scoring.

    For interval workouts (segments with reps > 1), uses velocity-based phase
    detection to accurately identify fast/recovery phases. Falls back to
    sequential distance/time walking for simple workouts or when phase
    detection doesn't match.

    Returns list of slice dicts:
      {segment_idx, segment, is_recovery, rep, points}
    where `points` is a columnar stream slice.
    """
    if _has_rep_work_segments(segments):
        result = _slice_intervals_by_velocity(streams, segments)
        if result is not None:
            return result

    # Compute total distance/time required by defined segments
    total_defined_m = 0
    total_defined_s = 0
    undefined_count = 0
    for seg in segments:
        reps = max(1, seg.get("repetitions") or 1)
        dist_m = (seg.get("distance_km") or 0) * 1000
        dur_s = (seg.get("duration_mins") or 0) * 60
        if dist_m > 0:
            total_defined_m += dist_m * reps
        elif dur_s > 0:
            total_defined_s += dur_s * reps
        else:
            undefined_count += 1
        # Account for recovery between reps
        rec_dist_m = (seg.get("recovery_distance_km") or 0) * 1000
        rec_dur_s = (seg.get("recovery_duration_mins") or 0) * 60
        if reps > 1:
            if rec_dist_m > 0:
                total_defined_m += rec_dist_m * (reps - 1)
            elif rec_dur_s > 0:
                total_defined_s += rec_dur_s * (reps - 1)

    n = _len(streams)
    if n >= 2:
        total_stream_m = _get(streams, "distance", n - 1) - _get(streams, "distance", 0)
        total_stream_s = _get(streams, "time", n - 1) - _get(streams, "time", 0)
    else:
        total_stream_m = 0
        total_stream_s = 0

    leftover_m = max(0, total_stream_m - total_defined_m)
    share_m = leftover_m / undefined_count if undefined_count > 0 else 0

    slices = []
    pos = 0

    for seg_idx, seg in enumerate(segments):
        reps = max(1, seg.get("repetitions") or 1)
        for rep in range(reps):
            dist_m = (seg.get("distance_km") or 0) * 1000
            dur_s = (seg.get("duration_mins") or 0) * 60

            if dist_m > 0:
                points, pos = _advance_by_distance(streams, pos, dist_m)
            elif dur_s > 0:
                points, pos = _advance_by_duration(streams, pos, dur_s)
            elif share_m > 0:
                points, pos = _advance_by_distance(streams, pos, share_m)
            else:
                points = _slice(streams, pos, n)
                pos = n

            slices.append({
                "segment_idx": seg_idx,
                "segment": seg,
                "is_recovery": False,
                "rep": rep + 1,
                "points": points,
            })

            rec_dur_s = (seg.get("recovery_duration_mins") or 0) * 60
            rec_dist_m = (seg.get("recovery_distance_km") or 0) * 1000
            has_recovery = rec_dur_s > 0 or rec_dist_m > 0
            if has_recovery and rep < reps - 1:
                if rec_dist_m > 0:
                    rec_points, pos = _advance_by_distance(streams, pos, rec_dist_m)
                elif rec_dur_s > 0:
                    rec_points, pos = _advance_by_duration(streams, pos, rec_dur_s)
                else:
                    rec_points = _slice(streams, pos, pos)

                if _len(rec_points):
                    rec_segment = {
                        "type": "recovery",
                        "distance_km": seg.get("recovery_distance_km"),
                        "duration_mins": seg.get("recovery_duration_mins"),
                    }
                    slices.append({
                        "segment_idx": seg_idx,
                        "segment": rec_segment,
                        "is_recovery": True,
                        "rep": rep + 1,
                        "points": rec_points,
                    })

    return slices


def _avg_speed_from_points(points: dict) -> float:
    """Compute average speed (m/s) from a columnar stream slice."""
    n = _len(points)
    if n < 2:
        return 0.0
    dist = _get(points, "distance", n - 1) - _get(points, "distance", 0)
    elapsed = _get(points, "time", n - 1) - _get(points, "time", 0)
    if elapsed <= 0:
        return 0.0
    return dist / elapsed


def _score_segment_slice(
    segment: dict,
    points: dict,
    sport_type: str,
    hr_zones: list[dict] | None,
) -> dict:
    """Score a single segment slice against its targets."""
    metrics: dict[str, dict] = {}

    n = _len(points)
    if n < 2:
        return {"overall_score": 0, "metrics": metrics}

    actual_dist_m = _get(points, "distance", n - 1) - _get(points, "distance", 0)
    actual_time_s = _get(points, "time", n - 1) - _get(points, "time", 0)

    dist_km = segment.get("distance_km")
    if dist_km:
        metrics["distance"] = _score_distance(dist_km, actual_dist_m / 1000)

    dur_mins = segment.get("duration_mins")
    if dur_mins and not dist_km:
        metrics["duration"] = _score_duration(dur_mins, actual_time_s / 60)

    pace_min = segment.get("target_pace_min")
    pace_max = segment.get("target_pace_max")
    if (pace_min is not None or pace_max is not None):
        avg_spd = _avg_speed_from_points(points)
        if avg_spd > 0:
            actual_pace, unit = convert_speed(avg_spd, sport_type)
            metrics["pace"] = _score_pace(pace_min, pace_max, actual_pace, unit)

    target_zone = segment.get("target_hr_zone")
    target_pct = segment.get("target_zone_pct") or 80
    if target_zone is not None and hr_zones:
        actual_pct = _compute_hr_zone_pct(points, target_zone, hr_zones)
        if actual_pct is not None:
            metrics["hr_zone"] = {
                "target_zone": target_zone,
                **_score_hr_zone(target_pct, actual_pct),
            }

    avg_spd = _avg_speed_from_points(points)
    if avg_spd > 0:
        actual_pace_val, pace_unit = convert_speed(avg_spd, sport_type)
        actual_pace_display = round(actual_pace_val, 2)
    else:
        actual_pace_display = None
        pace_unit = ""

    scores = [m["score"] for m in metrics.values()]
    overall = round(sum(scores) / len(scores)) if scores else None

    return {"overall_score": overall, "metrics": metrics, "actual_pace": actual_pace_display, "pace_unit": pace_unit}


def _compute_segmented_score(
    session: dict,
    activity: dict,
    segments: list[dict],
    hr_zones: list[dict] | None,
    streams: dict,
) -> dict:
    """Orchestrate segment slicing + scoring for a structured workout."""
    sport_type = session.get("sport_type", "")
    slices = slice_streams_by_segments(streams, segments, sport_type)

    segment_scores = []
    work_scores = []
    work_distances = []

    for sl in slices:
        seg = sl["segment"]
        pts = sl["points"]
        score_data = _score_segment_slice(seg, pts, session.get("sport_type", ""), hr_zones)

        n_pts = _len(pts)
        if n_pts >= 2:
            start_m = _get(pts, "distance", 0)
            end_m = _get(pts, "distance", n_pts - 1)
            actual_dist_m = end_m - start_m
            actual_time_s = _get(pts, "time", n_pts - 1) - _get(pts, "time", 0)
        else:
            start_m = 0
            end_m = 0
            actual_dist_m = 0
            actual_time_s = 0

        entry = {
            "segment_idx": sl["segment_idx"],
            "type": seg.get("type", "work"),
            "is_recovery": sl["is_recovery"],
            "rep": sl["rep"],
            "label": seg.get("label"),
            "distance_km": seg.get("distance_km"),
            "duration_mins": seg.get("duration_mins"),
            "start_km": round(start_m / 1000, 3),
            "end_km": round(end_m / 1000, 3),
            "actual_distance_km": round(actual_dist_m / 1000, 3),
            "actual_duration_mins": round(actual_time_s / 60, 2),
            **score_data,
        }
        segment_scores.append(entry)

        if not sl["is_recovery"] and seg.get("type") in ("work", "warmup", "cooldown") and score_data["overall_score"] is not None:
            dist_weight = seg.get("distance_km") or seg.get("duration_mins") or 1
            work_scores.append(score_data["overall_score"])
            work_distances.append(dist_weight)

    if work_scores and sum(work_distances) > 0:
        total_weight = sum(work_distances)
        overall = round(sum(s * w for s, w in zip(work_scores, work_distances)) / total_weight)
    else:
        overall = 0

    return {
        "overall_score": overall,
        "matched_activity_id": activity.get("id"),
        "mode": "segmented",
        "segment_scores": segment_scores,
    }


def compute_execution_score(
    session: dict,
    activity: dict,
    hr_zones: list[dict] | None = None,
    activity_streams: dict | None = None,
) -> dict:
    """Compute execution score comparing actual activity against session targets.

    `activity_streams` must be a columnar streams dict (or None when streams
    aren't available — non-streamed metrics still score).

    Returns dict with overall_score, matched_activity_id, and per-metric breakdown.
    Only metrics with targets set in the session are included.
    If the session has segments, delegates to segmented scoring.
    """
    segments = session.get("segments")
    if segments and isinstance(segments, list) and len(segments) > 0:
        if activity_streams and _len(activity_streams) > 0:
            return _compute_segmented_score(session, activity, segments, hr_zones, activity_streams)

    metrics: dict[str, dict] = {}

    planned_dist = session.get("planned_distance_km")
    if planned_dist is not None:
        actual_dist = activity.get("distance_km") or (activity.get("distance", 0) / 1000)
        metrics["distance"] = _score_distance(planned_dist, actual_dist)

    planned_dur = session.get("planned_duration_mins")
    if planned_dur is not None:
        actual_secs = activity.get("moving_time") or 0
        metrics["duration"] = _score_duration(planned_dur, actual_secs / 60)

    target_avg_pace = session.get("target_avg_pace")
    if target_avg_pace is not None:
        avg_speed = activity.get("average_speed") or 0
        if avg_speed > 0:
            actual_pace, unit = convert_speed(avg_speed, activity.get("sport_type"))
            if target_avg_pace > 0:
                deviation = abs(1 - actual_pace / target_avg_pace)
                penalty = _pace_penalty(deviation, unit)
                score = _clamp(100 - penalty)
            else:
                score = 0
            metrics["avg_pace"] = {
                "target": target_avg_pace,
                "actual": round(actual_pace, 2),
                "score": round(score),
                "unit": unit,
            }

    target_pace_min = session.get("target_pace_min")
    target_pace_max = session.get("target_pace_max")
    if target_pace_min is not None or target_pace_max is not None:
        avg_speed = activity.get("average_speed") or 0
        if avg_speed > 0:
            actual_pace, unit = convert_speed(avg_speed, activity.get("sport_type"))
            metrics["pace"] = _score_pace(target_pace_min, target_pace_max, actual_pace, unit)

    target_hr_zone = session.get("target_hr_zone")
    target_zone_pct = session.get("target_zone_pct") or 80
    if target_hr_zone is not None and hr_zones:
        if activity_streams and _len(activity_streams) > 0:
            actual_pct = _compute_hr_zone_pct(activity_streams, target_hr_zone, hr_zones)
            if actual_pct is not None:
                metrics["hr_zone"] = {
                    "target_zone": target_hr_zone,
                    **_score_hr_zone(target_zone_pct, actual_pct),
                }

    scores = [m["score"] for m in metrics.values()]
    overall = round(sum(scores) / len(scores)) if scores else 0

    return {
        "overall_score": overall,
        "matched_activity_id": activity.get("id"),
        "metrics": metrics,
    }


def has_targets(session: dict) -> bool:
    """Check if a session has any scoring targets set."""
    segments = session.get("segments")
    if segments and isinstance(segments, list) and len(segments) > 0:
        return True
    return any(
        session.get(k) is not None
        for k in ("planned_distance_km", "planned_duration_mins",
                   "target_avg_pace", "target_pace_min", "target_pace_max",
                   "target_hr_zone")
    )

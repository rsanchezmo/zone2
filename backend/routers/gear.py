import json
import logging

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from backend._ttl_cache import TTLCache
from backend.dependencies import get_z2
from backend.services.gear import gear_label, resolve_gear_catalog
from zone2.core import Zone2

router = APIRouter()
logger = logging.getLogger(__name__)

_gear_cache = TTLCache(maxsize=64, ttl_seconds=900)


def clear_gear_cache():
    _gear_cache.clear()


def _f(value) -> float:
    """Coerce a possibly-NaN pandas scalar to a plain float."""
    if value is None or pd.isna(value):
        return 0.0
    return float(value)


def _gear_activities(z2: Zone2) -> pd.DataFrame:
    """Activities carrying a gear_id, dates already parsed."""
    activities = z2.strava_analytics._get_prepared_activities()
    if activities.empty or "gear_id" not in activities.columns:
        return activities.iloc[0:0]
    return activities[activities["gear_id"].notna()]


def _rollup(gear: dict, acts: pd.DataFrame) -> dict:
    """Gear identity plus the totals derived from its synced activities.

    `strava_distance_km` is Strava's lifetime odometer; `distance_km` only
    covers activities present in the local cache, so the two differ whenever
    history predates the cache.
    """
    summary = {
        "id": gear["id"],
        "name": gear.get("name") or "",
        "nickname": (gear.get("nickname") or "").strip() or None,
        "label": gear_label(gear),
        "kind": gear["kind"],
        "primary": bool(gear.get("primary")),
        "retired": bool(gear.get("retired")),
        "brand_name": gear.get("brand_name"),
        "model_name": gear.get("model_name"),
        "strava_distance_km": round(_f(gear.get("converted_distance")), 1),
        "activities": int(len(acts)),
        "distance_km": 0.0,
        "moving_time_s": 0,
        "elevation_m": 0.0,
        "first_activity": None,
        "last_activity": None,
        "active_days": 0,
    }
    if acts.empty:
        return summary

    dates = acts["start_date_local"]
    first, last = dates.min(), dates.max()
    summary.update({
        "distance_km": round(_f(acts["distance"].sum()) / 1000, 1),
        "moving_time_s": int(_f(acts["moving_time"].sum())),
        "elevation_m": round(_f(acts["total_elevation_gain"].sum())),
        "first_activity": first.date().isoformat(),
        "last_activity": last.date().isoformat(),
        "active_days": int((last - first).days) + 1,
    })
    return summary


def _all_time_bests(z2: Zone2) -> dict[int, int]:
    """distance_m -> fastest elapsed time across every activity with best efforts.

    Strava computes these server-side and ships them on the detailed activity,
    so this needs no streams.
    """
    activities = z2.strava_analytics._get_prepared_activities()
    if activities.empty or "best_efforts" not in activities.columns:
        return {}

    bests: dict[int, int] = {}
    for raw in activities["best_efforts"].dropna():
        for effort in _parse_efforts(raw):
            distance, elapsed = effort.get("distance"), effort.get("elapsed_time")
            if distance and elapsed:
                distance = int(distance)
                bests[distance] = min(bests.get(distance, elapsed), int(elapsed))
    return bests


def _parse_efforts(raw) -> list[dict]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    if raw is None or isinstance(raw, float):
        return []
    return [e for e in raw if isinstance(e, dict)]


def _best_efforts_for(acts: pd.DataFrame, all_time: dict[int, int]) -> list[dict]:
    """Fastest effort per standard distance in this gear, flagged when it also
    happens to be the athlete's all-time best."""
    if acts.empty or "best_efforts" not in acts.columns:
        return []

    best: dict[int, dict] = {}
    for _, row in acts.iterrows():
        for effort in _parse_efforts(row.get("best_efforts")):
            distance, elapsed = effort.get("distance"), effort.get("elapsed_time")
            if not distance or not elapsed:
                continue
            distance, elapsed = int(distance), int(elapsed)
            current = best.get(distance)
            if current is None or elapsed < current["elapsed_time"]:
                best[distance] = {
                    "distance_m": distance,
                    "name": effort.get("name") or f"{distance} m",
                    "elapsed_time": elapsed,
                    "activity_id": int(row["id"]),
                    "activity_name": row.get("name") or "",
                    "date": row["start_date_local"].date().isoformat(),
                    "all_time_best": all_time.get(distance) == elapsed,
                }

    return [best[d] for d in sorted(best)]


def _monthly(acts: pd.DataFrame) -> list[dict]:
    """Volume per calendar month, gap-filled so idle months stay visible."""
    if acts.empty:
        return []

    by_month = acts.set_index("start_date_local").resample("MS").agg(
        distance_m=("distance", "sum"),
        activities=("id", "count"),
        moving_time_s=("moving_time", "sum"),
    )
    return [
        {
            "month": ts.strftime("%Y-%m"),
            "distance_km": round(_f(row["distance_m"]) / 1000, 1),
            "activities": int(row["activities"]),
            "moving_time_s": int(_f(row["moving_time_s"])),
        }
        for ts, row in by_month.iterrows()
    ]


def _activity_points(acts: pd.DataFrame) -> list[dict]:
    """One point per activity — feeds both the cumulative ramp and the pace
    scatter, so the page loads a single series."""
    ordered = acts.sort_values("start_date_local")
    cumulative_km = (ordered["distance"].cumsum() / 1000).round(2)

    points = []
    for (_, row), total in zip(ordered.iterrows(), cumulative_km):
        speed = row.get("average_speed")
        hr = row.get("average_heartrate")
        points.append({
            "id": int(row["id"]),
            "name": row.get("name") or "",
            "date": row["start_date_local"].date().isoformat(),
            "sport_type": row.get("sport_type") or "",
            "distance_km": round(_f(row.get("distance")) / 1000, 2),
            "cumulative_km": float(total),
            "speed_ms": round(float(speed), 3) if speed and not pd.isna(speed) else None,
            "heartrate": round(float(hr)) if hr and not pd.isna(hr) else None,
        })
    return points


def _sport_mix(acts: pd.DataFrame) -> list[dict]:
    grouped = acts.groupby("sport_type").agg(
        activities=("id", "count"),
        distance_m=("distance", "sum"),
    ).sort_values("distance_m", ascending=False)
    return [
        {
            "sport_type": sport,
            "activities": int(row["activities"]),
            "distance_km": round(_f(row["distance_m"]) / 1000, 1),
        }
        for sport, row in grouped.iterrows()
    ]


def _extreme(acts: pd.DataFrame, column: str, largest: bool = True) -> dict | None:
    valid = acts[acts[column].notna()]
    if valid.empty:
        return None
    row = valid.loc[valid[column].idxmax() if largest else valid[column].idxmin()]
    return {
        "id": int(row["id"]),
        "name": row.get("name") or "",
        "date": row["start_date_local"].date().isoformat(),
        "distance_km": round(_f(row.get("distance")) / 1000, 2),
        "moving_time_s": int(_f(row.get("moving_time"))),
        "speed_ms": round(_f(row.get("average_speed")), 3) or None,
        "elevation_m": round(_f(row.get("total_elevation_gain"))),
    }


@router.get("")
def list_gear(z2: Zone2 = Depends(get_z2)):
    """Every gear item with its activity rollup — powers the rotation timeline."""
    key = ("list", z2.strava_activities_cache.cache_version)
    cached = _gear_cache.get(key)
    if cached is not None:
        return cached

    catalog = resolve_gear_catalog(z2)
    activities = _gear_activities(z2)
    by_gear = dict(tuple(activities.groupby("gear_id"))) if not activities.empty else {}

    gear = [
        _rollup(item, by_gear.get(gear_id, activities.iloc[0:0]))
        for gear_id, item in catalog.items()
    ]
    gear.sort(key=lambda g: (g["last_activity"] or "", g["distance_km"]), reverse=True)

    result = {"gear": gear}
    _gear_cache.set(key, result)
    return result


@router.get("/{gear_id}")
def gear_detail(gear_id: str, z2: Zone2 = Depends(get_z2)):
    key = ("detail", gear_id, z2.strava_activities_cache.cache_version)
    cached = _gear_cache.get(key)
    if cached is not None:
        return cached

    catalog = resolve_gear_catalog(z2)
    gear = catalog.get(gear_id)
    if gear is None:
        raise HTTPException(status_code=404, detail=f"Unknown gear id {gear_id}")

    all_gear_activities = _gear_activities(z2)
    acts = (
        all_gear_activities[all_gear_activities["gear_id"] == gear_id]
        if not all_gear_activities.empty
        else all_gear_activities
    )

    summary = _rollup(gear, acts)

    # Sibling gear of the same kind, so the ramp can reference how far the
    # other pairs went.
    peers = [
        _rollup(item, all_gear_activities[all_gear_activities["gear_id"] == other_id]
                if not all_gear_activities.empty else all_gear_activities)
        for other_id, item in catalog.items()
        if other_id != gear_id and item["kind"] == gear["kind"]
    ]
    peers = sorted(
        ({"id": p["id"], "label": p["label"], "distance_km": p["distance_km"], "retired": p["retired"]}
         for p in peers if p["distance_km"] > 0),
        key=lambda p: p["distance_km"],
        reverse=True,
    )

    if acts.empty:
        result = {
            "gear": summary,
            "totals": None,
            "activities": [],
            "monthly": [],
            "sport_mix": [],
            "best_efforts": [],
            "extremes": {},
            "peers": peers,
        }
        _gear_cache.set(key, result)
        return result

    moving_time_s = summary["moving_time_s"]
    distance_m = _f(acts["distance"].sum())
    hr = acts["average_heartrate"].dropna() if "average_heartrate" in acts.columns else pd.Series(dtype=float)

    totals = {
        "prs": int(_f(acts["pr_count"].sum())) if "pr_count" in acts.columns else 0,
        "achievements": int(_f(acts["achievement_count"].sum())) if "achievement_count" in acts.columns else 0,
        "calories": int(_f(acts["calories"].sum())) if "calories" in acts.columns else 0,
        # Aggregate pace, not the mean of per-activity paces — long runs should
        # weigh more than a shakeout.
        "avg_speed_ms": round(distance_m / moving_time_s, 3) if moving_time_s else None,
        "avg_distance_km": round(distance_m / 1000 / len(acts), 2),
        "avg_heartrate": round(float(hr.mean())) if not hr.empty else None,
        "days_per_activity": round(summary["active_days"] / len(acts), 1) if len(acts) else None,
    }

    result = {
        "gear": summary,
        "totals": totals,
        "activities": _activity_points(acts),
        "monthly": _monthly(acts),
        "sport_mix": _sport_mix(acts),
        "best_efforts": _best_efforts_for(acts, _all_time_bests(z2)),
        "extremes": {
            "longest": _extreme(acts, "distance"),
            "fastest": _extreme(acts, "average_speed"),
            "biggest_climb": _extreme(acts, "total_elevation_gain"),
        },
        "peers": peers,
    }
    _gear_cache.set(key, result)
    return result

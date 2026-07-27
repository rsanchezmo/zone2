from typing import Literal

from zone2.core import Zone2

GearKind = Literal["shoes", "bikes"]


def gear_kind(gear_id: str) -> GearKind:
    """Strava ids are prefixed by type: `b…` for bikes, `g…` for shoes."""
    return "bikes" if gear_id.startswith("b") else "shoes"


def gear_label(gear: dict) -> str:
    nickname = (gear.get("nickname") or "").strip()
    return nickname or gear.get("name") or gear.get("id", "")


def resolve_gear_catalog(z2: Zone2) -> dict[str, dict]:
    """Every gear item the athlete owns, keyed by id, tagged with its `kind`.

    Strava omits retired gear from /athlete, but activities still carry the
    gear_id — those items are recovered via /gear/{id} and merged in.
    """
    profile = z2.strava_user_cache.get_athlete_profile()
    catalog = {
        g["id"]: dict(g)
        for g in (profile.get("shoes") or []) + (profile.get("bikes") or [])
    }

    activities = z2.strava_activities_cache.activities
    if not activities.empty and "gear_id" in activities.columns:
        missing = sorted(set(activities["gear_id"].dropna()) - set(catalog))
        for gear in z2.strava_user_cache.get_gear_details(missing).values():
            catalog[gear["id"]] = dict(gear)

    for gear_id, gear in catalog.items():
        gear["kind"] = gear_kind(gear_id)

    return catalog

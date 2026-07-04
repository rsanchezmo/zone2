import json
import logging
from pathlib import Path
from threading import Lock

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.config import settings
from backend.dependencies import get_si
from strava.strava_intelligence import StravaIntelligence
from strava.strava_map_matching import StravaMapMatcher
from strava.strava_utils import get_activities_as_gdf

router = APIRouter()
logger = logging.getLogger(__name__)

_matchers: dict[str, StravaMapMatcher] = {}
_matchers_lock = Lock()

# Per-city sync status; matching runs in a BackgroundTasks thread.
_sync_status: dict[str, dict] = {}
_sync_lock = Lock()


def _osm_dir() -> Path:
    return Path(settings.workdir) / "osm_maps"


def _known_cities() -> dict[str, str]:
    """slug -> city_name for every city with a slim map on disk."""
    cities = {}
    for edges_fp in sorted(_osm_dir().glob("*_edges.parquet")):
        if edges_fp.name.endswith("_covered_edges.parquet"):
            continue
        slug = edges_fp.name.removesuffix("_edges.parquet")
        meta_fp = _osm_dir() / f"{slug}_meta.json"
        city_name = slug
        if meta_fp.exists():
            try:
                city_name = json.loads(meta_fp.read_text()).get("city_name", slug)
            except json.JSONDecodeError:
                pass
        cities[slug] = city_name
    return cities


def _get_matcher(slug: str) -> StravaMapMatcher:
    cities = _known_cities()
    if slug not in cities:
        raise HTTPException(status_code=404, detail=f"No coverage map for '{slug}'")
    with _matchers_lock:
        if slug not in _matchers:
            _matchers[slug] = StravaMapMatcher(
                city_name=cities[slug], workdir=Path(settings.workdir)
            )
        return _matchers[slug]


@router.get("/cities")
def list_cities():
    out = []
    for slug, city_name in _known_cities().items():
        matcher = _get_matcher(slug)
        stats = matcher.coverage_stats_from_state()
        out.append({
            "slug": slug,
            "city_name": city_name,
            "num_matched_activities": len(matcher.matched_activity_ids()),
            **{k: v for k, v in stats.items() if not k.startswith("_")},
        })
    return out


@router.get("/{slug}/summary")
def coverage_summary(slug: str):
    matcher = _get_matcher(slug)
    stats = matcher.coverage_stats_from_state()
    return {
        "slug": slug,
        "city_name": matcher.city_name,
        "num_matched_activities": len(matcher.matched_activity_ids()),
        **{k: v for k, v in stats.items() if not k.startswith("_")},
    }


@router.get("/{slug}/edges")
def coverage_edges(
    slug: str,
    covered: bool = Query(True),
    bbox: str | None = Query(None, description="south,west,north,east — required for covered=false"),
):
    """Runnable edges as GeoJSON. Covered edges are few; uncovered edges are
    the whole city, so they must be bounded by a bbox."""
    if not covered and not bbox:
        raise HTTPException(status_code=400, detail="bbox is required for covered=false")

    matcher = _get_matcher(slug)
    und = matcher.undirected_with_covered()
    subset = und[und["covered"] == covered]

    subset = subset.to_crs("EPSG:4326")
    if bbox:
        try:
            south, west, north, east = (float(x) for x in bbox.split(","))
        except ValueError:
            raise HTTPException(status_code=400, detail="bbox must be south,west,north,east")
        subset = subset.cx[west:east, south:north]

    features = []
    for geom, name in zip(subset.geometry, subset["name"]):
        if geom is None or geom.is_empty:
            continue
        coords = [[round(x, 6), round(y, 6)] for x, y in geom.coords]
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"name": None if name is None or str(name) == "nan" else str(name)},
        })
    return {"type": "FeatureCollection", "features": features}


@router.get("/{slug}/districts")
def coverage_districts(slug: str, admin_level: int = Query(9, ge=4, le=11)):
    matcher = _get_matcher(slug)
    return matcher.coverage_by_district(admin_level=admin_level)


class AreaRequest(BaseModel):
    # Polygon vertices as [lat, lon]
    points: list[tuple[float, float]] = Field(min_length=3)


@router.post("/{slug}/area")
def coverage_area(slug: str, payload: AreaRequest):
    matcher = _get_matcher(slug)
    return matcher.coverage_in_polygon(payload.points)


def _run_coverage_sync(slug: str, si: StravaIntelligence, sport_types: list[str]):
    err = None
    try:
        matcher = _get_matcher(slug)
        gdf = get_activities_as_gdf(si.strava_activities_cache.activities)
        gdf = gdf[gdf["sport_type"].isin(sport_types)]
        stats = matcher.match_incremental(gdf)
        logger.info("Coverage sync for %s done: %s%%", slug, stats.get("coverage_pct"))
    except Exception as e:
        logger.exception("Coverage sync for %s failed", slug)
        err = f"{type(e).__name__}: {e}"
    finally:
        with _sync_lock:
            _sync_status[slug] = {"running": False, "last_error": err}


@router.post("/{slug}/sync")
def trigger_coverage_sync(
    slug: str,
    background_tasks: BackgroundTasks,
    sport_types: str = Query("Run", description="Comma-separated sport types"),
    si: StravaIntelligence = Depends(get_si),
):
    _get_matcher(slug)  # 404 before claiming the slot
    with _sync_lock:
        if _sync_status.get(slug, {}).get("running"):
            raise HTTPException(status_code=409, detail="Coverage sync already running")
        _sync_status[slug] = {"running": True, "last_error": None}
    sports = [s.strip() for s in sport_types.split(",") if s.strip()]
    background_tasks.add_task(_run_coverage_sync, slug, si, sports)
    return {"status": "started"}


@router.get("/{slug}/sync/status")
def coverage_sync_status(slug: str):
    with _sync_lock:
        return _sync_status.get(slug, {"running": False, "last_error": None})

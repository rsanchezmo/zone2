from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse

from backend.dependencies import get_si
from backend.export_cache import ExportCache
from backend.routers.stats import _get_weekly_report_cached
from strava.strava_intelligence import StravaIntelligence
from strava.strava_visualizer import StravaVisualizer

router = APIRouter()

_cache = ExportCache()


def _clamp_dpi(dpi: int) -> int:
    return max(72, min(600, dpi))


def _png_response(buf):
    if buf is None:
        raise HTTPException(status_code=500, detail="Failed to generate image")
    return StreamingResponse(buf, media_type="image/png",
                             headers={"Content-Disposition": "inline; filename=export.png"})


def _safe_export(fn):
    """Wrap a matplotlib export call to catch errors gracefully."""
    try:
        with StravaVisualizer._mpl_lock:
            return fn()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Export failed: {e}")


@router.get("/weekly-report")
def export_weekly_report(
    week_start: str | None = None,
    neon_color: str = "#fc0101",
    dpi: int = 300,
    si: StravaIntelligence = Depends(get_si),
):
    dpi = _clamp_dpi(dpi)
    params = {"week_start": week_start, "neon_color": neon_color, "dpi": dpi}
    cached = _cache.get("weekly-report", params)
    if cached:
        return _png_response(cached)

    # Reuse the stats router's TTL cache — same analytics call, same underlying
    # data, so serving this from the shared cache avoids a duplicate compute
    # whenever the UI has already hit /api/stats/weekly-report.
    report = _get_weekly_report_cached(si, week_start)
    from datetime import datetime, timedelta
    week_start_str = report.get("week_start")
    prev_report = None
    if week_start_str:
        prev_monday = datetime.strptime(week_start_str, "%Y-%m-%d") - timedelta(days=7)
        prev_report = _get_weekly_report_cached(si, prev_monday.strftime("%Y-%m-%d"))

    buf = _safe_export(lambda: si.strava_visualizer.plot_weekly_report(
        weekly_report=report, neon_color=neon_color,
        last_week_report=prev_report, return_buffer=True, dpi=dpi,
    ))
    _cache.put("weekly-report", params, buf)
    return _png_response(buf)


@router.get("/year-in-sport")
def export_year_in_sport(
    year: int = Query(default=2026),
    main_sport: str = Query(default="Run"),
    variant: str = Query(default="main"),
    neon_color: str = "#fc0101",
    dpi: int = 300,
    si: StravaIntelligence = Depends(get_si),
):
    dpi = _clamp_dpi(dpi)
    params = {"year": year, "main_sport": main_sport, "variant": variant, "neon_color": neon_color, "dpi": dpi}
    cached = _cache.get("year-in-sport", params)
    if cached:
        return _png_response(cached)

    main = si.strava_analytics.get_year_in_sport(year, main_sport)
    all_sports = si.strava_analytics.get_all_year_in_sport(year)
    year_in_sport = {main_sport: main, 'all': all_sports}

    if variant == "totals":
        buf = _safe_export(lambda: si.strava_visualizer.plot_year_in_sport_totals(
            year=year, year_in_sport=year_in_sport, neon_color=neon_color,
            return_buffer=True, dpi=dpi,
        ))
    else:
        buf = _safe_export(lambda: si.strava_visualizer.plot_year_in_sport_main(
            year=year, year_in_sport=year_in_sport, main_sport=main_sport,
            neon_color=neon_color, return_buffer=True, dpi=dpi,
        ))
    _cache.put("year-in-sport", params, buf)
    return _png_response(buf)


@router.get("/activity/{activity_id}")
def export_activity(
    activity_id: int,
    neon_color: str = "#fc0101",
    title: str | None = None,
    dpi: int = 300,
    si: StravaIntelligence = Depends(get_si),
):
    dpi = _clamp_dpi(dpi)
    params = {"activity_id": activity_id, "neon_color": neon_color, "title": title, "dpi": dpi}
    cached = _cache.get("activity", params)
    if cached:
        return _png_response(cached)

    buf = _safe_export(lambda: si.strava_visualizer.plot_activity(
        activity_id=activity_id, strava_endpoint=si.strava_endpoint,
        neon_color=neon_color, title=title, return_buffer=True, dpi=dpi,
    ))
    _cache.put("activity", params, buf)
    return _png_response(buf)


@router.get("/thunderstorm-heatmap")
def export_thunderstorm_heatmap(
    location: str | None = None,
    sport_types: str | None = None,
    year: int | None = None,
    radius_km: float = 20.0,
    neon_color: str = "#fc0101",
    show_title: bool = True,
    dpi: int = 600,
    si: StravaIntelligence = Depends(get_si),
):
    dpi = _clamp_dpi(dpi)
    params = {"location": location, "sport_types": sport_types, "year": year,
              "radius_km": radius_km, "neon_color": neon_color, "show_title": show_title, "dpi": dpi}
    cached = _cache.get("thunderstorm-heatmap", params)
    if cached:
        return _png_response(cached)

    sports = [s.strip() for s in sport_types.split(",")] if sport_types else None
    buf = _safe_export(lambda: si.strava_visualizer.thunderstorm_heatmap(
        location=location, sport_types=sports, radius_km=radius_km, year=year,
        neon_color=neon_color, show_title=show_title, return_buffer=True, dpi=dpi,
    ))
    _cache.put("thunderstorm-heatmap", params, buf)
    return _png_response(buf)


@router.get("/efficiency-factor")
def export_efficiency_factor(
    sport_type: str = "Run",
    dpi: int = 600,
    si: StravaIntelligence = Depends(get_si),
):
    dpi = _clamp_dpi(dpi)
    params = {"sport_type": sport_type, "dpi": dpi}
    cached = _cache.get("efficiency-factor", params)
    if cached:
        return _png_response(cached)

    buf = _safe_export(lambda: si.strava_visualizer.plot_efficiency_factor(
        sport_type=sport_type, return_buffer=True, dpi=dpi,
    ))
    _cache.put("efficiency-factor", params, buf)
    return _png_response(buf)


@router.get("/performance-frontier")
def export_performance_frontier(
    sport_types: str = "Run",
    dpi: int = 600,
    si: StravaIntelligence = Depends(get_si),
):
    dpi = _clamp_dpi(dpi)
    sports = [s.strip() for s in sport_types.split(",")]
    params = {"sport_types": sport_types, "dpi": dpi}
    cached = _cache.get("performance-frontier", params)
    if cached:
        return _png_response(cached)

    buf = _safe_export(lambda: si.strava_visualizer.plot_performance_frontier(
        sport_types=sports, return_buffer=True, dpi=dpi,
    ))
    _cache.put("performance-frontier", params, buf)
    return _png_response(buf)


@router.get("/activity-clock")
def export_activity_clock(
    sport_types: str | None = None,
    dpi: int = 600,
    si: StravaIntelligence = Depends(get_si),
):
    dpi = _clamp_dpi(dpi)
    params = {"sport_types": sport_types, "dpi": dpi}
    cached = _cache.get("activity-clock", params)
    if cached:
        return _png_response(cached)

    sports = [s.strip() for s in sport_types.split(",")] if sport_types else None
    buf = _safe_export(lambda: si.strava_visualizer.activity_clock(
        sport_types=sports, return_buffer=True, dpi=dpi,
    ))
    _cache.put("activity-clock", params, buf)
    return _png_response(buf)

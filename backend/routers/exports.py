from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse

from backend.dependencies import get_si
from strava.strava_intelligence import StravaIntelligence
from strava.strava_visualizer import StravaVisualizer

router = APIRouter()


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
    si: StravaIntelligence = Depends(get_si),
):
    report = si.strava_analytics.get_weekly_report(week_start)
    from datetime import datetime, timedelta
    week_start_str = report.get("week_start")
    prev_report = None
    if week_start_str:
        prev_monday = datetime.strptime(week_start_str, "%Y-%m-%d") - timedelta(days=7)
        prev_report = si.strava_analytics.get_weekly_report(prev_monday.strftime("%Y-%m-%d"))

    buf = _safe_export(lambda: si.strava_visualizer.plot_weekly_report(
        weekly_report=report, neon_color=neon_color,
        last_week_report=prev_report, return_buffer=True,
    ))
    return _png_response(buf)


@router.get("/year-in-sport")
def export_year_in_sport(
    year: int = Query(default=2026),
    main_sport: str = Query(default="Run"),
    variant: str = Query(default="main"),
    neon_color: str = "#fc0101",
    si: StravaIntelligence = Depends(get_si),
):
    main = si.strava_analytics.get_year_in_sport(year, main_sport)
    all_sports = si.strava_analytics.get_all_year_in_sport(year)
    year_in_sport = {main_sport: main, 'all': all_sports}

    if variant == "totals":
        buf = _safe_export(lambda: si.strava_visualizer.plot_year_in_sport_totals(
            year=year, year_in_sport=year_in_sport, neon_color=neon_color, return_buffer=True,
        ))
    else:
        buf = _safe_export(lambda: si.strava_visualizer.plot_year_in_sport_main(
            year=year, year_in_sport=year_in_sport, main_sport=main_sport,
            neon_color=neon_color, return_buffer=True,
        ))
    return _png_response(buf)


@router.get("/activity/{activity_id}")
def export_activity(
    activity_id: int,
    neon_color: str = "#fc0101",
    si: StravaIntelligence = Depends(get_si),
):
    buf = _safe_export(lambda: si.strava_visualizer.plot_activity(
        activity_id=activity_id, strava_endpoint=si.strava_endpoint,
        neon_color=neon_color, return_buffer=True,
    ))
    return _png_response(buf)


@router.get("/thunderstorm-heatmap")
def export_thunderstorm_heatmap(
    location: str | None = None,
    sport_types: str | None = None,
    year: int | None = None,
    radius_km: float = 20.0,
    si: StravaIntelligence = Depends(get_si),
):
    sports = [s.strip() for s in sport_types.split(",")] if sport_types else None
    buf = _safe_export(lambda: si.strava_visualizer.thunderstorm_heatmap(
        location=location, sport_types=sports, radius_km=radius_km, year=year, return_buffer=True,
    ))
    return _png_response(buf)


@router.get("/efficiency-factor")
def export_efficiency_factor(
    sport_type: str = "Run",
    si: StravaIntelligence = Depends(get_si),
):
    buf = _safe_export(lambda: si.strava_visualizer.plot_efficiency_factor(
        sport_type=sport_type, return_buffer=True,
    ))
    return _png_response(buf)


@router.get("/performance-frontier")
def export_performance_frontier(
    sport_types: str = "Run",
    si: StravaIntelligence = Depends(get_si),
):
    sports = [s.strip() for s in sport_types.split(",")]
    buf = _safe_export(lambda: si.strava_visualizer.plot_performance_frontier(
        sport_types=sports, return_buffer=True,
    ))
    return _png_response(buf)


@router.get("/activity-clock")
def export_activity_clock(
    sport_types: str | None = None,
    si: StravaIntelligence = Depends(get_si),
):
    sports = [s.strip() for s in sport_types.split(",")] if sport_types else None
    buf = _safe_export(lambda: si.strava_visualizer.activity_clock(
        sport_types=sports, return_buffer=True,
    ))
    return _png_response(buf)

"""Week and year boundaries in training load and the reports: ISO week 53 (2026 has one), New
Year's Day mid-week, a fitness series running from one year into the plan of the next, and the
analytics and weekly totals on a pinned athlete's clock. Activities are made up."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.services import training
from zone2.clock import Clock
from zone2.reports import activities_per_week, week_bounds, year_activities
from zone2.training_load import RE_DISPLAY_SCALE, DailyLoad, fitness_form, weekly_relative_effort
from zone2.utils import SportCategory, previous_week
from tests.synthetic import ZONES, FakeActivitiesCache, FakeUserCache, activities_frame

UTC = timezone.utc
# Week 53 of 2026 runs Monday 28 December to Sunday 3 January 2027
W53_MONDAY, NEW_YEARS_DAY, W53_SUNDAY, W01_MONDAY = (date(2026, 12, 28), date(2027, 1, 1), date(2027, 1, 3),
                                                     date(2027, 1, 4))


def clock_at(at: datetime) -> Clock:
    return Clock(lambda: UTC, lambda: at)


def test_the_weeks_around_new_year():
    assert W53_MONDAY.isocalendar()[:2] == (2026, 53) and W01_MONDAY.isocalendar()[:2] == (2027, 1)
    end_of_w53 = pd.Timestamp("2027-01-03T23:59:59", tz="UTC")
    assert week_bounds(NEW_YEARS_DAY.isoformat(), None, datetime.now(UTC)) == (pd.Timestamp("2026-12-28", tz="UTC"),
                                                                              end_of_w53)
    # The current week, late on its Sunday and just after midnight on the next Monday
    assert week_bounds(None, None, datetime(2027, 1, 3, 23, 59, tzinfo=UTC))[0] == datetime(2026, 12, 28, tzinfo=UTC)
    assert week_bounds(None, None, datetime(2027, 1, 4, 0, 1, tzinfo=UTC))[0] == datetime(2027, 1, 4, tzinfo=UTC)
    assert week_bounds("2026-12-31", "2027-01-02", datetime.now(UTC))[1] == pd.Timestamp("2027-01-02T23:59:59",
                                                                                        tz="UTC")


def test_the_week_before_crosses_the_year():
    # Wednesday of the first week of 2027: week 53 compared up to its Wednesday
    assert previous_week("2027-01-04", date(2027, 1, 6)) == ("2026-12-28", "2026-12-30")
    assert previous_week("2027-01-04", date(2027, 1, 20)) == ("2026-12-28", None)
    assert previous_week("2026-12-28", W53_MONDAY) == ("2026-12-21", "2026-12-21")
    # On its Sunday the week is still running, so the one before is cut at its own Sunday
    assert previous_week("2026-12-28", W53_SUNDAY) == ("2026-12-21", "2026-12-27")


def day(day_iso: str, trimp: float, sport: str = "Run", minutes: float = 60.0, km: float = 12.0) -> DailyLoad:
    act = {"name": "", "sport_type": sport, "trimp": trimp, "trimp_method": "banister", "minutes": minutes, "km": km}
    return {"date": day_iso, "trimp": trimp, "activities": [act], "trimp_method": "banister"}


def test_relative_effort_counts_week_53_as_one_week_across_new_year():
    daily = [day("2026-12-21", 10.0), day("2026-12-28", 50.0), day("2027-01-01", 30.0), day("2027-01-03", 20.0),
             day("2027-01-04", 40.0)]
    weeks = weekly_relative_effort(daily, (SportCategory.RUNNING,), band_span=6, band_k=0.6)["weeks"]
    assert [(w["week_start"], w["relative_effort"]) for w in weeks] == [
        ("2026-12-21", round(10 * RE_DISPLAY_SCALE)), ("2026-12-28", round(100 * RE_DISPLAY_SCALE)),
        ("2027-01-04", round(40 * RE_DISPLAY_SCALE))]


def test_fitness_runs_from_one_year_into_the_plan_of_the_next():
    daily = [day(f"2026-12-{d:02d}", 60.0) for d in (20, 23, 26, 29, 30)]
    planned = [{"date": "2026-12-31", "sport_type": "Run", "planned_duration_mins": 30, "planned_distance_km": None},
               {"date": "2027-01-02", "sport_type": "Rest", "planned_duration_mins": None, "planned_distance_km": None},
               {"date": "2027-01-03", "sport_type": "Run", "planned_duration_mins": 60, "planned_distance_km": None}]
    series = fitness_form(daily, planned, date(2026, 12, 30), days=7)["series"]
    dates = [d["date"] for d in series]
    assert dates == [(date(2026, 12, 23) + timedelta(days=n)).isoformat() for n in range(12)]
    by_day = {d["date"]: d for d in series}
    # Logged today stays actual; the plan carries on over New Year's Day (nothing planned) into 2027
    assert [by_day[d]["projected"] for d in ("2026-12-30", "2026-12-31", "2027-01-01")] == [False, True, True]
    assert [by_day[d]["load"] for d in ("2026-12-30", "2026-12-31", "2027-01-01", "2027-01-02", "2027-01-03")] == [
        60.0, 30.0, 0.0, 0.0, 60.0]
    # Fitness only decays on the days without load, over the year's end as on any other day
    assert by_day["2027-01-02"]["fitness"] < by_day["2027-01-01"]["fitness"] < by_day["2026-12-31"]["fitness"]


def test_a_history_shorter_than_the_window_starts_at_its_first_day():
    series = fitness_form([day("2026-12-29", 42.0)], [], date(2027, 1, 2), days=30)["series"]
    assert [d["date"] for d in series] == ["2026-12-29", "2026-12-30", "2026-12-31", "2027-01-01", "2027-01-02"]
    assert series[-1]["projected"] is True and series[-1]["load"] == 0.0


def test_a_year_cut_at_new_years_eve_keeps_its_last_minutes():
    activities = activities_frame([
        {"id": 1, "sport_type": "Run", "start_date_local": "2026-12-31T23:30:00Z"},
        {"id": 2, "sport_type": "Run", "start_date_local": "2027-01-01T00:10:00Z"},
    ])
    assert year_activities(activities, 2026, (12, 31))["id"].tolist() == [1]
    assert year_activities(activities, 2027, (1, 1))["id"].tolist() == [2]
    assert year_activities(activities, 2027, (12, 31))["id"].tolist() == [2]


@pytest.mark.parametrize("year, weeks", [(2026, 364 / 7), (2028, 365 / 7)])
def test_a_closed_year_counts_all_its_weeks(year: int, weeks: float):
    assert activities_per_week(52, year, None, datetime(year + 1, 3, 1)) == pytest.approx(52 / weeks)


# ── On the athlete's clock ───────────────────────────────────────────────

YEAR_END = [
    {"id": 1, "name": "Before", "sport_type": "Run", "start_date_local": "2026-12-27T09:00:00Z", "distance": 5000.0,
     "moving_time": 1500, "average_heartrate": 140.0},
    {"id": 2, "name": "W53 Monday", "sport_type": "Run", "start_date_local": "2026-12-28T09:00:00Z",
     "distance": 8000.0, "moving_time": 2400, "average_heartrate": 145.0},
    {"id": 3, "name": "New Year", "sport_type": "Run", "start_date_local": "2027-01-01T10:00:00Z", "distance": 10000.0,
     "moving_time": 3000, "average_heartrate": 150.0},
    {"id": 4, "name": "W53 Sunday", "sport_type": "Ride", "start_date_local": "2027-01-03T08:00:00Z",
     "distance": 30000.0, "moving_time": 3600, "average_heartrate": 130.0},
    {"id": 5, "name": "W01", "sport_type": "Run", "start_date_local": "2027-01-04T07:00:00Z", "distance": 6000.0,
     "moving_time": 1800, "average_heartrate": 140.0},
]


def year_end_analytics(at: datetime):
    from zone2.analytics import StravaAnalytics
    rows = [{**a, "max_heartrate": 185.0, "total_elevation_gain": 0.0} for a in YEAR_END]
    return StravaAnalytics(FakeActivitiesCache(activities_frame(rows)), FakeUserCache(),  # type: ignore[arg-type]
                           clock=clock_at(at))


def test_this_weeks_report_on_new_years_day_is_week_53():
    report = year_end_analytics(datetime(2027, 1, 1, 18, tzinfo=UTC)).get_weekly_report(hr_zones=ZONES)
    assert (report["week_start"], report["week_end"], report["total_activities"]) == ("2026-12-28", "2027-01-03", 3)
    assert report["activities_per_sport"] == {"Run": 2, "Ride": 1}


def test_fitness_on_the_clock_ends_today():
    analytics = year_end_analytics(datetime(2027, 1, 2, 12, tzinfo=UTC))
    planned = [{"date": "2027-01-04", "sport_type": "Run", "planned_duration_mins": 40, "planned_distance_km": None}]
    series = analytics.get_fitness_form(50.0, None, planned, days=30)["series"]
    actual = [d["date"] for d in series if not d["projected"]]
    assert actual[0] == "2026-12-27" and actual[-1] == "2027-01-01"
    assert [d["date"] for d in series if d["projected"]] == ["2027-01-02", "2027-01-03", "2027-01-04"]


def test_weekly_totals_cross_the_year_on_the_clock():
    activities = activities_frame(YEAR_END)
    z2 = SimpleNamespace(strava_activities_cache=SimpleNamespace(get_prepared_view=lambda: activities),
                         clock=clock_at(datetime(2027, 1, 6, 9, tzinfo=UTC)))
    totals = training.weekly_totals(z2, 3)["data"]
    assert [(w["week_start"], w["week_end"], w["total_activities"], w["total_distance_km"]) for w in totals] == [
        ("2026-12-21", "2026-12-27", 1, 5.0), ("2026-12-28", "2027-01-03", 3, 48.0), ("2027-01-04", "2027-01-10", 1, 6.0)]
    runs = training.weekly_totals(z2, 2, category=SportCategory.RUNNING)["data"]
    assert [w["total_distance_km"] for w in runs] == [18.0, 6.0]

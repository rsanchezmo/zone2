"""Training load as pure functions: TRIMP per day, weekly Relative Effort and
fitness, fatigue and form."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from zone2.training_load import (
    RE_DISPLAY_SCALE, DailyLoad, daily_training_load, fitness_form, heartrate_counts, planned_load_estimator,
    training_load_key, trimp_activities, weekly_relative_effort,
)
from zone2.utils import SportCategory
from tests.synthetic import ZONES, activities_frame

TODAY = date(2026, 11, 11)


def test_heartrate_counts():
    values, counts = heartrate_counts({"heartrate": [120, None, 130, 120]})
    assert (values.tolist(), counts.tolist()) == ([120.0, 130.0], [2, 1])
    assert heartrate_counts({"time": [0, 1]}) is None
    assert heartrate_counts({"heartrate": [None, None]}) is None


def test_training_load_key():
    assert training_load_key(50.04, 190, ZONES[:2]) == (50.0, 190.0, ((0, 120), (120, 140)))
    assert training_load_key(50, 190, None) == (50.0, 190.0, ())


def run(activity_id: int, start: str, moving_time: int, average_heartrate: float | None) -> dict:
    return {"id": activity_id, "name": f"Run {activity_id}", "sport_type": "Run", "start_date_local": start,
            "distance": 5000.0, "moving_time": moving_time, "average_heartrate": average_heartrate}


def test_trimp_needs_an_average_heart_rate_and_a_moving_time():
    activities = activities_frame([run(1, "2026-10-10T08:00:00Z", 1800, 120.0), run(2, "2026-10-10T09:00:00Z", 1800, None),
                                   run(3, "2026-10-10T10:00:00Z", 0, 120.0)])
    assert trimp_activities(activities)["id"].tolist() == [1]
    assert trimp_activities(pd.DataFrame()).empty


def test_zone_weighting_needs_more_than_ten_samples():
    activities = activities_frame([run(1, "2026-10-10T08:00:00Z", 1800, 120.0), run(2, "2026-10-10T18:00:00Z", 1800, 120.0)])
    # Every sample in Z2, weighted 1.1 per minute
    counts = {1: (np.array([130.0]), np.array([10])), 2: (np.array([130.0]), np.array([11]))}
    [day] = daily_training_load(activities, hr_rest=50, hr_max=190, hr_zones=ZONES, hr_counts=counts)
    # Half way from resting to max HR: Banister's 0.5 × 0.64·e^(1.92 × 0.5) per minute
    banister = round(30 * 0.5 * 0.64 * np.exp(1.92 * 0.5), 1)
    assert [(a["trimp_method"], a["trimp"]) for a in day["activities"]] == [("banister", banister),
                                                                            ("zone_weighted", 33.0)]
    assert (day["date"], day["trimp_method"], day["trimp"]) == ("2026-10-10", "banister", pytest.approx(banister + 33.0))
    [no_zones] = daily_training_load(activities, hr_rest=50, hr_max=190, hr_zones=None, hr_counts=counts)
    assert {a["trimp_method"] for a in no_zones["activities"]} == {"banister"}


def day(day_iso: str, *activities: tuple[str, float, float, float]) -> DailyLoad:
    """A day of (sport_type, trimp, minutes, km) activities."""
    acts = [{"name": "", "sport_type": s, "trimp": t, "trimp_method": "banister", "minutes": m, "km": k}
            for s, t, m, k in activities]
    return {"date": day_iso, "trimp": sum(a["trimp"] for a in acts), "activities": acts, "trimp_method": "banister"}


def test_weekly_relative_effort_scales_fills_rest_weeks_and_bands():
    daily = [day("2026-10-05", ("Run", 100.0, 60, 10)), day("2026-10-07", ("Swim", 50.0, 40, 2)),
             day("2026-10-08", ("Ride", 80.0, 90, 40)),   # not a Relative Effort sport
             day("2026-10-19", ("Run", 70.0, 45, 8))]
    result = weekly_relative_effort(daily, (SportCategory.RUNNING, SportCategory.SWIMMING), band_span=6, band_k=0.6)
    assert (result["scale"], result["sports"]) == (RE_DISPLAY_SCALE, [SportCategory.RUNNING, SportCategory.SWIMMING])
    weeks = result["weeks"]
    assert [(w["week_start"], w["relative_effort"]) for w in weeks] == [
        ("2026-10-05", 210.0), ("2026-10-12", 0.0), ("2026-10-19", 98.0),
    ]
    # The band starts on the first week alone, then spreads by the weeks' std
    assert (weeks[0]["band_low"], weeks[0]["band_high"], weeks[0]["status"]) == (210.0, 210.0, "in_range")
    ewm = (5 / 7 * 210) / (1 + 5 / 7)
    assert (weeks[1]["band_low"], weeks[1]["band_high"]) == (0.0, round(ewm + 0.6 * np.std([210, 0], ddof=1)))
    assert weekly_relative_effort(daily, (), 6, 0.6)["weeks"] == []


def test_fitness_and_fatigue_are_exponential_averages_continued_by_the_plan():
    daily = [day("2026-11-09", ("Run", 42.0, 60, 10))]
    planned = [{"date": "2026-11-11", "sport_type": "Run", "planned_duration_mins": 30, "planned_distance_km": None},
               {"date": "2026-11-01", "sport_type": "Run", "planned_duration_mins": 90, "planned_distance_km": None}]
    result = fitness_form(daily, planned, TODAY, days=3)
    series = result["series"]
    assert [d["date"] for d in series] == ["2026-11-09", "2026-11-10", "2026-11-11"]
    # Today has no activity yet: the 30 planned minutes at 42 / 60 per minute stand in
    assert [(d["load"], d["projected"]) for d in series] == [(42.0, False), (0.0, False), (21.0, True)]
    fitness = [42 / 42, 1 - 1 / 42]
    fitness.append(fitness[1] + (21 - fitness[1]) / 42)
    fatigue = [42 / 7, 6 - 6 / 7]
    fatigue.append(fatigue[1] + (21 - fatigue[1]) / 7)
    assert [d["fitness"] for d in series] == [round(f, 1) for f in fitness]
    assert [d["fatigue"] for d in series] == [round(f, 1) for f in fatigue]
    assert [d["form_pct"] for d in series] == [round(100 * (f - g) / f, 1) for f, g in zip(fitness, fatigue)]
    assert (result["fitness_days"], result["fatigue_days"]) == (42, 7)
    assert fitness_form([], planned, TODAY, 3) == {"series": []}


def test_a_planned_session_costs_your_own_load_for_that_sport():
    daily = [day(f"2026-10-0{i}", ("Ride", 60.0, 60, 30), ("Run", 30.0, 60, 12)) for i in range(1, 4)]
    cost = planned_load_estimator(daily, TODAY)

    def session(sport_type: str | None, minutes: float | None = None, km: float | None = None) -> float:
        return cost({"date": "2026-11-12", "sport_type": sport_type, "planned_duration_mins": minutes,
                     "planned_distance_km": km})

    assert session("Ride", 60) == 60.0
    assert session("Run", 60) == 30.0
    assert session("Run", km=10) == 25.0   # at your usual 5:00 /km
    assert session("Kayaking", 60) == 45.0   # all sports' median load per minute
    assert session("Run") == 30.0   # your typical run
    assert session("Rest", 60) == 0.0
    # Sessions older than the history the costs come from don't count
    assert planned_load_estimator(daily, date(2027, 6, 1))({"date": "2027-06-02", "sport_type": "Run",
                                                            "planned_duration_mins": 60,
                                                            "planned_distance_km": None}) == 0.0

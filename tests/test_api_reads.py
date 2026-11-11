"""The read API over HTTP: activities (filters, sort, paging, detail) and the stats endpoints,
with their ETag revalidation, on the app stood up offline over the synthetic store
(conftest.offline_app)."""
from datetime import date, datetime, timedelta, timezone

import pytest

from tests.conftest import OfflineApp, pin_clock
from tests.synthetic import RECENT_RUNS, SHOE, STREAM_RUN_IDS, store_activities

ALL = 5 + 3 + RECENT_RUNS


def ids(response) -> list[int]:
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


def days_ago(app: OfflineApp, days: int) -> str:
    return (app.today - timedelta(days=days)).isoformat()


# ── Activities list ──────────────────────────────────────────────────────

def test_the_list_pages_through_every_activity_newest_first(offline_app: OfflineApp):
    api = offline_app.client
    pages, page = [], 1
    while True:
        body = api.get("/api/activities", params={"page": page, "per_page": 5}).json()
        assert (body["total"], body["page"], body["per_page"]) == (ALL, page, 5)
        if not body["items"]:
            break
        pages.append(body["items"])
        page += 1
    assert [len(p) for p in pages] == [5] * 7 + [1]
    starts = [item["start_date_local"] for p in pages for item in p]
    assert starts == sorted(starts, reverse=True)
    assert len({item["id"] for p in pages for item in p}) == ALL
    assert pages[0][0]["id"] == STREAM_RUN_IDS[0]
    # The list leaves the map out but keeps its polyline, and formats what the table shows
    first = pages[0][0]
    assert "map" not in first and first["summary_polyline"]
    assert (first["distance_km"], first["moving_time_formatted"]) == (8.0, "40:00")


@pytest.mark.parametrize("params, expected", [
    ({"sport_type": "Ride"}, [201, 4]),
    ({"year": 2024}, [5, 4, 3, 2, 1]),
    ({"search": "SYNTHETIC half"}, [3]),
    ({"date_from": "2024-03-04", "date_to": "2024-03-06"}, [2, 1]),
    ({"date_to": "2024-03-05"}, [1]),
    ({"sport_type": "Run", "year": 2024, "sort_by": "distance", "sort_dir": "asc"}, [2, 5, 1, 3]),
    ({"year": 2024, "sort_by": "moving_time"}, [3, 4, 1, 5, 2]),
    # Unknown sort fields fall back to the date
    ({"year": 2024, "sort_by": "name", "sort_dir": "asc"}, [1, 2, 3, 4, 5]),
])
def test_filters_and_sort(offline_app: OfflineApp, params: dict, expected: list[int]):
    assert ids(offline_app.client.get("/api/activities", params=params)) == expected


def test_search_is_case_insensitive_and_literal(offline_app: OfflineApp):
    api = offline_app.client
    tempo = ids(api.get("/api/activities", params={"search": "tEmPo", "per_page": 100}))
    assert tempo == [100 + k for k in range(3, RECENT_RUNS + 1, 4)]
    assert ids(api.get("/api/activities", params={"search": "run.*"})) == []


def test_gear_and_local_day_filters(offline_app: OfflineApp):
    api = offline_app.client
    shod = ids(api.get("/api/activities", params={"gear_id": SHOE, "per_page": 100}))
    assert len(shod) == 1 + RECENT_RUNS // 2 and 1 in shod
    day = days_ago(offline_app, 6)
    assert ids(api.get("/api/activities", params={"date_from": day, "date_to": day})) == [STREAM_RUN_IDS[1]]


@pytest.mark.parametrize("params", [
    {"date_from": "2024-13-01"}, {"date_to": "yesterday"}, {"year": "last"}, {"page": 0}, {"per_page": 101},
    {"per_page": 0},
])
def test_bad_query_parameters_are_422(offline_app: OfflineApp, params: dict):
    response = offline_app.client.get("/api/activities", params=params)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][:2] == ["query", next(iter(params))]


def test_sport_types_years_and_days(offline_app: OfflineApp):
    api = offline_app.client
    assert api.get("/api/activities/sport-types").json() == ["Hike", "Ride", "Run", "Swim"]
    years = sorted({int(a["start_date_local"][:4]) for a in store_activities(offline_app.today)}, reverse=True)
    assert api.get("/api/activities/years").json() == years
    on = api.get("/api/activities/on-dates", params={"dates": f"{days_ago(offline_app, 3)}, 2024-03-04,"})
    assert sorted(a["id"] for a in on.json()["items"]) == [1, STREAM_RUN_IDS[0]]
    assert api.get("/api/activities/on-dates").status_code == 422


# ── Activity detail ──────────────────────────────────────────────────────

def test_an_activity_with_streams(offline_app: OfflineApp):
    response = offline_app.client.get(f"/api/activities/{STREAM_RUN_IDS[0]}")
    assert response.status_code == 200
    run = response.json()
    assert (run["description"], run["distance_km"], run["formatted_pace"][:4]) == ("Steady", 8.0, "5:00")
    assert len(run["streams"]) == 2400
    assert {"time", "distance", "heartrate", "lat", "lng", "grade_adjusted_speed"} <= set(run["streams"][0])
    assert run["stops"] == [] and run["drift"] is not None
    assert run["splits_metric"] == [{"split": 1, "distance": 1000.0, "moving_time": 300}]


def test_an_activity_without_streams_and_one_that_does_not_exist(offline_app: OfflineApp):
    api = offline_app.client
    swim = api.get("/api/activities/202").json()
    assert (swim["sport_type"], swim["streams"], swim["stops"], swim["drift"], swim["hr_recovery"]) == (
        "Swim", None, [], None, None)
    missing = api.get("/api/activities/999999")
    assert (missing.status_code, missing.json()) == (404, {"detail": "Activity not found"})
    assert api.get("/api/activities/not-a-number").status_code == 422


def test_similar_activities(offline_app: OfflineApp):
    api = offline_app.client
    # Runs within 10% of 8 km and 20% of its 30 m climb; the flat 2024 8 km is left out
    similar = api.get(f"/api/activities/{STREAM_RUN_IDS[0]}/similar").json()
    assert [a["id"] for a in similar] == [105, 109, 113, 117, 121]
    assert len(api.get(f"/api/activities/{STREAM_RUN_IDS[0]}/similar", params={"limit": 20}).json()) == 6
    assert api.get("/api/activities/999999/similar").status_code == 404
    assert api.get(f"/api/activities/{STREAM_RUN_IDS[0]}/similar", params={"limit": 21}).status_code == 422


# ── ETags ────────────────────────────────────────────────────────────────

def test_polylines_revalidate_with_their_etag(offline_app: OfflineApp):
    api = offline_app.client
    first = api.get("/api/activities/polylines", params={"sport_type": "Ride"})
    assert [(p["id"], p["year"]) for p in first.json()] == [(4, 2024), (201, (offline_app.today - timedelta(10)).year)]
    etag = first.headers["etag"]
    assert etag.startswith('W/"') and first.headers["cache-control"] == "no-cache"
    again = api.get("/api/activities/polylines", params={"sport_type": "Ride"}, headers={"If-None-Match": etag})
    assert (again.status_code, again.content, again.headers["etag"]) == (304, b"", etag)
    other = api.get("/api/activities/polylines", params={"sport_type": "Run"}, headers={"If-None-Match": etag})
    assert other.status_code == 200 and other.headers["etag"] != etag


def test_stats_answer_304_for_the_tag_they_sent_until_the_data_changes(offline_app: OfflineApp):
    api = offline_app.client
    first = api.get("/api/stats/streaks")
    etag = first.headers["etag"]
    for sent in (etag, etag.removeprefix("W/"), f'"other", {etag}', "*"):
        assert api.get("/api/stats/streaks", headers={"If-None-Match": sent}).status_code == 304, sent
    assert api.get("/api/stats/streaks", headers={"If-None-Match": 'W/"stale"'}).status_code == 200

    # A sync that brings a run in moves the data version: the old tag no longer matches
    offline_app.z2.strava_activities_cache.save_activities([{
        "id": 999, "name": "New run", "sport_type": "Run", "distance": 5000.0, "moving_time": 1500,
        "start_date": f"{offline_app.today}T06:00:00Z", "start_date_local": f"{offline_app.today}T07:00:00Z",
    }])
    changed = api.get("/api/stats/streaks", headers={"If-None-Match": etag})
    assert changed.status_code == 200 and changed.headers["etag"] != etag
    assert changed.json()["current_streak"] == 1


def test_large_payloads_are_served_gzipped(offline_app: OfflineApp):
    response = offline_app.client.get("/api/stats/relative-effort/weekly", headers={"Accept-Encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip"
    assert response.json()["weeks"]
    plain = offline_app.client.get("/api/stats/relative-effort/weekly", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers and plain.json() == response.json()


# ── Stats ────────────────────────────────────────────────────────────────

def test_weekly_report_of_a_past_week_and_the_one_before(offline_app: OfflineApp):
    body = offline_app.client.get("/api/stats/weekly-report", params={"week_start": "2024-03-06"}).json()
    current, previous = body["current"], body["previous"]
    assert (current["week_start"], current["week_end"], current["total_activities"]) == ("2024-03-04", "2024-03-10", 2)
    assert (current["total_distance_km"], current["activities_per_day"]["0"], current["activities_per_day"]["2"]) == (
        15.0, 1, 1)
    assert (previous["week_start"], previous["total_activities"]) == ("2024-02-26", 0)


def test_weekly_report_of_the_iso_week_that_starts_the_next_year(offline_app: OfflineApp):
    current = offline_app.client.get("/api/stats/weekly-report", params={"week_start": "2025-01-01"}).json()["current"]
    assert (current["week_start"], current["week_end"], current["total_activities"]) == ("2024-12-30", "2025-01-05", 1)


def test_weekly_report_defaults_to_the_athletes_week(offline_app: OfflineApp):
    monday = offline_app.today - timedelta(days=offline_app.today.weekday())
    current = offline_app.client.get("/api/stats/weekly-report").json()["current"]
    expected = [a for a in store_activities(offline_app.today) if monday.isoformat() <= a["start_date_local"][:10]]
    assert (current["week_start"], current["total_activities"]) == (monday.isoformat(), len(expected))


def test_year_in_sport_of_a_closed_year(offline_app: OfflineApp):
    api = offline_app.client
    body = api.get("/api/stats/year-in-sport", params={"year": 2024, "comparison_year": 2023}).json()
    main, every = body["main_sport"], body["all_sports"]
    assert (body["year"], body["sport"]) == (2024, "Run")
    assert (main["total_activities"], main["total_distance_km"], main["longest_activity_km_id"]) == (4, 44.1, "3")
    assert main["activities_per_month"] == {"3": 2, "6": 1, "12": 1}
    assert (every["total_activities"], every["activities_per_sport"]) == (5, {"Ride": 1, "Run": 4})
    assert body["comparison"]["year"] == 2023 and body["comparison"]["main_sport"]["total_activities"] == 0
    ride = api.get("/api/stats/year-in-sport", params={"year": 2024, "main_sport": "Ride"}).json()
    assert ride["main_sport"]["total_distance_km"] == 40.0


@pytest.mark.xfail(strict=True, raises=ValueError, reason=(
    "backend/routers/stats.py cuts every year at today's (month, day); on Feb 29 the comparison "
    "with a non-leap year builds Feb 29 of that year in zone2/reports.py:84 (year_activities) "
    "and the request fails"))
def test_year_in_sport_compares_with_a_non_leap_year_on_feb_29(offline_app: OfflineApp,
                                                               monkeypatch: pytest.MonkeyPatch):
    pin_clock(monkeypatch, offline_app.z2, datetime(2028, 2, 29, 12, tzinfo=timezone.utc))
    response = offline_app.client.get("/api/stats/year-in-sport", params={"year": 2028, "comparison_year": 2027})
    assert response.status_code == 200


def test_cumulative_distance_of_a_leap_year(offline_app: OfflineApp):
    body = offline_app.client.get("/api/stats/cumulative-distance",
                                  params={"year": 2024, "yearly_target_km": 366}).json()
    data = body["data"]
    assert len(data) == 366 and data[-1]["date"] == "2024-12-31"
    assert (data[-1]["km"], data[-1]["target"], data[0]["target"]) == (44.1, 366.0, 1.0)


def test_personal_records_and_race_predictions_come_from_the_streams(offline_app: OfflineApp):
    api = offline_app.client
    records = api.get("/api/stats/personal-records").json()
    assert set(records) == {"running"}
    five_k = next(r for r in records["running"] if r["distance_m"] == 5000)
    assert five_k["activity_id"] in STREAM_RUN_IDS and five_k["time_s"] == pytest.approx(1500, abs=1)

    predictions = api.get("/api/stats/race-predictions").json()["predictions"]
    assert predictions and all(p["predicted_time_s"] > 0 for p in predictions)
    assert api.get("/api/stats/race-predictions", params={"sport_category": "cycling"}).status_code == 200
    assert api.get("/api/stats/race-predictions", params={"sport_category": "rowing"}).status_code == 422
    history = api.get("/api/stats/race-predictions/history", params={"weeks": 4}).json()
    assert history["weeks"] == 4 and history["points"]


def test_relative_effort_by_sport(offline_app: OfflineApp):
    api = offline_app.client
    weeks = api.get("/api/stats/relative-effort/weekly").json()["weeks"]
    assert weeks[0]["week_start"] == "2024-03-04"
    assert all(date.fromisoformat(w["week_start"]).weekday() == 0 for w in weeks)
    # A ride has no Relative Effort: an empty series hides the chart
    assert api.get("/api/stats/relative-effort/weekly", params={"sport_type": "Ride"}).json()["weeks"] == []
    swims = api.get("/api/stats/relative-effort/weekly", params={"sport_type": "Swim"}).json()["weeks"]
    assert sum(w["relative_effort"] > 0 for w in swims) == 1


def test_streaks_totals_and_weekly_totals(offline_app: OfflineApp):
    api = offline_app.client
    streaks = api.get("/api/stats/streaks").json()
    # Runs every third day; the swim, the ride and the hike each fall the day after one
    assert (streaks["current_streak"], streaks["longest_streak"]) == (0, 2)
    assert streaks["longest_week_streak"] >= 12
    totals = api.get("/api/stats/sport-totals").json()
    assert (totals["running"]["count"], totals["cycling"]["count"], totals["swimming"]["count"]) == (4 + RECENT_RUNS, 2, 1)
    weekly = api.get("/api/stats/weekly-totals", params={"weeks": 4, "sport_type": "Run"}).json()["data"]
    assert len(weekly) == 4 and all(date.fromisoformat(w["week_start"]).weekday() == 0 for w in weekly)
    assert weekly[-1]["week_end"] >= offline_app.today.isoformat()
    assert api.get("/api/stats/weekly-totals", params={"weeks": 0}).status_code == 422


def test_fitness_and_form_over_the_last_days(offline_app: OfflineApp):
    api = offline_app.client
    series = api.get("/api/stats/fitness", params={"days": 30}).json()["series"]
    assert [d["date"] for d in series] == [days_ago(offline_app, n) for n in range(30, -1, -1)]
    assert not any(d["projected"] for d in series[:-1])
    assert series[-1]["fitness"] > 0
    assert api.get("/api/stats/fitness", params={"days": 29}).status_code == 422

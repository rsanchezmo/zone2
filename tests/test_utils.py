import json
from collections import Counter
from datetime import date

import numpy as np
import polyline
import pytest

from zone2.utils import (
    CYCLING_SPORTS, RUNNING_SPORTS, SPEED_SPORTS, SWIMMING_SPORTS, WALKING_SPORTS, WATER_SPORTS,
    SportCategory, TrainingPace, compute_trimp_banister, compute_trimp_zone_weighted, convert_speed,
    fit_riegel_exponent, format_pace_or_speed, get_sport_category, gpx_track, hr_zone_counts,
    is_speed_sport, predicted_time_from_vdot, previous_week, riegel_predict, summary_polyline_geometry,
    training_paces_from_vdot, vdot_from_time_distance,
)
from tests.synthetic import ZONES

# Strava's sport_type values, spelled as the API sends them
STRAVA_SPORT_TYPES = {
    SportCategory.RUNNING: ["Run", "TrailRun", "VirtualRun"],
    SportCategory.WALKING: ["Walk", "Hike", "Snowshoe"],
    SportCategory.CYCLING: ["Ride", "VirtualRide", "EBikeRide", "Handcycle", "Velomobile", "GravelRide",
                            "MountainBikeRide", "EMountainBikeRide", "RollerSki"],
    SportCategory.SWIMMING: ["Swim"],
    SportCategory.WATER: ["Canoeing", "StandUpPaddling", "Kayaking", "Surfing", "Kitesurf", "Rowing",
                          "Windsurf", "Sail"],
    SportCategory.SPEED: ["Squash", "Tennis", "Pickleball", "Racquetball", "Badminton", "TableTennis", "Padel",
                          "WeightTraining", "Workout", "Yoga", "Pilates", "Crossfit",
                          "HighIntensityIntervalTraining", "Elliptical", "StairStepper", "Dance", "RockClimbing",
                          "AlpineSki", "BackcountrySki", "NordicSki", "Snowboard", "IceSkate", "InlineSkate",
                          "Skateboard", "Soccer", "Basketball", "Volleyball", "Cricket", "Golf"],
}


# ── Sport classification ─────────────────────────────────────────────────

@pytest.mark.parametrize("category, sport_types",
                         [pytest.param(c, s, id=c.value) for c, s in STRAVA_SPORT_TYPES.items()])
def test_strava_sport_types_map_to_their_category(category, sport_types):
    wrong = {s: get_sport_category(s) for s in sport_types if get_sport_category(s) != category}
    assert wrong == {}


@pytest.mark.xfail(reason="VirtualRow is missing from WATER_SPORTS (Rowing is there, as VirtualRide and "
                          "VirtualRun are with theirs), so indoor rows read as OTHER, in min/km")
def test_virtual_row_reads_like_rowing():
    assert get_sport_category("VirtualRow") == get_sport_category("Rowing")


def test_walks_and_hikes_are_not_runs():
    for sport_type in ("Walk", "Hike"):
        assert get_sport_category(sport_type) == SportCategory.WALKING
        # Still read as pace, like a run
        assert convert_speed(1.25, sport_type)[1] == "min/km"


def test_unknown_sports_are_other():
    assert {get_sport_category(s) for s in (None, "", "Wheelchair", "NotASport")} == {SportCategory.OTHER}


def test_sport_type_matching_ignores_case_and_spaces():
    assert {get_sport_category(s) for s in ("Trail Run", "trailrun", "TRAILRUN")} == {SportCategory.RUNNING}


def test_category_sets_are_disjoint():
    counts = Counter(s for group in (RUNNING_SPORTS, WALKING_SPORTS, CYCLING_SPORTS, SWIMMING_SPORTS,
                                     WATER_SPORTS, SPEED_SPORTS) for s in group)
    assert [s for s, n in counts.items() if n > 1] == []


def test_is_speed_sport():
    assert all(is_speed_sport(s) for s in ("Ride", "Kayaking", "Tennis"))
    assert not any(is_speed_sport(s) for s in ("Run", "Walk", "Swim", None))


# ── Units ────────────────────────────────────────────────────────────────

def test_convert_speed():
    for speed_ms, sport_type, value, unit in [
        (4.0, "Run", 1000 / 240, "min/km"),        # 4:10 /km
        (1.25, "Hike", 40 / 3, "min/km"),          # 13:20 /km
        (10.0, "Ride", 36.0, "km/h"),
        (2.5, "Kayaking", 9.0, "km/h"),
        (1.0, "Swim", 100 / 60, "min/100m"),       # 1:40 /100m
    ]:
        assert convert_speed(speed_ms, sport_type) == (pytest.approx(value), unit), sport_type
    assert convert_speed(0.0, "Run") == convert_speed(-1.0, "Ride") == (0.0, "N/A")


def test_pace_round_trips_through_speed():
    for pace_min_km in (3.0, 4.5, 6.25, 9.0):
        assert convert_speed(1000 / (60 * pace_min_km), "Run")[0] == pytest.approx(pace_min_km)


def test_format_pace_or_speed():
    for speed_ms, sport_type, text in [
        (1000 / 330, "Run", "5:30 /km"),
        # 4:59.6 rounds up to the next minute, never to "4:60"
        (1000 / 299.6, "Run", "5:00 /km"),
        (100 / 105, "Swim", "1:45 /100m"),
        (100 / 119.8, "Swim", "2:00 /100m"),
        (25.3 / 3.6, "Ride", "25.3 km/h"),
        (0.0, "Run", "N/A"),
    ]:
        assert format_pace_or_speed(speed_ms, sport_type) == text


def test_formatted_pace_agrees_with_converted_pace():
    for speed in np.linspace(1.5, 6.5, 41):
        minutes, seconds = format_pace_or_speed(speed, "Run").removesuffix(" /km").split(":")
        assert int(seconds) < 60
        assert int(minutes) + int(seconds) / 60 == pytest.approx(convert_speed(speed, "Run")[0], abs=1 / 120)


# ── VDOT and Riegel ──────────────────────────────────────────────────────

def test_vdot_matches_daniels_table():
    # Daniels' Running Formula, VDOT 50 row
    for distance_m, time_s in [(5000, 19 * 60 + 57), (10000, 41 * 60 + 21), (21097.5, 3600 + 31 * 60 + 35),
                               (42195, 3 * 3600 + 10 * 60 + 49)]:
        assert vdot_from_time_distance(time_s, distance_m) == pytest.approx(50, abs=0.15), distance_m


def test_vdot_rejects_invalid_efforts():
    for time_s, distance_m in [(179, 1000), (0, 5000), (1200, 0), (-5, 5000)]:
        assert vdot_from_time_distance(time_s, distance_m) is None


def test_predicted_time_inverts_vdot():
    distances = (5000, 10000, 21097, 42195)
    for vdot in (35.0, 50.0, 65.0):
        times = [predicted_time_from_vdot(vdot, d) for d in distances]
        assert times == sorted(times)
        for d, t in zip(distances, times):
            assert vdot_from_time_distance(t, d) == pytest.approx(vdot, abs=0.05)
        assert predicted_time_from_vdot(vdot + 1, 10000) < predicted_time_from_vdot(vdot, 10000)


def test_training_paces_match_daniels_table():
    def sec_per_km(speed_ms: float) -> float:
        return 1000 / speed_ms

    paces = training_paces_from_vdot(50)
    assert list(paces) == list(TrainingPace)
    slow, fast = paces[TrainingPace.EASY]
    assert sec_per_km(slow) == pytest.approx(5 * 60 + 38, abs=2)
    assert sec_per_km(fast) == pytest.approx(5 * 60 + 7, abs=2)
    for zone, expected in [(TrainingPace.MARATHON, 4 * 60 + 31), (TrainingPace.THRESHOLD, 4 * 60 + 15),
                           (TrainingPace.INTERVAL, 3 * 60 + 55), (TrainingPace.REPETITION, 3 * 60 + 41)]:
        assert sec_per_km(paces[zone][0]) == pytest.approx(expected, abs=2)
    assert training_paces_from_vdot(0) is None


def test_riegel_predict():
    assert riegel_predict(1200, 5000, 10000) == pytest.approx(1200 * 2 ** 1.06)
    assert riegel_predict(1200, 5000, 10000, exponent=1.0) == pytest.approx(2400)


def _on_power_law(exponent: float, distances=(5000, 10000, 21097)) -> list[dict]:
    return [{"distance_m": d, "time_s": 1200 * (d / 5000) ** exponent} for d in distances]


def test_riegel_exponent_recovers_an_exact_power_law():
    assert fit_riegel_exponent(_on_power_law(1.08)) == (1.08, 0.0)


def test_riegel_exponent_needs_three_plausible_efforts():
    assert fit_riegel_exponent(_on_power_law(1.08)[:2]) is None
    assert fit_riegel_exponent(_on_power_law(0.5)) is None
    assert fit_riegel_exponent(_on_power_law(1.08), weights=[0, 0, 0]) is None


def test_riegel_exponent_weights():
    efforts = _on_power_law(1.06, (5000, 10000)) + [{"distance_m": 21097, "time_s": 6000}]
    # A zero weight drops the off-law half; two efforts left leave no standard error
    assert fit_riegel_exponent(efforts, weights=[1, 1, 0]) == (1.06, None)
    exponent, stderr = fit_riegel_exponent(efforts)
    assert exponent > 1.06 and stderr > 0


# ── Training load and HR zones ───────────────────────────────────────────

def test_banister_trimp():
    # Halfway between resting (50) and max (190) for an hour
    male = compute_trimp_banister(np.array([60.0]), np.array([120.0]), 50, 190)
    female = compute_trimp_banister(np.array([60.0]), np.array([120.0]), 50, 190, gender="female")
    assert male[0] == pytest.approx(60 * 0.5 * 0.64 * np.exp(1.92 * 0.5))
    assert female[0] == pytest.approx(60 * 0.5 * 0.86 * np.exp(1.67 * 0.5))
    # Above max HR counts as max
    above = compute_trimp_banister(np.array([60.0]), np.array([200.0]), 50, 190)
    assert above[0] == pytest.approx(60 * 0.64 * np.exp(1.92))
    # No HR range to scale by
    assert compute_trimp_banister(np.array([60.0, 30.0]), np.array([120.0, 130.0]), 190, 190).tolist() == [0, 0]


def test_zone_weighted_trimp():
    assert compute_trimp_zone_weighted([10, 20, 15, 5, 2]) == pytest.approx(10 + 22 + 22.5 + 11 + 9)


def test_hr_zone_counts_edges():
    # A bpm on the edge two zones share counts in the upper one; below Z1 and
    # above Z5 count in them.
    counts = hr_zone_counts([50, 119, 120, 139.9, 140, 179.9, 180, 230], ZONES)
    assert counts.tolist() == [2, 2, 1, 1, 2]
    assert hr_zone_counts([130, 150], ZONES, weights=[3, 7]).tolist() == [0, 3, 7, 0, 0]
    assert hr_zone_counts([], ZONES).tolist() == [0, 0, 0, 0, 0]


# ── Weeks ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("today, cutoff", [
    (date(2026, 11, 9), "2026-11-02"),    # Monday: only the previous Monday
    (date(2026, 11, 11), "2026-11-04"),   # Wednesday
    (date(2026, 11, 15), "2026-11-08"),   # Sunday: still running
    (date(2026, 11, 16), None),           # the week is over: compare whole weeks
])
def test_previous_week_cutoff(today, cutoff):
    assert previous_week("2026-11-09", today=today) == ("2026-11-02", cutoff)


def test_previous_week_across_a_year():
    assert previous_week("2026-01-05", today=date(2026, 2, 1)) == ("2025-12-29", None)


# ── Geometry ─────────────────────────────────────────────────────────────

def test_gpx_track_escapes_the_name_and_writes_lat_lon():
    gpx = gpx_track("Loop & <back>", [[10.0, 50.0], [10.5, 50.25]]).decode()
    assert "<name>Loop &amp; &lt;back></name>" in gpx
    assert '<trkpt lat="50.0" lon="10.0"/>' in gpx
    assert '<trkpt lat="50.25" lon="10.5"/>' in gpx


def test_summary_polyline_geometry():
    encoded = polyline.encode([(50.0, 10.0), (50.001, 10.002)])
    for cell in ({"summary_polyline": encoded}, json.dumps({"summary_polyline": encoded})):
        # GeoJSON order: lon, lat
        assert np.allclose(summary_polyline_geometry(cell).coords, [(10.0, 50.0), (10.002, 50.001)])
    single = polyline.encode([(50.0, 10.0)])
    for cell in (None, "{not json", {"summary_polyline": ""}, {"summary_polyline": single}):
        assert summary_polyline_geometry(cell) is None

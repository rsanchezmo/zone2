"""The activities' true UTC start next to their local wall time: kept from Strava for new
activities, derived from local time and UTC offset for files written before it existed, and
used where an activity meets Garmin's real instants. Synthetic activities only."""
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from backend.services.activity_cost import activity_cost
from backend.services.day_timeline import day_timeline
from zone2.activities_cache import UTC_START, StravaActivitiesCache


def _cache(root: Path) -> StravaActivitiesCache:
    return StravaActivitiesCache(root / "activities", root / "streams", root / "metadata.json")


def _utc(s: str) -> pd.Timestamp:
    return pd.Timestamp(s, tz="UTC")


def _strava_activity(id: int, start_date: str, start_date_local: str, utc_offset: float | None) -> dict[str, Any]:
    """An activity as Strava's API returns it: start_date in UTC, start_date_local as wall time with a Z."""
    return {"id": id, "name": f"Synthetic {id}", "sport_type": "Run", "distance": 5000.0,
            "start_date": start_date, "start_date_local": start_date_local, "utc_offset": utc_offset}


def _write_old_year_file(root: Path, year: int, rows: list[dict[str, Any]]) -> pd.DataFrame:
    """A year file as written before the UTC column: start_date overwritten with the wall time."""
    df = pd.DataFrame(rows)
    df["start_date"] = pd.to_datetime(df["start_date_local"])
    (root / "activities").mkdir(parents=True, exist_ok=True)
    df.to_parquet(root / "activities" / f"{year}.parquet", index=False, engine="pyarrow")
    return df


# ── New activities ───────────────────────────────────────────────────────

def test_new_activities_keep_stravas_utc_start(tmp_path: Path):
    cache = _cache(tmp_path)
    cache.save_activities([
        _strava_activity(1, "2024-06-01T07:00:00Z", "2024-06-01T09:00:00Z", 7200.0),
        # Strava's own instant, even without an offset to derive it from
        _strava_activity(2, "2024-06-02T15:30:00Z", "2024-06-02T08:30:00Z", None),
    ])

    rows = _cache(tmp_path).activities_raw.set_index("id")
    assert str(rows[UTC_START].dtype) == "datetime64[ns, UTC]"
    assert rows.loc[1, UTC_START] == _utc("2024-06-01 07:00")
    assert rows.loc[2, UTC_START] == _utc("2024-06-02 15:30")
    # start_date stays the local wall time every day and week bucket reads
    assert rows.loc[1, "start_date"] == _utc("2024-06-01 09:00")
    assert UTC_START in pq.read_schema(tmp_path / "activities" / "2024.parquet").names


def test_an_activity_resaved_from_the_cache_keeps_its_utc_start(tmp_path: Path):
    cache = _cache(tmp_path)
    cache.save_activities([_strava_activity(1, "2024-06-02T15:30:00Z", "2024-06-02T08:30:00Z", None)])
    row = cache.activities_raw.iloc[0].to_dict()
    row["name"] = "Renamed"
    cache.save_activities([row])

    saved = _cache(tmp_path).activities_raw.iloc[0]
    assert saved["name"] == "Renamed"
    assert saved[UTC_START] == _utc("2024-06-02 15:30")


# ── Files written before the column ──────────────────────────────────────

_OLD_ROWS = [
    # Paris on the night clocks go forward (02:00 CET -> 03:00 CEST)
    {"id": 1, "start_date_local": "2024-03-31T01:30:00Z", "utc_offset": 3600.0, "timezone": "(GMT+01:00) Europe/Paris"},
    {"id": 2, "start_date_local": "2024-03-31T03:30:00Z", "utc_offset": 7200.0, "timezone": "(GMT+01:00) Europe/Paris"},
    # The hour that happens twice when they go back: the offset tells the two apart
    {"id": 3, "start_date_local": "2024-10-27T02:30:00Z", "utc_offset": 7200.0, "timezone": "(GMT+01:00) Europe/Paris"},
    {"id": 4, "start_date_local": "2024-10-27T02:30:00Z", "utc_offset": 3600.0, "timezone": "(GMT+01:00) Europe/Paris"},
    # Behind UTC, and across the date line from it
    {"id": 5, "start_date_local": "2024-07-04T18:00:00Z", "utc_offset": -25200.0, "timezone": "(GMT-08:00) America/Los_Angeles"},
    # Half-hour offset
    {"id": 6, "start_date_local": "2024-01-15T06:00:00Z", "utc_offset": 19800.0, "timezone": "(GMT+05:30) Asia/Kolkata"},
    # No offset stored: nothing to derive it from
    {"id": 7, "start_date_local": "2024-02-01T10:00:00Z", "utc_offset": np.nan, "timezone": None},
]


def test_files_written_before_the_column_get_it_from_local_time_and_offset(tmp_path: Path):
    _write_old_year_file(tmp_path, 2024, _OLD_ROWS)

    utc = _cache(tmp_path).activities_raw.set_index("id")[UTC_START]

    assert utc[1] == _utc("2024-03-31 00:30")
    assert utc[2] == _utc("2024-03-31 01:30")
    assert utc[3] == _utc("2024-10-27 00:30")
    assert utc[4] == _utc("2024-10-27 01:30")
    assert utc[5] == _utc("2024-07-05 01:00")
    assert utc[6] == _utc("2024-01-15 00:30")
    assert pd.isna(utc[7])


def test_the_backfill_only_adds_the_column(tmp_path: Path):
    old = _write_old_year_file(tmp_path, 2024, _OLD_ROWS)
    _cache(tmp_path).warm()

    stored = pd.read_parquet(tmp_path / "activities" / "2024.parquet")
    assert list(stored.columns) == [*old.columns, UTC_START]
    pd.testing.assert_frame_equal(stored.drop(columns=[UTC_START]), old)
    assert str(stored[UTC_START].dtype) == "datetime64[ns, UTC]"


def test_the_backfill_runs_once(tmp_path: Path):
    _write_old_year_file(tmp_path, 2024, _OLD_ROWS)
    year_file = tmp_path / "activities" / "2024.parquet"
    first = _cache(tmp_path).activities_raw
    written = year_file.read_bytes()

    again = _cache(tmp_path).activities_raw

    assert year_file.read_bytes() == written
    pd.testing.assert_series_equal(again[UTC_START], first[UTC_START])


def test_a_file_without_offsets_gets_an_empty_column_once(tmp_path: Path):
    _write_old_year_file(tmp_path, 2024, [{"id": 1, "start_date_local": "2024-02-01T10:00:00Z"}])
    year_file = tmp_path / "activities" / "2024.parquet"

    assert _cache(tmp_path).activities_raw[UTC_START].isna().all()
    assert UTC_START in pq.read_schema(year_file).names
    written = year_file.read_bytes()
    _cache(tmp_path).warm()
    assert year_file.read_bytes() == written


def test_a_save_into_an_old_file_backfills_its_rows(tmp_path: Path):
    _write_old_year_file(tmp_path, 2024, _OLD_ROWS)
    _cache(tmp_path).save_activities([_strava_activity(8, "2024-12-01T08:00:00Z", "2024-12-01T09:00:00Z", 3600.0)])

    stored = pd.read_parquet(tmp_path / "activities" / "2024.parquet").set_index("id")[UTC_START]
    assert stored[8] == _utc("2024-12-01 08:00")
    assert stored[2] == _utc("2024-03-31 01:30")
    assert pd.isna(stored[7])


# ── Where an activity meets Garmin's instants ────────────────────────────

class _Garmin:
    def __init__(self, payloads: dict[tuple[str, str], Any]):
        self.payloads = payloads

    def get(self, d: date | str, metric: str) -> Any:
        return self.payloads.get((str(d), metric))

    def get_summary_range(self, metric: str, start: date | str, end: date | str) -> list[dict]:
        return []


def _gmt_ms(s: str) -> int:
    return int(pd.Timestamp(s, tz="UTC").value // 1_000_000)


def _z2(rows: list[dict[str, Any]], garmin: _Garmin) -> SimpleNamespace:
    view = pd.DataFrame(rows)
    view["start_date_local"] = pd.to_datetime(view["start_date_local"], utc=True)
    view[UTC_START] = pd.to_datetime(view[UTC_START], utc=True)
    by_id = {int(r["id"]): pd.Series(r) for r in rows}
    cache = SimpleNamespace(get_prepared_view=lambda: view, get_activity_by_id=lambda i: by_id.get(int(i)))
    return SimpleNamespace(strava_activities_cache=cache, garmin_cache=garmin)


def test_the_day_timeline_puts_an_activity_on_its_heart_rate_after_a_dst_change():
    # Garmin frames the day at its start (CET, +1 h); the run starts at 10:00 CEST, 08:00 UTC
    garmin = _Garmin({("2024-03-31", "heart_rates"): {
        "startTimestampGMT": "2024-03-30T23:00:00.0", "startTimestampLocal": "2024-03-31T00:00:00.0",
        "heartRateValues": [[_gmt_ms("2024-03-31 07:59"), 70], [_gmt_ms("2024-03-31 08:00"), 150]],
    }})
    z2 = _z2([
        {"id": 1, "name": "Run", "sport_type": "Run", "elapsed_time": 1800,
         "start_date_local": "2024-03-31T10:00:00Z", UTC_START: "2024-03-31T08:00:00Z"},
        {"id": 2, "name": "No offset", "sport_type": "Run", "elapsed_time": 600,
         "start_date_local": "2024-03-31T18:00:00Z", UTC_START: None},
    ], garmin)

    timeline = day_timeline(z2, date(2024, 3, 31))

    assert timeline is not None
    run, unknown = timeline["activities"]
    assert run["start"] == timeline["heart_rate"][1][0]
    assert run["end"] - run["start"] == 1_800_000
    assert unknown["start"] == _gmt_ms("2024-03-31 18:00")


def _event(gmt: str, impact: int) -> dict[str, Any]:
    return {"eventType": "ACTIVITY", "eventStartTimeGmt": gmt, "durationInMilliseconds": 1_800_000,
            "bodyBatteryImpact": impact, "shortFeedback": "IMPROVING"}


def test_activity_cost_matches_garmins_event_on_the_utc_start():
    garmin = _Garmin({
        ("2024-07-04", "body_battery"): {"bodyBatteryActivityEvent": [_event("2024-07-04T13:02:00.0", -9)]},
        ("2024-07-05", "body_battery"): {"bodyBatteryActivityEvent": [_event("2024-07-05T06:01:00.0", -4)]},
    })
    # Recorded in Los Angeles, 06:00 local, with Strava's UTC start but no offset stored
    known = {"id": 1, "elapsed_time": 1800, "utc_offset": np.nan,
             "start_date_local": "2024-07-04T06:00:00Z", UTC_START: pd.Timestamp("2024-07-04T13:00:00Z")}
    # Its UTC start unknown: taking the wall time as UTC would claim the 06:01 GMT event
    unknown = {"id": 2, "elapsed_time": 1800, "utc_offset": np.nan,
               "start_date_local": "2024-07-05T06:00:00Z", UTC_START: pd.NaT}
    z2 = _z2([known, unknown], garmin)

    assert activity_cost(z2, 1)["body_battery"]["impact"] == -9
    assert activity_cost(z2, 2) == {"body_battery": None, "recovery_hours": None, "night": None}

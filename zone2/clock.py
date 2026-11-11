"""Today and now on the athlete's wall clock.

Activities' start_date_local, the calendar's sessions and Garmin's days are all
the athlete's local dates, so the current day, week and year are counted in the
athlete's time zone, whatever zone the server runs in (the Docker image runs in
UTC)."""

import re
from collections.abc import Callable
from datetime import date, datetime, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Strava's activity `timezone`: "(GMT+01:00) Europe/Paris"
_STRAVA_ZONE = re.compile(r"\)\s*(\S+)\s*$")


def zone_from_strava(name: str | None) -> ZoneInfo | None:
    """The zone a Strava activity's `timezone` names, None when it names none z2 knows."""
    match = _STRAVA_ZONE.search(name or "")
    if match is None:
        return None
    try:
        return ZoneInfo(match.group(1))
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Clock:
    """The athlete's today and now. `zone` gives the athlete's time zone (None
    while unknown, when the server's own stands in); `utc_now` is the current
    instant, which tests pin."""

    def __init__(self, zone: Callable[[], tzinfo | None] = lambda: None,
                 utc_now: Callable[[], datetime] | None = None) -> None:
        self._zone = zone
        self._utc_now = utc_now or _utc_now

    def now(self) -> datetime:
        """The athlete's wall-clock time labelled UTC, as start_date_local holds
        times, so the two compare directly."""
        instant = self._utc_now()
        zone = self._zone()
        local = instant.astimezone(zone) if zone is not None else instant.astimezone()
        return local.replace(tzinfo=timezone.utc)

    def today(self) -> date:
        return self.now().date()

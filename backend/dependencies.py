from strava.strava_intelligence import StravaIntelligence

_instance: StravaIntelligence | None = None


def set_strava_intelligence(si: StravaIntelligence) -> None:
    global _instance
    _instance = si


def get_si() -> StravaIntelligence:
    assert _instance is not None, "StravaIntelligence not initialized"
    return _instance

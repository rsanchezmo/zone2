from zone2.core import Zone2

_instance: Zone2 | None = None


def set_zone2(z2: Zone2) -> None:
    global _instance
    _instance = z2


def get_z2() -> Zone2:
    assert _instance is not None, "Zone2 not initialized"
    return _instance

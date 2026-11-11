"""Loops planned and not saved yet go with their city when it is deleted."""
from pathlib import Path

import pytest

from backend.config import settings
from backend.services import coverage


def loop(slug: str) -> dict:
    return {"slug": slug, "feature": {"type": "Feature", "properties": {}, "geometry": None}, "new_ways": [],
            "network": "stamp", "request": {}}


def test_deleting_a_city_drops_its_held_plans(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "workdir", tmp_path)
    coverage.hold_plan("plan-a", loop("city-a"))
    coverage.hold_plan("plan-b", loop("city-b"))
    assert coverage.held_plan("city-b", "plan-a") is None   # another city's plan id

    coverage.delete_city("city-a")
    assert coverage.held_plan("city-a", "plan-a") is None
    assert coverage.held_plan("city-b", "plan-b") == loop("city-b")

"""Tests for the pure logic of the LYWSD02 Sync integration.

Everything here runs without Home Assistant: the helpers module deliberately
imports nothing from HA, so the tests exercise real behaviour (timestamp
conversion, schedule parsing, option merging) instead of mocking it away.

Run: ``python -m pytest tests/test_sync_logic.py`` (or execute the file).
"""

from __future__ import annotations

import importlib.util
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "lywsd02"


def _load(name: str, path: Path):
    """Load a module by path, registering it so intra-package imports work."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# `const.py` imports Platform from Home Assistant. Stubbing the single symbol it
# needs keeps the production code free of test-only branches while letting these
# tests run outside Home Assistant.
import types

class _Platform:  # minimal stand-in for homeassistant.const.Platform
    BINARY_SENSOR = "binary_sensor"
    BUTTON = "button"
    SENSOR = "sensor"


_ha = types.ModuleType("homeassistant")
_ha_const = types.ModuleType("homeassistant.const")
_ha_const.Platform = _Platform
_ha.const = _ha_const
sys.modules.setdefault("homeassistant", _ha)
sys.modules["homeassistant.const"] = _ha_const

# helpers.py does `from .const import ...`, so the package name must match.
_load("lywsd02_testpkg.const", COMPONENT / "const.py")
sys.modules["lywsd02_testpkg.const"].__package__ = "lywsd02_testpkg"
helpers = _load("lywsd02_testpkg.helpers", COMPONENT / "helpers.py")


# --- timestamp -------------------------------------------------------------


def test_local_offset_is_baked_in():
    """At UTC+2 with tz_offset=0, the clock must receive local time as 'fake UTC'."""
    fixed = lambda: datetime(2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    before = int(time.time())
    value = helpers.get_localized_timestamp(0, now_factory=fixed)
    delta = value - before
    assert 7200 - 2 <= delta <= 7200 + 2, f"offset applique : {delta}s (attendu ~7200)"


def test_tz_offset_is_not_double_counted():
    """With tz_offset=2 at UTC+2, the offset must NOT be added twice.

    This is the regression fixed upstream in #13: baking the full local offset
    in while also sending tz_offset=2 made the clock run two hours fast.
    """
    fixed = lambda: datetime(2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    without = helpers.get_localized_timestamp(0, now_factory=fixed)
    with_offset = helpers.get_localized_timestamp(2, now_factory=fixed)
    assert without - with_offset == 2 * 3600


def test_no_offset_in_winter_and_summer_are_consistent():
    """Winter (UTC+1) vs summer (UTC+2) must each bake in the right offset."""
    winter = lambda: datetime(2026, 1, 15, 12, 0, tzinfo=timezone(timedelta(hours=1)))
    summer = lambda: datetime(2026, 7, 15, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    before = int(time.time())
    assert 3600 - 2 <= helpers.get_localized_timestamp(0, now_factory=winter) - before <= 3600 + 2
    assert 7200 - 2 <= helpers.get_localized_timestamp(0, now_factory=summer) - before <= 7200 + 2


# --- schedule --------------------------------------------------------------


def test_parse_sync_time_accepts_both_formats():
    assert helpers.parse_sync_time("04:00") == (4, 0, 0)
    assert helpers.parse_sync_time("04:00:30") == (4, 0, 30)
    assert helpers.parse_sync_time(" 23:59 ") == (23, 59, 0)


def test_parse_sync_time_rejects_junk():
    for bad in ("", "4h", "24:00", "12:60", "a:b", None, 400, "12"):
        assert helpers.parse_sync_time(bad) is None, bad


def test_next_sync_time_today_or_tomorrow():
    """Before the scheduled time -> today; after -> tomorrow."""
    now = datetime(2026, 5, 10, 2, 0, tzinfo=timezone(timedelta(hours=2)))
    assert helpers.next_sync_time("04:00", now) == now.replace(hour=4, minute=0, second=0)
    later = datetime(2026, 5, 10, 5, 0, tzinfo=timezone(timedelta(hours=2)))
    assert helpers.next_sync_time("04:00", later) == later.replace(
        hour=4, minute=0, second=0
    ) + timedelta(days=1)


def test_next_sync_time_invalid_schedule():
    now = datetime(2026, 5, 10, 2, 0, tzinfo=timezone.utc)
    assert helpers.next_sync_time("nope", now) is None


# --- options ---------------------------------------------------------------


def test_options_merge_defaults_and_user_values():
    entry = SimpleNamespace(
        data={"mac": "E7:2E:01:01:DC:29"},
        options={"sync_time": "06:30:00", "sync_enabled": False},
    )
    merged = helpers.options_for(entry)
    assert merged["sync_time"] == "06:30:00"  # user value wins
    assert merged["sync_enabled"] is False
    assert merged["timeout"] == 60  # default applied
    assert merged["sync_on_start"] is True  # default applied
    assert merged["mac"] == "E7:2E:01:01:DC:29"  # entry data preserved


def test_options_override_entry_data():
    """Options win over data, so an options-flow change really takes effect."""
    entry = SimpleNamespace(data={"sync_time": "04:00:00"}, options={"sync_time": "07:15:00"})
    assert helpers.options_for(entry)["sync_time"] == "07:15:00"


def test_as_int_tolerates_none_and_empty():
    assert helpers.as_int("24") == 24
    assert helpers.as_int(12) == 12
    assert helpers.as_int("none") is None
    assert helpers.as_int("") is None
    assert helpers.as_int(None) is None
    assert helpers.as_int("12h") is None


def test_should_skip_resync_window():
    """Garde-fou anti-boucle : fenêtre de 5 min pour l'automatique, jamais pour le manuel."""
    now = datetime(2026, 5, 10, 4, 0, tzinfo=timezone.utc)
    recent = now - timedelta(seconds=299)
    just_out = now - timedelta(seconds=301)
    assert helpers.should_skip_resync(recent, now, "schedule", min_interval=300, manual_trigger="button")
    assert not helpers.should_skip_resync(just_out, now, "schedule", min_interval=300, manual_trigger="button")
    assert not helpers.should_skip_resync(recent, now, "button", min_interval=300, manual_trigger="button")


if __name__ == "__main__":
    passed = failed = 0
    for name in sorted(n for n in dir() if n.startswith("test_")):
        try:
            globals()[name]()
            print(f"  PASS {name}")
            passed += 1
        except AssertionError as err:
            print(f"  FAIL {name}: {err}")
            failed += 1
    print(f"\n{passed} passes, {failed} echecs")

"""Integrations taken to behave alike, with a profile for where one names things its own way"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from homeassistant.core import HomeAssistant

from custom_components.appliance_autonotify import platforms
from custom_components.appliance_autonotify.const import CYCLE_KEY, PROGRESS_KEY, STAGE_KEY
from custom_components.appliance_autonotify.discovery import find_appliances
from custom_components.appliance_autonotify.platforms import GENERIC, PlatformProfile, profile_for

from .test_samsung import add_device

VENDOR = PlatformProfile(
    "vendor",
    status="beta",
    role_keys={"run_status": CYCLE_KEY, "progress": PROGRESS_KEY},
    role_key_prefixes={"remaining_": "program_finish_time"},
    program_types={"laundry_": "washer"},
    key_types={"tumble_": "dryer"},
)


def test_unknown_integration_is_taken_to_behave_like_the_others() -> None:
    assert profile_for("never_heard_of_it") is GENERIC
    assert profile_for(None) is GENERIC
    assert not GENERIC.beta
    assert GENERIC.role_key("operation_state") == CYCLE_KEY
    assert GENERIC.role_key("dryer_machine_state") == CYCLE_KEY
    assert GENERIC.role_key("dryer_cycle_table_03") == "selected_program"
    assert GENERIC.role_key("something_else") == "something_else"
    assert GENERIC.role_key(None) is None


def test_known_integrations_are_supported() -> None:
    for platform in ("home_connect", "smartthings", "localthings"):
        assert profile_for(platform).platform == platform
        assert not profile_for(platform).beta


def test_an_integration_own_names_come_first() -> None:
    assert VENDOR.beta
    # its own name for what LocalThings calls the stage
    assert GENERIC.role_key("progress") == STAGE_KEY
    assert VENDOR.role_key("progress") == PROGRESS_KEY
    assert VENDOR.role_key("run_status") == CYCLE_KEY
    assert VENDOR.role_key("remaining_time") == "program_finish_time"
    # and every integration's names still hold where it has none of its own
    assert VENDOR.role_key("operation_state") == CYCLE_KEY
    assert VENDOR.role_key("dryer_cycle_table_03") == "selected_program"


def test_appliance_type_by_an_integration_own_names_first() -> None:
    assert VENDOR.appliance_type(["laundry_cotton"], []) == "washer"
    assert VENDOR.appliance_type(["dishcare_dishwasher_program_eco_50"], []) == "dishwasher"
    assert VENDOR.appliance_type([], ["tumble_state"]) == "dryer"
    assert VENDOR.appliance_type([], ["washer_machine_state"]) == "washer"
    # programs say more than entity names
    assert VENDOR.appliance_type(["laundry_cotton"], ["tumble_state"]) == "washer"
    assert GENERIC.appliance_type(["laundry_cotton"], ["tumble_state"]) is None


async def test_appliance_found_by_its_integration_own_names(hass: HomeAssistant) -> None:
    entities: dict[str, tuple[str, list[str] | None]] = {"run_status": ("sensor", ["off", "run", "pause", "finished"])}
    add_device(hass, "vendor", "1", "Washer", entities)
    assert find_appliances(hass) == []
    with patch.dict(platforms.PROFILES, {"vendor": VENDOR}):
        assert [appliance.name for appliance in find_appliances(hass)] == ["Washer"]


def test_every_known_integration_set_up_first() -> None:
    """Each integration with a profile is set up before this one, so its appliances are there to be found"""
    manifest = json.loads((Path(platforms.__file__).parent / "manifest.json").read_text())
    assert set(platforms.PROFILES) <= set(manifest["after_dependencies"])

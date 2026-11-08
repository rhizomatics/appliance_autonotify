from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.appliance_autonotify.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    return


@pytest.fixture(autouse=True)
def no_live_settle():
    """Nothing held back before or after the start, other than in the tests of that"""
    with (
        patch("custom_components.appliance_autonotify.watcher.LIVE_SETTLE", 0),
        patch("custom_components.appliance_autonotify.watcher.START_SETTLE", 0),
    ):
        yield


@dataclass
class FakeAppliance:
    device_id: str
    cycle: str
    progress: str
    finish_time: str
    program: str
    # by translation key, those that only some appliances have
    others: dict[str, str] = field(default_factory=dict)


DISHWASHER_PROGRAMS = ["dishcare_dishwasher_program_eco_50", "dishcare_dishwasher_program_auto_2"]
OVEN_PROGRAMS = ["cooking_oven_program_heating_mode_pre_heating", "cooking_oven_program_heating_mode_pizza_setting"]
OVEN_ENTITIES = {
    "selected_program": "select",
    "setpoint_temperature": "number",
    "oven_current_cavity_temperature": "sensor",
    "preheat_finished": "sensor",
    "regular_preheat_finished": "sensor",
    "fast_pre_heat": "switch",
}


# the states Home Connect lists for the state of an appliance's cycle
OPERATION_STATES = ["inactive", "ready", "delayedstart", "run", "pause", "actionrequired", "finished", "error", "aborting"]


def add_appliance(
    hass: HomeAssistant,
    name: str = "Dishwasher",
    ha_id: str = "BOSCH-1",
    programs: list[str] | None = None,
    oven: bool = False,
) -> FakeAppliance:
    """Register a Home Connect appliance as the core integration would"""
    source = MockConfigEntry(domain="home_connect", entry_id=f"hc_{ha_id}")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("home_connect", ha_id)}, name=name
    )
    entity_registry = er.async_get(hass)
    entity_ids: dict[str, str] = {}
    domains = dict.fromkeys(("operation_state", "program_progress", "program_finish_time"), "sensor")
    domains["active_program"] = "select"
    if oven:
        domains |= OVEN_ENTITIES
        programs = OVEN_PROGRAMS if programs is None else programs
    for key, domain in domains.items():
        entity_ids[key] = entity_registry.async_get_or_create(
            domain,
            "home_connect",
            f"{ha_id}-{key}",
            suggested_object_id=f"{name.lower()}_{key}",
            device_id=device.id,
            config_entry=source,
            translation_key=key,
            capabilities={"options": programs}
            if domain == "select" and programs
            else {"options": OPERATION_STATES}
            if key == "operation_state"
            else None,
        ).entity_id
    return FakeAppliance(
        device.id,
        entity_ids["operation_state"],
        entity_ids["program_progress"],
        entity_ids["program_finish_time"],
        entity_ids["active_program"],
        {key: entity_ids[key] for key in OVEN_ENTITIES if key in entity_ids},
    )


def mock_dashboards(hass: HomeAssistant) -> None:
    """The dashboards as the lovelace integration keeps them, the default one being there with and without a path"""
    overview = SimpleNamespace(config={"title": "Overview", "url_path": "lovelace"})
    kitchen = SimpleNamespace(config={"title": "Kitchen", "url_path": "dashboard-kitchen"})
    hass.data["lovelace"] = SimpleNamespace(
        dashboards={None: SimpleNamespace(config=None), "lovelace": overview, "dashboard-kitchen": kitchen}
    )


def mock_dashboard(hass: HomeAssistant, url_path: str, title: str) -> None:
    hass.data["lovelace"].dashboards[url_path] = SimpleNamespace(config={"title": title, "url_path": url_path})


def mock_supernotify(hass: HomeAssistant) -> list[ServiceCall]:
    """Register the Supernotify actions used, returning the calls made to supernotify.notify"""
    async_mock_service(
        hass,
        "supernotify",
        "enquire_implicit_deliveries",
        response={"mobile_push": ["mobile_push"], "email": ["email"]},
        supports_response=SupportsResponse.ONLY,
    )
    async_mock_service(
        hass,
        "supernotify",
        "enquire_configuration",
        response={"delivery": {"chimes": {"transport": "chime"}, "phones": {"transport": "mobile_push"}}},
        supports_response=SupportsResponse.ONLY,
    )
    return async_mock_service(hass, "supernotify", "notify")


async def setup_watcher(
    hass: HomeAssistant, appliance: FakeAppliance, options: dict[str, Any] | None = None, minor_version: int = 3
) -> MockConfigEntry:
    """An appliance as just added, or as saved by an earlier version with a lower minor version"""
    assert await async_setup_component(hass, "notify", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Dishwasher",
        unique_id=appliance.device_id,
        data={CONF_DEVICE_ID: appliance.device_id},
        options=options or {},
        minor_version=minor_version,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def schema(result: Mapping[str, Any]) -> dict[Any, Any]:
    """The fields of the form a flow is showing"""
    data_schema = result["data_schema"]
    assert data_schema is not None
    return data_schema.schema


def placeholders(result: Mapping[str, Any]) -> Mapping[str, str]:
    """What the description of the form a flow is showing is filled in with"""
    found = result["description_placeholders"]
    assert found is not None
    return found


def state_of(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None
    return state.state

"""The diagnostics of automatic discovery, listing the devices that look like appliances but weren't found to be, so
that an issue asking for their integration to be supported comes with what's needed to support it"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.appliance_autonotify.diagnostics import async_get_config_entry_diagnostics
from tests.ha_testing import MockConfigEntry

from .conftest import add_appliance
from .test_config_flow import start_discovery


def add_device(
    hass: HomeAssistant, platform: str, uid: str, name: str, sensors: dict[str, tuple[str, list[str] | None]]
) -> dr.DeviceEntry:
    """A device of an integration yet to be supported, with sensors by translation key, of a device class and options"""
    source = MockConfigEntry(domain=platform)
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={(platform, uid)}, name=name, manufacturer="Acme", model="AC-1"
    )
    for key, (device_class, options) in sensors.items():
        entity = er.async_get(hass).async_get_or_create(
            "sensor",
            platform,
            f"{uid}-{key}",
            suggested_object_id=f"{name.lower().replace(' ', '_')}_{key}",
            device_id=device.id,
            config_entry=source,
            translation_key=key,
            original_device_class=device_class,
            capabilities={"options": options} if options else None,
        )
        hass.states.async_set(entity.entity_id, options[0] if options else "2026-11-19T10:00:00+00:00")
    return device


async def unmatched(hass: HomeAssistant) -> list[dict[str, Any]]:
    entry = await start_discovery(hass)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert "devices" not in diagnostics
    return diagnostics["unmatched"]


async def test_device_named_as_an_appliance_listed_without_its_names(hass: HomeAssistant) -> None:
    add_device(hass, "acme", "1", "Tumble Dryer", {"machine_status": ("enum", ["idle", "tumbling"])})
    [device] = await unmatched(hass)
    assert device["type"] == "dryer"
    assert device["manufacturer"] == "Acme"
    assert device["model"] == "AC-1"
    assert device["identifier_domains"] == ["acme"]
    [entity] = device["entities"]
    assert entity == {
        "platform": "acme",
        "domain": "sensor",
        "translation_key": "machine_status",
        # as every integration names it, there being nothing known of this one
        "role": "machine_status",
        "device_class": "enum",
        "unit": None,
        "options": ["idle", "tumbling"],
        "disabled": False,
        "state": "idle",
    }
    # nothing of the household's own naming, since it's for a public issue
    assert "Tumble" not in str(device)


async def test_device_with_a_running_state_listed_whatever_its_name(hass: HomeAssistant) -> None:
    add_device(
        hass,
        "acme",
        "2",
        "Utility room",
        {"status": ("enum", ["off", "running", "done"]), "finish": ("timestamp", None)},
    )
    [device] = await unmatched(hass)
    assert device["type"] is None
    assert [e["translation_key"] for e in device["entities"]] == ["finish", "status"]


async def test_devices_unlike_appliances_or_already_found_left_out(hass: HomeAssistant) -> None:
    # no state of a cycle, nor a name that says it's an appliance
    add_device(hass, "weather", "3", "Garden", {"condition": ("enum", ["sunny", "rainy"])})
    # named as one, but with no sensor such as an appliance tells of its cycle with
    add_device(hass, "acme", "4", "Washing machine", {"power": ("power", None)})
    # found already
    add_appliance(hass)
    assert await unmatched(hass) == []

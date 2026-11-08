from __future__ import annotations

from typing import Any

import pytest
from homeassistant.config_entries import (
    SOURCE_INTEGRATION_DISCOVERY,
    SOURCE_USER,
    ConfigEntry,
    ConfigEntryDisabler,
    ConfigFlowResult,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.appliance_autonotify.compat import vol
from custom_components.appliance_autonotify.const import DOMAIN, SUPERNOTIFY_MISSING, SUPERNOTIFY_PRESENT

from .conftest import add_appliance, mock_dashboard, mock_dashboards, mock_supernotify, placeholders, schema, setup_watcher


async def start_discovery(hass: HomeAssistant, auto_discover: bool = True) -> ConfigEntry:
    """Go through the first screen, as when the integration is added"""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"auto_discover": auto_discover})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Automatic discovery"
    await hass.async_block_till_done()
    return result["result"]


def appliances(hass: HomeAssistant) -> dict[str | None, str]:
    return {e.unique_id: e.title for e in hass.config_entries.async_entries(DOMAIN) if e.data.get("type") != "discovery"}


def suggested(result: ConfigFlowResult) -> dict[str, Any]:
    """Suggested values of a form, with those in sections alongside the rest"""
    values: dict[str, Any] = {}
    for key, field in schema(result).items():
        for k in field.schema.schema if hasattr(field, "schema") else [key]:
            if k.description:
                values[str(k)] = k.description["suggested_value"]
    return values


async def test_first_screen_sets_up_every_appliance(hass: HomeAssistant) -> None:
    dishwasher = add_appliance(hass)
    oven = add_appliance(hass, "Oven", "NEFF-2")

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["description_placeholders"] == {
        "found": "Appliances found:\n\n- Dishwasher\n- Oven",
        "supernotify": SUPERNOTIFY_MISSING,
    }
    # automatic discovery unless turned off
    defaults = {str(k): k.default() for k in schema(result)}
    assert defaults == {"auto_discover": True}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"auto_discover": True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"type": "discovery"}
    assert result["options"] == {"auto_discover": True}
    await hass.async_block_till_done()

    # each appliance has its own entry, with nothing asked and nothing left waiting as discovered
    assert appliances(hass) == {dishwasher.device_id: "Dishwasher", oven.device_id: "Oven"}
    assert all(not e.options for e in hass.config_entries.async_entries(DOMAIN) if e.unique_id != "discovery")
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_first_screen_with_nothing_found(hass: HomeAssistant) -> None:
    mock_supernotify(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["description_placeholders"] == {
        "found": "No appliances could be automatically installed.",
        "supernotify": SUPERNOTIFY_PRESENT,
    }
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"auto_discover": True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert not appliances(hass)

    # an appliance added later is set up as soon as it's there
    washer = add_appliance(hass, "Washer", "BOSCH-3")
    await hass.async_block_till_done()
    assert appliances(hass) == {washer.device_id: "Washer"}
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_disabled_appliance_is_left_alone(hass: HomeAssistant) -> None:
    dishwasher = add_appliance(hass)
    discovery = await start_discovery(hass)
    entry = hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, dishwasher.device_id)
    assert entry is not None
    await hass.config_entries.async_set_disabled_by(entry.entry_id, ConfigEntryDisabler.USER)

    await hass.config_entries.async_reload(discovery.entry_id)
    await hass.async_block_till_done()
    assert len(hass.config_entries.async_entries(DOMAIN)) == 2
    assert entry.disabled_by is ConfigEntryDisabler.USER
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_without_automatic_discovery_appliances_are_offered(hass: HomeAssistant) -> None:
    dishwasher = add_appliance(hass)
    oven = add_appliance(hass, "Oven", "NEFF-2")
    discovery = await start_discovery(hass, auto_discover=False)

    assert not appliances(hass)
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert {f["context"]["unique_id"] for f in flows} == {dishwasher.device_id, oven.device_id}
    assert all(f["context"]["source"] == SOURCE_INTEGRATION_DISCOVERY for f in flows)
    assert all(f["step_id"] == "confirm" for f in flows)
    offered = next(f for f in flows if f["context"]["unique_id"] == oven.device_id)
    assert offered["context"]["title_placeholders"] == {"name": "Oven"}
    assert offered["context"]["confirm_only"] is True

    # adding one takes no more than a confirmation
    result = await hass.config_entries.flow.async_configure(offered["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Oven"
    assert result["data"] == {"device_id": oven.device_id}
    assert result["options"] == {}

    # the switch is on the discovery entry, and turning it on sets up whatever is still on offer
    result = await hass.config_entries.options.async_init(discovery.entry_id)
    assert result["step_id"] == "discovery"
    defaults = {str(k): k.default() for k in schema(result)}
    assert defaults == {"auto_discover": False}
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"auto_discover": True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert appliances(hass) == {dishwasher.device_id: "Dishwasher", oven.device_id: "Oven"}
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_appliances_offered_while_discovery_disabled(hass: HomeAssistant) -> None:
    discovery = await start_discovery(hass)
    await hass.config_entries.async_set_disabled_by(discovery.entry_id, ConfigEntryDisabler.USER)

    washer = add_appliance(hass, "Washer", "BOSCH-3")
    await hass.async_block_till_done()
    assert not appliances(hass)
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["unique_id"] for f in flows] == [washer.device_id]


async def test_existing_install_without_discovery_entry(hass: HomeAssistant) -> None:
    # appliances set up by an earlier version, when there was no discovery entry
    dishwasher = add_appliance(hass)
    oven = add_appliance(hass, "Oven", "NEFF-2")
    await setup_watcher(hass, dishwasher)
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["unique_id"] for f in flows] == [oven.device_id]

    # adding to the integration gives the first screen, with only what isn't yet set up
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["step_id"] == "user"
    assert placeholders(result)["found"] == "Appliances found:\n\n- Oven"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"auto_discover": True})
    await hass.async_block_till_done()
    assert appliances(hass) == {dishwasher.device_id: "Dishwasher", oven.device_id: "Oven"}
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_new_cycle_state_of_no_device_is_ignored(hass: HomeAssistant) -> None:
    await start_discovery(hass)
    er.async_get(hass).async_get_or_create("sensor", "demo", "other", translation_key="operation_state")
    await hass.async_block_till_done()
    assert not appliances(hass)


async def test_power_flow(hass: HomeAssistant) -> None:
    await start_discovery(hass)
    # with discovery chosen, adding to the integration goes straight to an appliance described by hand
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "power"
    defaults = {str(k): k.default() for k in schema(result) if k.default is not vol.UNDEFINED}
    assert defaults == {"threshold": 1, "grace_period": 60, "min_duration": 0, "switch_off_button": True}

    power = {"power_entity": "sensor.washer_power", "threshold": 5, "grace_period": 60, "min_duration": 60}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "Washer", **power})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Washer"
    assert result["data"] == {"type": "power"}
    # the button to switch off a smart plug is there unless turned off, and only once there's a plug
    stored = power | {"switch_off_button": True}
    assert result["options"] == stored
    await hass.async_block_till_done()
    entry = result["result"]
    assert entry.runtime_data.power_entity_id == "sensor.washer_power"

    # one entry for each power sensor
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "Again", **power})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"

    # the settings have a second page for the power monitoring
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "settings"
    assert suggested(result)["end_message"] == "Washer is finished"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"start": {}, "end": {"end_message": "Hang out the washing"}, "notify": {}}
    )
    assert result["step_id"] == "power"
    assert "name" not in schema(result)
    assert suggested(result) == stored
    plug = {"switch_entity": "switch.washer_plug", "switch_off_button": False}
    result = await hass.config_entries.options.async_configure(result["flow_id"], power | plug | {"threshold": 3})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == {"end_message": "Hang out the washing", **power, **plug, "threshold": 3}
    assert entry.runtime_data.threshold == 3
    assert entry.runtime_data.switch_entity_id is None


def add_power_monitor(
    hass: HomeAssistant,
    name: str,
    platform: str = "shelly",
    unit: str = "W",
    switch: bool = True,
) -> tuple[str, str | None, str]:
    """Register a smart plug measuring power as its integration would, returning its sensor, switch and device"""
    slug = name.lower().replace(" ", "_")
    source = MockConfigEntry(domain=platform, entry_id=f"{platform}_{slug}")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(config_entry_id=source.entry_id, identifiers={(platform, slug)}, name=name)
    entity_registry = er.async_get(hass)
    sensor = entity_registry.async_get_or_create(
        "sensor",
        platform,
        f"{slug}-power",
        suggested_object_id=f"{slug}_power",
        device_id=device.id,
        config_entry=source,
        original_device_class="power",
        original_name="Power",
        unit_of_measurement=unit,
    ).entity_id
    switch_id = None
    if switch:
        switch_id = entity_registry.async_get_or_create(
            "switch", platform, f"{slug}-switch", suggested_object_id=slug, device_id=device.id, config_entry=source
        ).entity_id
    return sensor, switch_id, device.id


def offered(hass: HomeAssistant) -> dict[str, ConfigFlowResult]:
    """Flows waiting as discovered, by the name they're offered with"""
    return {
        flow["context"]["title_placeholders"]["name"]: flow
        for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        if flow["context"]["source"] == SOURCE_INTEGRATION_DISCOVERY
    }


async def test_power_monitor_named_for_an_appliance_is_offered(hass: HomeAssistant) -> None:
    await start_discovery(hass)
    washer, plug, _ = add_power_monitor(hass, "Washing Machine Plug")
    # not an appliance that runs in cycles, or with no name to tell
    add_power_monitor(hass, "Kettle")
    add_power_monitor(hass, "Smart Plug 2")
    # Powercalc's estimate of a plug's own standby, which has the name of the plug, and power not in watts
    add_power_monitor(hass, "Dishwasher Plug", platform="powercalc")
    add_power_monitor(hass, "Oven", unit="kW")
    await hass.async_block_till_done()

    # only ever offered, even with automatic discovery on, since a name is a guess
    assert appliances(hass) == {}
    flows = offered(hass)
    assert list(flows) == ["Washing Machine Plug"]
    flow = flows["Washing Machine Plug"]
    assert flow["step_id"] == "power"
    assert flow["context"]["unique_id"] == washer

    # the form is filled in from the plug, to check the threshold before it's added
    result = await hass.config_entries.flow.async_configure(flow["flow_id"])
    assert result["step_id"] == "power"
    assert suggested(result) == {"name": "Washing Machine Plug", "power_entity": washer, "switch_entity": plug}
    power = {"power_entity": washer, "threshold": 5, "grace_period": 60, "min_duration": 0, "switch_entity": plug}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "Washing machine", **power})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"type": "power"}
    assert result["options"] == power | {"switch_off_button": True}
    await hass.async_block_till_done()
    assert appliances(hass) == {washer: "Washing machine"}

    # and not offered again once set up
    discovery = next(e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get("type") == "discovery")
    await hass.config_entries.async_reload(discovery.entry_id)
    await hass.async_block_till_done()
    assert offered(hass) == {}


async def test_power_monitor_offered_once_named_for_an_appliance(hass: HomeAssistant) -> None:
    # an Italian name in an Italian Home Assistant, on a plug with more than one switch, so none is chosen for it
    hass.config.language = "it"
    sensor, _, device_id = add_power_monitor(hass, "Presa 3")
    # English names too, whatever the language, and the longest word wins, so a microwave oven isn't an oven
    add_power_monitor(hass, "Washer plug")
    add_power_monitor(hass, "Forno a microonde")
    er.async_get(hass).async_get_or_create("switch", "shelly", "presa_3-switch-2", device_id=device_id)
    await start_discovery(hass)
    assert list(offered(hass)) == ["Washer plug"]

    dr.async_get(hass).async_update_device(device_id, name_by_user="Presa Lavastoviglie")
    await hass.async_block_till_done()
    flow = offered(hass)["Presa Lavastoviglie"]
    result = await hass.config_entries.flow.async_configure(flow["flow_id"])
    assert suggested(result) == {"name": "Presa Lavastoviglie", "power_entity": sensor}

    # one offer for each sensor, however many times the device changes
    dr.async_get(hass).async_update_device(device_id, name_by_user="Lavastoviglie")
    await hass.async_block_till_done()
    assert len(hass.config_entries.flow.async_progress_by_handler(DOMAIN)) == 2

    # a sensor of no device goes by its own name, and has no plug
    oven = er.async_get(hass).async_get_or_create(
        "sensor", "mqtt", "forno-w", original_name="Potenza Forno", original_device_class="power", unit_of_measurement="W"
    )
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(offered(hass)["Potenza Forno"]["flow_id"])
    assert suggested(result) == {"name": "Potenza Forno", "power_entity": oven.entity_id}
    er.async_get(hass).async_remove(oven.entity_id)
    await hass.async_block_till_done()


async def test_power_monitor_of_an_appliance_with_a_setting_switch(hass: HomeAssistant) -> None:
    # a dryer measuring its own power, whose only switch is a setting of its own, not the plug it's on
    sensor, _, device_id = add_power_monitor(hass, "Dryer", switch=False)
    er.async_get(hass).async_get_or_create(
        "switch", "shelly", "dryer-wrinkle", device_id=device_id, entity_category=EntityCategory.CONFIG
    )
    await start_discovery(hass)
    result = await hass.config_entries.flow.async_configure(offered(hass)["Dryer"]["flow_id"])
    assert suggested(result) == {"name": "Dryer", "power_entity": sensor}


async def test_power_monitor_of_an_appliance_set_up_already(hass: HomeAssistant) -> None:
    # a dishwasher of its own integration, whose device also has a power sensor
    appliance = add_appliance(hass, name="Dishwasher")
    er.async_get(hass).async_get_or_create(
        "sensor",
        "home_connect",
        "BOSCH-1-power",
        device_id=appliance.device_id,
        original_device_class="power",
        unit_of_measurement="W",
    )
    await start_discovery(hass)
    assert appliances(hass) == {appliance.device_id: "Dishwasher"}
    assert offered(hass) == {}


async def test_settings_without_supernotify(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    entry = await setup_watcher(hass, appliance)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "settings"
    assert result["description_placeholders"] == {
        "name": "Dishwasher",
        "supernotify": SUPERNOTIFY_MISSING,
        "program_placeholder": "{program}",
    }
    # with no Live Activity, there's no title for the program to go in
    assert not {"live_title", "live_detail"} & {str(k) for k in schema(result)}
    # everything but whether to notify progress is tucked away in three sections
    sections = {str(k): v for k, v in schema(result).items()}
    for switch in ("notify_start", "notify_end", "maintenance", "notify_progress"):
        assert sections.pop(switch) is not None
    assert list(sections) == ["start", "end", "notify", "maintenance_items"]
    assert all(s.options == {"collapsed": True} for s in sections.values())
    assert list(sections["notify"].schema.schema) == ["targets"]
    assert list(sections["end"].schema.schema) == ["end_title", "end_message"]
    # titles and messages are shown as they'll be sent, with no template to work out
    assert suggested(result) == {
        "start_title": "Dishwasher",
        "start_message": "Dishwasher started",
        "end_title": "Dishwasher",
        "end_message": "Dishwasher is finished",
    }

    # nothing is mandatory, and text left alone isn't kept as a setting
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "start": {"start_title": "Dishwasher", "start_message": "Dishwasher started"},
            "end": {"end_title": "Kitchen", "end_message": "Dishwasher is finished"},
            "notify": {"targets": []},
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == {"end_title": "Kitchen"}
    assert entry.runtime_data.entry.options["end_title"] == "Kitchen"

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert suggested(result)["end_title"] == "Kitchen"
    # a cleared box goes back to the default
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"start": {}, "end": {}, "notify": {"targets": ["notify.hall_display"]}}
    )
    await hass.async_block_till_done()
    assert entry.options == {"targets": ["notify.hall_display"]}
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert suggested(result)["end_title"] == "Dishwasher"
    assert suggested(result)["targets"] == ["notify.hall_display"]


async def test_settings_with_supernotify(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    mock_supernotify(hass)
    # as saved by an earlier version, which kept the templates it showed
    entry = await setup_watcher(hass, appliance, {"start_title": "{name}", "start_message": "{name} is go"})

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert placeholders(result)["supernotify"] == SUPERNOTIFY_PRESENT
    assert suggested(result)["start_title"] == "Dishwasher"
    assert suggested(result)["start_message"] == "Dishwasher is go"
    # progress isn't notified until asked for, and the choice isn't hidden away in a section
    assert list(schema(result)) == [
        "notify_start",
        "notify_end",
        "maintenance",
        "notify_progress",
        "live_title",
        "live_detail",
        "start",
        "end",
        "notify",
        "maintenance_items",
    ]
    switches = {str(k): k.default() for k in schema(result) if k.default is not vol.UNDEFINED}
    assert switches == {
        "notify_start": False,
        "notify_end": True,
        "maintenance": False,
        "notify_progress": False,
        "live_title": "name_program",
        "live_detail": "time_remaining",
    }
    notify = next(v for k, v in schema(result).items() if k == "notify").schema.schema
    # the notify entity list is only for use without Supernotify
    assert list(notify) == ["target", "custom_target", "deliveries"]
    # reminders and buttons on the end need Supernotify, so are only offered with it
    end = next(v for k, v in schema(result).items() if k == "end").schema.schema
    assert list(end) == ["end_title", "end_message", "reminder", "reminder_repeats"]
    assert notify["deliveries"].config["options"] == ["chimes", "email", "mobile_push", "phones"]

    settings = {"target": {"entity_id": ["person.joe"]}, "custom_target": ["joe@example.com"], "deliveries": ["phones"]}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "notify_end": False,
            "notify_progress": True,
            "start": {"start_title": "Dishwasher", "start_message": "Dishwasher is go"},
            "end": {},
            "notify": settings,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    # a switch is only kept once it's been changed
    assert entry.options == {"notify_end": False, "notify_progress": True, "start_message": "Dishwasher is go", **settings}
    assert entry.runtime_data.notify_progress is True
    assert (entry.runtime_data.notify_start, entry.runtime_data.notify_end) == (False, False)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert suggested(result)["notify_progress"] is True
    assert suggested(result)["notify_end"] is False
    assert "notify_start" not in suggested(result)
    assert suggested(result)["target"] == {"entity_id": ["person.joe"]}
    assert suggested(result)["deliveries"] == ["phones"]

    # reminders are tuned by how long between them and how many, the usual number of them not being a setting
    form = {"notify_end": False, "notify_progress": True, "start": {}, "notify": settings}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], form | {"end": {"reminder": 15, "reminder_repeats": 5}}
    )
    await hass.async_block_till_done()
    assert (entry.options["reminder"], entry.options["reminder_repeats"]) == (15, 5)
    assert (entry.runtime_data.reminder, entry.runtime_data.reminder_repeats) == (15, 5)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], form | {"end": {"reminder": 15}})
    await hass.async_block_till_done()
    assert "reminder_repeats" not in entry.options
    assert entry.runtime_data.reminder_repeats == 3


async def test_phases_are_notified_for_an_oven_unless_turned_off(hass: HomeAssistant) -> None:
    mock_supernotify(hass)
    oven = add_appliance(hass, "Oven", "NEFF-2", oven=True)
    entry = await setup_watcher(hass, oven)
    assert entry.runtime_data.notify_phase is True

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert list(schema(result))[:4] == ["notify_start", "notify_end", "notify_phase", "notify_progress"]
    assert next(k for k in schema(result) if k == "notify_phase").default() is True

    # left as it comes it isn't a setting, turned off it is
    form: dict[str, dict[str, Any]] = {"start": {}, "end": {}, "notify": {}}
    result = await hass.config_entries.options.async_configure(result["flow_id"], form)
    await hass.async_block_till_done()
    assert entry.options == {}
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], form | {"notify_phase": False})
    await hass.async_block_till_done()
    assert entry.options == {"notify_phase": False}
    assert entry.runtime_data.notify_phase is False

    # something with the temperatures of an oven that isn't one has phases only if asked for
    other = add_appliance(hass, "Warmer", "BOSCH-4", programs=["cooking_hob_program_power_mode"], oven=True)
    entry = await setup_watcher(hass, other)
    assert entry.runtime_data.notify_phase is False
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert next(k for k in schema(result) if k == "notify_phase").default() is False
    result = await hass.config_entries.options.async_configure(result["flow_id"], form | {"notify_phase": True})
    await hass.async_block_till_done()
    assert entry.options == {"notify_phase": True}

    # and an appliance that reports none has no switch for them
    entry = await setup_watcher(hass, add_appliance(hass))
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "notify_phase" not in schema(result)


async def test_dashboard_is_chosen_from_those_there_are(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    mock_supernotify(hass)
    mock_dashboards(hass)
    # as chosen before the dashboard was removed
    entry = await setup_watcher(hass, appliance, {"dashboard": "dashboard-garage"})

    result = await hass.config_entries.options.async_init(entry.entry_id)
    dashboard = next(v for k, v in schema(result).items() if k == "dashboard")
    assert dashboard.config["options"] == [
        {"value": "dashboard-kitchen", "label": "Kitchen"},
        {"value": "lovelace", "label": "Overview"},
    ]
    assert not dashboard.config.get("custom_value")
    assert "dashboard" not in suggested(result)

    choice = {"dashboard": "dashboard-kitchen", "start": {}, "end": {}, "notify": {}}
    result = await hass.config_entries.options.async_configure(result["flow_id"], choice)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == {"dashboard": "dashboard-kitchen"}
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert suggested(result)["dashboard"] == "dashboard-kitchen"

    # anything else is turned away
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(result["flow_id"], choice | {"dashboard": "https://example.com"})


async def test_dashboard_chosen_when_set_up_can_be_cleared(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    mock_supernotify(hass)
    mock_dashboards(hass)
    mock_dashboard(hass, "dashboard-dishwasher", "Dishwasher")
    entry = await setup_watcher(hass, appliance)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert suggested(result)["dashboard"] == "dashboard-dishwasher"
    await hass.config_entries.options.async_configure(result["flow_id"], {"start": {}, "end": {}, "notify": {}})
    await hass.async_block_till_done()
    # and stays cleared, through the reload
    assert "dashboard" not in entry.options
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "dashboard" not in suggested(result)


async def test_dashboards_with_the_same_title_are_told_apart(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    mock_supernotify(hass)
    mock_dashboards(hass)
    mock_dashboard(hass, "dashboard-supernotify", "Supernotify")
    mock_dashboard(hass, "dashboard-supernotify-2", "SuperNotify")
    entry = await setup_watcher(hass, appliance)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    dashboard = next(v for k, v in schema(result).items() if k == "dashboard")
    assert [option["label"] for option in dashboard.config["options"]] == [
        "Kitchen",
        "Overview",
        "Supernotify (dashboard-supernotify)",
        "SuperNotify (dashboard-supernotify-2)",
    ]


async def test_setup_without_entries(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})

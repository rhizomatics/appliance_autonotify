"""Repairs for an appliance removed from Home Assistant, and for notifications with nowhere to go, and the messages of
errors as they're translated"""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from custom_components.appliance_autonotify import async_remove_config_entry_device
from custom_components.appliance_autonotify.compat import LINKED_DEVICES
from custom_components.appliance_autonotify.const import DOMAIN
from custom_components.appliance_autonotify.repairs import (
    NO_TARGETS_ISSUE,
    RemoveApplianceFlow,
    async_create_fix_flow,
    removed_issue_id,
)
from tests.ha_testing import MockConfigEntry, async_mock_service

from .conftest import add_appliance, setup_watcher
from .test_watcher import set_state, setup_power_watcher


async def fix(hass: HomeAssistant, issue_id: str) -> None:
    """Go through the repair's fix flow, as when Submit is pressed"""
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.is_fixable
    flow = await async_create_fix_flow(hass, issue_id, issue.data)
    assert isinstance(flow, RemoveApplianceFlow)
    flow.hass, flow.handler, flow.flow_id = hass, DOMAIN, "fix"
    result = await flow.async_step_init()
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    result = await flow.async_step_confirm({})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()


def issue(hass: HomeAssistant, issue_id: str) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


async def test_appliance_removed_from_its_integration_offered_to_be_removed(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    hass.states.async_set(appliance.cycle, "inactive")
    entry = await setup_watcher(hass, appliance)
    assert entry.state is ConfigEntryState.LOADED
    # the entry's own device, from when devices were linked, or the appliance's before
    own: dr.AnyDeviceEntry | None = next(iter(dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)), None)
    own = own or dr.async_get(hass).async_get(appliance.device_id)
    assert own is not None
    # not while it's there, since it would only be made again
    assert not await async_remove_config_entry_device(hass, entry, own)

    dr.async_get(hass).async_remove_device(appliance.device_id)
    await hass.async_block_till_done()
    # no longer watching, but waiting in case it's back
    assert entry.state is ConfigEntryState.SETUP_RETRY
    found = issue(hass, removed_issue_id(entry.entry_id))
    assert found is not None
    assert found.translation_key == "appliance_removed"
    assert found.translation_placeholders == {"name": "Dishwasher"}
    assert await async_remove_config_entry_device(hass, entry, own)

    await fix(hass, removed_issue_id(entry.entry_id))
    assert hass.config_entries.async_get_entry(entry.entry_id) is None
    assert issue(hass, removed_issue_id(entry.entry_id)) is None
    # its device with it
    if LINKED_DEVICES:
        assert dr.async_get(hass).async_get(own.id) is None


async def test_appliance_back_once_its_integration_restores_it(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    hass.states.async_set(appliance.cycle, "inactive")
    entry = await setup_watcher(hass, appliance)
    device_registry = dr.async_get(hass)
    device = device_registry.async_get(appliance.device_id)
    assert device is not None
    # one entry to a device from when devices were linked, any number before
    source = device.config_entry_id if LINKED_DEVICES else next(iter(device.config_entries))

    device_registry.async_remove_device(appliance.device_id)
    await hass.async_block_till_done()
    assert issue(hass, removed_issue_id(entry.entry_id)) is not None

    # the same identifiers bring back the same device
    restored = device_registry.async_get_or_create(config_entry_id=source, identifiers=device.identifiers)
    assert restored.id == appliance.device_id
    await hass.async_block_till_done()
    if LINKED_DEVICES:
        # told of as it's restored
        assert issue(hass, removed_issue_id(entry.entry_id)) is None
    else:
        # restored with nothing said of it before, so found when setup is next retried
        await hass.config_entries.async_reload(entry.entry_id)
    assert issue(hass, removed_issue_id(entry.entry_id)) is None


async def test_appliance_removed_while_home_assistant_was_off(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="Dryer", unique_id="gone", data={CONF_DEVICE_ID: "gone"})
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.reason == "Dryer has been removed from Home Assistant"
    assert issue(hass, removed_issue_id(entry.entry_id)) is not None
    # gone with the entry however it's removed
    assert await hass.config_entries.async_remove(entry.entry_id)
    assert issue(hass, removed_issue_id(entry.entry_id)) is None


async def test_power_sensor_removed(hass: HomeAssistant) -> None:
    registry = er.async_get(hass)
    registry.async_get_or_create("sensor", "shelly", "plug-power", suggested_object_id="washer_power")
    hass.states.async_set("sensor.washer_power", "0.4", {"unit_of_measurement": "W"})
    entry = await setup_power_watcher(hass)

    registry.async_remove("sensor.washer_power")
    hass.states.async_remove("sensor.washer_power")
    await hass.async_block_till_done()
    assert issue(hass, removed_issue_id(entry.entry_id)) is not None
    await fix(hass, removed_issue_id(entry.entry_id))
    assert hass.config_entries.async_get_entry(entry.entry_id) is None


async def test_power_sensor_never_registered_is_not_taken_for_removed(hass: HomeAssistant) -> None:
    """A template sensor with no unique id has no registry entry, so only its state says it's there"""
    hass.states.async_set("sensor.washer_power", "0.4", {"unit_of_measurement": "W"})
    entry = await setup_power_watcher(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert issue(hass, removed_issue_id(entry.entry_id)) is None


async def test_nowhere_to_notify_is_a_repair_till_there_is(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    await setup_watcher(hass, appliance, {"notify_start": True})
    calls = async_mock_service(hass, "notify", "send_message")

    await set_state(hass, appliance.cycle, "run")
    found = issue(hass, NO_TARGETS_ISSUE)
    assert found is not None
    assert found.translation_placeholders == {"name": "Dishwasher"}
    assert found.learn_more_url is not None

    er.async_get(hass).async_get_or_create("notify", "mobile_app", "phone", suggested_object_id="phone")
    await set_state(hass, appliance.cycle, "finished")
    assert len(calls) == 1
    assert issue(hass, NO_TARGETS_ISSUE) is None


async def test_errors_translated(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    hass.states.async_set(appliance.cycle, "inactive")
    entry = await setup_watcher(hass, appliance)
    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(DOMAIN, "snooze_maintenance", {"config_entry_id": "other"}, blocking=True)
    assert raised.value.translation_key == "not_tracked"
    assert str(raised.value) == "Maintenance isn't tracked for other"

    # a cycle state sensor gone, with the device still there
    er.async_get(hass).async_remove(appliance.cycle)
    await hass.config_entries.async_reload(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.reason == "No cycle state entity found for Dishwasher"

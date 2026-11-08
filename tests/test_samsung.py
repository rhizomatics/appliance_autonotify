"""Appliances found by what their entities do rather than by their integration: Samsung's, through SmartThings and
through LocalThings, as the same appliance through both"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import IntegrationNotLoaded
from homeassistant.setup import async_setup_component

from custom_components.appliance_autonotify import discovery
from custom_components.appliance_autonotify.const import CYCLE_SETTLE, DOMAIN
from custom_components.appliance_autonotify.discovery import find_appliances
from tests.ha_testing import MockConfigEntry

from .conftest import mock_supernotify
from .test_config_flow import start_discovery
from .test_watcher import ended, pass_time, set_state

DRYER = "e0e642fe-074f-343c-a118-dd5b73b7c5e0"
FRIDGE = "f4a57510-53ce-ed03-a6d2-3fffb364fad0"
TUMBLE_DRYER = "mdi:tumble-dryer"

# the entities of a real Samsung dryer and fridge, with the states their integrations list
SMARTTHINGS_DRYER: dict[str, tuple[str, list[str] | None]] = {
    "dryer_machine_state": ("sensor", ["pause", "run", "stop"]),
    "dryer_job_state": ("sensor", ["cooling", "drying", "finished", "none", "weight_sensing", "wrinkle_prevent"]),
    "completion_time": ("sensor", None),
    "operating_state": ("select", ["stop", "run", "pause"]),
    "energy_difference": ("sensor", None),
}
LOCALTHINGS_DRYER: dict[str, tuple[str, list[str] | None]] = {
    "machine_state": ("sensor", ["idle", "active", "pause"]),
    "progress": ("sensor", ["cooling", "drying", "finish", "idle", "wash"]),
    "progress_percentage": ("sensor", None),
    "finish_time": ("sensor", None),
    "dryer_type": ("sensor", ["electricity", "gas"]),
    "diagnosis": ("sensor", ["ready"]),
    "dryer_cycle_table_03": ("select", ["16", "19", "23"]),
}
SMARTTHINGS_FRIDGE: dict[str, tuple[str, list[str] | None]] = {
    "cooler_temperature": ("sensor", None),
    "freezer_temperature": ("sensor", None),
    "energy_difference": ("sensor", None),
    "power_cool": ("switch", None),
}
LOCALTHINGS_FRIDGE: dict[str, tuple[str, list[str] | None]] = {
    "instance_temperature": ("sensor", None),
    "connection_mode": ("sensor", ["observe", "poll"]),
    "selfcheck_status": ("sensor", None),
    "door_alert": ("select", ["1", "2", "3", "4"]),
}


def add_device(
    hass: HomeAssistant, platform: str, uuid: str, name: str, entities: dict[str, tuple[str, list[str] | None]]
) -> dict[str, str]:
    """A device as its integration registers it, by its Samsung id, with its entities by translation key"""
    source = MockConfigEntry(domain=platform)
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(config_entry_id=source.entry_id, identifiers={(platform, uuid)}, name=name)
    registry = er.async_get(hass)
    found = {"device_id": device.id}
    for key, (domain, options) in entities.items():
        found[key] = registry.async_get_or_create(
            domain,
            platform,
            f"{uuid}_{key}",
            suggested_object_id=f"{platform}_{name.lower().replace(' ', '_')}_{key}",
            device_id=device.id,
            config_entry=source,
            translation_key=key,
            capabilities={"options": options} if options else None,
        ).entity_id
    return found


def smartthings_dryer(hass: HomeAssistant) -> dict[str, str]:
    return add_device(hass, "smartthings", DRYER, "Asciugatrice", SMARTTHINGS_DRYER)


def localthings_dryer(hass: HomeAssistant) -> dict[str, str]:
    return add_device(hass, "localthings", DRYER, "Samsung Dryer", LOCALTHINGS_DRYER)


async def setup_appliance(hass: HomeAssistant, device_id: str, **options: object) -> MockConfigEntry:
    assert await async_setup_component(hass, "notify", {})
    entry = MockConfigEntry(domain=DOMAIN, title="Dryer", unique_id=device_id, data={"device_id": device_id}, options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_samsung_dryer_is_found(hass: HomeAssistant) -> None:
    dryer = smartthings_dryer(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["description_placeholders"]["found"] == "Appliances found:\n\n- Asciugatrice"
    await hass.config_entries.flow.async_configure(result["flow_id"], {"auto_discover": True})
    await hass.async_block_till_done()
    assert hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, dryer["device_id"]) is not None


async def test_one_added_later_is_set_up_as_it_appears(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    await hass.config_entries.flow.async_configure(result["flow_id"], {"auto_discover": True})
    await hass.async_block_till_done()
    dryer = localthings_dryer(hass)
    await hass.async_block_till_done()
    assert hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, dryer["device_id"]) is not None


async def test_fridge_is_no_appliance(hass: HomeAssistant) -> None:
    """A fridge on both integrations, the same appliance by its id as the dryer is, has no cycle to tell of"""
    add_device(hass, "smartthings", FRIDGE, "Frigorifero", SMARTTHINGS_FRIDGE)
    add_device(hass, "localthings", FRIDGE, "Samsung Refrigerator", LOCALTHINGS_FRIDGE)
    smartthings_dryer(hass)
    assert [appliance.name for appliance in find_appliances(hass)] == ["Asciugatrice"]


async def test_same_key_without_a_cycle_is_no_appliance(hass: HomeAssistant) -> None:
    """An entity of another integration that happens to have the same name, but none of the states of a cycle"""
    add_device(hass, "other", "1", "Heat pump", {"machine_state": ("sensor", ["heating", "cooling", "defrost"])})
    add_device(hass, "other", "2", "Gate", {"machine_state": ("select", ["idle", "active"])})
    add_device(hass, "other", "3", "Boiler", {"operation_state": ("sensor", None)})
    assert find_appliances(hass) == []


async def test_drying_is_a_cycle_over_once_it_only_tumbles(hass: HomeAssistant) -> None:
    dryer = smartthings_dryer(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(dryer["dryer_machine_state"], "stop")
    hass.states.async_set(dryer["dryer_job_state"], "none")
    entry = await setup_appliance(hass, dryer["device_id"], notify_start=True)

    await set_state(hass, dryer["dryer_machine_state"], "run")
    assert len(calls) == 1
    assert calls[0].data["message"] == "Asciugatrice started"
    assert calls[0].data["extra_data"]["notification_icon"] == TUMBLE_DRYER

    # what it's doing, and when it will be done, on the Live Activity
    hass.states.async_set(dryer["completion_time"], "2026-10-19T14:30:00+00:00")
    await set_state(hass, dryer["dryer_job_state"], "drying")
    assert calls[1].data["message"] == "drying"
    assert calls[1].data["extra_data"]["when"] == 1792420200
    await set_state(hass, dryer["dryer_job_state"], "cooling")
    assert calls[2].data["message"] == "cooling"

    # tumbling now and then so the load won't crease is the end, though it's still running
    await set_state(hass, dryer["dryer_job_state"], "wrinkle_prevent")
    assert len(calls) == 5
    assert calls[4].data == ended("Asciugatrice", entry.entry_id, TUMBLE_DRYER, track=True, force_resend=True)

    # nothing more while it's still said to be running, nor once it stops
    hass.states.async_set(dryer["dryer_machine_state"], "run", {"refreshed": True})
    await hass.async_block_till_done()
    await set_state(hass, dryer["dryer_machine_state"], "stop")
    assert len(calls) == 5

    # and the next is a cycle of its own
    await set_state(hass, dryer["dryer_machine_state"], "run")
    assert len(calls) == 6


async def test_stopped_is_the_end(hass: HomeAssistant) -> None:
    dryer = smartthings_dryer(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(dryer["dryer_machine_state"], "run")
    entry = await setup_appliance(hass, dryer["device_id"])
    for state in ("pause", "run", "unavailable", "run"):
        await set_state(hass, dryer["dryer_machine_state"], state)
    assert calls == []
    await set_state(hass, dryer["dryer_machine_state"], "stop")
    assert calls[-1].data == ended("Asciugatrice", entry.entry_id, TUMBLE_DRYER, track=True, force_resend=True)


async def test_local_dryer_with_progress_and_program(hass: HomeAssistant) -> None:
    dryer = localthings_dryer(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(dryer["machine_state"], "idle")
    hass.states.async_set(dryer["dryer_cycle_table_03"], "16")
    entry = await setup_appliance(hass, dryer["device_id"], notify_start=True, start_message="{name}: {program}")

    hass.states.async_set(dryer["progress"], "drying")
    await set_state(hass, dryer["machine_state"], "active")
    # the program from the cycle select, named per model
    assert calls[0].data["message"] == "Samsung Dryer: 16"
    await set_state(hass, dryer["progress_percentage"], "40")
    assert calls[-1].data["extra_data"]["progress"] == 40
    assert calls[-1].data["message"] == "drying"
    # with a countdown, the program beside the name, and what it's doing below
    await set_state(hass, dryer["finish_time"], "2026-10-20T09:41:00+00:00")
    await set_state(hass, dryer["progress_percentage"], "55")
    assert calls[-1].data["title"] == "Samsung Dryer · 16"
    assert calls[-1].data["message"] == "drying"

    # idle is the end once it has stayed so
    await set_state(hass, dryer["machine_state"], "idle")
    await pass_time(hass, CYCLE_SETTLE)
    assert calls[-1].data == ended("Samsung Dryer", entry.entry_id, TUMBLE_DRYER, track=True, force_resend=True)


async def test_local_network_preferred_to_the_cloud(hass: HomeAssistant) -> None:
    smartthings_dryer(hass)
    local = localthings_dryer(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["description_placeholders"]["found"] == "Appliances found:\n\n- Samsung Dryer"
    await hass.config_entries.flow.async_configure(result["flow_id"], {"auto_discover": True})
    await hass.async_block_till_done()
    appliances = [e.unique_id for e in hass.config_entries.async_entries(DOMAIN) if e.data.get("device_id")]
    assert appliances == [local["device_id"]]


async def test_local_integration_preferred_whatever_it_tells(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> None:
    """The integration on the local network is preferred even where the cloud one tells more of the cycle"""

    def loaded(hass: HomeAssistant, domain: str) -> SimpleNamespace:
        if domain not in ("smartthings", "localthings"):
            raise IntegrationNotLoaded(domain)
        return SimpleNamespace(iot_class="local_push" if domain == "localthings" else "cloud_push")

    monkeypatch.setattr(discovery, "async_get_loaded_integration", loaded)
    smartthings_dryer(hass)
    add_device(hass, "localthings", DRYER, "Samsung Dryer", {"machine_state": LOCALTHINGS_DRYER["machine_state"]})
    assert [appliance.name for appliance in find_appliances(hass)] == ["Samsung Dryer"]


async def test_already_set_up_through_the_cloud(hass: HomeAssistant) -> None:
    """Set up before the other integration was added, so not offered again through that one"""
    cloud = smartthings_dryer(hass)
    await setup_appliance(hass, cloud["device_id"])
    localthings_dryer(hass)
    assert [appliance.name for appliance in find_appliances(hass)] == ["Asciugatrice"]


async def test_cloud_heard_from_while_local_is_away(hass: HomeAssistant) -> None:
    cloud = smartthings_dryer(hass)
    local = localthings_dryer(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(local["machine_state"], "idle")
    hass.states.async_set(cloud["dryer_machine_state"], "stop")
    entry = await setup_appliance(hass, local["device_id"], notify_start=True)

    # the cloud lagging behind the local network is no second start, nor any end
    await set_state(hass, local["machine_state"], "active")
    await set_state(hass, cloud["dryer_machine_state"], "run")
    assert len(calls) == 1
    await set_state(hass, cloud["dryer_machine_state"], "stop")
    assert len(calls) == 1
    # nor is its stage, while the local one tells its own
    await set_state(hass, local["progress"], "drying")
    await set_state(hass, cloud["dryer_job_state"], "wrinkle_prevent")
    assert [call.data["message"] for call in calls] == ["Samsung Dryer started", "drying"]

    # while the local one can't be heard from, the cloud one tells what it's doing, and when it ends
    for entity_id in (local["machine_state"], local["progress"]):
        await set_state(hass, entity_id, "unavailable")
    await set_state(hass, cloud["dryer_machine_state"], "run")
    await set_state(hass, cloud["dryer_job_state"], "cooling")
    assert calls[-1].data["message"] == "cooling"
    await set_state(hass, cloud["dryer_job_state"], "wrinkle_prevent")
    assert calls[-1].data == ended("Samsung Dryer", entry.entry_id, TUMBLE_DRYER, force_resend=True)
    count = len(calls)

    # nor is the local one coming back a cycle of its own
    await set_state(hass, local["machine_state"], "idle")
    await pass_time(hass, CYCLE_SETTLE)
    assert len(calls) == count


async def test_offered_through_the_cloud_then_found_locally(hass: HomeAssistant) -> None:
    """Offered through SmartThings, then LocalThings added: one offer, through the local network"""
    await start_discovery(hass, auto_discover=False)
    smartthings_dryer(hass)
    await hass.async_block_till_done()
    local = localthings_dryer(hass)
    await hass.async_block_till_done()
    offered = [flow["context"]["unique_id"] for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN)]
    assert offered == [local["device_id"]]


async def test_end_told_by_the_cloud_before_the_local_one_went(hass: HomeAssistant) -> None:
    """Stopped as the cloud said, while the local network still said it was running, then that gone quiet"""
    cloud = smartthings_dryer(hass)
    local = localthings_dryer(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(local["machine_state"], "active")
    hass.states.async_set(cloud["dryer_machine_state"], "run")
    entry = await setup_appliance(hass, local["device_id"])

    await set_state(hass, cloud["dryer_machine_state"], "stop")
    assert calls == []
    await set_state(hass, local["machine_state"], "unavailable")
    assert calls[-1].data == ended("Samsung Dryer", entry.entry_id, TUMBLE_DRYER, track=True, force_resend=True)


async def test_still_running_after_its_stage_said_it_was_over(hass: HomeAssistant) -> None:
    """Paused and carrying on during wrinkle prevent, the door opened say, is no new cycle"""
    dryer = smartthings_dryer(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(dryer["dryer_machine_state"], "run")
    await setup_appliance(hass, dryer["device_id"], notify_start=True)

    await set_state(hass, dryer["dryer_job_state"], "wrinkle_prevent")
    count = len(calls)
    for state in ("pause", "run"):
        await set_state(hass, dryer["dryer_machine_state"], state)
    assert len(calls) == count


async def test_start_waits_for_the_program(hass: HomeAssistant) -> None:
    """LocalThings reports the cycle under way a moment before the program chosen, as on a real cold air cycle"""
    dryer = localthings_dryer(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(dryer["machine_state"], "idle")
    hass.states.async_set(dryer["dryer_cycle_table_03"], "16")
    await setup_appliance(hass, dryer["device_id"], notify_start=True, start_message="{program}")

    with patch("custom_components.appliance_autonotify.watcher.START_SETTLE", 0.2):
        hass.states.async_set(dryer["machine_state"], "active")
        await asyncio.sleep(0.05)
        hass.states.async_set(dryer["dryer_cycle_table_03"], "24")
        assert calls == []
        await asyncio.sleep(0.3)
        await hass.async_block_till_done()
    assert calls[0].data["message"] == "24"


async def test_start_over_before_it_was_told(hass: HomeAssistant) -> None:
    dryer = localthings_dryer(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(dryer["machine_state"], "idle")
    await setup_appliance(hass, dryer["device_id"], notify_start=True)

    with patch("custom_components.appliance_autonotify.watcher.START_SETTLE", 0.2):
        hass.states.async_set(dryer["machine_state"], "active")
        await asyncio.sleep(0.05)
        hass.states.async_set(dryer["machine_state"], "idle")
        await asyncio.sleep(0.3)
        await hass.async_block_till_done()
    assert calls == []


async def test_reminder_names_the_program_of_the_cycle_over(hass: HomeAssistant) -> None:
    """A Samsung dryer goes back to the program it starts on once a cycle is over, which isn't the one to remind of"""
    dryer = localthings_dryer(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(dryer["machine_state"], "idle")
    hass.states.async_set(dryer["dryer_cycle_table_03"], "24")
    await setup_appliance(hass, dryer["device_id"], end_message="{program}", reminder=1)

    await set_state(hass, dryer["machine_state"], "active")
    await set_state(hass, dryer["progress"], "finish")
    assert calls[-1].data["message"] == "24"
    await set_state(hass, dryer["dryer_cycle_table_03"], "16")
    await pass_time(hass, 60)
    assert calls[-1].data["message"] == "24"


@pytest.mark.parametrize(
    ("options", "title", "message"),
    [
        ({"live_detail": "program_status", "live_title": "name"}, "Samsung Dryer", "23 · drying"),
        # the status alone, with the program in the title, there being no timer to take the message's place
        ({"live_detail": "status"}, "Samsung Dryer · 23", "drying"),
        ({"live_detail": "program"}, "Samsung Dryer", "23"),
    ],
)
async def test_status_and_program_shown_in_place_of_the_time_left(
    hass: HomeAssistant, options: dict[str, str], title: str, message: str
) -> None:
    """The stage of any appliance is its status, shown alone, or with its program, in place of the time left"""
    dryer = localthings_dryer(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(dryer["machine_state"], "idle")
    hass.states.async_set(dryer["dryer_cycle_table_03"], "23")
    hass.states.async_set(dryer["finish_time"], "2026-10-06T21:44:16+00:00")
    await setup_appliance(hass, dryer["device_id"], **options)

    await set_state(hass, dryer["machine_state"], "active")
    await set_state(hass, dryer["progress"], "drying")
    assert (calls[-1].data["title"], calls[-1].data["message"]) == (title, message)
    assert "when" not in calls[-1].data["extra_data"]

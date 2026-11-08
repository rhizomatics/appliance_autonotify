"""Maintenance, offered once, counted in cycles or read from how much life a part has left, on one to-do list"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
from homeassistant.const import CONF_DEVICE_ID, EVENT_HOMEASSISTANT_FINAL_WRITE
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed, async_mock_service

from custom_components.appliance_autonotify.const import DOMAIN, VACUUM_SETTLE
from custom_components.appliance_autonotify.maintenance import DATA_MAINTENANCE, STORAGE_KEY

from .conftest import FakeAppliance, add_appliance, mock_supernotify, setup_watcher
from .test_vacuum import add_vacuum, advance, setup_vacuum
from .test_watcher import set_state

if TYPE_CHECKING:
    from freezegun.api import FrozenDateTimeFactory

LIST = "todo.appliance_maintenance"


async def setup_list(hass: HomeAssistant) -> MockConfigEntry:
    """The entry for automatic discovery, which holds the list"""
    entry = MockConfigEntry(domain=DOMAIN, unique_id="discovery", data={"type": "discovery"}, options={"auto_discover": False})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def cycle(hass: HomeAssistant, appliance: FakeAppliance) -> None:
    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.cycle, "finished")


async def press(hass: HomeAssistant, action: str) -> None:
    hass.bus.async_fire("mobile_app_notification_action", {"action": action})
    await hass.async_block_till_done()


async def items(hass: HomeAssistant) -> list[dict[str, Any]]:
    result = await hass.services.async_call("todo", "get_items", {"entity_id": LIST}, blocking=True, return_response=True)
    return list(result[LIST]["items"])  # type: ignore[index]


def tag(entry_id: str, key: str) -> str:
    return f"appliance_{entry_id}_maintenance_{hashlib.sha256(key.encode()).hexdigest()[:8]}"


def maintenance_calls(calls: list[ServiceCall]) -> list[ServiceCall]:
    """Those telling of maintenance due, not those clearing them"""
    return [
        c
        for c in calls
        if "_maintenance_" in str(c.data.get("extra_data", {}).get("mobile_push_notification_tag"))
        and not c.data["extra_data"].get("mobile_push_clear_notification")
    ]


async def test_offered_once_on_the_first_end(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    entry = await setup_watcher(hass, appliance)
    track = {"action": f"APPLIANCE_TRACK_MAINTENANCE_{entry.entry_id}", "title": "Track Maintenance"}

    await cycle(hass, appliance)
    assert track in calls[-1].data["actions"]
    await cycle(hass, appliance)
    assert track not in calls[-1].data["actions"]
    # and nothing counted or told meanwhile
    assert not hass.data[DATA_MAINTENANCE].tracked(entry.entry_id)
    assert not maintenance_calls(calls)


async def test_not_offered_with_nothing_to_maintain(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass, name="Kettle")
    calls = mock_supernotify(hass)
    await setup_watcher(hass, appliance)
    await cycle(hass, appliance)
    assert all("TRACK" not in a["action"] for a in calls[-1].data["actions"])


async def test_tracked_once_asked_for(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    await setup_list(hass)
    entry = await setup_watcher(hass, appliance)
    await cycle(hass, appliance)

    await press(hass, f"APPLIANCE_TRACK_MAINTENANCE_{entry.entry_id}")
    assert entry.options == {"maintenance": True}
    tracker = hass.data[DATA_MAINTENANCE]
    assert tracker.tracked(entry.entry_id)
    # counted from now, not from the cycle that offered it
    await cycle(hass, appliance)
    assert {tracker.cycles(entry.entry_id, item) for item in entry.runtime_data.maintenance_items} == {1}
    assert not maintenance_calls(calls)


async def test_due_after_its_cycles(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    await setup_list(hass)
    # the dishwasher's filter every 2 cycles, and no machine clean
    entry = await setup_watcher(hass, appliance, {"maintenance": True, "maintenance_filter": 2, "maintenance_machine_clean": 0})
    filter_tag = tag(entry.entry_id, "filter")

    await cycle(hass, appliance)
    assert not maintenance_calls(calls)
    assert hass.states.get(LIST).state == "0"

    await cycle(hass, appliance)
    assert calls[-1].data == {
        "message": "Filter clean, 2 cycles since the last one",
        "title": "Dishwasher",
        "force_resend": True,
        "actions": [
            {"action": f"APPLIANCE_MAINTAINED_{entry.entry_id}_filter", "title": "Done"},
            {"action": f"APPLIANCE_MAINTENANCE_LATER_{entry.entry_id}_filter", "title": "In a Month"},
        ],
        "extra_data": {"notification_icon": "mdi:wrench-clock", "mobile_push_notification_tag": filter_tag},
    }
    assert hass.states.get(LIST).state == "1"
    assert await items(hass) == [
        {
            "uid": f"{entry.entry_id}|filter",
            "summary": "Dishwasher: Filter clean",
            "status": "needs_action",
            "description": "Filter clean, 2 cycles since the last one",
        }
    ]

    # told the once, though still due
    await cycle(hass, appliance)
    assert len(maintenance_calls(calls)) == 1
    assert (await items(hass))[0]["description"] == "Filter clean, 3 cycles since the last one"

    # ticked off, it starts again
    await hass.services.async_call(
        "todo", "update_item", {"entity_id": LIST, "item": f"{entry.entry_id}|filter", "status": "completed"}, blocking=True
    )
    await hass.async_block_till_done()
    assert await items(hass) == []
    await cycle(hass, appliance)
    assert len(maintenance_calls(calls)) == 1
    await cycle(hass, appliance)
    assert len(maintenance_calls(calls)) == 2


async def test_done_and_later_from_the_notification(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    await setup_list(hass)
    entry = await setup_watcher(hass, appliance, {"maintenance": True, "maintenance_filter": 1, "maintenance_machine_clean": 1})
    await cycle(hass, appliance)
    assert len(maintenance_calls(calls)) == 2

    # done, and the notification cleared
    await press(hass, f"APPLIANCE_MAINTAINED_{entry.entry_id}_filter")
    assert calls[-1].data["extra_data"] == {
        "mobile_push_notification_tag": tag(entry.entry_id, "filter"),
        "mobile_push_clear_notification": True,
    }
    assert [i["uid"] for i in await items(hass)] == [f"{entry.entry_id}|machine_clean"]

    # put off for a month, off the list till then
    await press(hass, f"APPLIANCE_MAINTENANCE_LATER_{entry.entry_id}_machine_clean")
    assert await items(hass) == []
    freezer.tick(timedelta(days=29))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert await items(hass) == []
    freezer.tick(timedelta(days=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(LIST).state == "1"
    told = len(maintenance_calls(calls))
    # and told of again with the next cycle, along with the filter due again by then
    await cycle(hass, appliance)
    assert len(maintenance_calls(calls)) == told + 2


async def test_deleted_from_the_list_is_put_off(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    mock_supernotify(hass)
    await setup_list(hass)
    entry = await setup_watcher(hass, appliance, {"maintenance": True, "maintenance_filter": 1})
    await cycle(hass, appliance)
    await hass.services.async_call(
        "todo", "remove_item", {"entity_id": LIST, "item": [f"{entry.entry_id}|filter"]}, blocking=True
    )
    await hass.async_block_till_done()
    assert [i["uid"] for i in await items(hass)] == []
    # put off, not done
    tracker = hass.data[DATA_MAINTENANCE]
    assert tracker.cycles(entry.entry_id, tracker.item(entry.entry_id, "filter")) == 1


async def test_counts_kept_across_restarts(hass: HomeAssistant, hass_storage: dict[str, Any]) -> None:
    appliance = add_appliance(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Dishwasher",
        unique_id=appliance.device_id,
        data={CONF_DEVICE_ID: appliance.device_id},
        options={"maintenance": True},
        minor_version=3,
    )
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "key": STORAGE_KEY,
        "data": {"entries": {entry.entry_id: {"items": {"filter": {"cycles": 29}}}}},
    }
    calls = mock_supernotify(hass)
    assert await async_setup_component(hass, "notify", {})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await cycle(hass, appliance)
    assert maintenance_calls(calls)[0].data["message"] == "Filter clean, 30 cycles since the last one"
    # written at the latest as Home Assistant stops
    hass.bus.async_fire(EVENT_HOMEASSISTANT_FINAL_WRITE)
    await hass.async_block_till_done()
    saved = hass_storage[STORAGE_KEY]["data"]["entries"][entry.entry_id]["items"]
    assert saved["filter"] == {"cycles": 30, "told": True}
    assert saved["machine_clean"] == {"cycles": 1}


async def test_actions(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    await setup_list(hass)
    entry = await setup_watcher(hass, appliance, {"maintenance": True})
    tracker = hass.data[DATA_MAINTENANCE]
    filter_item = tracker.item(entry.entry_id, "filter")

    # the cycles since it was last done, as counted before it was tracked here
    await hass.services.async_call(
        DOMAIN, "reset_maintenance", {"config_entry_id": entry.entry_id, "item": "filter", "cycles": 29}, blocking=True
    )
    await cycle(hass, appliance)
    assert [c.data["message"] for c in maintenance_calls(calls)] == ["Filter clean, 30 cycles since the last one"]

    await hass.services.async_call(DOMAIN, "snooze_maintenance", {"config_entry_id": entry.entry_id}, blocking=True)
    await hass.async_block_till_done()
    assert await items(hass) == []

    await hass.services.async_call(DOMAIN, "reset_maintenance", {"config_entry_id": entry.entry_id}, blocking=True)
    assert tracker.cycles(entry.entry_id, filter_item) == 0

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "reset_maintenance", {"config_entry_id": entry.entry_id, "item": "salt"}, blocking=True
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "reset_maintenance", {"config_entry_id": "nothing"}, blocking=True)


def add_lifespan(hass: HomeAssistant, device_id: str, part: str, value: str, reset: bool = True) -> str:
    """A part's life left as a robot vacuum's integration reports it, with the button to reset it"""
    registry = er.async_get(hass)
    sensor = registry.async_get_or_create(
        "sensor",
        "ecovacs",
        f"lifespan_{part}",
        suggested_object_id=f"bruno_{part}_lifespan",
        device_id=device_id,
        translation_key=f"lifespan_{part}",
        unit_of_measurement="%",
    ).entity_id
    hass.states.async_set(sensor, value, {"unit_of_measurement": "%", "friendly_name": f"Bruno {part.title()} lifespan"})
    button = registry.async_get_or_create(
        "button",
        "ecovacs",
        f"reset_lifespan_{part}",
        suggested_object_id=f"bruno_reset_{part}",
        device_id=device_id,
        translation_key=f"reset_lifespan_{part}",
    ).entity_id
    if reset:
        hass.states.async_set(button, "unknown")
    else:
        registry.async_update_entity(button, disabled_by=er.RegistryEntryDisabler.INTEGRATION)
    return sensor


async def clean(hass: HomeAssistant, freezer: FrozenDateTimeFactory, vacuum: str) -> None:
    await set_state(hass, vacuum, "cleaning")
    await advance(hass, freezer, 600)
    await set_state(hass, vacuum, "returning")
    await set_state(hass, vacuum, "docked")
    await advance(hass, freezer, VACUUM_SETTLE)


async def test_lifespan_of_a_vacuums_parts(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    device_id, vacuum = add_vacuum(hass, platform="ecovacs")
    filter_sensor = add_lifespan(hass, device_id, "filter", "5")
    brush = add_lifespan(hass, device_id, "brush", "61.26", reset=False)
    pressed = async_mock_service(hass, "button", "press")
    calls = mock_supernotify(hass)
    await setup_list(hass)
    hass.states.async_set(vacuum, "docked")
    entry = await setup_vacuum(hass, device_id, maintenance=True)
    # already low, so on the list straight away, and told of as the cleaning ends
    assert [i["summary"] for i in await items(hass)] == ["Bruno: Filter lifespan"]
    await clean(hass, freezer, vacuum)
    assert [c.data["message"] for c in maintenance_calls(calls)] == ["Filter lifespan at 5%"]

    # done resets it with the integration's own button, which makes it read as replaced
    await press(hass, f"APPLIANCE_MAINTAINED_{entry.entry_id}_{filter_sensor}")
    assert [c.data["entity_id"] for c in pressed] == ["button.bruno_reset_filter"]
    assert await items(hass) == []
    await set_state(hass, filter_sensor, "100")
    assert await items(hass) == []

    # one running low between cleanings is told of as it does, the once
    for value in ("9", "8"):
        hass.states.async_set(brush, value, {"unit_of_measurement": "%", "friendly_name": "Bruno Brush lifespan"})
        await hass.async_block_till_done()
    assert [c.data["message"] for c in maintenance_calls(calls)][1:] == ["Brush lifespan at 9%"]
    assert [i["summary"] for i in await items(hass)] == ["Bruno: Brush lifespan"]

    # with no button to reset it, done leaves it off the list till it's been replaced and runs low again
    await press(hass, f"APPLIANCE_MAINTAINED_{entry.entry_id}_{brush}")
    assert len(pressed) == 1
    assert await items(hass) == []
    await clean(hass, freezer, vacuum)
    assert len(maintenance_calls(calls)) == 2
    for value in ("100", "7"):
        hass.states.async_set(brush, value, {"unit_of_measurement": "%", "friendly_name": "Bruno Brush lifespan"})
    await hass.async_block_till_done()
    assert [i["summary"] for i in await items(hass)] == ["Bruno: Brush lifespan"]
    assert len(maintenance_calls(calls)) == 3


async def test_part_dropping_out_isnt_told_again(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """As an Ecovacs part's sensor does with the cloud, often around docking"""
    device_id, vacuum = add_vacuum(hass, platform="ecovacs")
    part = add_lifespan(hass, device_id, "filter", "50")
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    await setup_vacuum(hass, device_id, maintenance=True)
    low = {"unit_of_measurement": "%", "friendly_name": "Bruno Filter lifespan"}
    hass.states.async_set(part, "5", low)
    await hass.async_block_till_done()
    hass.states.async_set(part, "unavailable")
    await clean(hass, freezer, vacuum)
    hass.states.async_set(part, "5", low)
    await hass.async_block_till_done()
    assert [c.data["message"] for c in maintenance_calls(calls)] == ["Filter lifespan at 5%"]


async def test_parts_reset_only_when_due(hass: HomeAssistant) -> None:
    device_id, vacuum = add_vacuum(hass, platform="ecovacs")
    add_lifespan(hass, device_id, "filter", "4")
    brush = add_lifespan(hass, device_id, "brush", "61.26")
    # a part whose life isn't a percentage can never be due, so isn't an item
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor", "ecovacs", "lifespan_mop", device_id=device_id, translation_key="lifespan_mop", unit_of_measurement="h"
    )
    pressed = async_mock_service(hass, "button", "press")
    mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    entry = await setup_vacuum(hass, device_id, maintenance=True)
    assert len(entry.runtime_data.maintenance_items) == 2

    # all of them done, which leaves alone the life of the parts that aren't low, and resets one put off
    await hass.services.async_call(DOMAIN, "snooze_maintenance", {"config_entry_id": entry.entry_id}, blocking=True)
    await hass.services.async_call(DOMAIN, "reset_maintenance", {"config_entry_id": entry.entry_id}, blocking=True)
    assert [c.data["entity_id"] for c in pressed] == ["button.bruno_reset_filter"]
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "reset_maintenance", {"config_entry_id": entry.entry_id, "item": brush, "cycles": 3}, blocking=True
        )


async def test_told_again_once_due_again(hass: HomeAssistant) -> None:
    """As after its cycles are changed while it was due"""
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    entry = await setup_watcher(hass, appliance, {"maintenance": True, "maintenance_filter": 1, "maintenance_machine_clean": 0})
    await cycle(hass, appliance)
    assert len(maintenance_calls(calls)) == 1
    hass.config_entries.async_update_entry(entry, options=dict(entry.options) | {"maintenance_filter": 3})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    # at 2, no longer due
    await cycle(hass, appliance)
    assert len(maintenance_calls(calls)) == 1
    await cycle(hass, appliance)
    assert [c.data["message"] for c in maintenance_calls(calls)][-1] == "Filter clean, 3 cycles since the last one"


async def test_track_keeps_the_reminders(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    entry = await setup_watcher(hass, appliance, {"reminder": 10})
    await cycle(hass, appliance)
    told = len(calls)

    await press(hass, f"APPLIANCE_TRACK_MAINTENANCE_{entry.entry_id}")
    assert entry.options == {"reminder": 10, "maintenance": True}
    assert hass.data[DATA_MAINTENANCE].tracked(entry.entry_id)
    await advance(hass, freezer, 600)
    # reminded as before, and no longer offered tracking
    assert len(calls) == told + 1
    assert all("TRACK" not in a["action"] for a in calls[-1].data["actions"])

    # nor does a press left on that notification turn it back on once it's been turned off
    hass.config_entries.async_update_entry(entry, options={"reminder": 10, "maintenance": False})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await press(hass, f"APPLIANCE_TRACK_MAINTENANCE_{entry.entry_id}")
    assert entry.options == {"reminder": 10, "maintenance": False}
    assert not hass.data[DATA_MAINTENANCE].tracked(entry.entry_id)


async def test_without_supernotify(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    entry = await setup_watcher(hass, appliance, {"maintenance": True, "maintenance_filter": 1, "targets": ["notify.phone"]})
    # after notify itself is set up, which has the action of its own
    sent = async_mock_service(hass, "notify", "send_message")
    await cycle(hass, appliance)
    assert [c.data["message"] for c in sent][-1] == "Filter clean, 1 cycle since the last one"
    assert hass.data[DATA_MAINTENANCE].tracked(entry.entry_id)


async def test_forgotten_with_the_appliance(hass: HomeAssistant, hass_storage: dict[str, Any]) -> None:
    appliance = add_appliance(hass)
    mock_supernotify(hass)
    entry = await setup_watcher(hass, appliance, {"maintenance": True})
    await cycle(hass, appliance)
    tracker = hass.data[DATA_MAINTENANCE]
    assert tracker.tracked(entry.entry_id)
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert not tracker.tracked(entry.entry_id)
    assert entry.entry_id not in tracker._data["entries"]


async def test_settings(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    mock_supernotify(hass)
    entry = await setup_watcher(hass, appliance)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    items_section = next(v for k, v in result["data_schema"].schema.items() if k == "maintenance_items").schema.schema
    assert {str(k): k.default() for k in items_section} == {"maintenance_filter": 30, "maintenance_machine_clean": 60}

    # left as they come, nothing is kept, and an item at 0 is one taken out
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "maintenance": True,
            "start": {},
            "end": {},
            "notify": {},
            "maintenance_items": {"maintenance_filter": 30, "maintenance_machine_clean": 0},
        },
    )
    await hass.async_block_till_done()
    assert entry.options == {"maintenance": True, "maintenance_machine_clean": 0}
    assert [item.key for item in entry.runtime_data.maintenance_items] == ["filter"]

    # every item taken out still leaves the settings there to put them back
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "maintenance": True,
            "start": {},
            "end": {},
            "notify": {},
            "maintenance_items": {"maintenance_filter": 0, "maintenance_machine_clean": 0},
        },
    )
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "maintenance" in {str(k) for k in result["data_schema"].schema}
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "maintenance": True,
            "start": {},
            "end": {},
            "notify": {},
            "maintenance_items": {"maintenance_filter": 30, "maintenance_machine_clean": 0},
        },
    )
    await hass.async_block_till_done()
    assert entry.options == {"maintenance": True, "maintenance_machine_clean": 0}

    # turned off once it was on is kept, so it isn't offered again
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"maintenance": False, "start": {}, "end": {}, "notify": {}}
    )
    await hass.async_block_till_done()
    assert entry.options == {"maintenance": False}
    assert not hass.data[DATA_MAINTENANCE].tracked(entry.entry_id)

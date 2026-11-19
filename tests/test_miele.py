"""Miele appliances, whose status every appliance has, a fridge as much as a washer, with progress worked out from the
time taken and the time left, in beta till it's been tried with a real appliance"""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.appliance_autonotify.const import PROGRESS_TICK
from custom_components.appliance_autonotify.discovery import find_appliances
from custom_components.appliance_autonotify.platforms import profile_for

from .conftest import mock_supernotify
from .test_samsung import add_device, setup_appliance
from .test_vacuum import add_sensor, add_vacuum, setup_vacuum
from .test_watcher import ended, pass_time, set_state

# the states the integration lists for the status of any appliance
STATUSES = [
    "autocleaning", "failure", "idle", "in_use", "not_connected", "off", "on", "pause", "program_ended",
    "program_interrupted", "programmed", "reserved", "rinse_hold", "service", "supercooling",
    "supercooling_superfreezing", "superfreezing", "superheating", "waiting_to_start",
]  # fmt: skip
PHASES = ["anti_crease", "drain", "finished", "main_wash", "not_running", "pre_wash", "rinse", "spin"]
WASHER: dict[str, tuple[str, list[str] | None]] = {
    "status": ("sensor", STATUSES),
    "program_phase": ("sensor", PHASES),
    "program_id": ("sensor", ["cottons", "minimum_iron", "quick_power_wash"]),
    "finish": ("sensor", None),
    "remaining_time": ("sensor", None),
    "elapsed_time": ("sensor", None),
    "spin_speed": ("sensor", None),
}
FRIDGE: dict[str, tuple[str, list[str] | None]] = {"status": ("sensor", STATUSES), "temperature_zone_2": ("sensor", None)}
NOW = datetime.fromisoformat("2026-11-13T10:00:00+00:00")
WASHING_MACHINE = "mdi:washing-machine"


def miele_device(
    hass: HomeAssistant, serial: str, name: str, model: str, entities: dict[str, tuple[str, list[str] | None]]
) -> dict[str, str]:
    """A device as Miele registers it, with its model named for its type"""
    found = add_device(hass, "miele", serial, name, entities)
    dr.async_get(hass).async_update_device(found["device_id"], model=model)
    return found


def test_miele_is_in_beta() -> None:
    profile = profile_for("miele")
    assert profile.beta
    assert [profile.cycle_state(s) for s in ("in_use", "program_ended", "program_interrupted", "superfreezing")] == [
        "run",
        "finished",
        "aborting",
        "superfreezing",
    ]


async def test_only_appliances_with_a_program_phase_have_a_cycle(hass: HomeAssistant) -> None:
    """A fridge has the same status as a washer, with the same states, but no cycle"""
    miele_device(hass, "000123456789", "Fridge", "Fridge", FRIDGE)
    washer = miele_device(hass, "000987654321", "Washer", "Washing machine", WASHER)
    assert [appliance.device_id for appliance in find_appliances(hass)] == [washer["device_id"]]


async def test_washer_cycle(hass: HomeAssistant, freezer) -> None:
    freezer.move_to(NOW)
    washer = miele_device(hass, "000987654321", "Washer", "Washing machine", WASHER)
    calls = mock_supernotify(hass)
    hass.states.async_set(washer["status"], "off")
    hass.states.async_set(washer["program_phase"], "not_running")
    hass.states.async_set(washer["program_id"], "cottons")
    entry = await setup_appliance(hass, washer["device_id"], notify_start=True)
    watcher = entry.runtime_data
    # its type from its model, its programs being named for neither
    assert watcher.appliance_type == "washer"
    assert watcher.entity_ids["active_program"] == washer["program_id"]

    await set_state(hass, washer["status"], "in_use")
    assert [call.data["message"] for call in calls] == ["Washer started"]
    assert calls[0].data["extra_data"]["notification_icon"] == WASHING_MACHINE

    # how far along it is from the time it has taken and the time it has left
    hass.states.async_set(washer["finish"], (NOW + timedelta(minutes=60)).isoformat())
    hass.states.async_set(washer["elapsed_time"], "20", {"unit_of_measurement": "min"})
    await set_state(hass, washer["program_phase"], "main_wash")
    assert calls[-1].data["message"] == "main_wash"
    extra = calls[-1].data["extra_data"]
    assert extra["progress"] == 25
    assert extra["when"] == int((NOW + timedelta(minutes=60)).timestamp())

    # and as time goes by, with the time taken moving on too
    sent = len(calls)
    freezer.tick(timedelta(minutes=20))
    hass.states.async_set(washer["elapsed_time"], "40", {"unit_of_measurement": "min"})
    await pass_time(hass, PROGRESS_TICK)
    assert len(calls) == sent + 1
    assert calls[-1].data["extra_data"]["progress"] == 50

    # done once it only turns its load now and then so it won't crease, and its end after is no second one
    await set_state(hass, washer["program_phase"], "anti_crease")
    assert calls[-1].data == ended("Washer", entry.entry_id, WASHING_MACHINE, track=True, force_resend=True)
    sent = len(calls)
    await set_state(hass, washer["status"], "program_ended")
    await set_state(hass, washer["status"], "on")
    assert len(calls) == sent


async def test_interrupted_is_no_end(hass: HomeAssistant) -> None:
    washer = miele_device(hass, "000987654321", "Washer", "Washing machine", WASHER)
    calls = mock_supernotify(hass)
    hass.states.async_set(washer["status"], "off")
    await setup_appliance(hass, washer["device_id"], notify_start=True)
    await set_state(hass, washer["status"], "in_use")
    await set_state(hass, washer["status"], "program_interrupted")
    # the Live Activity closed, with no end notification after, as there is for a cycle that finishes
    assert len(calls) == 2
    assert calls[-1].data["extra_data"]["mobile_push_clear_notification"] is True


async def test_vacuum_status_is_its_program_phase(hass: HomeAssistant) -> None:
    """A Miele robot vacuum's status is the one every Miele appliance has, so what it's doing is its program phase,
    and it's set up as a vacuum, traced while Miele is new"""
    device_id, vacuum = add_vacuum(hass, platform="miele")
    status = add_sensor(hass, device_id, "sensor", "status", "enum", translation_key="status")
    phase = add_sensor(hass, device_id, "sensor", "program_phase", "enum", translation_key="program_phase")
    program = add_sensor(hass, device_id, "sensor", "program_id", "enum", translation_key="program_id")
    [appliance] = find_appliances(hass)
    assert appliance.type == "vacuum"

    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    hass.states.async_set(status, "on")
    hass.states.async_set(phase, "docked")
    hass.states.async_set(program, "auto")
    entry = await setup_vacuum(hass, device_id)
    watcher = entry.runtime_data
    assert watcher.entity_ids == {"stage": phase, "active_program": program}
    assert watcher.trace is not None

    hass.states.async_set(status, "in_use")
    hass.states.async_set(phase, "vacuum_cleaning")
    await set_state(hass, vacuum, "cleaning")
    await set_state(hass, phase, "returning")
    assert [c.data["message"] for c in calls] == ["Bruno started", "auto · vacuum_cleaning", "auto · returning"]

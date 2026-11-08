"""A cycle under way carried through a restart of Home Assistant"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.appliance_autonotify.const import (
    CYCLE_SETTLE,
    CYCLE_STORE_VERSION,
    VACUUM_MIDWAY_SETTLE,
    VACUUM_SETTLE,
)

from .conftest import add_appliance, mock_supernotify, setup_watcher
from .test_vacuum import add_vacuum, setup_vacuum
from .test_watcher import PIZZA, ended, pass_time, set_state, set_temperature, setup_power_watcher, start_oven

if TYPE_CHECKING:
    from freezegun.api import FrozenDateTimeFactory

POWER = "sensor.washer_power"


def store_key(entry: MockConfigEntry) -> str:
    return f"appliance_autonotify.cycle.{entry.entry_id}"


async def restart(hass: HomeAssistant, entry: MockConfigEntry, freezer: FrozenDateTimeFactory, off_for: float = 0) -> None:
    """Home Assistant stopping and, after a while off, starting again, which for the appliance is being unloaded and
    set up again, with whatever was kept of its cycle"""
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    freezer.tick(off_for)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    # anything already due as it starts
    await pass_time(hass, 0)


async def wait(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float) -> None:
    freezer.tick(seconds)
    await pass_time(hass, 0)


def messages(calls: list[Any]) -> list[str]:
    return [call.data["message"] for call in calls]


async def test_power_end_waited_for_through_a_restart(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    calls = mock_supernotify(hass)
    hass.states.async_set(POWER, "0", {"unit_of_measurement": "W"})
    entry = await setup_power_watcher(hass, threshold=5, grace_period=120, notify_start=True)
    await set_state(hass, POWER, "1800")
    assert messages(calls) == ["Washer started"]

    # paused to soak, or done, with Home Assistant restarting part way through the wait to see which
    await set_state(hass, POWER, "2")
    await wait(hass, freezer, 30)
    await restart(hass, entry, freezer, off_for=20)
    assert entry.runtime_data.running
    assert messages(calls) == ["Washer started"]

    # told once the rest of the wait is over, and not started again
    await wait(hass, freezer, 69)
    assert len(calls) == 1
    await wait(hass, freezer, 1)
    assert messages(calls) == ["Washer started", "Washer is finished", "Washer is finished"]
    assert calls[2].data == ended("Washer", entry.entry_id, "mdi:washing-machine", track=True, force_resend=True)
    assert not entry.runtime_data.running


async def test_power_end_due_while_off_told_as_it_starts(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    calls = mock_supernotify(hass)
    hass.states.async_set(POWER, "0", {"unit_of_measurement": "W"})
    entry = await setup_power_watcher(hass, threshold=5, grace_period=120)
    await set_state(hass, POWER, "1800")
    await set_state(hass, POWER, "0")
    await wait(hass, freezer, 30)
    started = len(calls)

    await restart(hass, entry, freezer, off_for=600)
    assert messages(calls)[started:] == ["Washer is finished", "Washer is finished"]
    assert not entry.runtime_data.running

    # and only once
    await wait(hass, freezer, 600)
    assert len(calls) == started + 2


async def test_power_stopped_while_off_waits_from_the_start(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    calls = mock_supernotify(hass)
    hass.states.async_set(POWER, "0", {"unit_of_measurement": "W"})
    entry = await setup_power_watcher(hass, threshold=5, grace_period=120)
    await set_state(hass, POWER, "1800")
    started = len(calls)

    # gone quiet while Home Assistant was off, so not known to be done till the wait from now is over
    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.states.async_set(POWER, "0", {"unit_of_measurement": "W"})
    freezer.tick(300)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await wait(hass, freezer, 119)
    assert len(calls) == started
    await wait(hass, freezer, 1)
    assert messages(calls)[started:] == ["Washer is finished", "Washer is finished"]


async def test_power_drawn_again_after_a_restart_is_the_same_cycle(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    calls = mock_supernotify(hass)
    hass.states.async_set(POWER, "0", {"unit_of_measurement": "W"})
    entry = await setup_power_watcher(hass, threshold=5, grace_period=120, notify_start=True)
    await set_state(hass, POWER, "1800")
    await set_state(hass, POWER, "2")
    await wait(hass, freezer, 30)

    # spinning again by the time Home Assistant is back
    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.states.async_set(POWER, "1800", {"unit_of_measurement": "W"})
    freezer.tick(20)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await wait(hass, freezer, 600)
    assert entry.runtime_data.running
    assert messages(calls) == ["Washer started"]

    await set_state(hass, POWER, "0")
    await wait(hass, freezer, 120)
    assert messages(calls) == ["Washer started", "Washer is finished", "Washer is finished"]


async def test_power_not_yet_a_cycle_counted_through_a_restart(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    calls = mock_supernotify(hass)
    hass.states.async_set(POWER, "0", {"unit_of_measurement": "W"})
    entry = await setup_power_watcher(hass, threshold=5, grace_period=120, min_duration=60, notify_start=True)
    await set_state(hass, POWER, "70")
    await wait(hass, freezer, 20)

    # drawing power all along, so started once a minute of it is up
    await restart(hass, entry, freezer, off_for=10)
    assert entry.runtime_data.pending
    await wait(hass, freezer, 29)
    assert not calls
    await wait(hass, freezer, 1)
    assert messages(calls) == ["Washer started"]


async def test_vacuum_end_waited_for_through_a_restart(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    device_id, vacuum = add_vacuum(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    entry = await setup_vacuum(hass, device_id)
    await set_state(hass, vacuum, "cleaning")
    await wait(hass, freezer, 600)
    await set_state(hass, vacuum, "returning")
    await set_state(hass, vacuum, "docked")
    started = len(calls)

    # back on its dock 4 minutes when Home Assistant restarts, so done 6 minutes later, as it would have been
    await wait(hass, freezer, 4 * 60)
    await restart(hass, entry, freezer)
    assert entry.runtime_data.running
    await wait(hass, freezer, VACUUM_SETTLE - 4 * 60 - 1)
    assert len(calls) == started
    await wait(hass, freezer, 1)
    assert messages(calls)[started:] == ["Bruno is finished", "Bruno is finished"]
    assert calls[-1].data == ended("Bruno", entry.entry_id, "mdi:robot-vacuum", force_resend=True)


async def test_vacuum_back_midway_through_a_restart(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    device_id, vacuum = add_vacuum(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    entry = await setup_vacuum(hass, device_id)
    await set_state(hass, vacuum, "cleaning")
    await wait(hass, freezer, 600)
    # straight back, as when it washes its mop, given half an hour to set off again
    await set_state(hass, vacuum, "docked")
    started = len(calls)

    await wait(hass, freezer, 20 * 60)
    await restart(hass, entry, freezer, off_for=5 * 60)
    await wait(hass, freezer, VACUUM_MIDWAY_SETTLE - 25 * 60 - 1)
    assert len(calls) == started
    await wait(hass, freezer, 1)
    assert messages(calls)[started:] == ["Bruno is finished", "Bruno is finished"]


async def test_vacuum_midway_over_while_off_told_as_it_starts(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    device_id, vacuum = add_vacuum(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    entry = await setup_vacuum(hass, device_id)
    await set_state(hass, vacuum, "cleaning")
    await wait(hass, freezer, 600)
    await set_state(hass, vacuum, "docked")
    started = len(calls)

    await restart(hass, entry, freezer, off_for=VACUUM_MIDWAY_SETTLE + 60)
    assert messages(calls)[started:] == ["Bruno is finished", "Bruno is finished"]
    assert not entry.runtime_data.running


async def test_vacuum_set_off_again_after_a_restart_is_the_same_cleaning(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    device_id, vacuum = add_vacuum(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    entry = await setup_vacuum(hass, device_id, notify_start=True)
    await set_state(hass, vacuum, "cleaning")
    await wait(hass, freezer, 600)
    await set_state(hass, vacuum, "docked")

    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.states.async_set(vacuum, "cleaning")
    freezer.tick(60)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await wait(hass, freezer, VACUUM_MIDWAY_SETTLE)
    assert messages(calls) == ["Bruno started"]

    await set_state(hass, vacuum, "returning")
    await set_state(hass, vacuum, "docked")
    await wait(hass, freezer, VACUUM_SETTLE)
    assert messages(calls) == ["Bruno started", "Bruno is finished", "Bruno is finished"]


async def test_reminder_kept_through_a_restart(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    calls = mock_supernotify(hass)
    hass.states.async_set(POWER, "0", {"unit_of_measurement": "W"})
    entry = await setup_power_watcher(hass, reminder=20)
    await set_state(hass, POWER, "1800")
    await set_state(hass, POWER, "0")
    await wait(hass, freezer, 60)
    told = len(calls)
    end = calls[-1].data

    await wait(hass, freezer, 10 * 60)
    await restart(hass, entry, freezer, off_for=5 * 60)
    await wait(hass, freezer, 5 * 60 - 1)
    assert len(calls) == told
    await wait(hass, freezer, 1)
    assert len(calls) == told + 1
    assert calls[-1].data == end

    # and the next as usual
    await wait(hass, freezer, 20 * 60)
    assert len(calls) == told + 2


async def test_reminders_due_while_off_told_once(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    calls = mock_supernotify(hass)
    hass.states.async_set(POWER, "0", {"unit_of_measurement": "W"})
    entry = await setup_power_watcher(hass, reminder=20)
    await set_state(hass, POWER, "1800")
    await set_state(hass, POWER, "0")
    await wait(hass, freezer, 60)
    told = len(calls)

    # off for longer than two reminders, which are told as one as it starts
    await restart(hass, entry, freezer, off_for=50 * 60)
    assert len(calls) == told + 1
    await wait(hass, freezer, 20 * 60 - 1)
    assert len(calls) == told + 1
    await wait(hass, freezer, 1)
    assert len(calls) == told + 2


async def test_remind_me_later_kept_through_a_restart(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    calls = mock_supernotify(hass)
    hass.states.async_set(POWER, "0", {"unit_of_measurement": "W"})
    entry = await setup_power_watcher(hass)
    await set_state(hass, POWER, "1800")
    await set_state(hass, POWER, "0")
    await wait(hass, freezer, 60)
    hass.bus.async_fire("mobile_app_notification_action", {"action": f"APPLIANCE_REMIND_{entry.entry_id}"})
    await hass.async_block_till_done()
    told = len(calls)

    await wait(hass, freezer, 10 * 60)
    await restart(hass, entry, freezer)
    await wait(hass, freezer, 20 * 60 - 1)
    assert len(calls) == told
    await wait(hass, freezer, 1)
    assert len(calls) == told + 1
    # once only, as asked
    await wait(hass, freezer, 60 * 60)
    assert len(calls) == told + 1


def kept(saved_at: timedelta, **data: Any) -> dict[str, Any]:
    """A cycle as kept by an earlier run of Home Assistant, a while ago"""
    return {
        "version": CYCLE_STORE_VERSION,
        "minor_version": 1,
        "key": "",
        "data": {
            "running": True,
            "started_at": None,
            "program": "",
            "program_kept": False,
            "end_due": None,
            "reminder_due": None,
            "reminders_sent": 0,
            "phase": {},
            "saved_at": (dt_util.utcnow() - saved_at).isoformat(),
        }
        | data,
    }


async def setup_kept_power_watcher(hass: HomeAssistant, hass_storage: dict[str, Any], saved_at: timedelta) -> MockConfigEntry:
    """A power monitored washer with a cycle kept from before Home Assistant was last stopped"""
    entry_id = "washer"
    hass_storage[f"appliance_autonotify.cycle.{entry_id}"] = kept(saved_at)
    entry = MockConfigEntry(
        domain="appliance_autonotify",
        entry_id=entry_id,
        title="Washer",
        unique_id=POWER,
        data={"type": "power"},
        options={"power_entity": POWER, "grace_period": 120},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_cycle_kept_from_a_while_ago_carried_on_with(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer: FrozenDateTimeFactory
) -> None:
    calls = mock_supernotify(hass)
    hass.states.async_set(POWER, "0", {"unit_of_measurement": "W"})
    entry = await setup_kept_power_watcher(hass, hass_storage, timedelta(hours=2))
    assert entry.runtime_data.running
    await wait(hass, freezer, 120)
    assert messages(calls) == ["Washer is finished", "Washer is finished"]


async def test_cycle_kept_too_long_ago_ignored(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer: FrozenDateTimeFactory
) -> None:
    calls = mock_supernotify(hass)
    hass.states.async_set(POWER, "0", {"unit_of_measurement": "W"})
    entry = await setup_kept_power_watcher(hass, hass_storage, timedelta(hours=25))
    assert not entry.runtime_data.running
    await wait(hass, freezer, 600)
    assert not calls


async def test_cycle_kept_of_a_power_monitor_gone_ignored(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer: FrozenDateTimeFactory
) -> None:
    calls = mock_supernotify(hass)
    entry = await setup_kept_power_watcher(hass, hass_storage, timedelta(hours=2))
    assert not entry.runtime_data.running
    await wait(hass, freezer, 600)
    assert not calls


async def test_cycle_kept_as_home_assistant_stops(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer: FrozenDateTimeFactory
) -> None:
    mock_supernotify(hass)
    hass.states.async_set(POWER, "0", {"unit_of_measurement": "W"})
    entry = await setup_power_watcher(hass, threshold=5, grace_period=120)
    await set_state(hass, POWER, "1800")
    await set_state(hass, POWER, "0")

    # written straight away, without waiting the moment it otherwise would
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    data = hass_storage[store_key(entry)]["data"]
    assert data["running"] is True
    assert data["end_due"] == (dt_util.utcnow() + timedelta(seconds=120)).isoformat()


async def test_nothing_kept_once_the_cycle_is_over(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer: FrozenDateTimeFactory
) -> None:
    mock_supernotify(hass)
    hass.states.async_set(POWER, "0", {"unit_of_measurement": "W"})
    entry = await setup_power_watcher(hass, threshold=5, grace_period=120)
    await set_state(hass, POWER, "1800")
    await wait(hass, freezer, 2)
    assert hass_storage[store_key(entry)]["data"]["running"] is True

    await set_state(hass, POWER, "0")
    await wait(hass, freezer, 120)
    await wait(hass, freezer, 2)
    assert hass_storage[store_key(entry)]["data"] == {}


async def test_kept_cycle_removed_with_the_appliance(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer: FrozenDateTimeFactory
) -> None:
    mock_supernotify(hass)
    hass.states.async_set(POWER, "0", {"unit_of_measurement": "W"})
    entry = await setup_power_watcher(hass, threshold=5, grace_period=120)
    await set_state(hass, POWER, "1800")
    await wait(hass, freezer, 2)
    assert store_key(entry) in hass_storage

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert store_key(entry) not in hass_storage


async def test_home_connect_cycle_carried_on_without_starting_again(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.cycle, "ready")
    entry = await setup_watcher(hass, appliance, {"notify_start": True})
    await set_state(hass, appliance.cycle, "run")
    assert messages(calls) == ["Dishwasher started"]

    await restart(hass, entry, freezer, off_for=60)
    assert entry.runtime_data.running
    await set_state(hass, appliance.cycle, "pause")
    await set_state(hass, appliance.cycle, "run")
    assert messages(calls) == ["Dishwasher started"]

    # finished while Home Assistant was off, and told as it starts
    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.states.async_set(appliance.cycle, "finished")
    freezer.tick(600)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert messages(calls) == ["Dishwasher started", "Dishwasher is finished", "Dishwasher is finished"]
    assert not entry.runtime_data.running


async def test_home_connect_settling_through_a_restart(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.cycle, "ready")
    entry = await setup_watcher(hass, appliance)
    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.cycle, "ready")
    started = len(calls)

    await wait(hass, freezer, 4)
    await restart(hass, entry, freezer, off_for=2)
    await wait(hass, freezer, CYCLE_SETTLE - 6 - 1)
    assert len(calls) == started
    await wait(hass, freezer, 1)
    assert messages(calls)[started:] == ["Dishwasher is finished", "Dishwasher is finished"]


async def test_oven_warming_up_through_a_restart(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    oven, calls, entry = await start_oven(hass)
    cavity = oven.others["oven_current_cavity_temperature"]
    await set_temperature(hass, cavity, "104")
    told = len(calls)

    # still warming up, as it was before Home Assistant restarted
    await restart(hass, entry, freezer, off_for=30)
    await set_temperature(hass, cavity, "150")
    assert messages(calls)[told:] == ["Pre-heating, 150 of 200°C"]
    assert calls[-1].data["extra_data"]["progress"] == 75

    # and told once up to heat
    await set_temperature(hass, cavity, "201")
    assert messages(calls)[told + 1 :] == ["Oven is pre-heated", f"{PIZZA}, 201°C"]

"""An appliance unavailable for longer than chosen told of as offline, and then as back, only where chosen, since one
switched off at the wall is offline too"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant

from .conftest import add_appliance, mock_supernotify, setup_watcher
from .test_restart import restart, wait
from .test_watcher import set_state, setup_power_watcher

if TYPE_CHECKING:
    from freezegun.api import FrozenDateTimeFactory

NOW = "2026-11-24T08:00:00+00:00"


async def test_told_offline_and_back(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    await hass.config.async_set_time_zone("Europe/London")
    freezer.move_to(NOW)
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.cycle, "ready")
    entry = await setup_watcher(hass, appliance, {"offline_after": 30})
    tag = f"appliance_{entry.entry_id}_offline"

    await set_state(hass, appliance.cycle, "unavailable")
    await wait(hass, freezer, 29 * 60)
    assert calls == []
    await wait(hass, freezer, 60)
    assert [call.data["message"] for call in calls] == ["Dishwasher is offline since 08:00"]
    assert calls[0].data["extra_data"]["mobile_push_notification_tag"] == tag

    # told once, however long it stays offline
    await wait(hass, freezer, 3 * 3600)
    assert len(calls) == 1

    # and back, in place of being offline
    await set_state(hass, appliance.cycle, "ready")
    assert calls[-1].data["message"] == "Dishwasher is back online after 3 h 30 min"
    assert calls[-1].data["extra_data"]["mobile_push_notification_tag"] == tag


async def test_not_told_unless_chosen(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Switched off at the wall, as many are, so offline as expected"""
    freezer.move_to(NOW)
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.cycle, "ready")
    await setup_watcher(hass, appliance)

    await set_state(hass, appliance.cycle, "unavailable")
    await wait(hass, freezer, 2 * 86400)
    await set_state(hass, appliance.cycle, "ready")
    assert calls == []


async def test_a_moment_offline_isnt_told(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Back before it's been offline long enough, so neither offline nor back"""
    freezer.move_to(NOW)
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.cycle, "ready")
    await setup_watcher(hass, appliance, {"offline_after": 30})

    await set_state(hass, appliance.cycle, "unavailable")
    await wait(hass, freezer, 10 * 60)
    await set_state(hass, appliance.cycle, "ready")
    await wait(hass, freezer, 60 * 60)
    assert calls == []
    # and a fresh wait the next time
    await set_state(hass, appliance.cycle, "unavailable")
    await wait(hass, freezer, 29 * 60)
    assert calls == []
    await wait(hass, freezer, 60)
    assert len(calls) == 1


async def test_unknown_isnt_offline(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Reached, though with nothing to say"""
    freezer.move_to(NOW)
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.cycle, "unknown")
    await setup_watcher(hass, appliance, {"offline_after": 30})
    await wait(hass, freezer, 3600)
    assert calls == []


async def test_offline_as_home_assistant_starts(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Already unavailable, so counted from when it went"""
    freezer.move_to(NOW)
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.cycle, "unavailable")
    await wait(hass, freezer, 20 * 60)
    await setup_watcher(hass, appliance, {"offline_after": 30})
    assert calls == []
    await wait(hass, freezer, 10 * 60)
    assert len(calls) == 1


async def test_back_after_a_restart(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Told as offline before Home Assistant restarted, and as back after, not told again in between"""
    await hass.config.async_set_time_zone("Europe/London")
    freezer.move_to(NOW)
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.cycle, "ready")
    entry = await setup_watcher(hass, appliance, {"offline_after": 30})
    await set_state(hass, appliance.cycle, "unavailable")
    await wait(hass, freezer, 30 * 60)
    assert len(calls) == 1

    await restart(hass, entry, freezer, off_for=60)
    hass.states.async_set(appliance.cycle, "unavailable")
    await wait(hass, freezer, 3600)
    assert len(calls) == 1
    await set_state(hass, appliance.cycle, "ready")
    assert calls[-1].data["message"] == "Dishwasher is back online after 1 h 31 min"


async def test_smart_plug_offline(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A power monitored appliance is offline with its smart plug's power sensor"""
    await hass.config.async_set_time_zone("Europe/London")
    freezer.move_to(NOW)
    calls = mock_supernotify(hass)
    hass.states.async_set("sensor.washer_power", "0", {"unit_of_measurement": "W"})
    await setup_power_watcher(hass, offline_after=30)

    await set_state(hass, "sensor.washer_power", "unavailable")
    await wait(hass, freezer, 30 * 60)
    assert [call.data["message"] for call in calls] == ["Washer is offline since 08:00"]


async def test_in_the_language_of_home_assistant(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    hass.config.language = "de"
    freezer.move_to(NOW)
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.cycle, "ready")
    await setup_watcher(hass, appliance, {"offline_after": 30})

    await set_state(hass, appliance.cycle, "unavailable")
    await wait(hass, freezer, 30 * 60)
    await wait(hass, freezer, 70 * 60)
    await set_state(hass, appliance.cycle, "ready")
    assert [call.data["message"] for call in calls] == [
        "Dishwasher ist seit 09:00 offline",
        "Dishwasher ist nach 1 Std. 40 Min. wieder online",
    ]

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import Context, HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.appliance_autonotify.const import ANDROID_CHANNEL, CYCLE_SETTLE, DOMAIN, PREHEAT_SETTLE
from tests.ha_testing import MockConfigEntry, async_fire_time_changed, async_mock_service

from .conftest import (
    DISHWASHER_PROGRAMS,
    add_appliance,
    mock_dashboard,
    mock_dashboards,
    mock_supernotify,
    setup_watcher,
)

# the Android only fields that every Live Activity notification carries
ANDROID = {"channel": ANDROID_CHANNEL, "importance": "high", "sticky": True}


def ended(name: str, entry_id: str, icon: str, switch: bool = False, track: bool = False, **extra: Any) -> dict[str, Any]:
    """The end notification, with its buttons, the first of an appliance with maintenance to track offering that, in
    place of Remind Later where there'd otherwise be more than Android shows"""
    actions = [{"action": f"APPLIANCE_FINISHED_{entry_id}", "title": "Finished"}]
    if not (switch and track):
        actions.append({"action": f"APPLIANCE_REMIND_{entry_id}", "title": "Remind Later"})
    if switch:
        actions.append({"action": f"APPLIANCE_SWITCH_OFF_{entry_id}", "title": "Switch Off"})
    if track:
        actions.append({"action": f"APPLIANCE_TRACK_MAINTENANCE_{entry_id}", "title": "Track Maintenance"})
    return {
        "message": f"{name} is finished",
        "title": name,
        "actions": actions,
        "extra_data": {"notification_icon": icon, "mobile_push_notification_tag": f"appliance_{entry_id}_end"},
    } | extra


async def set_state(hass: HomeAssistant, entity_id: str, state: str) -> None:
    hass.states.async_set(entity_id, state)
    await hass.async_block_till_done()


async def test_cycle_with_supernotify(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.cycle, "ready")
    entry = await setup_watcher(hass, appliance, {"notify_start": True})
    tag = f"appliance_{entry.entry_id}"

    await set_state(hass, appliance.cycle, "run")
    assert len(calls) == 1
    assert calls[0].data == {
        "message": "Dishwasher started",
        "title": "Dishwasher",
        "force_resend": True,
        "extra_data": {
            "mobile_push_notification_tag": tag,
            "live_update": True,
            "notification_icon": "mdi:dishwasher",
            **ANDROID,
        },
    }

    # paused and resumed is the same cycle
    await set_state(hass, appliance.cycle, "pause")
    await set_state(hass, appliance.cycle, "unavailable")
    await set_state(hass, appliance.cycle, "run")
    assert len(calls) == 1

    await set_state(hass, appliance.cycle, "finished")
    assert len(calls) == 3
    assert calls[1].data == {
        "message": "Dishwasher is finished",
        "title": "Dishwasher",
        "delivery_selection": "fixed",
        "force_resend": True,
        "delivery": ["mobile_push", "phones"],
        "extra_data": {"mobile_push_notification_tag": tag, "mobile_push_clear_notification": True},
    }
    assert calls[2].data == ended("Dishwasher", entry.entry_id, "mdi:dishwasher", track=True, force_resend=True)

    # finished only once
    await set_state(hass, appliance.cycle, "inactive")
    assert len(calls) == 3


async def test_progress_updates_mobile_only(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    entry = await setup_watcher(hass, appliance)
    tag = f"appliance_{entry.entry_id}"

    # progress outside a cycle is ignored
    await set_state(hass, appliance.progress, "50")
    assert not calls

    await set_state(hass, appliance.progress, "unavailable")
    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.finish_time, "2026-10-06T21:44:16+00:00")
    # the first reading is sent whatever it is, since the start had no progress to show
    await set_state(hass, appliance.progress, "1")
    assert len(calls) == 2
    assert calls[1].data["extra_data"]["progress"] == 1
    await set_state(hass, appliance.progress, "4")
    assert len(calls) == 2

    await set_state(hass, appliance.progress, "12")
    assert len(calls) == 3
    assert calls[2].data == {
        "message": "12% complete",
        "title": "Dishwasher",
        "delivery_selection": "fixed",
        "force_resend": True,
        "delivery": ["mobile_push", "phones"],
        "extra_data": {
            "mobile_push_notification_tag": tag,
            "live_update": True,
            "notification_icon": "mdi:dishwasher",
            **ANDROID,
            "progress": 12,
            "progress_max": 100,
            "chronometer": True,
            "when": 1791323056,
            "silent": True,
            "alert_once": True,
        },
    }

    # throttled to steps of five percent
    await set_state(hass, appliance.progress, "14")
    assert len(calls) == 3
    await set_state(hass, appliance.progress, "15")
    assert len(calls) == 4


async def test_progress_notified_when_asked_for(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    entry = await setup_watcher(hass, appliance, {"notify_progress": True, "deliveries": ["chimes", "phones"]})
    tag = f"appliance_{entry.entry_id}"

    await set_state(hass, appliance.cycle, "run")
    # the first reading comes straight after the start, so only fills in the Live Activity
    await set_state(hass, appliance.progress, "4")
    assert len(calls) == 2
    assert calls[1].data["delivery"] == ["phones"]
    assert calls[1].data["extra_data"]["silent"] is True

    # an ordinary notification, everywhere chosen, which keeps the Live Activity up to date too
    await set_state(hass, appliance.progress, "10")
    assert len(calls) == 3
    assert calls[2].data == {
        "message": "10% complete",
        "title": "Dishwasher",
        "force_resend": True,
        "delivery_selection": "explicit",
        "delivery": ["chimes", "phones"],
        "extra_data": {
            "mobile_push_notification_tag": tag,
            "live_update": True,
            "notification_icon": "mdi:dishwasher",
            **ANDROID,
            "progress": 10,
            "progress_max": 100,
            # with no finish time, the Android status bar chip has the progress to show
            "critical_text": "10%",
        },
    }


async def test_progress_notified_without_supernotify(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    await setup_watcher(hass, appliance, {"targets": ["notify.kitchen_display"], "notify_start": True, "notify_progress": True})
    calls = async_mock_service(hass, "notify", "send_message")

    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.progress, "4")
    assert len(calls) == 1
    # the steps of five in between are only for a Live Activity
    await set_state(hass, appliance.progress, "5")
    assert len(calls) == 1
    await set_state(hass, appliance.progress, "30")
    assert [c.data["message"] for c in calls] == ["Dishwasher started", "30% complete"]


async def test_progress_bar_updated_more_often_towards_the_end(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.progress, "0")
    await setup_watcher(hass, appliance, {"notify_progress": True})
    await set_state(hass, appliance.cycle, "run")

    sent: list[tuple[int, bool]] = []
    for progress in (80, 89, 90, 91, 92, 93, 97, 99, 100):
        await set_state(hass, appliance.progress, str(progress))
        sent = [(c.data["extra_data"]["progress"], "silent" in c.data["extra_data"]) for c in calls[1:]]
    # every five percent, then every two from ninety, of which only the tens are also ordinary notifications
    assert sent == [(80, False), (89, True), (90, False), (92, True), (97, True), (99, True), (100, False)]


async def test_live_activity_names_the_program(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.progress, "0")
    await setup_watcher(hass, appliance)
    await set_state(hass, appliance.cycle, "run")

    # not yet known, so nothing to say but the progress
    await set_state(hass, appliance.program, "unknown")
    await set_state(hass, appliance.progress, "10")
    assert calls[1].data["message"] == "10% complete"

    await set_state(hass, appliance.program, "dishcare_dishwasher_program_eco_50")
    key = "component.home_connect.entity.select.active_program.state.dishcare_dishwasher_program_eco_50"
    with patch("homeassistant.helpers.translation.async_get_cached_translations", return_value={key: "Eco 50ºC"}):
        await set_state(hass, appliance.progress, "20")
    assert calls[2].data["message"] == "Eco 50ºC"
    assert calls[2].data["extra_data"]["progress"] == 20


async def test_program_is_in_the_title_when_there_is_a_timer(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.program, "Eco")
    hass.states.async_set(appliance.finish_time, "2026-10-06T21:44:16+00:00")
    await setup_watcher(hass, appliance)

    # the start too, which is only a Live Activity unless asked for
    await set_state(hass, appliance.cycle, "run")
    assert (calls[0].data["title"], calls[0].data["message"]) == ("Dishwasher · Eco", "Dishwasher started")
    # the message, which iOS shows only in the Dynamic Island, has the progress to itself
    await set_state(hass, appliance.progress, "5")
    assert (calls[1].data["title"], calls[1].data["message"]) == ("Dishwasher · Eco", "5% complete")


async def test_program_is_kept_out_of_the_title_when_switched_off(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.program, "Eco")
    hass.states.async_set(appliance.finish_time, "2026-10-06T21:44:16+00:00")
    # as saved before the title was a choice, and taken as the name alone
    entry = await setup_watcher(hass, appliance, {"program_in_title": False}, minor_version=1)
    assert (entry.minor_version, dict(entry.options)) == (3, {"live_title": "name"})

    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.progress, "5")
    assert [(call.data["title"], call.data["message"]) for call in calls] == [
        ("Dishwasher", "Dishwasher started"),
        ("Dishwasher", "Eco"),
    ]


async def test_title_can_be_the_program_alone(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.program, "Eco")
    hass.states.async_set(appliance.finish_time, "2026-10-06T21:44:16+00:00")
    await setup_watcher(hass, appliance, {"live_title": "program"})

    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.progress, "5")
    assert [(call.data["title"], call.data["message"]) for call in calls] == [
        ("Eco", "Dishwasher started"),
        ("Eco", "5% complete"),
    ]


async def test_program_can_be_shown_in_place_of_the_time_left(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.program, "Eco")
    hass.states.async_set(appliance.finish_time, "2026-10-06T21:44:16+00:00")
    await setup_watcher(hass, appliance, {"live_title": "name", "live_detail": "program"})

    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.progress, "5")
    assert (calls[-1].data["title"], calls[-1].data["message"]) == ("Dishwasher", "Eco")
    extra = calls[-1].data["extra_data"]
    assert "when" not in extra
    assert "chronometer" not in extra
    # the Android chip has the percentage, with no time left to show
    assert extra["critical_text"] == "5%"


async def test_program_can_be_named_in_the_messages(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.finish_time, "2026-10-06T21:44:16+00:00")
    options = {"start_title": "{name} {program}", "start_message": "{program} started", "end_message": "{program} is done"}
    await setup_watcher(hass, appliance, options)

    # with no program known, its place is closed up
    await set_state(hass, appliance.cycle, "run")
    assert (calls[0].data["title"], calls[0].data["message"]) == ("Dishwasher", "started")

    # and one already in the title isn't put there a second time
    await set_state(hass, appliance.program, "Eco")
    await set_state(hass, appliance.progress, "5")
    assert (calls[1].data["title"], calls[1].data["message"]) == ("Dishwasher Eco", "Eco")

    # the end names the program that ran, though the appliance has stopped reporting it
    await set_state(hass, appliance.program, "unknown")
    await set_state(hass, appliance.cycle, "finished")
    assert calls[-1].data["message"] == "Eco is done"


async def test_title_is_left_alone_where_notified_everywhere(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.program, "Eco")
    hass.states.async_set(appliance.finish_time, "2026-10-06T21:44:16+00:00")
    await setup_watcher(hass, appliance, {"notify_start": True})

    await set_state(hass, appliance.cycle, "run")
    assert calls[0].data["title"] == "Dishwasher"


async def test_program_chosen_is_named_when_none_is_under_way(hass: HomeAssistant) -> None:
    # an oven reports the program it's set to, and never one under way
    oven = add_appliance(hass, "Oven", "NEFF-2", oven=True)
    calls = mock_supernotify(hass)
    hass.states.async_set(oven.progress, "0")
    hass.states.async_set(oven.program, "unknown")
    hass.states.async_set(oven.others["selected_program"], "cooking_oven_program_heating_mode_pizza_setting")
    await setup_watcher(hass, oven)
    await set_state(hass, oven.cycle, "run")

    key = "component.home_connect.entity.select.selected_program.state.cooking_oven_program_heating_mode_pizza_setting"
    with patch("homeassistant.helpers.translation.async_get_cached_translations", return_value={key: "Pizza setting"}):
        await set_state(hass, oven.progress, "10")
    assert calls[1].data["message"] == "Pizza setting"

    # the one under way is the one to go by, where there is one
    await set_state(hass, oven.program, "cooking_oven_program_heating_mode_hot_air")
    await set_state(hass, oven.progress, "20")
    assert calls[2].data["message"] == "cooking_oven_program_heating_mode_hot_air"


async def test_icon_follows_the_type_of_appliance(hass: HomeAssistant) -> None:
    # known by its programs, whatever it has been called
    appliance = add_appliance(hass, "Bertha", programs=DISHWASHER_PROGRAMS)
    oven = add_appliance(hass, "Downstairs", "NEFF-2", oven=True)
    unknown = add_appliance(hass, "Coffee machine", "BOSCH-3")
    calls = mock_supernotify(hass)
    for each in (appliance, oven, unknown):
        await setup_watcher(hass, each)
        await set_state(hass, each.cycle, "run")
        await set_state(hass, each.cycle, "finished")

    icons = [c.data["extra_data"].get("notification_icon") for c in calls]
    # on the start and the end, the clearing of the Live Activity between them having nothing to show
    assert icons == [
        "mdi:dishwasher",
        None,
        "mdi:dishwasher",
        "mdi:stove",
        None,
        "mdi:stove",
        "mdi:coffee-maker",
        None,
        "mdi:coffee-maker",
    ]


async def test_start_and_end_notifications_switched_off(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    entry = await setup_watcher(hass, appliance, {"notify_start": False, "notify_end": False})
    tag = f"appliance_{entry.entry_id}"

    # the Live Activity is still opened, on phones alone and without a sound
    await set_state(hass, appliance.cycle, "run")
    assert len(calls) == 1
    assert calls[0].data == {
        "message": "Dishwasher started",
        "title": "Dishwasher",
        "delivery_selection": "fixed",
        "force_resend": True,
        "delivery": ["mobile_push", "phones"],
        "extra_data": {
            "mobile_push_notification_tag": tag,
            "live_update": True,
            "notification_icon": "mdi:dishwasher",
            **ANDROID,
            "silent": True,
            "alert_once": True,
        },
    }

    # and still closed
    await set_state(hass, appliance.cycle, "finished")
    assert len(calls) == 2
    assert calls[1].data["extra_data"] == {"mobile_push_notification_tag": tag, "mobile_push_clear_notification": True}


async def test_start_is_only_a_live_activity_unless_asked_for(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    await setup_watcher(hass, appliance)

    await set_state(hass, appliance.cycle, "run")
    assert len(calls) == 1
    assert calls[0].data["delivery"] == ["mobile_push", "phones"]
    assert calls[0].data["extra_data"]["silent"] is True


async def test_start_and_end_switched_separately(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    await setup_watcher(hass, appliance, {"notify_start": True, "notify_end": False})

    await set_state(hass, appliance.cycle, "run")
    assert "delivery_selection" not in calls[0].data
    await set_state(hass, appliance.cycle, "finished")
    assert len(calls) == 2


async def test_start_and_end_switched_off_without_supernotify(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    await setup_watcher(hass, appliance, {"targets": ["notify.kitchen_display"], "notify_start": False})
    calls = async_mock_service(hass, "notify", "send_message")

    await set_state(hass, appliance.cycle, "run")
    assert not calls
    await set_state(hass, appliance.cycle, "finished")
    assert [c.data["message"] for c in calls] == ["Dishwasher is finished"]


PIZZA = "cooking_oven_program_heating_mode_pizza_setting"


async def start_oven(
    hass: HomeAssistant, target: str = "200", current: str = "20", options: dict[str, Any] | None = None, cycle: str = "ready"
):
    oven = add_appliance(hass, "Oven", "NEFF-2", oven=True)
    calls = mock_supernotify(hass)
    hass.states.async_set(oven.cycle, cycle)
    # any program will do, an oven warms up for all of them
    hass.states.async_set(oven.program, PIZZA)
    hass.states.async_set(oven.others["setpoint_temperature"], target, {"unit_of_measurement": "°C"})
    hass.states.async_set(oven.others["oven_current_cavity_temperature"], current, {"unit_of_measurement": "°C"})
    # as left by the last time the oven was heated
    hass.states.async_set(oven.others["preheat_finished"], "confirmed")
    hass.states.async_set(oven.others["regular_preheat_finished"], "off")
    hass.states.async_set(oven.others["fast_pre_heat"], "off")
    entry = await setup_watcher(hass, oven, options)
    await set_state(hass, oven.cycle, "run")
    return oven, calls, entry


async def set_temperature(hass: HomeAssistant, entity_id: str, temperature: str) -> None:
    hass.states.async_set(entity_id, temperature, {"unit_of_measurement": "°C"})
    await hass.async_block_till_done()


async def test_oven_progress_is_its_temperature_until_up_to_heat(hass: HomeAssistant) -> None:
    oven, calls, entry = await start_oven(hass)
    cavity = oven.others["oven_current_cavity_temperature"]
    # the bar starts where the oven is, a tenth of the way to its temperature
    assert len(calls) == 1
    assert calls[0].data["message"] == "Oven started"
    assert calls[0].data["extra_data"]["progress"] == 10
    assert calls[0].data["extra_data"]["progress_max"] == 100

    # throttled as any other progress
    await set_temperature(hass, cavity, "28")
    assert len(calls) == 1
    await set_temperature(hass, cavity, "104")
    assert len(calls) == 2
    assert calls[1].data["message"] == "Pre-heating, 104 of 200°C"
    assert calls[1].data["extra_data"]["progress"] == 52
    assert calls[1].data["extra_data"]["silent"] is True

    await set_state(hass, oven.others["fast_pre_heat"], "on")
    await set_temperature(hass, cavity, "150")
    assert calls[2].data["message"] == "Fast pre-heat, 150 of 200°C"
    assert calls[2].data["extra_data"]["progress"] == 75

    # a lower temperature asked for moves the bar on too
    await set_temperature(hass, oven.others["setpoint_temperature"], "170")
    assert calls[3].data["message"] == "Fast pre-heat, 150 of 170°C"
    assert calls[3].data["extra_data"]["progress"] == 88

    # up to heat is told everywhere, in a notification of its own
    await set_temperature(hass, cavity, "171")
    assert len(calls) == 6
    assert calls[4].data == {
        "message": "Oven is pre-heated",
        "title": "Oven",
        "force_resend": True,
        "extra_data": {"notification_icon": "mdi:stove"},
    }
    # and the Live Activity, which stays for as long as the oven is on, goes straight on to what it's now doing
    assert calls[5].data["message"] == f"{PIZZA}, 171°C"
    assert calls[5].data["delivery"] == ["mobile_push", "phones"]
    assert calls[5].data["extra_data"] == {
        "mobile_push_notification_tag": f"appliance_{entry.entry_id}",
        "live_update": True,
        "notification_icon": "mdi:stove",
        **ANDROID,
        "silent": True,
        "alert_once": True,
    }

    # however the temperature then wanders, it isn't warming up again, nor told of twice
    await set_temperature(hass, cavity, "168")
    await set_temperature(hass, cavity, "174")
    await set_state(hass, oven.others["regular_preheat_finished"], "present")
    assert len(calls) == 6
    # though the Live Activity is kept to within a few degrees of it
    await set_temperature(hass, cavity, "160")
    assert [c.data["message"] for c in calls[6:]] == [f"{PIZZA}, 160°C"]
    assert calls[6].data["extra_data"]["silent"] is True

    # with a timer set there's then the progress of the program to show, whatever the bar had got to
    await set_state(hass, oven.progress, "30")
    assert len(calls) == 8
    assert calls[7].data["message"] == f"{PIZZA}, 160°C"
    assert calls[7].data["extra_data"]["progress"] == 30

    await set_state(hass, oven.cycle, "inactive")
    assert [c.data["message"] for c in calls[8:]] == ["Oven is finished", "Oven is finished"]
    calls.clear()

    # switched on again while warm, it has only the rest of the way to go
    await set_state(hass, oven.progress, "unavailable")
    await set_temperature(hass, cavity, "101")
    await set_state(hass, oven.cycle, "run")
    assert calls[0].data["extra_data"]["progress"] == 59
    await set_temperature(hass, cavity, "165")
    assert calls[1].data["message"] == "Fast pre-heat, 165 of 170°C"


async def test_oven_is_up_to_heat_when_it_says_so(hass: HomeAssistant) -> None:
    oven, calls, _entry = await start_oven(hass, options={"notify_phase": False})
    await set_temperature(hass, oven.others["oven_current_cavity_temperature"], "190")
    assert len(calls) == 2

    # only as it happens, and with phases not to be told of, on the Live Activity alone
    await set_state(hass, oven.others["preheat_finished"], "off")
    assert len(calls) == 2
    await set_state(hass, oven.others["preheat_finished"], "present")
    # nor until it's seen that the oven wasn't being switched off
    assert len(calls) == 2
    await pass_time(hass, PREHEAT_SETTLE)
    assert len(calls) == 3
    assert calls[2].data["message"] == f"{PIZZA}, 190°C"
    assert calls[2].data["delivery"] == ["mobile_push", "phones"]
    assert calls[2].data["extra_data"]["silent"] is True
    assert "progress" not in calls[2].data["extra_data"]

    await set_state(hass, oven.others["regular_preheat_finished"], "present")
    await set_temperature(hass, oven.others["oven_current_cavity_temperature"], "193")
    assert len(calls) == 3


async def test_oven_already_hot_is_not_warming_up(hass: HomeAssistant) -> None:
    oven, calls, _entry = await start_oven(hass, current="210")
    cavity = oven.others["oven_current_cavity_temperature"]
    assert "progress" not in calls[0].data["extra_data"]
    # nor told of as up to heat, only shown on the Live Activity as doing what it's doing
    await set_temperature(hass, cavity, "190")
    await set_temperature(hass, cavity, "192")
    await set_temperature(hass, cavity, "205")
    assert [c.data["message"] for c in calls[1:]] == [f"{PIZZA}, 190°C", f"{PIZZA}, 205°C"]
    assert all(c.data["extra_data"]["silent"] for c in calls[1:])


async def test_oven_on_at_startup_is_not_warming_up(hass: HomeAssistant) -> None:
    # there's no knowing whether it has been up to heat
    oven, calls, _entry = await start_oven(hass, cycle="run")
    cavity = oven.others["oven_current_cavity_temperature"]
    await set_temperature(hass, cavity, "120")
    await set_temperature(hass, cavity, "210")
    await set_state(hass, oven.others["regular_preheat_finished"], "present")
    assert [c.data["message"] for c in calls] == [f"{PIZZA}, 120°C", f"{PIZZA}, 210°C"]


async def test_oven_temperatures_known_only_once_started(hass: HomeAssistant) -> None:
    oven, calls, _entry = await start_oven(hass, target="unavailable")
    cavity = oven.others["oven_current_cavity_temperature"]
    assert "progress" not in calls[0].data["extra_data"]
    await set_state(hass, cavity, "garbled")
    assert len(calls) == 1

    # with no timer set, an oven's own progress is of nothing
    await set_state(hass, oven.progress, "100")
    assert calls[1].data["extra_data"]["progress"] == 100

    # the bar goes back to how far there is to go
    await set_temperature(hass, cavity, "50")
    await set_temperature(hass, oven.others["setpoint_temperature"], "200")
    assert len(calls) == 3
    assert calls[2].data["message"] == "Pre-heating, 50 of 200°C"
    assert calls[2].data["extra_data"]["progress"] == 25

    # hot enough without ever having been seen to warm up is still told of
    hass.states.async_set(oven.others["setpoint_temperature"], "unavailable")
    await set_temperature(hass, cavity, "220")
    await set_temperature(hass, oven.others["setpoint_temperature"], "200")
    assert [c.data["message"] for c in calls[3:]] == ["Oven is pre-heated", f"{PIZZA}, 220°C"]


async def test_tap_opens_chosen_dashboard(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    mock_dashboards(hass)
    hass.states.async_set(appliance.progress, "0")
    await setup_watcher(hass, appliance, {"dashboard": "dashboard-kitchen"})

    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.progress, "10")
    await set_state(hass, appliance.cycle, "finished")
    tap = {"level": "notification", "uri": "/dashboard-kitchen"}
    # the start, each update of the Live Activity since iOS forgets otherwise, and the end, but not the clearing
    assert [[a for a in c.data.get("actions", []) if a.get("level") == "notification"] for c in calls] == [
        [tap],
        [tap],
        [],
        [tap],
    ]
    assert not any(key in call.data.get("extra_data", {}) for call in calls for key in ("url", "clickAction"))


async def test_dashboard_named_for_the_appliance_is_chosen_when_set_up(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    mock_dashboards(hass)
    mock_dashboard(hass, "dashboard-dish-washer", "Kitchen Appliances")
    entry = await setup_watcher(hass, appliance)

    # by its path, and kept as if chosen, so it's there in the settings to change or clear
    assert entry.options == {"dashboard": "dashboard-dish-washer"}
    await set_state(hass, appliance.cycle, "run")
    assert {"level": "notification", "uri": "/dashboard-dish-washer"} in calls[-1].data["actions"]


async def test_dashboard_named_for_the_type_is_chosen_when_set_up(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass, name="Bosch SMV6", programs=DISHWASHER_PROGRAMS)
    mock_dashboards(hass)
    mock_dashboard(hass, "dashboard-dishes", "Dishwasher")
    mock_dashboard(hass, "dashboard-laundry", "Washing Machine")
    # a dishwasher by its programs, though not by its name
    entry = await setup_watcher(hass, appliance)
    assert entry.options == {"dashboard": "dashboard-dishes"}


async def test_no_dashboard_is_chosen_when_several_match(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    mock_dashboards(hass)
    mock_dashboard(hass, "dashboard-dishes", "Dishwasher")
    mock_dashboard(hass, "dashboard-dishwasher", "Kitchen")
    entry = await setup_watcher(hass, appliance)
    assert entry.options == {}
    assert entry.data["dashboard_found"] is True


async def test_dashboard_is_only_looked_for_once(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    mock_dashboards(hass)
    mock_dashboard(hass, "dashboard-dishwasher", "Dishwasher")
    # set up before dashboards were looked for, with none chosen
    old = await setup_watcher(hass, appliance, minor_version=2)
    assert old.options == {}

    # nor again once cleared, or changed, in the settings
    entry = await setup_watcher(hass, add_appliance(hass, ha_id="BOSCH-2"))
    assert entry.options == {"dashboard": "dashboard-dishwasher"}
    hass.config_entries.async_update_entry(entry, options={})
    assert await hass.config_entries.async_reload(entry.entry_id)
    assert entry.options == {}


async def test_tap_goes_nowhere_but_a_dashboard(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    mock_dashboards(hass)
    # not something the settings would save, nor a dashboard that's since been removed
    await setup_watcher(hass, appliance, {"dashboard": "/example.com/rickroll"})

    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.cycle, "finished")
    assert len(calls) == 3
    assert not any(action.get("level") == "notification" for call in calls for action in call.data.get("actions", []))


async def test_progress_known_at_start_is_not_repeated(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.progress, "0")
    await setup_watcher(hass, appliance)

    await set_state(hass, appliance.cycle, "run")
    assert len(calls) == 1
    assert calls[0].data["extra_data"]["progress"] == 0

    await set_state(hass, appliance.progress, "4")
    assert len(calls) == 1
    await set_state(hass, appliance.progress, "10")
    assert len(calls) == 2


async def test_first_progress_waits_for_the_live_activity_to_open(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    await setup_watcher(hass, appliance)

    # as Home Connect tells it, the progress coming moments after the cycle starts
    with patch("custom_components.appliance_autonotify.watcher.LIVE_SETTLE", 0.2):
        hass.states.async_set(appliance.cycle, "run")
        # a moment between, else HA before 2026.10 has both states set before telling of either
        await asyncio.sleep(0.01)
        hass.states.async_set(appliance.progress, "0")
        await asyncio.sleep(0.05)
        assert [call.data["message"] for call in calls] == ["Dishwasher started"]
        await hass.async_block_till_done()
    assert len(calls) == 2
    assert calls[1].data["extra_data"]["progress"] == 0


async def test_start_is_not_held_up_without_supernotify(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    await setup_watcher(hass, appliance, {"targets": ["notify.kitchen_display"], "notify_start": True})
    calls = async_mock_service(hass, "notify", "send_message")

    # with no Live Activity to open, there's nothing to wait for
    with patch("custom_components.appliance_autonotify.watcher.LIVE_SETTLE", 60):
        async with asyncio.timeout(1):
            await set_state(hass, appliance.cycle, "run")
    assert len(calls) == 1


async def test_progress_update_cannot_overtake_the_end(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    await setup_watcher(hass, appliance)
    await set_state(hass, appliance.cycle, "run")
    assert len(calls) == 1

    # hold up the progress update while it's finding the mobile deliveries
    held = asyncio.Event()
    release = asyncio.Event()

    async def slow_enquiry(call: ServiceCall) -> dict[str, list[str]]:
        if not held.is_set():
            held.set()
            await release.wait()
        return {"mobile_push": ["mobile_push"]}

    hass.services.async_register(
        "supernotify", "enquire_implicit_deliveries", slow_enquiry, supports_response=SupportsResponse.ONLY
    )
    hass.states.async_set(appliance.progress, "100")
    await held.wait()
    hass.states.async_set(appliance.cycle, "finished")
    await asyncio.sleep(0.05)
    release.set()
    await hass.async_block_till_done()

    # were the update sent after the clear, the mobile app would open the Live Activity again
    assert [bool(call.data.get("extra_data", {}).get("live_update")) for call in calls[1:]] == [True, False, False]
    assert calls[2].data["extra_data"]["mobile_push_clear_notification"] is True


async def test_live_activity_cleared_on_delivery_known_only_by_its_switch(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    # Delivery Control can leave the standard mobile push delivery neither implicit nor configured
    async_mock_service(hass, "supernotify", "enquire_implicit_deliveries", response={}, supports_response=SupportsResponse.ONLY)
    async_mock_service(
        hass, "supernotify", "enquire_configuration", response={"delivery": {}}, supports_response=SupportsResponse.ONLY
    )
    calls = async_mock_service(hass, "supernotify", "notify")
    hass.states.async_set("switch.supernotify_delivery_mobile_push", "on", {"name": "mobile_push", "transport": "mobile_push"})
    hass.states.async_set("switch.supernotify_delivery_chimes", "on", {"name": "chimes", "transport": "chime"})
    await setup_watcher(hass, appliance)

    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.cycle, "finished")
    assert len(calls) == 3
    assert calls[1].data["delivery"] == ["mobile_push"]
    assert calls[1].data["extra_data"]["mobile_push_clear_notification"] is True


async def test_cycle_ends_without_finished_state(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass, "Oven")
    calls = mock_supernotify(hass)
    entry = await setup_watcher(hass, appliance)

    # an oven switched off never reports `finished`
    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.cycle, "inactive")
    assert len(calls) == 3
    assert calls[1].data["extra_data"]["mobile_push_clear_notification"] is True
    assert calls[2].data == ended("Oven", entry.entry_id, "mdi:stove", force_resend=True)

    await set_state(hass, appliance.cycle, "ready")
    await pass_time(hass, CYCLE_SETTLE)
    assert len(calls) == 3


async def test_cycle_is_over_once_ready_has_settled(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass, "Oven")
    calls = mock_supernotify(hass)
    await setup_watcher(hass, appliance)

    # an oven is `ready` for a moment as it starts, and again when its settings are changed
    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.cycle, "ready")
    await set_state(hass, appliance.cycle, "run")
    await pass_time(hass, CYCLE_SETTLE)
    assert [c.data["message"] for c in calls] == ["Oven started"]

    # left `ready`, it's over
    await set_state(hass, appliance.cycle, "ready")
    assert len(calls) == 1
    await pass_time(hass, CYCLE_SETTLE)
    assert [c.data["message"] for c in calls[1:]] == ["Oven is finished", "Oven is finished"]

    # and switched off before it has settled, over there and then, and only the once
    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.cycle, "ready")
    await set_state(hass, appliance.cycle, "inactive")
    assert len(calls) == 6
    await pass_time(hass, CYCLE_SETTLE)
    assert len(calls) == 6


async def test_oven_switched_off_is_not_up_to_heat(hass: HomeAssistant) -> None:
    oven, calls, _entry = await start_oven(hass)
    assert len(calls) == 1

    # Home Connect says an oven switched off is up to heat, a moment before saying that it's off
    await set_state(hass, oven.others["preheat_finished"], "off")
    await set_state(hass, oven.others["preheat_finished"], "present")
    await set_state(hass, oven.cycle, "inactive")
    await pass_time(hass, PREHEAT_SETTLE)
    assert [c.data["message"] for c in calls[1:]] == ["Oven is finished", "Oven is finished"]


async def test_abandoned_cycle_clears_without_end_notification(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    await setup_watcher(hass, appliance)

    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.cycle, "aborting")
    assert len(calls) == 2
    assert calls[1].data["extra_data"]["mobile_push_clear_notification"] is True


async def test_cycle_running_at_startup_is_ended(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(appliance.cycle, "run")
    await setup_watcher(hass, appliance)
    assert not calls

    await set_state(hass, appliance.cycle, "finished")
    assert len(calls) == 2


async def test_overrides_targets_and_deliveries(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    await setup_watcher(
        hass,
        appliance,
        {
            "start_title": "Kitchen",
            "start_message": "{name} is go {odd}",
            "end_title": "Kitchen done",
            "end_message": "Empty the {name}",
            "target": {"entity_id": ["person.joe"], "area_id": ["kitchen"]},
            "custom_target": ["joe@example.com"],
            "deliveries": ["phones", "chimes"],
            "notify_start": True,
        },
    )

    await set_state(hass, appliance.cycle, "run")
    assert calls[0].data["title"] == "Kitchen"
    assert calls[0].data["message"] == "Dishwasher is go {odd}"
    assert calls[0].data["target"] == {"entity_id": ["person.joe"], "area_id": ["kitchen"]}
    assert calls[0].data["custom_target"] == ["joe@example.com"]
    assert calls[0].data["delivery"] == ["phones", "chimes"]
    assert calls[0].data["delivery_selection"] == "explicit"

    await set_state(hass, appliance.cycle, "finished")
    # only the chosen deliveries that are mobile push have a Live Activity to clear
    assert calls[1].data["delivery"] == ["phones"]
    assert calls[2].data["title"] == "Kitchen done"
    assert calls[2].data["message"] == "Empty the Dishwasher"


async def test_no_mobile_deliveries_chosen(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    await setup_watcher(hass, appliance, {"deliveries": ["chimes"], "notify_start": True})

    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.progress, "50")
    await set_state(hass, appliance.cycle, "finished")
    assert [c.data["message"] for c in calls] == ["Dishwasher started", "Dishwasher is finished"]


async def test_cycle_without_supernotify(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    entry = await setup_watcher(hass, appliance, {"targets": ["notify.kitchen_display"], "notify_start": True})
    calls = async_mock_service(hass, "notify", "send_message")

    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.progress, "50")
    assert len(calls) == 1
    assert calls[0].data == {"entity_id": ["notify.kitchen_display"], "message": "Dishwasher started", "title": "Dishwasher"}

    await set_state(hass, appliance.cycle, "finished")
    assert len(calls) == 2
    assert calls[1].data["message"] == "Dishwasher is finished"

    # nothing to say when a cycle is abandoned and there's no Live Activity to clear
    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.cycle, "error")
    assert len(calls) == 3

    assert await hass.config_entries.async_unload(entry.entry_id)
    await set_state(hass, appliance.cycle, "run")
    assert len(calls) == 3


async def test_phones_notified_when_nothing_chosen(hass: HomeAssistant, caplog) -> None:
    appliance = add_appliance(hass)
    await setup_watcher(hass, appliance, {"notify_start": True})
    calls = async_mock_service(hass, "notify", "send_message")

    await set_state(hass, appliance.cycle, "run")
    assert not calls
    assert "Nothing to notify for Dishwasher" in caplog.text

    registry = er.async_get(hass)
    phone = registry.async_get_or_create("notify", "mobile_app", "phone", suggested_object_id="phone")
    registry.async_get_or_create("notify", "mobile_app", "old", disabled_by=er.RegistryEntryDisabler.USER)
    registry.async_get_or_create("notify", "demo", "display")
    await set_state(hass, appliance.cycle, "finished")
    assert len(calls) == 1
    assert calls[0].data["entity_id"] == [phone.entity_id]


async def test_notification_failure_is_logged(hass: HomeAssistant, caplog) -> None:
    appliance = add_appliance(hass)
    await setup_watcher(hass, appliance, {"targets": ["notify.kitchen_display"], "notify_start": True})

    def fail(call) -> None:
        raise HomeAssistantError("offline")

    hass.services.async_register("notify", "send_message", fail)
    await set_state(hass, appliance.cycle, "run")
    assert "Notification failed for Dishwasher" in caplog.text

    hass.services.async_register("supernotify", "notify", fail)
    await set_state(hass, appliance.cycle, "finished")
    assert "Supernotify notification failed for Dishwasher" in caplog.text


async def test_setup_retried_when_appliance_missing(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="Gone", data={CONF_DEVICE_ID: "nosuchdevice"})
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def setup_power_watcher(hass: HomeAssistant, title: str = "Washer", **options: Any) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=title,
        unique_id="sensor.washer_power",
        data={"type": "power"},
        options={"power_entity": "sensor.washer_power", **options},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def pass_time(hass: HomeAssistant, seconds: float) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


async def test_power_monitored_cycle(hass: HomeAssistant, freezer) -> None:
    calls = mock_supernotify(hass)
    hass.states.async_set("sensor.washer_power", "0.4", {"unit_of_measurement": "W"})
    entry = await setup_power_watcher(hass, grace_period=10, notify_start=True)
    tag = f"appliance_{entry.entry_id}"

    # at the threshold isn't running
    await set_state(hass, "sensor.washer_power", "1")
    assert not calls

    await set_state(hass, "sensor.washer_power", "1800")
    assert len(calls) == 1
    assert calls[0].data == {
        "message": "Washer started",
        "title": "Washer",
        "force_resend": True,
        "extra_data": {
            "mobile_push_notification_tag": tag,
            "live_update": True,
            "notification_icon": "mdi:washing-machine",
            **ANDROID,
        },
    }

    # a drop out shorter than the grace period is the same cycle
    await set_state(hass, "sensor.washer_power", "0")
    freezer.tick(6)
    await pass_time(hass, 0)
    await set_state(hass, "sensor.washer_power", "unavailable")
    await set_state(hass, "sensor.washer_power", "300")
    freezer.tick(6)
    await pass_time(hass, 0)
    assert len(calls) == 1

    # the grace period is from when the power first dropped
    await set_state(hass, "sensor.washer_power", "0.8")
    freezer.tick(6)
    await pass_time(hass, 0)
    await set_state(hass, "sensor.washer_power", "0.2")
    assert len(calls) == 1
    freezer.tick(5)
    await pass_time(hass, 0)
    assert len(calls) == 3
    assert calls[1].data["extra_data"] == {"mobile_push_notification_tag": tag, "mobile_push_clear_notification": True}
    assert calls[2].data == ended("Washer", entry.entry_id, "mdi:washing-machine", track=True, force_resend=True)

    # ended only once
    await set_state(hass, "sensor.washer_power", "0")
    freezer.tick(60)
    await pass_time(hass, 0)
    assert len(calls) == 3


async def test_power_threshold_grace_and_units(hass: HomeAssistant, freezer) -> None:
    calls = mock_supernotify(hass)
    # running at startup, so no start is notified
    hass.states.async_set("sensor.washer_power", "1.2", {"unit_of_measurement": "kW"})
    entry = await setup_power_watcher(hass, threshold=50, grace_period=120)
    assert entry.runtime_data.running
    assert not calls

    await set_state(hass, "sensor.washer_power", "0.04")
    freezer.tick(119)
    await pass_time(hass, 0)
    assert not calls
    freezer.tick(2)
    await pass_time(hass, 0)
    assert [c.data["message"] for c in calls] == ["Washer is finished", "Washer is finished"]

    hass.states.async_set("sensor.washer_power", "0.06", {"unit_of_measurement": "kW"})
    await hass.async_block_till_done()
    assert len(calls) == 3

    # nothing left waiting once unloaded
    hass.states.async_set("sensor.washer_power", "0", {"unit_of_measurement": "kW"})
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)
    freezer.tick(300)
    await pass_time(hass, 0)
    assert len(calls) == 3


async def test_power_too_short_for_a_cycle_is_ignored(hass: HomeAssistant, freezer) -> None:
    calls = mock_supernotify(hass)
    hass.states.async_set("sensor.washer_power", "3", {"unit_of_measurement": "W"})
    await setup_power_watcher(hass, threshold=5, grace_period=100, min_duration=60)

    # a door opened, as seen on a real dishwasher: 14W for 11 seconds
    await set_state(hass, "sensor.washer_power", "14")
    freezer.tick(11)
    await pass_time(hass, 0)
    await set_state(hass, "sensor.washer_power", "3")
    freezer.tick(100)
    await pass_time(hass, 0)
    assert not calls

    # and a later cycle still counts from nothing
    await set_state(hass, "sensor.washer_power", "14")
    freezer.tick(50)
    await pass_time(hass, 0)
    assert not calls


async def test_power_long_enough_is_a_cycle(hass: HomeAssistant, freezer) -> None:
    calls = mock_supernotify(hass)
    hass.states.async_set("sensor.washer_power", "0", {"unit_of_measurement": "W"})
    await setup_power_watcher(hass, threshold=5, grace_period=120, min_duration=60)

    # time above the threshold adds up across drop outs shorter than the grace period
    await set_state(hass, "sensor.washer_power", "70")
    freezer.tick(40)
    await pass_time(hass, 0)
    await set_state(hass, "sensor.washer_power", "0")
    freezer.tick(20)
    await pass_time(hass, 0)
    await set_state(hass, "sensor.washer_power", "190")
    freezer.tick(19)
    await pass_time(hass, 0)
    assert not calls
    freezer.tick(1)
    await pass_time(hass, 0)
    assert [c.data["message"] for c in calls] == ["Washer started"]

    await set_state(hass, "sensor.washer_power", "0")
    freezer.tick(120)
    await pass_time(hass, 0)
    assert [c.data["message"] for c in calls] == ["Washer started", "Washer is finished", "Washer is finished"]


async def test_power_not_yet_a_cycle_when_unloaded(hass: HomeAssistant, freezer) -> None:
    calls = mock_supernotify(hass)
    hass.states.async_set("sensor.washer_power", "0", {"unit_of_measurement": "W"})
    entry = await setup_power_watcher(hass, min_duration=60)
    await set_state(hass, "sensor.washer_power", "1800")
    assert await hass.config_entries.async_unload(entry.entry_id)
    freezer.tick(120)
    await pass_time(hass, 0)
    assert not calls


async def finish_power_cycle(hass: HomeAssistant, freezer) -> None:
    await set_state(hass, "sensor.washer_power", "1800")
    await set_state(hass, "sensor.washer_power", "0")
    freezer.tick(60)
    await pass_time(hass, 0)


async def press(hass: HomeAssistant, action: str) -> None:
    hass.bus.async_fire("mobile_app_notification_action", {"action": action})
    await hass.async_block_till_done()


async def test_end_reminded_until_finished(hass: HomeAssistant, freezer) -> None:
    calls = mock_supernotify(hass)
    hass.states.async_set("sensor.washer_power", "0", {"unit_of_measurement": "W"})
    entry = await setup_power_watcher(hass, reminder=20)
    await finish_power_cycle(hass, freezer)
    assert len(calls) == 3

    # told again, as the same notification and past Supernotify's duplicate check
    freezer.tick(20 * 60)
    await pass_time(hass, 0)
    assert len(calls) == 4
    assert calls[3].data == calls[2].data | {"force_resend": True}

    # until it's said to be finished with, which also clears the notification
    await press(hass, f"APPLIANCE_FINISHED_{entry.entry_id}")
    assert len(calls) == 5
    assert calls[4].data["extra_data"] == {
        "mobile_push_notification_tag": f"appliance_{entry.entry_id}_end",
        "mobile_push_clear_notification": True,
    }
    freezer.tick(60 * 60)
    await pass_time(hass, 0)
    assert len(calls) == 5


async def test_end_reminded_no_more_than_three_times(hass: HomeAssistant, freezer) -> None:
    calls = mock_supernotify(hass)
    hass.states.async_set("sensor.washer_power", "0", {"unit_of_measurement": "W"})
    await setup_power_watcher(hass, reminder=10)
    await finish_power_cycle(hass, freezer)
    for _ in range(5):
        freezer.tick(10 * 60)
        await pass_time(hass, 0)
    assert len(calls) == 3 + 3


async def test_end_reminded_as_many_times_as_asked(hass: HomeAssistant, freezer) -> None:
    calls = mock_supernotify(hass)
    hass.states.async_set("sensor.washer_power", "0", {"unit_of_measurement": "W"})
    await setup_power_watcher(hass, reminder=10, reminder_repeats=1)
    await finish_power_cycle(hass, freezer)
    for _ in range(3):
        freezer.tick(10 * 60)
        await pass_time(hass, 0)
    assert len(calls) == 3 + 1


async def test_next_cycle_stops_reminders(hass: HomeAssistant, freezer) -> None:
    calls = mock_supernotify(hass)
    hass.states.async_set("sensor.washer_power", "0", {"unit_of_measurement": "W"})
    await setup_power_watcher(hass, reminder=10)
    await finish_power_cycle(hass, freezer)
    await set_state(hass, "sensor.washer_power", "1800")
    assert len(calls) == 4
    freezer.tick(10 * 60)
    await pass_time(hass, 0)
    assert len(calls) == 4


async def test_remind_me_later(hass: HomeAssistant, freezer) -> None:
    calls = mock_supernotify(hass)
    hass.states.async_set("sensor.washer_power", "0", {"unit_of_measurement": "W"})
    entry = await setup_power_watcher(hass)
    await finish_power_cycle(hass, freezer)

    # with no reminder set, once, after half an hour
    await press(hass, f"APPLIANCE_REMIND_{entry.entry_id}")
    freezer.tick(29 * 60)
    await pass_time(hass, 0)
    assert len(calls) == 3
    freezer.tick(60)
    await pass_time(hass, 0)
    assert len(calls) == 4
    assert calls[3].data["message"] == "Washer is finished"
    freezer.tick(60 * 60)
    await pass_time(hass, 0)
    assert len(calls) == 4

    # buttons for another appliance, or anything else, are left alone
    await press(hass, "APPLIANCE_REMIND_another")
    await press(hass, "SUPERNOTIFY_SNOOZE")
    freezer.tick(60 * 60)
    await pass_time(hass, 0)
    assert len(calls) == 4


async def test_switch_off_once_finished(hass: HomeAssistant, freezer, caplog) -> None:
    calls = mock_supernotify(hass)
    switched = async_mock_service(hass, "switch", "turn_off")
    hass.states.async_set("sensor.washer_power", "0", {"unit_of_measurement": "W"})
    hass.states.async_set("switch.washer_plug", "on")
    entry = await setup_power_watcher(hass, switch_entity="switch.washer_plug")
    await finish_power_cycle(hass, freezer)
    assert calls[2].data == ended("Washer", entry.entry_id, "mdi:washing-machine", switch=True, track=True, force_resend=True)

    await press(hass, f"APPLIANCE_SWITCH_OFF_{entry.entry_id}")
    assert [c.data for c in switched] == [{"entity_id": "switch.washer_plug"}]

    # not while it's running again
    await set_state(hass, "sensor.washer_power", "1800")
    await press(hass, f"APPLIANCE_SWITCH_OFF_{entry.entry_id}")
    assert len(switched) == 1
    assert "running again" in caplog.text


async def test_switch_off_failure_is_logged(hass: HomeAssistant, freezer, caplog) -> None:
    mock_supernotify(hass)

    async def fail(call: ServiceCall) -> None:
        raise HomeAssistantError("plug offline")

    hass.services.async_register("switch", "turn_off", fail)
    hass.states.async_set("sensor.washer_power", "0", {"unit_of_measurement": "W"})
    hass.states.async_set("switch.washer_plug", "on")
    entry = await setup_power_watcher(hass, switch_entity="switch.washer_plug")
    await finish_power_cycle(hass, freezer)
    await press(hass, f"APPLIANCE_SWITCH_OFF_{entry.entry_id}")
    assert "Switching off Washer failed" in caplog.text


async def test_switch_off_only_offered_with_a_plug_to_switch(hass: HomeAssistant, freezer) -> None:
    calls = mock_supernotify(hass)
    switched = async_mock_service(hass, "switch", "turn_off")
    hass.states.async_set("sensor.washer_power", "0", {"unit_of_measurement": "W"})
    # a plug chosen that has since gone
    entry = await setup_power_watcher(hass, switch_entity="switch.washer_plug")
    await finish_power_cycle(hass, freezer)
    assert calls[2].data == ended("Washer", entry.entry_id, "mdi:washing-machine", track=True, force_resend=True)
    # nor is a button left from before answered
    await press(hass, f"APPLIANCE_SWITCH_OFF_{entry.entry_id}")
    assert not switched


async def test_switch_off_button_turned_off(hass: HomeAssistant, freezer) -> None:
    calls = mock_supernotify(hass)
    switched = async_mock_service(hass, "switch", "turn_off")
    hass.states.async_set("sensor.washer_power", "0", {"unit_of_measurement": "W"})
    hass.states.async_set("switch.washer_plug", "on")
    entry = await setup_power_watcher(hass, switch_entity="switch.washer_plug", switch_off_button=False)
    await finish_power_cycle(hass, freezer)
    assert calls[2].data == ended("Washer", entry.entry_id, "mdi:washing-machine", track=True, force_resend=True)
    await press(hass, f"APPLIANCE_SWITCH_OFF_{entry.entry_id}")
    assert not switched


async def test_switch_off_is_not_for_a_discovered_appliance(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set("switch.washer_plug", "on")
    # an option that only the settings of a power monitored appliance can make
    entry = await setup_watcher(hass, appliance, {"switch_entity": "switch.washer_plug"})
    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.cycle, "finished")
    assert calls[2].data == ended("Dishwasher", entry.entry_id, "mdi:dishwasher", track=True, force_resend=True)


async def test_buttons_in_the_language_of_home_assistant(hass: HomeAssistant, freezer) -> None:
    calls = mock_supernotify(hass)
    hass.config.language = "it"
    hass.states.async_set("sensor.washer_power", "0", {"unit_of_measurement": "W"})
    hass.states.async_set("switch.washer_plug", "on")
    await setup_power_watcher(hass, switch_entity="switch.washer_plug", reminder=45)
    await finish_power_cycle(hass, freezer)
    assert [a["title"] for a in calls[2].data["actions"]] == [
        "Finito",
        "Spegni presa",
        "Segui manutenzione",
    ]


async def test_reminders_stop_when_unloaded(hass: HomeAssistant, freezer) -> None:
    calls = mock_supernotify(hass)
    hass.states.async_set("sensor.washer_power", "0", {"unit_of_measurement": "W"})
    entry = await setup_power_watcher(hass, reminder=10)
    await finish_power_cycle(hass, freezer)
    assert await hass.config_entries.async_unload(entry.entry_id)
    freezer.tick(60 * 60)
    await pass_time(hass, 0)
    assert len(calls) == 3


async def test_icon_follows_an_italian_name(hass: HomeAssistant) -> None:
    # the words of the language Home Assistant is in, from the translations
    hass.config.language = "it"
    calls = mock_supernotify(hass)
    hass.states.async_set("sensor.washer_power", "0", {"unit_of_measurement": "W"})
    await setup_power_watcher(hass, "Lavastoviglie cucina")
    await set_state(hass, "sensor.washer_power", "1800")
    assert calls[0].data["extra_data"]["notification_icon"] == "mdi:dishwasher"


async def test_context_passed_on_from_the_state_change(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    enquiries = async_mock_service(
        hass,
        "supernotify",
        "enquire_implicit_deliveries",
        response={"mobile_push": ["mobile_push"]},
        supports_response=SupportsResponse.ONLY,
    )
    async_mock_service(
        hass, "supernotify", "enquire_configuration", response={"delivery": {}}, supports_response=SupportsResponse.ONLY
    )
    calls = async_mock_service(hass, "supernotify", "notify")
    await setup_watcher(hass, appliance)

    started, finished = Context(), Context()
    hass.states.async_set(appliance.cycle, "run", context=started)
    await hass.async_block_till_done()
    assert [call.context for call in calls] == [started]

    # the Live Activity cleared and the end told, and the deliveries looked up on the way, all for the one change
    hass.states.async_set(appliance.cycle, "finished", context=finished)
    await hass.async_block_till_done()
    assert [call.context for call in calls[1:]] == [finished, finished]
    assert enquiries[-1].context == finished


async def test_context_passed_on_without_supernotify(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    await setup_watcher(hass, appliance, {"targets": ["notify.phone"]})
    calls = async_mock_service(hass, "notify", "send_message")
    await set_state(hass, appliance.cycle, "run")

    finished = Context()
    hass.states.async_set(appliance.cycle, "finished", context=finished)
    await hass.async_block_till_done()
    assert [call.context for call in calls] == [finished]


async def test_context_of_its_own_when_a_timer_ends_the_cycle(hass: HomeAssistant, freezer) -> None:
    calls = mock_supernotify(hass)
    hass.states.async_set("sensor.washer_power", "0", {"unit_of_measurement": "W"})
    await setup_power_watcher(hass, reminder=20)
    dropped = Context()
    await set_state(hass, "sensor.washer_power", "1800")
    hass.states.async_set("sensor.washer_power", "0", {"unit_of_measurement": "W"}, context=dropped)
    # the change handled before time moves on, which HA before 2026.10 leaves to a later turn of the loop
    await hass.async_block_till_done()
    freezer.tick(60)
    await pass_time(hass, 0)

    # one new context for all that the timer set off, leading back to the change that set it
    assert len(calls) == 3
    assert calls[1].context == calls[2].context
    assert calls[1].context not in (dropped, calls[0].context)
    assert calls[1].context.parent_id == dropped.id

    # and another for the reminder, a timer later, leading back to the end it reminds of
    freezer.tick(20 * 60)
    await pass_time(hass, 0)
    assert len(calls) == 4
    assert calls[3].context.parent_id == calls[1].context.id


async def test_context_passed_on_from_a_button(hass: HomeAssistant, freezer) -> None:
    calls = mock_supernotify(hass)
    switched = async_mock_service(hass, "switch", "turn_off")
    hass.states.async_set("sensor.washer_power", "0", {"unit_of_measurement": "W"})
    hass.states.async_set("switch.washer_plug", "on")
    entry = await setup_power_watcher(hass, switch_entity="switch.washer_plug")
    await finish_power_cycle(hass, freezer)

    pressed = Context(user_id="someone")
    for action in ("SWITCH_OFF", "FINISHED"):
        hass.bus.async_fire(
            "mobile_app_notification_action", {"action": f"APPLIANCE_{action}_{entry.entry_id}"}, context=pressed
        )
        await hass.async_block_till_done()
    assert switched[0].context == pressed
    assert calls[-1].context == pressed

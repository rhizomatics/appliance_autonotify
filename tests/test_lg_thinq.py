"""LG washers, dryers and dishwashers through LG ThinQ, whose one state says both whether the cycle is running and what
it's doing, with how far along it is worked out from the time, a washer seen to work, a dryer or dishwasher in beta till
it's been tried with a real appliance"""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.appliance_autonotify.const import BETA_FOUND, DOMAIN, PROGRESS_TICK
from custom_components.appliance_autonotify.discovery import find_appliances, is_cycle_entity
from custom_components.appliance_autonotify.platforms import GENERIC, profile_for

from .conftest import mock_supernotify, placeholders
from .test_samsung import add_device, setup_appliance
from .test_watcher import ended, pass_time, set_state

WASHER_ID = "c6ee0c7f-1d4a-4b6e-9a51-washer000001"
DRYER_ID = "c6ee0c7f-1d4a-4b6e-9a51-dryer0000001"
DISHWASHER_ID = "c6ee0c7f-1d4a-4b6e-9a51-dishwasher01"
# the states the integration lists for a washer's or dryer's current status, those for any device of the type
STATES = [
    "add_drain", "cancel", "change_condition", "cooling", "detecting", "drying", "end", "error", "firmware",
    "initial", "pause", "power_off", "prewash", "refreshing", "reservation", "rinse_hold", "rinsing", "running",
    "smart_grid_run", "soaking", "spinning", "steam_softening", "wrinkle_care",
]  # fmt: skip
ENTITIES: dict[str, tuple[str, list[str] | None]] = {
    "current_state": ("sensor", STATES),
    "remain": ("sensor", None),
    "total": ("sensor", None),
    "relative_to_start_wm": ("sensor", None),
    "relative_to_stop_wm": ("sensor", None),
    "cycle_count": ("sensor", None),
}
NOW = datetime.fromisoformat("2026-11-13T10:00:00+00:00")


def thinq_device(hass: HomeAssistant, uuid: str, name: str, model: str) -> dict[str, str]:
    """A device as LG ThinQ registers it, with its model named for its type"""
    found = add_device(hass, "lg_thinq", uuid, name, ENTITIES)
    dr.async_get(hass).async_update_device(found["device_id"], model=model)
    return found


def washer(hass: HomeAssistant) -> dict[str, str]:
    return thinq_device(hass, WASHER_ID, "Laundry", "WM4000HWA (DEVICE_WASHER)")


def test_states_as_every_integration_has_them() -> None:
    profile = profile_for("lg_thinq")
    assert profile.beta
    assert not profile.beta_for("washer")
    assert not profile.beta_for("dryer")
    assert profile.beta_for("dishwasher")
    assert profile.issue_url is not None
    assert profile.issue_url.endswith("/issues/27")
    assert profile.stage_from_cycle
    assert [profile.cycle_state(s) for s in ("rinsing", "pause", "rinse_hold", "end", "power_off", "reservation")] == [
        "run",
        "pause",
        "actionrequired",
        "finished",
        "inactive",
        "delayedstart",
    ]
    # anything it isn't known to mean is left as it is, and so not taken for any state of a cycle
    assert profile.cycle_state("firmware") == "firmware"
    assert GENERIC.cycle_state("rinsing") == "rinsing"


async def test_washer_set_up_and_dishwasher_offered_as_new(hass: HomeAssistant) -> None:
    """A washer has been seen to work, so it's set up like any other, while a dishwasher is only offered"""
    laundry = washer(hass)
    dishes = thinq_device(hass, DISHWASHER_ID, "Lavastoviglie", "DF425HSS (DEVICE_DISH_WASHER)")
    assert {appliance.device_id for appliance in find_appliances(hass)} == {laundry["device_id"], dishes["device_id"]}
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    found = placeholders(result)["found"]
    assert "- Laundry\n" in f"{found}\n"
    assert f"- Lavastoviglie{BETA_FOUND}" in found
    await hass.config_entries.flow.async_configure(result["flow_id"], {"auto_discover": True})
    await hass.async_block_till_done()
    [flow] = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flow["context"]["source"] == SOURCE_INTEGRATION_DISCOVERY
    assert flow["context"]["unique_id"] == dishes["device_id"]
    assert laundry["device_id"] in {entry.data.get("device_id") for entry in hass.config_entries.async_entries(DOMAIN)}


async def test_only_a_type_in_beta_is_traced(hass: HomeAssistant) -> None:
    laundry = washer(hass)
    dishes = thinq_device(hass, DISHWASHER_ID, "Lavastoviglie", "DF425HSS (DEVICE_DISH_WASHER)")
    hass.states.async_set(laundry["current_state"], "power_off")
    hass.states.async_set(dishes["current_state"], "power_off")
    washer_entry = await setup_appliance(hass, laundry["device_id"])
    dishwasher_entry = await setup_appliance(hass, dishes["device_id"])
    assert not washer_entry.runtime_data.beta
    assert washer_entry.runtime_data.trace is None
    assert dishwasher_entry.runtime_data.beta
    assert dishwasher_entry.runtime_data.trace is not None


async def test_same_states_of_another_integration_are_no_cycle(hass: HomeAssistant) -> None:
    """The states of a cycle are LG's only for LG ThinQ"""
    other = add_device(hass, "other", "1", "Laundry", {"current_state": ("sensor", STATES)})
    assert find_appliances(hass) == []
    entity = er.async_get(hass).async_get(other["current_state"])
    assert entity is not None
    assert not is_cycle_entity(entity)


async def test_washer_cycle(hass: HomeAssistant, freezer) -> None:
    freezer.move_to(NOW)
    laundry = washer(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(laundry["current_state"], "initial")
    entry = await setup_appliance(hass, laundry["device_id"], notify_start=True)
    watcher = entry.runtime_data
    # its type from its model, there being no program to tell by
    assert watcher.appliance_type == "washer"
    assert watcher.entity_ids["stage"] == laundry["current_state"]

    await set_state(hass, laundry["current_state"], "detecting")
    assert [call.data["message"] for call in calls] == ["Laundry started"]
    assert calls[0].data["extra_data"]["notification_icon"] == "mdi:washing-machine"

    # what it's doing is its state, with when it will finish, and how far along it is from the time it takes
    hass.states.async_set(laundry["total"], "60", {"unit_of_measurement": "min"})
    hass.states.async_set(laundry["remain"], (NOW + timedelta(minutes=45)).isoformat())
    await set_state(hass, laundry["current_state"], "rinsing")
    # beside the name, the timer taking the message's place on an iPhone
    assert (calls[-1].data["title"], calls[-1].data["message"]) == ("Laundry · rinsing", "25% complete")
    extra = calls[-1].data["extra_data"]
    assert extra["when"] == int((NOW + timedelta(minutes=45)).timestamp())
    assert extra["progress"] == 25

    # and as time goes by, with nothing from the washer to say so
    sent = len(calls)
    freezer.tick(timedelta(minutes=15))
    await pass_time(hass, PROGRESS_TICK)
    assert len(calls) == sent + 1
    assert calls[-1].data["extra_data"]["progress"] == 50

    # paused and on again is the same cycle
    await set_state(hass, laundry["current_state"], "pause")
    await set_state(hass, laundry["current_state"], "spinning")
    assert [call.data["message"] for call in calls].count("Laundry started") == 1

    sent = len(calls)
    await set_state(hass, laundry["current_state"], "end")
    assert calls[-1].data == ended("Laundry", entry.entry_id, "mdi:washing-machine", track=True, force_resend=True)
    # the end is no stage to tell of
    assert [call.data["message"] for call in calls[sent:]] == ["Laundry is finished", "Laundry is finished"]

    # nor anything once it's off, nor as time goes by
    sent = len(calls)
    await set_state(hass, laundry["current_state"], "power_off")
    await pass_time(hass, PROGRESS_TICK)
    assert len(calls) == sent


async def test_dryer_putting_its_finish_back(hass: HomeAssistant, freezer) -> None:
    """As a real one did, on a bedding cycle: its total kept at the 55 minutes it first said, its finish put back 11
    minutes at a time as the end came near, for an hour and a half longer"""
    freezer.move_to(NOW)
    dryer = thinq_device(hass, DRYER_ID, "Dryer", "BDV_TX_BT_LED_6203 (DEVICE_DRYER)")
    calls = mock_supernotify(hass)
    hass.states.async_set(dryer["current_state"], "initial")
    hass.states.async_set(dryer["total"], "55", {"unit_of_measurement": "min"})
    hass.states.async_set(dryer["remain"], (NOW + timedelta(minutes=55)).isoformat())
    await setup_appliance(hass, dryer["device_id"])
    await set_state(hass, dryer["current_state"], "running")

    freezer.tick(timedelta(minutes=50))
    await pass_time(hass, PROGRESS_TICK)
    assert calls[-1].data["extra_data"]["progress"] == 90
    assert calls[-1].data["extra_data"]["when"] == int((NOW + timedelta(minutes=55)).timestamp())

    # the countdown put right, not left at nought, and the bar back to how far along it now is of the longer cycle
    sent = len(calls)
    finish = NOW + timedelta(minutes=66)
    await set_state(hass, dryer["remain"], finish.isoformat())
    assert len(calls) == sent + 1
    extra = calls[-1].data["extra_data"]
    assert extra["when"] == int(finish.timestamp())
    assert extra["progress"] == 75

    # and from there climbing again, with time
    freezer.tick(timedelta(minutes=6))
    await pass_time(hass, PROGRESS_TICK)
    assert calls[-1].data["extra_data"]["progress"] == 84

    # a remaining time a minute out either way is no change of mind to tell of
    sent = len(calls)
    await set_state(hass, dryer["remain"], (finish + timedelta(minutes=1)).isoformat())
    assert len(calls) == sent


async def test_dryer_over_once_it_only_tumbles(hass: HomeAssistant) -> None:
    dryer = thinq_device(hass, DRYER_ID, "Asciugatrice", "RH90V9AV4N (DEVICE_DRYER)")
    calls = mock_supernotify(hass)
    hass.states.async_set(dryer["current_state"], "power_off")
    entry = await setup_appliance(hass, dryer["device_id"])
    assert entry.runtime_data.appliance_type == "dryer"

    await set_state(hass, dryer["current_state"], "drying")
    await set_state(hass, dryer["current_state"], "cooling")
    assert calls[-1].data["message"] == "cooling"
    await set_state(hass, dryer["current_state"], "wrinkle_care")
    assert calls[-1].data == ended("Asciugatrice", entry.entry_id, "mdi:tumble-dryer", track=True, force_resend=True)

    # its end, once it's done tumbling, is no second one
    sent = len(calls)
    await set_state(hass, dryer["current_state"], "end")
    assert len(calls) == sent

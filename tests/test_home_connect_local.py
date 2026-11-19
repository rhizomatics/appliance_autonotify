"""Bosch, Siemens and Neff appliances through Home Connect Local, on the local network, with the entities as its source
names them, in beta till it's been tried with a real appliance"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.loader import IntegrationNotLoaded

from custom_components.appliance_autonotify import discovery
from custom_components.appliance_autonotify.const import BETA_FOUND, DOMAIN
from custom_components.appliance_autonotify.discovery import find_appliances
from custom_components.appliance_autonotify.platforms import profile_for

from .conftest import OPERATION_STATES, mock_supernotify, placeholders
from .test_samsung import add_device, setup_appliance
from .test_watcher import set_state

HA_ID = "BOSCH-WAT28400-68A40E000000"
PROGRAMS = ["laundrycare_washer_program_cotton", "laundrycare_washer_program_mix", "favorite_001"]
# the entities of a washer, by translation key, as Home Connect Local registers them
WASHER: dict[str, tuple[str, list[str] | None]] = {
    "sensor_operation_state": ("sensor", OPERATION_STATES),
    "sensor_program_progress": ("sensor", None),
    "sensor_remaining_program_time": ("sensor", None),
    "sensor_active_program": ("sensor", PROGRAMS),
    "select_program": ("select", PROGRAMS),
    "binary_sensor_door_state": ("binary_sensor", None),
}
WASHING_MACHINE = "mdi:washing-machine"


def local_washer(hass: HomeAssistant) -> dict[str, str]:
    return add_device(hass, "homeconnect_ws", HA_ID, "Washer", WASHER)


def test_home_connect_local_is_in_beta() -> None:
    profile = profile_for("homeconnect_ws")
    assert profile.beta
    assert profile.issue_url is not None
    assert profile.issue_url.endswith("/issues/28")
    assert profile.appliance_type(PROGRAMS, []) == "washer"
    assert profile.appliance_type(["laundrycare_washerdryer_program_mix"], []) == "washer_dryer"
    assert profile.appliance_type(["dishcare_dishwasher_program_eco50"], []) == "dishwasher"


async def test_washer_offered_as_new(hass: HomeAssistant) -> None:
    washer = local_washer(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert placeholders(result)["found"] == f"Appliances found:\n\n- Washer{BETA_FOUND}"
    await hass.config_entries.flow.async_configure(result["flow_id"], {"auto_discover": True})
    await hass.async_block_till_done()
    assert hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, washer["device_id"]) is None
    [flow] = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flow["context"]["source"] == SOURCE_INTEGRATION_DISCOVERY
    assert flow["context"]["unique_id"] == washer["device_id"]


async def test_washer_cycle(hass: HomeAssistant, freezer) -> None:
    freezer.move_to(datetime.fromisoformat("2026-11-13T10:00:20+00:00"))
    washer = local_washer(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(washer["sensor_operation_state"], "ready")
    hass.states.async_set(washer["sensor_active_program"], "laundrycare_washer_program_cotton")
    entry = await setup_appliance(hass, washer["device_id"], notify_start=True)
    assert entry.runtime_data.appliance_type == "washer"
    # its program a sensor, where Home Connect's is a select
    assert entry.runtime_data.entity_ids["active_program"] == washer["sensor_active_program"]
    assert entry.runtime_data.trace is not None

    await set_state(hass, washer["sensor_operation_state"], "run")
    assert calls[0].data["message"] == "Washer started"
    assert calls[0].data["extra_data"]["notification_icon"] == WASHING_MACHINE

    # the time left is a duration, shown in hours, which the countdown takes from now, to the minute
    hass.states.async_set(washer["sensor_remaining_program_time"], "1.5", {"unit_of_measurement": "h"})
    await set_state(hass, washer["sensor_program_progress"], "10")
    extra = calls[-1].data["extra_data"]
    assert extra["progress"] == 10
    assert extra["when"] == int(datetime.fromisoformat("2026-11-13T11:30:00+00:00").timestamp())

    # nothing left, or no unit of time, is no countdown
    hass.states.async_set(washer["sensor_remaining_program_time"], "0", {"unit_of_measurement": "h"})
    await set_state(hass, washer["sensor_program_progress"], "20")
    assert "when" not in calls[-1].data["extra_data"]
    hass.states.async_set(washer["sensor_remaining_program_time"], "30", {"unit_of_measurement": "%"})
    await set_state(hass, washer["sensor_program_progress"], "30")
    assert "when" not in calls[-1].data["extra_data"]

    sent = len(calls)
    await set_state(hass, washer["sensor_operation_state"], "finished")
    assert [call.data["message"] for call in calls[sent:]] == ["Washer is finished", "Washer is finished"]


async def test_local_preferred_to_the_cloud_for_the_same_appliance(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same appliance through Home Connect, by its id, is set up once, through the local network"""

    def loaded(hass: HomeAssistant, domain: str) -> SimpleNamespace:
        if domain not in ("home_connect", "homeconnect_ws"):
            raise IntegrationNotLoaded(domain)
        return SimpleNamespace(iot_class="local_push" if domain == "homeconnect_ws" else "cloud_push")

    monkeypatch.setattr(discovery, "async_get_loaded_integration", loaded)
    cloud = add_device(
        hass,
        "home_connect",
        HA_ID,
        "Lavatrice",
        {"operation_state": ("sensor", OPERATION_STATES), "program_progress": ("sensor", None)},
    )
    local = local_washer(hass)
    assert [appliance.device_id for appliance in find_appliances(hass)] == [local["device_id"]]

    # and heard from through the cloud while the local network can't be
    hass.states.async_set(local["sensor_operation_state"], "unavailable")
    hass.states.async_set(cloud["operation_state"], "ready")
    calls = mock_supernotify(hass)
    entry = await setup_appliance(hass, local["device_id"], notify_start=True)
    assert entry.runtime_data.fallback_cycle_entity_id == cloud["operation_state"]
    await set_state(hass, cloud["operation_state"], "run")
    assert calls[0].data["message"] == "Washer started"

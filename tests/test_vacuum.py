from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed, async_mock_service

from custom_components.appliance_autonotify.const import (
    DOMAIN,
    VACUUM_BLIP_SETTLE,
    VACUUM_COMPLETE_SETTLE,
    VACUUM_HELD_SETTLE,
    VACUUM_MIDWAY_SETTLE,
    VACUUM_SETTLE,
)

from .conftest import mock_supernotify, placeholders, schema
from .test_watcher import ANDROID, ended, pass_time, set_state

if TYPE_CHECKING:
    from freezegun.api import FrozenDateTimeFactory

ICON = "mdi:robot-vacuum"


def add_vacuum(hass: HomeAssistant, name: str = "Bruno", platform: str = "roborock") -> tuple[str, str]:
    """Register a robot vacuum as any vendor integration would, returning its device and vacuum entity"""
    source = MockConfigEntry(domain=platform)
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(config_entry_id=source.entry_id, identifiers={(platform, name)}, name=name)
    entity = er.async_get(hass).async_get_or_create(
        "vacuum", platform, name, suggested_object_id=name.lower(), device_id=device.id, config_entry=source
    )
    return device.id, entity.entity_id


def add_percentage(hass: HomeAssistant, device_id: str, key: str, device_class: str | None = None) -> str:
    """A sensor of the vacuum's in %, as its integration would have it, returning its entity"""
    return add_sensor(hass, device_id, "sensor", key, device_class, "%")


def add_running(hass: HomeAssistant, device_id: str, key: str) -> str:
    """A running binary sensor of the vacuum's, as Roborock's Cleaning or its mop drying, returning its entity"""
    return add_sensor(hass, device_id, "binary_sensor", key, "running")


def add_sensor(
    hass: HomeAssistant,
    device_id: str,
    domain: str,
    key: str,
    device_class: str | None,
    unit: str | None = None,
    translation_key: str | None = None,
) -> str:
    vacuum = next(e for e in er.async_entries_for_device(er.async_get(hass), device_id) if e.domain == "vacuum")
    source = hass.config_entries.async_get_entry(vacuum.config_entry_id or "")
    assert source is not None
    entity = er.async_get(hass).async_get_or_create(
        domain,
        source.domain,
        f"{device_id}_{key}",
        suggested_object_id=f"bruno_{key}",
        device_id=device_id,
        config_entry=source,
        unit_of_measurement=unit,
        original_device_class=device_class,
        translation_key=translation_key,
    )
    return entity.entity_id


async def setup_vacuum(hass: HomeAssistant, device_id: str, **options: object) -> MockConfigEntry:
    assert await async_setup_component(hass, "notify", {})
    entry = MockConfigEntry(
        domain=DOMAIN, title="Bruno", unique_id=device_id, data={"device_id": device_id, "type": "vacuum"}, options=options
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_vacuum_is_set_up_automatically(hass: HomeAssistant) -> None:
    device_id, _ = add_vacuum(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert placeholders(result)["found"] == "Appliances found:\n\n- Bruno"
    await hass.config_entries.flow.async_configure(result["flow_id"], {"auto_discover": True})
    await hass.async_block_till_done()

    entry = hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, device_id)
    assert entry is not None
    assert entry.data == {"device_id": device_id, "type": "vacuum", "dashboard_found": True}
    assert entry.state is ConfigEntryState.LOADED

    # and one added later is set up as it appears
    other_id, _ = add_vacuum(hass, "Upstairs", "ecovacs")
    await hass.async_block_till_done()
    other = hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, other_id)
    assert other is not None
    assert other.data == {"device_id": other_id, "type": "vacuum", "dashboard_found": True}


async def test_vacuum_offered_keeps_its_type(hass: HomeAssistant) -> None:
    device_id, _ = add_vacuum(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    await hass.config_entries.flow.async_configure(result["flow_id"], {"auto_discover": False})
    await hass.async_block_till_done()
    flow = next(f for f in hass.config_entries.flow.async_progress_by_handler(DOMAIN) if f["context"]["unique_id"] == device_id)
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert result["data"] == {"device_id": device_id, "type": "vacuum"}


async def test_vacuum_cleaning_is_a_cycle(hass: HomeAssistant) -> None:
    device_id, vacuum = add_vacuum(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    entry = await setup_vacuum(hass, device_id, notify_start=True)
    tag = f"appliance_{entry.entry_id}"

    await set_state(hass, vacuum, "cleaning")
    assert len(calls) == 1
    assert calls[0].data == {
        "message": "Bruno started",
        "title": "Bruno",
        "force_resend": True,
        "extra_data": {"mobile_push_notification_tag": tag, "live_update": True, "notification_icon": ICON, **ANDROID},
    }

    # paused, on its way back, or away with the vendor cloud, it's still the same cleaning
    for state in ("paused", "cleaning", "returning", "unavailable"):
        await set_state(hass, vacuum, state)
    assert len(calls) == 1

    # back, but not over till it has stayed back
    await set_state(hass, vacuum, "docked")
    assert len(calls) == 1
    await pass_time(hass, VACUUM_SETTLE)
    assert len(calls) == 3
    assert calls[1].data["extra_data"] == {"mobile_push_notification_tag": tag, "mobile_push_clear_notification": True}
    assert calls[2].data == ended("Bruno", entry.entry_id, ICON, force_resend=True)

    # docked again is no new end
    await set_state(hass, vacuum, "idle")
    assert len(calls) == 3


async def test_vacuum_stuck_is_told(hass: HomeAssistant) -> None:
    device_id, vacuum = add_vacuum(hass)
    calls = mock_supernotify(hass)
    # already cleaning when Home Assistant starts
    hass.states.async_set(vacuum, "cleaning")
    entry = await setup_vacuum(hass, device_id)
    tag = f"appliance_{entry.entry_id}"

    await set_state(hass, vacuum, "error")
    assert calls == []
    # stuck once it has stayed so, the Live Activity closed, with no end since it didn't finish, and a call for help
    await pass_time(hass, VACUUM_SETTLE)
    assert len(calls) == 2
    assert calls[0].data["extra_data"] == {"mobile_push_notification_tag": tag, "mobile_push_clear_notification": True}
    assert calls[1].data == {
        "message": "Bruno needs help",
        "title": "Bruno",
        "force_resend": True,
        "extra_data": {"notification_icon": ICON},
    }

    # once seen to and docked, nothing more to tell
    await set_state(hass, vacuum, "docked")
    assert len(calls) == 2


async def test_vacuum_without_supernotify(hass: HomeAssistant) -> None:
    device_id, vacuum = add_vacuum(hass)
    hass.states.async_set(vacuum, "docked")
    await setup_vacuum(hass, device_id, targets=["notify.phone"])
    calls = async_mock_service(hass, "notify", "send_message")
    await set_state(hass, vacuum, "cleaning")
    await set_state(hass, vacuum, "error")
    await pass_time(hass, VACUUM_SETTLE)
    assert [call.data["message"] for call in calls] == ["Bruno needs help"]


async def test_vacuum_gone_is_retried(hass: HomeAssistant) -> None:
    device_id, vacuum = add_vacuum(hass)
    er.async_get(hass).async_remove(vacuum)
    entry = MockConfigEntry(domain=DOMAIN, title="Bruno", data={"device_id": device_id, "type": "vacuum"})
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float) -> None:
    """Time passing, on the clock the states are stamped with as well as for the timers"""
    freezer.tick(seconds)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_vacuum_back_to_wash_its_mop_is_the_same_cleaning(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    device_id, vacuum = add_vacuum(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    await setup_vacuum(hass, device_id, notify_start=True)

    await set_state(hass, vacuum, "cleaning")
    await set_state(hass, vacuum, "returning")
    await set_state(hass, vacuum, "docked")
    await advance(hass, freezer, VACUUM_SETTLE - 60)
    await set_state(hass, vacuum, "cleaning")
    await advance(hass, freezer, VACUUM_SETTLE)
    assert len(calls) == 1

    await set_state(hass, vacuum, "returning")
    await set_state(hass, vacuum, "docked")
    await advance(hass, freezer, VACUUM_SETTLE)
    assert len(calls) == 3


async def test_vacuum_docked_as_it_sets_off_is_the_same_cleaning(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A real Ecovacs cleaning, washing its mop after each room, which its integration reports docked within a second
    of most times it sets off, and keeps to while it cleans the room, until it's back for the next wash"""
    freezer.move_to("2026-10-15T12:46:00+00:00")
    device_id, vacuum = add_vacuum(hass, platform="ecovacs")
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    await setup_vacuum(hass, device_id, notify_start=True)

    # seconds from one activity to the next, as reported from 14:46:53 to 15:59:30
    for state, seconds in (
        ("cleaning", 0.6),
        ("docked", 1161),  # out cleaning for 19 minutes, said to be docked, and back for its mop till 15:06:15
        ("cleaning", 1123),
        ("docked", 117),  # back for its mop
        ("cleaning", 0.8),
        ("docked", 290),
        ("cleaning", 0.6),
        ("docked", 339),
        ("cleaning", 1051),
        ("docked", 110),
        ("cleaning", 119),
        ("returning", 44),
    ):
        await set_state(hass, vacuum, state)
        await advance(hass, freezer, seconds)
    assert [call.data["message"] for call in calls] == ["Bruno started"]

    # back for good, and over once it has stayed so
    await set_state(hass, vacuum, "docked")
    await advance(hass, freezer, VACUUM_SETTLE - 1)
    assert len(calls) == 1
    await advance(hass, freezer, 1)
    assert [call.data["message"] for call in calls] == ["Bruno started", "Bruno is finished", "Bruno is finished"]


async def test_vacuum_long_on_its_dock_part_way_through(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A real Ecovacs cleaning, back on its dock straight from cleaning for twelve minutes part way through, as it was
    from 10:59:32 to 11:11:47, which is the same cleaning, not one ending and another starting"""
    freezer.move_to("2026-10-17T08:21:00+00:00")
    device_id, vacuum = add_vacuum(hass, platform="ecovacs")
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    await setup_vacuum(hass, device_id, notify_start=True)

    # seconds from one activity to the next, as reported from 10:21:32 to 11:26:08
    for state, seconds in (
        ("cleaning", 1115),
        ("docked", 111),  # back for its mop
        ("cleaning", 1054),
        ("docked", 735),  # on its dock for over ten minutes
        ("cleaning", 819),
        ("returning", 42),
    ):
        await set_state(hass, vacuum, state)
        await advance(hass, freezer, seconds)
    assert [call.data["message"] for call in calls] == ["Bruno started"]

    await set_state(hass, vacuum, "docked")
    await advance(hass, freezer, VACUUM_SETTLE)
    assert [call.data["message"] for call in calls] == ["Bruno started", "Bruno is finished", "Bruno is finished"]


async def test_vacuum_straight_back_from_cleaning_for_good(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """One that never says it's on its way back is over once it has stayed on its dock long enough not to set off again"""
    device_id, vacuum = add_vacuum(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    await setup_vacuum(hass, device_id)

    await set_state(hass, vacuum, "cleaning")
    await advance(hass, freezer, 1200)
    await set_state(hass, vacuum, "docked")
    await advance(hass, freezer, VACUUM_SETTLE)
    # a second docked, or idle, doesn't make it any sooner
    await set_state(hass, vacuum, "idle")
    await advance(hass, freezer, VACUUM_MIDWAY_SETTLE - VACUUM_SETTLE - 1)
    assert len(calls) == 1
    await advance(hass, freezer, 1)
    assert [call.data["message"] for call in calls] == ["Bruno started", "Bruno is finished", "Bruno is finished"]


async def test_vacuum_paused_on_its_dock_once_back(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A real Ecovacs, said to be paused two minutes after it was back on its dock, as it was at 22:53:39, then away
    with the vendor cloud for the night, which is still the end of its cleaning"""
    device_id, vacuum = add_vacuum(hass, platform="ecovacs")
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    await setup_vacuum(hass, device_id)

    await set_state(hass, vacuum, "cleaning")
    await advance(hass, freezer, 1200)
    await set_state(hass, vacuum, "returning")
    await advance(hass, freezer, 36)
    await set_state(hass, vacuum, "docked")
    await advance(hass, freezer, 116)
    await set_state(hass, vacuum, "paused")
    await advance(hass, freezer, 60)
    await set_state(hass, vacuum, "unavailable")
    await advance(hass, freezer, VACUUM_SETTLE - 176)
    assert [call.data["message"] for call in calls] == ["Bruno started", "Bruno is finished", "Bruno is finished"]

    # nor is it a new cleaning when it's back from the cloud
    for state in ("paused", "docked"):
        await set_state(hass, vacuum, state)
    assert len(calls) == 3


async def test_vacuum_paused_out_cleaning(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Paused while it's out, even if its integration said it was docked as it set off, is still the same cleaning"""
    device_id, vacuum = add_vacuum(hass, platform="ecovacs")
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    await setup_vacuum(hass, device_id)

    await set_state(hass, vacuum, "cleaning")
    await advance(hass, freezer, 1)
    await set_state(hass, vacuum, "docked")
    await advance(hass, freezer, 600)
    await set_state(hass, vacuum, "paused")
    await advance(hass, freezer, VACUUM_BLIP_SETTLE)
    assert len(calls) == 1


async def test_vacuum_cleaning_through_a_restart(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Home Assistant restarted part way through a cleaning, while the integration reports a past error again, as on
    17/10 at 15:17: what it says next shows it was cleaning, so its end is still told, with no second start"""
    device_id, vacuum = add_vacuum(hass, platform="ecovacs")
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "error")
    await setup_vacuum(hass, device_id, notify_start=True)

    await advance(hass, freezer, 557)
    await set_state(hass, vacuum, "returning")
    await advance(hass, freezer, 44)
    await set_state(hass, vacuum, "docked")
    await advance(hass, freezer, VACUUM_SETTLE)
    assert [call.data["message"] for call in calls] == ["Bruno is finished", "Bruno is finished"]


async def test_vacuum_docked_through_a_restart(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Restarted with nothing to go by, then docked: no cleaning to tell of, and the next one starts as usual"""
    device_id, vacuum = add_vacuum(hass, platform="ecovacs")
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "unknown")
    await setup_vacuum(hass, device_id, notify_start=True)

    for state in ("docked", "error", "docked"):
        await set_state(hass, vacuum, state)
    await advance(hass, freezer, VACUUM_MIDWAY_SETTLE)
    assert calls == []

    await set_state(hass, vacuum, "cleaning")
    assert [call.data["message"] for call in calls] == ["Bruno started"]


async def test_vacuum_docked_as_it_sets_off_and_never_heard_from_again(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Stopped as soon as it set off, which the integration reports just as it would one leaving its dock"""
    device_id, vacuum = add_vacuum(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    await setup_vacuum(hass, device_id)

    await set_state(hass, vacuum, "cleaning")
    await advance(hass, freezer, 1)
    await set_state(hass, vacuum, "docked")
    await advance(hass, freezer, VACUUM_SETTLE)
    assert len(calls) == 1
    await advance(hass, freezer, VACUUM_BLIP_SETTLE)
    assert [call.data["message"] for call in calls] == ["Bruno started", "Bruno is finished", "Bruno is finished"]


async def test_vacuum_as_a_real_one_reports_it(hass: HomeAssistant) -> None:
    """The activities of a real vacuum, docked with an error, washing its mop, then out for a short cleaning that it
    reports docked for two minutes as it sets off"""
    device_id, vacuum = add_vacuum(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "unknown")
    await setup_vacuum(hass, device_id, notify_start=True)

    for state in ("docked", "error", "docked", "paused", "docked", "paused", "docked"):
        await set_state(hass, vacuum, state)
    assert calls == []

    await set_state(hass, vacuum, "cleaning")
    await set_state(hass, vacuum, "docked")
    await pass_time(hass, 128)
    await set_state(hass, vacuum, "returning")
    await set_state(hass, vacuum, "docked")
    assert len(calls) == 1
    await pass_time(hass, VACUUM_SETTLE)
    assert len(calls) == 3
    assert calls[2].data["message"] == "Bruno is finished"


async def test_vacuum_error_once_back_is_the_end(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    device_id, vacuum = add_vacuum(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "cleaning")
    await setup_vacuum(hass, device_id)

    await advance(hass, freezer, 1200)
    await set_state(hass, vacuum, "returning")
    await set_state(hass, vacuum, "docked")
    # an empty water tank, say, which the vacuum's own app tells of
    await set_state(hass, vacuum, "error")
    await pass_time(hass, VACUUM_SETTLE)
    assert len(calls) == 2
    assert calls[1].data["message"] == "Bruno is finished"


async def test_vacuum_error_again_on_reconnecting_isnt_stuck(hass: HomeAssistant) -> None:
    """A real vacuum whose integration, on reconnecting part way through, reports a past error for four minutes while
    the vacuum carries on, washing its mop twice before"""
    device_id, vacuum = add_vacuum(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    await setup_vacuum(hass, device_id, notify_start=True)

    await set_state(hass, vacuum, "cleaning")
    for _ in range(2):
        await set_state(hass, vacuum, "docked")
        await pass_time(hass, 180)
        await set_state(hass, vacuum, "cleaning")
    for state in ("unknown", "cleaning", "error"):
        await set_state(hass, vacuum, state)
    await pass_time(hass, 240)
    await set_state(hass, vacuum, "returning")
    await set_state(hass, vacuum, "docked")
    assert len(calls) == 1
    await pass_time(hass, VACUUM_SETTLE)
    assert len(calls) == 3
    assert calls[2].data["message"] == "Bruno is finished"
    assert "Bruno needs help" not in [call.data["message"] for call in calls]


async def test_vacuum_stuck_in_italian(hass: HomeAssistant) -> None:
    hass.config.language = "it"
    device_id, vacuum = add_vacuum(hass)
    hass.states.async_set(vacuum, "cleaning")
    await setup_vacuum(hass, device_id, targets=["notify.phone"])
    calls = async_mock_service(hass, "notify", "send_message")
    await set_state(hass, vacuum, "error")
    await pass_time(hass, VACUUM_SETTLE)
    assert [call.data["message"] for call in calls] == ["Bruno ha bisogno di aiuto"]


async def test_vacuum_done_by_its_own_progress_ends_soon(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A real Roborock cleaning on 21/10, its progress going to 100 as it set off back at 08:20:20, docked at 08:23:26,
    over 30 seconds later rather than 10 minutes, while its battery reaching 100 and a brush's life left at 100 don't
    count"""
    device_id, vacuum = add_vacuum(hass)
    progress = add_percentage(hass, device_id, "cleaning_progress")
    battery = add_percentage(hass, device_id, "battery", "battery")
    brush = add_percentage(hass, device_id, "brush_left")
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    # as left by the cleaning before
    hass.states.async_set(progress, "100")
    hass.states.async_set(brush, "100")
    hass.states.async_set(battery, "99")
    await setup_vacuum(hass, device_id, notify_start=True)

    await set_state(hass, vacuum, "cleaning")
    await advance(hass, freezer, 16)
    await set_state(hass, progress, "0")
    await set_state(hass, battery, "100")
    await advance(hass, freezer, 3000)
    await set_state(hass, progress, "77")
    await set_state(hass, progress, "100")
    await advance(hass, freezer, 3)
    await set_state(hass, vacuum, "returning")
    await advance(hass, freezer, 183)
    await set_state(hass, vacuum, "docked")
    await advance(hass, freezer, VACUUM_COMPLETE_SETTLE - 1)
    assert len(calls) == 1
    await advance(hass, freezer, 1)
    assert [call.data["message"] for call in calls] == ["Bruno started", "Bruno is finished", "Bruno is finished"]

    # the next cleaning starts from the 100 left by this one, which isn't its end
    await set_state(hass, vacuum, "cleaning")
    await set_state(hass, vacuum, "returning")
    await set_state(hass, vacuum, "docked")
    await advance(hass, freezer, VACUUM_SETTLE - 1)
    assert len(calls) == 4
    await advance(hass, freezer, 1)
    assert len(calls) == 6


async def test_vacuum_back_to_wash_its_mop_short_of_100(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Back on its dock to wash its mop, as Roborock reports it, with its progress not yet at 100, is the same
    cleaning"""
    device_id, vacuum = add_vacuum(hass)
    progress = add_percentage(hass, device_id, "cleaning_progress")
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    hass.states.async_set(progress, "100")
    await setup_vacuum(hass, device_id)

    await set_state(hass, vacuum, "cleaning")
    await set_state(hass, progress, "40")
    await set_state(hass, vacuum, "returning")
    await set_state(hass, vacuum, "docked")
    await advance(hass, freezer, VACUUM_SETTLE - 60)
    await set_state(hass, vacuum, "cleaning")
    await advance(hass, freezer, VACUUM_SETTLE)
    assert len(calls) == 1


async def test_vacuum_progress_at_100_once_back(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Progress that only reaches 100 once the vacuum is back on its dock ends the cleaning as soon"""
    device_id, vacuum = add_vacuum(hass)
    progress = add_percentage(hass, device_id, "cleaning_progress")
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    await setup_vacuum(hass, device_id)

    await set_state(hass, vacuum, "cleaning")
    await set_state(hass, progress, "90")
    await set_state(hass, vacuum, "returning")
    await set_state(hass, vacuum, "docked")
    await advance(hass, freezer, 60)
    await set_state(hass, progress, "100")
    await advance(hass, freezer, VACUUM_COMPLETE_SETTLE)
    assert len(calls) == 3


async def test_vacuum_wait_on_its_dock_is_a_setting(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    device_id, vacuum = add_vacuum(hass)
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    entry = await setup_vacuum(hass, device_id)

    # offered with the end, as it comes and so not kept
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["data_schema"] is not None
    end = next(v for k, v in schema(result).items() if k == "end")
    assert next(k for k in end.schema.schema if k == "grace_period").default() == VACUUM_SETTLE
    form: dict[str, dict[str, object]] = {"start": {}, "notify": {}}
    await hass.config_entries.options.async_configure(result["flow_id"], form | {"end": {"grace_period": VACUUM_SETTLE}})
    await hass.async_block_till_done()
    assert entry.options == {}

    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(result["flow_id"], form | {"end": {"grace_period": 120}})
    await hass.async_block_till_done()
    assert entry.options == {"grace_period": 120}

    await set_state(hass, vacuum, "cleaning")
    await set_state(hass, vacuum, "returning")
    await set_state(hass, vacuum, "docked")
    await advance(hass, freezer, 119)
    assert len(calls) == 1
    await advance(hass, freezer, 1)
    assert len(calls) == 3


async def test_vacuum_recharging_part_way_through(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A Roborock S6 as Vacuum Agent recorded it, its Cleaning on through a recharge at 19% and the cleaning carried on
    after, going off only at the end, which is then over soon after it's back, while its mop drying coming on once it's
    back holds nothing open"""
    device_id, vacuum = add_vacuum(hass)
    cleaning = add_running(hass, device_id, "cleaning")
    drying = add_running(hass, device_id, "mop_drying")
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    hass.states.async_set(cleaning, "off")
    hass.states.async_set(drying, "off")
    await setup_vacuum(hass, device_id, notify_start=True)

    await set_state(hass, vacuum, "cleaning")
    await set_state(hass, cleaning, "on")
    await advance(hass, freezer, 3600)
    await set_state(hass, vacuum, "returning")
    await advance(hass, freezer, 60)
    await set_state(hass, vacuum, "docked")
    await advance(hass, freezer, 2 * 3600)
    assert len(calls) == 1
    await set_state(hass, vacuum, "cleaning")
    await advance(hass, freezer, 1800)
    await set_state(hass, vacuum, "returning")
    await advance(hass, freezer, 60)
    await set_state(hass, vacuum, "docked")
    await set_state(hass, drying, "on")
    await advance(hass, freezer, 10)
    await set_state(hass, cleaning, "off")
    await advance(hass, freezer, VACUUM_COMPLETE_SETTLE - 1)
    assert len(calls) == 1
    await advance(hass, freezer, 1)
    assert [call.data["message"] for call in calls] == ["Bruno started", "Bruno is finished", "Bruno is finished"]


async def test_vacuum_running_sensor_off_before_its_back(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    device_id, vacuum = add_vacuum(hass)
    cleaning = add_running(hass, device_id, "cleaning")
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    hass.states.async_set(cleaning, "off")
    await setup_vacuum(hass, device_id)

    # on just before the vacuum says it's cleaning, as one tick of its integration can have it
    await set_state(hass, cleaning, "on")
    await advance(hass, freezer, 1)
    await set_state(hass, vacuum, "cleaning")
    await advance(hass, freezer, 1200)
    await set_state(hass, cleaning, "off")
    await set_state(hass, vacuum, "returning")
    await set_state(hass, vacuum, "docked")
    await advance(hass, freezer, VACUUM_COMPLETE_SETTLE)
    assert len(calls) == 3


async def test_vacuum_running_sensor_stuck_on(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A running sensor that never goes off holds the cleaning open only so long"""
    device_id, vacuum = add_vacuum(hass)
    cleaning = add_running(hass, device_id, "cleaning")
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    hass.states.async_set(cleaning, "off")
    await setup_vacuum(hass, device_id)

    await set_state(hass, vacuum, "cleaning")
    await set_state(hass, cleaning, "on")
    await set_state(hass, vacuum, "returning")
    await set_state(hass, vacuum, "docked")
    # paused on its dock is still waiting on it
    await set_state(hass, vacuum, "paused")
    await advance(hass, freezer, VACUUM_HELD_SETTLE - 1)
    assert len(calls) == 1
    await advance(hass, freezer, 1)
    assert len(calls) == 3


async def test_vacuum_running_sensor_on_from_before(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Its mop still drying from the cleaning before as it sets off, or coming on later, isn't its cleaning"""
    device_id, vacuum = add_vacuum(hass)
    drying = add_running(hass, device_id, "mop_drying")
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    hass.states.async_set(drying, "on")
    await setup_vacuum(hass, device_id)
    await advance(hass, freezer, 3600)

    await set_state(hass, vacuum, "cleaning")
    await set_state(hass, vacuum, "returning")
    await set_state(hass, vacuum, "docked")
    await advance(hass, freezer, VACUUM_SETTLE)
    assert len(calls) == 3

    await set_state(hass, drying, "off")
    await set_state(hass, vacuum, "cleaning")
    await advance(hass, freezer, 600)
    await set_state(hass, drying, "on")
    await set_state(hass, vacuum, "returning")
    await set_state(hass, vacuum, "docked")
    await advance(hass, freezer, VACUUM_SETTLE)
    assert len(calls) == 6


async def test_vacuum_running_sensor_through_a_restart(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Cleaning as Home Assistant starts, its running sensor on, still holds the cleaning open"""
    device_id, vacuum = add_vacuum(hass)
    cleaning = add_running(hass, device_id, "cleaning")
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "cleaning")
    hass.states.async_set(cleaning, "on")
    await setup_vacuum(hass, device_id)

    await set_state(hass, vacuum, "returning")
    await set_state(hass, vacuum, "docked")
    await advance(hass, freezer, VACUUM_SETTLE)
    assert calls == []
    await set_state(hass, cleaning, "off")
    await advance(hass, freezer, VACUUM_COMPLETE_SETTLE)
    assert len(calls) == 2


async def test_vacuum_status_is_said_as_it_goes(hass: HomeAssistant) -> None:
    """What Roborock's Status says it's doing, sweeping or relocating, is what its Live Activity says, as a stage"""
    device_id, vacuum = add_vacuum(hass)
    status = add_sensor(hass, device_id, "sensor", "status", "enum", translation_key="status")
    calls = mock_supernotify(hass)
    hass.states.async_set(vacuum, "docked")
    hass.states.async_set(status, "charging")
    entry = await setup_vacuum(hass, device_id)
    tag = f"appliance_{entry.entry_id}"

    # docked, what it's doing is nothing to tell
    await set_state(hass, status, "sweeping")
    assert calls == []

    # already sweeping as it's said to be cleaning, so told straight after the start
    await set_state(hass, vacuum, "cleaning")
    assert [c.data["message"] for c in calls] == ["Bruno started", "sweeping"]
    assert calls[1].data["title"] == "Bruno"
    assert calls[1].data["force_resend"] is True
    assert calls[1].data["extra_data"] == {
        "mobile_push_notification_tag": tag,
        "live_update": True,
        "notification_icon": ICON,
        **ANDROID,
        "silent": True,
        "alert_once": True,
    }

    # and again as it goes, back to sweeping after relocating, with nothing said while it can't be heard from
    for state in ("relocating", "unavailable", "sweeping"):
        await set_state(hass, status, state)
    assert [c.data["message"] for c in calls[2:]] == ["relocating", "sweeping"]

    # once its cleaning is over, nothing more
    await set_state(hass, vacuum, "docked")
    await set_state(hass, status, "charging")
    await pass_time(hass, VACUUM_SETTLE)
    count = len(calls)
    await set_state(hass, status, "idle")
    assert len(calls) == count


def add_roborock(hass: HomeAssistant) -> tuple[str, str, str, str, str]:
    """A vacuum with Roborock's Status, Cleaning mode and Cleaning progress, returning its device and those entities"""
    device_id, vacuum = add_vacuum(hass)
    status = add_sensor(hass, device_id, "sensor", "status", "enum", translation_key="status")
    mode = add_sensor(hass, device_id, "select", "cleaning_mode", None, translation_key="cleaning_mode")
    progress = add_sensor(hass, device_id, "sensor", "cleaning_progress", None, "%", translation_key="clean_percent")
    hass.states.async_set(vacuum, "docked")
    hass.states.async_set(status, "charging")
    hass.states.async_set(mode, "vac_and_mop")
    # as left by the cleaning before
    hass.states.async_set(progress, "100")
    return device_id, vacuum, status, mode, progress


async def test_vacuum_shows_its_cleaning_mode_status_and_progress(hass: HomeAssistant) -> None:
    """Its cleaning mode is its program, said with its status unless chosen otherwise, under its name alone, with its
    own progress on the bar once that's no longer what the cleaning before left"""
    device_id, vacuum, status, _, progress = add_roborock(hass)
    calls = mock_supernotify(hass)
    await setup_vacuum(hass, device_id)

    await set_state(hass, status, "sweeping")
    await set_state(hass, vacuum, "cleaning")
    assert [(c.data["title"], c.data["message"]) for c in calls] == [
        ("Bruno", "Bruno started"),
        ("Bruno", "vac_and_mop · sweeping"),
    ]
    # the 100 left from before is no progress of this cleaning
    assert all("progress" not in c.data["extra_data"] for c in calls)

    await set_state(hass, progress, "0")
    assert calls[-1].data["message"] == "vac_and_mop · sweeping"
    assert (calls[-1].data["extra_data"]["progress"], calls[-1].data["extra_data"]["critical_text"]) == (0, "0%")
    await set_state(hass, progress, "3")
    assert len(calls) == 3
    await set_state(hass, progress, "5")
    assert len(calls) == 4
    await set_state(hass, status, "relocating")
    assert (calls[-1].data["message"], calls[-1].data["extra_data"]["progress"]) == ("vac_and_mop · relocating", 5)


@pytest.mark.parametrize(
    ("detail", "title", "message"),
    [
        ("status", "Bruno · vac_and_mop", "sweeping"),
        # with the mode in the message there's no need for it in the title too
        ("program_status", "Bruno", "vac_and_mop · sweeping"),
        ("program", "Bruno", "vac_and_mop"),
    ],
)
async def test_vacuum_title_can_have_its_cleaning_mode(hass: HomeAssistant, detail: str, title: str, message: str) -> None:
    device_id, vacuum, status, _, _ = add_roborock(hass)
    calls = mock_supernotify(hass)
    await setup_vacuum(hass, device_id, live_title="name_program", live_detail=detail)

    await set_state(hass, status, "sweeping")
    await set_state(hass, vacuum, "cleaning")
    assert (calls[-1].data["title"], calls[-1].data["message"]) == (title, message)


async def test_vacuum_live_activity_settings(hass: HomeAssistant) -> None:
    """A vacuum has no time left to show, and its own choices unless chosen otherwise, which aren't kept as settings"""
    device_id, _, _, _, _ = add_roborock(hass)
    mock_supernotify(hass)
    entry = await setup_vacuum(hass, device_id)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["data_schema"] is not None
    fields = {str(k): k for k in schema(result)}
    assert "notify_progress" not in fields
    assert (fields["live_title"].default(), fields["live_detail"].default()) == ("name", "program_status")
    detail = schema(result)[fields["live_detail"]]
    assert detail.config["options"] == ["program_status", "status", "program"]

    form: dict[str, object] = {"start": {}, "end": {}, "notify": {}}
    await hass.config_entries.options.async_configure(
        result["flow_id"], form | {"live_title": "name", "live_detail": "program_status"}
    )
    await hass.async_block_till_done()
    assert entry.options == {}
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"], form | {"live_title": "name_program", "live_detail": "status"}
    )
    await hass.async_block_till_done()
    assert entry.options == {"live_title": "name_program", "live_detail": "status"}

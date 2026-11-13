"""An appliance of an integration not yet tried on a real appliance: offered rather than set up, its first cycles kept,
and how they went asked for"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from custom_components.appliance_autonotify import platforms
from custom_components.appliance_autonotify.const import BETA_FOUND, DOMAIN
from custom_components.appliance_autonotify.diagnostics import async_get_config_entry_diagnostics
from custom_components.appliance_autonotify.platforms import PlatformProfile
from custom_components.appliance_autonotify.trace import (
    ENDED,
    ISSUE_TRACKER,
    TRACE_CYCLES,
    TRACE_LIMIT,
    CycleTrace,
    feedback_issue_id,
)
from tests.ha_testing import MockConfigEntry

from .conftest import add_appliance, mock_supernotify, placeholders, setup_watcher
from .test_config_flow import appliances, start_discovery
from .test_watcher import set_state, setup_power_watcher

ISSUE_URL = "https://github.com/rhizomatics/appliance_autonotify/issues/28"


@pytest.fixture
def beta() -> Iterator[None]:
    """Home Connect as if it were yet to be tried, for the appliances of the tests to stand in for one that is"""
    with patch.dict(platforms.PROFILES, {"home_connect": PlatformProfile("home_connect", "beta", issue_url=ISSUE_URL)}):
        yield


@pytest.mark.usefixtures("beta")
async def test_beta_appliance_offered_rather_than_set_up(hass: HomeAssistant) -> None:
    add_appliance(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert placeholders(result)["found"] == f"Appliances found:\n\n- Dishwasher{BETA_FOUND}"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"auto_discover": True})
    await hass.async_block_till_done()

    assert appliances(hass) == {}
    [flow] = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flow["context"]["source"] == SOURCE_INTEGRATION_DISCOVERY
    result = await hass.config_entries.flow.async_configure(flow["flow_id"])
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert "**Support for home_connect is new**" in placeholders(result)["beta"]

    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert list(appliances(hass).values()) == ["Dishwasher"]


async def test_supported_appliance_has_no_beta_notice(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    await start_discovery(hass, auto_discover=False)
    [flow] = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    result = await hass.config_entries.flow.async_configure(flow["flow_id"])
    assert placeholders(result)["beta"] == ""
    assert flow["context"]["unique_id"] == appliance.device_id


@pytest.mark.usefixtures("beta")
async def test_first_cycles_traced_and_feedback_asked_for_once(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    mock_supernotify(hass)
    hass.states.async_set(appliance.cycle, "ready")
    entry = await setup_watcher(hass, appliance)
    issues = ir.async_get(hass)
    issue_id = feedback_issue_id(entry.entry_id)

    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.progress, "40")
    # a cycle given up on isn't one to ask about
    await set_state(hass, appliance.cycle, "aborting")
    assert issues.async_get_issue(DOMAIN, issue_id) is None

    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.cycle, "finished")
    issue = issues.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.learn_more_url == ISSUE_URL
    assert issue.translation_placeholders == {"name": "Dishwasher", "integration": "home_connect"}

    trace = entry.runtime_data.trace
    assert trace is not None
    assert (trace.cycles_ended, trace.cycles_finished) == (2, 1)
    assert [(e["role"], e.get("to")) for e in trace.events if e["role"] in ("operation_state", ENDED)] == [
        ("operation_state", "run"),
        ("operation_state", "aborting"),
        (ENDED, None),
        ("operation_state", "run"),
        ("operation_state", "finished"),
        (ENDED, None),
    ]
    assert {"role": "program_progress", "entity_id": appliance.progress, "from": None, "to": "40"}.items() <= next(
        e for e in trace.events if e["role"] == "program_progress"
    ).items()

    # asked the once, however many more cycles finish
    ir.async_delete_issue(hass, DOMAIN, issue_id)
    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.cycle, "finished")
    assert issues.async_get_issue(DOMAIN, issue_id) is None

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["platform"] == {"platform": "home_connect", "name": "home_connect", "status": "beta"}
    assert diagnostics["trace"]["cycles_ended"] == TRACE_CYCLES
    assert diagnostics["watcher"]["cycle_entity_id"] == appliance.cycle
    [device] = diagnostics["devices"]
    cycle = next(e for e in device["entities"] if e["entity_id"] == appliance.cycle)
    assert cycle["role"] == "operation_state"
    assert "run" in cycle["options"]
    assert cycle["state"] == "finished"

    # no longer traced once enough cycles have been
    events = len(trace.events)
    await set_state(hass, appliance.cycle, "run")
    assert len(trace.events) == events


async def test_supported_appliance_is_not_traced(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    mock_supernotify(hass)
    hass.states.async_set(appliance.cycle, "ready")
    entry = await setup_watcher(hass, appliance, {"target": ["person.alice"]})
    await set_state(hass, appliance.cycle, "run")
    await set_state(hass, appliance.cycle, "finished")
    assert entry.runtime_data.trace is None
    assert ir.async_get(hass).async_get_issue(DOMAIN, feedback_issue_id(entry.entry_id)) is None

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["platform"]["status"] == "supported"
    assert diagnostics["entry"]["options"] == {"target": "**REDACTED**"}
    assert diagnostics["trace"] == {"cycles_ended": 0, "cycles_finished": 0, "events": []}


async def test_feedback_forgotten_once_supported_or_removed(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    mock_supernotify(hass)
    hass.states.async_set(appliance.cycle, "ready")
    with patch.dict(platforms.PROFILES, {"home_connect": PlatformProfile("home_connect", "beta")}):
        entry = await setup_watcher(hass, appliance)
        await set_state(hass, appliance.cycle, "run")
        await set_state(hass, appliance.cycle, "finished")
        issue = ir.async_get(hass).async_get_issue(DOMAIN, feedback_issue_id(entry.entry_id))
        assert issue is not None
        assert issue.learn_more_url == ISSUE_TRACKER
        await hass.config_entries.async_unload(entry.entry_id)
    # its integration now seen to work
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, feedback_issue_id(entry.entry_id)) is None

    with patch.dict(platforms.PROFILES, {"home_connect": PlatformProfile("home_connect", "beta")}):
        await hass.config_entries.async_reload(entry.entry_id)
        await set_state(hass, appliance.cycle, "run")
        await set_state(hass, appliance.cycle, "finished")
    await hass.config_entries.async_remove(entry.entry_id)
    assert ir.async_get(hass).async_get_issue(DOMAIN, feedback_issue_id(entry.entry_id)) is None


async def test_trace_keeps_the_latest_and_carries_on_after_a_restart(hass: HomeAssistant) -> None:
    trace = CycleTrace(hass, "abc")
    for n in range(TRACE_LIMIT + 5):
        trace._add({"role": "operation_state", "to": str(n)})
    assert len(trace.events) == TRACE_LIMIT
    assert trace.events[0]["to"] == "5"
    assert trace.async_cycle_ended(False) is False
    assert trace.async_cycle_ended(True) is True
    assert trace.async_cycle_ended(True) is False
    assert not trace.recording
    assert trace.async_cycle_ended(True) is False
    assert trace.async_start({"sensor.x": "operation_state"}) is None
    await hass.async_block_till_done()
    assert [e.get("finished") for e in trace.events if e["role"] == ENDED] == [False, True, True]
    assert len(trace.events) == TRACE_LIMIT

    await trace._store.async_save(trace.as_dict())
    restarted = CycleTrace(hass, "abc")
    await restarted.async_load()
    assert restarted.as_dict() == trace.as_dict()
    await restarted.async_remove()


async def test_power_monitored_appliance_diagnostics(hass: HomeAssistant) -> None:
    """The plug the appliance is on, as the device to look at, with no integration of the appliance's own"""
    source = MockConfigEntry(domain="shelly")
    source.add_to_hass(hass)
    plug = dr.async_get(hass).async_get_or_create(config_entry_id=source.entry_id, identifiers={("shelly", "plug")})
    er.async_get(hass).async_get_or_create(
        "sensor", "shelly", "plug-power", suggested_object_id="washer_power", device_id=plug.id, config_entry=source
    )
    hass.states.async_set("sensor.washer_power", "0.4", {"unit_of_measurement": "W"})
    entry = await setup_power_watcher(hass)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["platform"] is None
    assert diagnostics["watcher"]["class"] == "PowerWatcher"
    [device] = diagnostics["devices"]
    assert device["identifier_domains"] == ["shelly"]
    assert [e["entity_id"] for e in device["entities"]] == ["sensor.washer_power"]

"""Repairs for what needs someone to act on it: an appliance removed from Home Assistant, whose entry would otherwise be
left retrying for good, and notifications with nowhere to go"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.const import CONF_DEVICE_ID, CONF_TYPE
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from .const import CONF_POWER_ENTITY, DOMAIN, TYPE_DISCOVERY, TYPE_POWER

if TYPE_CHECKING:
    from homeassistant.components.repairs import RepairsFlowResult
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.helpers.device_registry import EventDeviceRegistryUpdatedData
    from homeassistant.helpers.entity_registry import EventEntityRegistryUpdatedData

REMOVED_ISSUE: Final[str] = "appliance_removed"
NO_TARGETS_ISSUE: Final[str] = "no_targets"
TROUBLESHOOTING_URL: Final[str] = "https://appliance-autonotify.rhizomatics.org.uk/#nothing-sent"


def removed_issue_id(entry_id: str) -> str:
    return f"{REMOVED_ISSUE}_{entry_id}"


@callback
def appliance_gone(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Whether what the appliance is watched through has been removed from Home Assistant: its own device, or for one
    known by its power, the power sensor, which may be one never registered, so is only gone with no state either"""
    if entry.data.get(CONF_TYPE) == TYPE_DISCOVERY:
        return False
    if entry.data.get(CONF_TYPE) == TYPE_POWER:
        power: str = entry.options.get(CONF_POWER_ENTITY, "")
        return er.async_get(hass).async_get(power) is None and hass.states.get(power) is None
    return dr.async_get(hass).async_get(entry.data.get(CONF_DEVICE_ID, "")) is None


@callback
def appliance_registered(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Whether what the appliance is watched through is in Home Assistant's registries, which is the one sure sign it's
    there: the state of a power sensor removed lingers a moment after its registry entry goes"""
    if entry.data.get(CONF_TYPE) == TYPE_POWER:
        return er.async_get(hass).async_get(entry.options.get(CONF_POWER_ENTITY, "")) is not None
    return not appliance_gone(hass, entry)


@callback
def async_report_removed(hass: HomeAssistant, entry: ConfigEntry) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        removed_issue_id(entry.entry_id),
        is_fixable=True,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=REMOVED_ISSUE,
        translation_placeholders={"name": entry.title},
        data={"entry_id": entry.entry_id},
    )


@callback
def async_forget_removed(hass: HomeAssistant, entry_id: str) -> None:
    ir.async_delete_issue(hass, DOMAIN, removed_issue_id(entry_id))


@callback
def async_watch_removals(hass: HomeAssistant) -> None:
    """An appliance's device, or the power sensor of one known by its power, removed from Home Assistant, as when the
    appliance is removed from its own integration, raises a repair offering to remove it here too, and its entry is
    reloaded so it stops watching; added back, as a device restored by its integration is, it's watched again"""

    @callback
    def changed(entry: ConfigEntry, removed: bool) -> None:
        if removed:
            async_report_removed(hass, entry)
        else:
            async_forget_removed(hass, entry.entry_id)
        # a power monitored appliance just has nothing more to hear from, where one with a device of its own retries
        if entry.data.get(CONF_TYPE) != TYPE_POWER and not entry.disabled_by:
            hass.config_entries.async_schedule_reload(entry.entry_id)

    @callback
    def device_updated(event: Event[EventDeviceRegistryUpdatedData]) -> None:
        if event.data["action"] not in ("create", "remove"):
            return
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_TYPE) not in (TYPE_DISCOVERY, TYPE_POWER) and (
                entry.data.get(CONF_DEVICE_ID) == event.data["device_id"]
            ):
                changed(entry, event.data["action"] == "remove")

    @callback
    def entity_updated(event: Event[EventEntityRegistryUpdatedData]) -> None:
        if event.data["action"] not in ("create", "remove"):
            return
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_TYPE) == TYPE_POWER and entry.options.get(CONF_POWER_ENTITY) == event.data["entity_id"]:
                changed(entry, event.data["action"] == "remove")

    hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, device_updated)
    hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, entity_updated)


@callback
def async_report_no_targets(hass: HomeAssistant, name: str) -> None:
    """Nowhere to send notifications, with no Supernotify, no targets chosen and no phone with the app, which is
    otherwise only logged, where it may never be seen"""
    ir.async_create_issue(
        hass,
        DOMAIN,
        NO_TARGETS_ISSUE,
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        learn_more_url=TROUBLESHOOTING_URL,
        translation_key=NO_TARGETS_ISSUE,
        translation_placeholders={"name": name},
    )


@callback
def async_forget_no_targets(hass: HomeAssistant) -> None:
    ir.async_delete_issue(hass, DOMAIN, NO_TARGETS_ISSUE)


class RemoveApplianceFlow(RepairsFlow):
    """Remove the entry of an appliance that's gone from Home Assistant, with its device and all that was kept of it"""

    def __init__(self, entry_id: str) -> None:
        self.entry_id = entry_id

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> RepairsFlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> RepairsFlowResult:
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        if user_input is not None:
            if entry is not None:
                await self.hass.config_entries.async_remove(self.entry_id)
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="confirm", description_placeholders={"name": entry.title if entry is not None else ""}
        )


async def async_create_fix_flow(hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None) -> RepairsFlow:
    if issue_id.startswith(REMOVED_ISSUE) and data is not None:
        return RemoveApplianceFlow(str(data["entry_id"]))
    return ConfirmRepairFlow()

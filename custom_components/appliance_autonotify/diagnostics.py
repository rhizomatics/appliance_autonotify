"""What an appliance is, as its integration has it, and what it did through its first cycles, to be attached to an
issue, as asked for of an appliance of an integration in beta"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_DEVICE_ID
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import CONF_CUSTOM_TARGET, CONF_POWER_ENTITY, CONF_TARGET, CONF_TARGETS
from .discovery import appliance_profile, companions, integration_name, role_key
from .trace import CycleTrace

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .watcher import ApplianceWatcher

# who is notified is nobody's business but the household's
TO_REDACT = {CONF_TARGET, CONF_CUSTOM_TARGET, CONF_TARGETS}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    watcher: ApplianceWatcher | None = getattr(entry, "runtime_data", None)
    device_ids: list[str] = []
    if device_id := entry.data.get(CONF_DEVICE_ID):
        device_ids = [device_id, *companions(hass, device_id)]
    elif (power := er.async_get(hass).async_get(entry.options.get(CONF_POWER_ENTITY) or "")) and power.device_id:
        device_ids = [power.device_id]
    profile = appliance_profile(hass, device_id) if device_id else None
    trace = watcher.trace if watcher is not None else None
    if trace is None:
        # kept from when its integration was in beta, or from before it was disabled
        trace = CycleTrace(hass, entry.entry_id)
        await trace.async_load()
    return {
        "entry": {
            "title": entry.title,
            "version": f"{entry.version}.{entry.minor_version}",
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "platform": None
        if profile is None
        else {
            "platform": profile.platform,
            "name": integration_name(hass, profile.platform),
            "status": profile.status,
        },
        "watcher": None if watcher is None else _watcher(watcher),
        "devices": [_device(hass, device_id) for device_id in device_ids],
        "trace": trace.as_dict(),
    }


def _watcher(watcher: ApplianceWatcher) -> dict[str, Any]:
    return {
        "class": type(watcher).__name__,
        "name": watcher.name,
        "appliance_type": watcher.appliance_type,
        "running": watcher.running,
        "cycle_entity_id": watcher.cycle_entity_id,
        "fallback_cycle_entity_id": watcher.fallback_cycle_entity_id,
        "entity_ids": dict(watcher.entity_ids),
        "fallback_ids": dict(watcher.fallback_ids),
    }


def _device(hass: HomeAssistant, device_id: str) -> dict[str, Any]:
    """The device, and every entity it has as its integration registers it, with what it's taken to do"""
    device = dr.async_get(hass).async_get(device_id)
    entities = er.async_entries_for_device(er.async_get(hass), device_id, include_disabled_entities=True)
    # a device linked to another has none of the details of its own
    details = device if isinstance(device, dr.DeviceEntry) else None
    return {
        "manufacturer": details.manufacturer if details else None,
        "model": details.model if details else None,
        "model_id": details.model_id if details else None,
        "sw_version": details.sw_version if details else None,
        "identifier_domains": sorted({domain for domain, _ in device.identifiers}) if device else [],
        "entities": [_entity(hass, entity) for entity in sorted(entities, key=lambda e: e.entity_id)],
    }


def _entity(hass: HomeAssistant, entity: er.RegistryEntry) -> dict[str, Any]:
    state = hass.states.get(entity.entity_id)
    return {
        "entity_id": entity.entity_id,
        "platform": entity.platform,
        "domain": entity.domain,
        "translation_key": entity.translation_key,
        "role": role_key(entity),
        "device_class": entity.device_class or entity.original_device_class,
        "unit": entity.unit_of_measurement,
        "options": (entity.capabilities or {}).get("options"),
        "disabled": entity.disabled,
        "state": state.state if state is not None else None,
    }

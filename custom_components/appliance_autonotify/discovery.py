"""Find appliances with an identifiable cycle, and set each up or offer it as a discovered config entry"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_INTEGRATION_DISCOVERY
from homeassistant.const import CONF_DEVICE_ID, CONF_NAME, CONF_TYPE, UnitOfPower
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import discovery_flow
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import IntegrationNotLoaded, async_get_loaded_integration

from .const import (
    CONF_AUTO_DISCOVER,
    CONF_POWER_ENTITY,
    CYCLE_KEY,
    CYCLE_TYPES,
    DERIVED_POWER_PLATFORMS,
    DOMAIN,
    ENTITY_DOMAINS,
    STATES_RUN,
    TYPE_DISCOVERY,
    TYPE_VACUUM,
)
from .platforms import PlatformProfile, profile_for
from .words import name_type

if TYPE_CHECKING:
    from homeassistant.helpers.device_registry import EventDeviceRegistryUpdatedData
    from homeassistant.helpers.entity_registry import EventEntityRegistryUpdatedData

POWER_DEVICE_CLASS = "power"
SENSOR_DOMAIN = "sensor"
SWITCH_DOMAIN = "switch"


@dataclass(frozen=True)
class Appliance:
    device_id: str
    name: str
    # how its cycle is told, None for an appliance of a vendor platform
    type: str | None = None
    # the integration it comes through
    platform: str | None = None


@dataclass(frozen=True)
class PowerMonitor:
    """A power sensor whose name says it's on an appliance that runs in cycles"""

    entity_id: str
    name: str


def role_key(entity: er.RegistryEntry) -> str | None:
    """What an entity does, as the translation key Home Connect gives an entity that does the same, by the names of
    its own integration before those of every integration"""
    return profile_for(entity.platform).role_key(entity.translation_key)


def is_cycle_entity(entity: er.RegistryEntry) -> bool:
    """A sensor of the state of an appliance's cycle, of whichever integration, whose states include one of a cycle
    under way, so not a sensor of something else that happens to have the same name"""
    if entity.disabled or entity.device_id is None or entity.domain != SENSOR_DOMAIN or role_key(entity) != CYCLE_KEY:
        return False
    options = (entity.capabilities or {}).get("options") or []
    profile = profile_for(entity.platform)
    return any(profile.cycle_state(option) in STATES_RUN for option in options)


@callback
def cycle_entities(hass: HomeAssistant) -> dict[str, er.RegistryEntry]:
    """The cycle state entity of every device that has one, by device"""
    registry = er.async_get(hass)
    found: dict[str, er.RegistryEntry] = {}
    for entity in registry.entities.values():
        if is_cycle_entity(entity) and entity.device_id is not None and _has_needs(registry, entity):
            found.setdefault(entity.device_id, entity)
    return found


def _has_needs(registry: er.EntityRegistry, cycle: er.RegistryEntry) -> bool:
    """Whether the device of a cycle state entity has whatever else its integration needs it to, to be an appliance"""
    needs = profile_for(cycle.platform).cycle_needs
    if not needs:
        return True
    roles = {role_key(e) for e in er.async_entries_for_device(registry, cycle.device_id or "") if not e.disabled}
    return all(need in roles for need in needs)


@callback
def companions(hass: HomeAssistant, device_id: str, cycles: dict[str, er.RegistryEntry] | None = None) -> list[str]:
    """Other devices with a cycle that are the same appliance through another integration, by an id they have in
    common, as a Samsung appliance's own id is to both SmartThings and LocalThings"""
    cycles = cycle_entities(hass) if cycles is None else cycles
    device_registry = dr.async_get(hass)
    device = device_registry.async_get(device_id)
    if device is None:
        return []
    domains = {domain for domain, _ in device.identifiers}
    ids = {value for _, value in device.identifiers}
    found: list[str] = []
    for other_id in cycles:
        other = device_registry.async_get(other_id) if other_id != device_id else None
        if other is not None and any(value in ids and domain not in domains for domain, value in other.identifiers):
            found.append(other_id)
    return found


@callback
def preference(hass: HomeAssistant, cycle: er.RegistryEntry) -> tuple[bool, int, str]:
    """How much an appliance's device is preferred to another for the same appliance: one its integration reaches on
    the local network over one reached through the vendor's cloud, then the one that tells more of its cycle"""
    try:
        iot_class = async_get_loaded_integration(hass, cycle.platform).iot_class or ""
    except IntegrationNotLoaded:
        iot_class = ""
    entities = er.async_entries_for_device(er.async_get(hass), cycle.device_id or "")
    roles = {key for entity in entities if not entity.disabled and (key := role_key(entity)) in ENTITY_DOMAINS}
    # and of two alike, always the same one
    return iot_class.startswith("local"), len(roles), cycle.device_id or ""


@callback
def _chosen_devices(hass: HomeAssistant) -> tuple[dict[str, er.RegistryEntry], set[str]]:
    """The cycle state entity of each appliance to offer, by device, and the devices passed over for another one
    of the same appliance"""
    cycles = cycle_entities(hass)
    configured = {entry.unique_id for entry in hass.config_entries.async_entries(DOMAIN, include_ignore=True)}
    chosen: dict[str, er.RegistryEntry] = {}
    passed_over: set[str] = set()
    for device_id, cycle in cycles.items():
        # the same appliance through two integrations is set up once, through the one preferred, unless it
        # already is through the other
        others = [] if device_id in configured else companions(hass, device_id, cycles)
        if others and (
            any(other in configured for other in others)
            or max([device_id, *others], key=lambda d: preference(hass, cycles[d])) != device_id
        ):
            passed_over.add(device_id)
            continue
        chosen[device_id] = cycle
    return chosen, passed_over


@callback
def find_appliances(hass: HomeAssistant) -> list[Appliance]:
    """Devices with a cycle state entity, of whichever integration, one for each appliance, and robot vacuums of
    any make"""
    device_registry = dr.async_get(hass)
    found: dict[str, Appliance] = {}
    for device_id, cycle in _chosen_devices(hass)[0].items():
        if (device := device_registry.async_get(device_id)) is not None:
            found[device_id] = Appliance(
                device_id, device.name_by_user or device.name or cycle.entity_id, platform=cycle.platform
            )
    for entity in er.async_get(hass).entities.values():
        if entity.domain != TYPE_VACUUM or entity.device_id is None or entity.disabled:
            continue
        if (device := device_registry.async_get(entity.device_id)) is not None:
            found[device.id] = Appliance(
                device.id, device.name_by_user or device.name or entity.entity_id, TYPE_VACUUM, entity.platform
            )
    return list(found.values())


@callback
def appliance_profile(hass: HomeAssistant, device_id: str) -> PlatformProfile:
    """The profile of the integration an appliance comes through, by its cycle state entity, or its vacuum"""
    if (cycle := cycle_entities(hass).get(device_id)) is not None:
        return profile_for(cycle.platform)
    vacuum = next(
        (
            entity
            for entity in er.async_entries_for_device(er.async_get(hass), device_id)
            if entity.domain == TYPE_VACUUM and not entity.disabled
        ),
        None,
    )
    return profile_for(vacuum.platform if vacuum is not None else None)


@callback
def integration_name(hass: HomeAssistant, platform: str | None) -> str:
    """The name an integration goes by, or its domain where it isn't loaded"""
    try:
        return async_get_loaded_integration(hass, platform or "").name
    except IntegrationNotLoaded:
        return platform or ""


def is_power_sensor(entity: er.RegistryEntry) -> bool:
    """A power sensor in watts, measured by the device itself rather than estimated or worked out from others"""
    return (
        entity.domain == SENSOR_DOMAIN
        and (entity.device_class or entity.original_device_class) == POWER_DEVICE_CLASS
        and entity.unit_of_measurement == UnitOfPower.WATT
        and entity.platform not in DERIVED_POWER_PLATFORMS
    )


def names_cycle_appliance(hass: HomeAssistant, name: str) -> bool:
    """Whether a name is that of an appliance that runs in cycles, by the same words that choose its icon"""
    return name_type(hass, name) in CYCLE_TYPES


@callback
def find_power_monitors(hass: HomeAssistant) -> list[PowerMonitor]:
    """Power sensors named for an appliance, such as a "Washing machine" plug, one for each device"""
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    # a device already set up by its own integration has no need of its power too
    configured = {entry.unique_id for entry in hass.config_entries.async_entries(DOMAIN, include_ignore=True)}
    found: dict[str, PowerMonitor] = {}
    for entity in sorted(entity_registry.entities.values(), key=lambda e: e.entity_id):
        if entity.disabled or not is_power_sensor(entity):
            continue
        device = device_registry.async_get(entity.device_id) if entity.device_id else None
        if device is not None and (device.id in configured or device.id in found):
            continue
        device_name = (device.name_by_user or device.name or "") if device is not None else ""
        entity_name = entity.name or entity.original_name or ""
        if not names_cycle_appliance(hass, f"{device_name} {entity_name}"):
            continue
        found[device.id if device is not None else entity.entity_id] = PowerMonitor(
            entity.entity_id, device_name or entity_name or entity.entity_id
        )
    return list(found.values())


@callback
def plug_switch(hass: HomeAssistant, power_entity_id: str) -> str | None:
    """The switch of the device a power sensor is on, where it has only the one, so the plug the appliance is on.
    A setting, such as a dryer's own Wrinkle prevent, isn't a plug, so isn't counted"""
    entity_registry = er.async_get(hass)
    entity = entity_registry.async_get(power_entity_id)
    if entity is None or entity.device_id is None:
        return None
    switches = [
        switch.entity_id
        for switch in er.async_entries_for_device(entity_registry, entity.device_id)
        if switch.domain == SWITCH_DOMAIN and switch.entity_category is None
    ]
    return switches[0] if len(switches) == 1 else None


@callback
def auto_discovery(hass: HomeAssistant) -> bool:
    """Whether appliances found are set up without asking, so not while the discovery entry is disabled or deleted"""
    return any(
        entry.data.get(CONF_TYPE) == TYPE_DISCOVERY and entry.options.get(CONF_AUTO_DISCOVER)
        for entry in hass.config_entries.async_entries(DOMAIN, include_disabled=False)
    )


@callback
def async_discover(hass: HomeAssistant) -> None:
    """Set up every appliance found, or with automatic discovery off, offer each to be added"""
    source = SOURCE_IMPORT if auto_discovery(hass) else SOURCE_INTEGRATION_DISCOVERY
    # an appliance offered through one integration, and now found through another preferred to it, is offered
    # through that one instead
    passed_over = _chosen_devices(hass)[1]
    for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN):
        if flow["context"].get("unique_id") in passed_over:
            hass.config_entries.flow.async_abort(flow["flow_id"])
    for appliance in find_appliances(hass):
        # appliances already configured, ignored or in progress are dropped by the flow's unique id, and one of an
        # integration not yet tried on a real appliance is only ever offered, to be added knowing that
        discovery_flow.async_create_flow(
            hass,
            DOMAIN,
            context={"source": SOURCE_INTEGRATION_DISCOVERY if profile_for(appliance.platform).beta else source},
            data={CONF_DEVICE_ID: appliance.device_id, CONF_NAME: appliance.name}
            | ({CONF_TYPE: appliance.type} if appliance.type else {}),
        )
    for monitor in find_power_monitors(hass):
        # only ever offered, since the name is a guess where a cycle state entity isn't, and the threshold is
        # worth a look before it's set up
        discovery_flow.async_create_flow(
            hass,
            DOMAIN,
            context={"source": SOURCE_INTEGRATION_DISCOVERY},
            data={CONF_POWER_ENTITY: monitor.entity_id, CONF_NAME: monitor.name},
        )


@callback
def async_start_discovery(hass: HomeAssistant) -> None:
    """Look for appliances now, and again whenever one may have been added or named"""

    @callback
    def entity_registry_updated(event: Event[EventEntityRegistryUpdatedData]) -> None:
        if event.data["action"] not in ("create", "update"):
            return
        entity = er.async_get(hass).async_get(event.data["entity_id"])
        if entity is None:
            return
        # any entity of an appliance, which may make one through another integration the one to prefer
        appliance_entity = role_key(entity) == CYCLE_KEY or role_key(entity) in ENTITY_DOMAINS or entity.domain == TYPE_VACUUM
        if (event.data["action"] == "create" and appliance_entity) or is_power_sensor(entity):
            async_discover(hass)

    @callback
    def device_registry_updated(event: Event[EventDeviceRegistryUpdatedData]) -> None:
        # a plug renamed after the appliance it's on
        if event.data["action"] == "update" and {"name", "name_by_user"} & set(event.data["changes"]):
            async_discover(hass)

    hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, entity_registry_updated)
    hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, device_registry_updated)
    async_discover(hass)

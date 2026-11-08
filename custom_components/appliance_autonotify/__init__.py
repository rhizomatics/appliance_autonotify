"""Appliance Auto Notify - automatic notifications for household appliance cycles"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import CONF_TYPE, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store

from .compat import vol
from .const import (
    CONF_DASHBOARD,
    CONF_DASHBOARD_FOUND,
    CONF_LIVE_TITLE,
    CONF_PROGRAM_IN_TITLE,
    CYCLE_STORE,
    CYCLE_STORE_VERSION,
    DOMAIN,
    LIVE_TITLE_NAME,
    MAINTENANCE_SNOOZE_DAYS,
    TYPE_DISCOVERY,
    TYPE_POWER,
    TYPE_VACUUM,
)
from .dashboards import matching_dashboard
from .device import async_register_device
from .discovery import async_discover, async_start_discovery
from .maintenance import DATA_MAINTENANCE, MaintenanceTracker
from .watcher import ApplianceWatcher, HomeConnectWatcher, PowerWatcher, VacuumWatcher
from .words import async_load_words

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
# the maintenance list is held by the entry for automatic discovery, there being one for every appliance
DISCOVERY_PLATFORMS: list[Platform] = [Platform.TODO]

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_ITEM = "item"
ATTR_CYCLES = "cycles"
ATTR_DAYS = "days"
SERVICE_RESET_MAINTENANCE = "reset_maintenance"
SERVICE_SNOOZE_MAINTENANCE = "snooze_maintenance"
RESET_SCHEMA = vol.Schema({
    vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
    vol.Optional(ATTR_ITEM): cv.string,
    vol.Optional(ATTR_CYCLES, default=0): vol.All(vol.Coerce(int), vol.Range(min=0)),
})
SNOOZE_SCHEMA = vol.Schema({
    vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
    vol.Optional(ATTR_ITEM): cv.string,
    vol.Optional(ATTR_DAYS, default=MAINTENANCE_SNOOZE_DAYS): vol.All(vol.Coerce(float), vol.Range(min=0)),
})

type AppliancesConfigEntry = ConfigEntry[ApplianceWatcher]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    await async_load_words(hass)
    tracker = MaintenanceTracker(hass)
    await tracker.async_load()
    hass.data[DATA_MAINTENANCE] = tracker
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, tracker.async_stop)
    _register_services(hass, tracker)
    async_start_discovery(hass)
    return True


@callback
def _register_services(hass: HomeAssistant, tracker: MaintenanceTracker) -> None:
    """Maintenance done, or put off, without the notification, for one item of an appliance or all it has"""

    def tracked(call: ServiceCall) -> tuple[str, str | None]:
        entry_id: str = call.data[ATTR_CONFIG_ENTRY_ID]
        key: str | None = call.data.get(ATTR_ITEM)
        if not tracker.tracked(entry_id):
            raise ServiceValidationError(f"Maintenance isn't tracked for {entry_id}")
        if key is not None and tracker.item(entry_id, key) is None:
            raise ServiceValidationError(f"No maintenance item {key} for {entry_id}")
        return entry_id, key

    async def reset(call: ServiceCall) -> None:
        entry_id, key = tracked(call)
        if call.data[ATTR_CYCLES] and key is not None and (item := tracker.item(entry_id, key)) and item.every is None:
            raise ServiceValidationError(f"{key} is a part whose life is read, not counted in cycles")
        if call.data[ATTR_CYCLES]:
            tracker.async_set_cycles(entry_id, key, call.data[ATTR_CYCLES])
        else:
            await tracker.async_done(entry_id, key, call.context)

    async def snooze(call: ServiceCall) -> None:
        entry_id, key = tracked(call)
        tracker.async_snooze(entry_id, key, call.data[ATTR_DAYS])

    hass.services.async_register(DOMAIN, SERVICE_RESET_MAINTENANCE, reset, schema=RESET_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SNOOZE_MAINTENANCE, snooze, schema=SNOOZE_SCHEMA)


async def async_migrate_entry(hass: HomeAssistant, entry: AppliancesConfigEntry) -> bool:
    if entry.version > 1:
        # from a later version, so not to be guessed at
        return False
    if entry.minor_version < 2:
        options = dict(entry.options)
        # the program left out of the title is the name alone, and left in it is the choice as it comes
        if options.pop(CONF_PROGRAM_IN_TITLE, True) is False:
            options[CONF_LIVE_TITLE] = LIVE_TITLE_NAME
        hass.config_entries.async_update_entry(entry, options=options, minor_version=2)
    if entry.minor_version < 3:
        # set up before a dashboard was looked for, so left with whatever was chosen
        hass.config_entries.async_update_entry(entry, data=entry.data | {CONF_DASHBOARD_FOUND: True}, minor_version=3)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AppliancesConfigEntry) -> bool:
    if entry.data.get(CONF_TYPE) == TYPE_DISCOVERY:
        # nothing to watch, only to look again now that automatic discovery may have been switched
        async_discover(hass)
        await hass.config_entries.async_forward_entry_setups(entry, DISCOVERY_PLATFORMS)
        return True
    watchers: dict[str | None, type[ApplianceWatcher]] = {TYPE_POWER: PowerWatcher, TYPE_VACUUM: VacuumWatcher}
    watcher = watchers.get(entry.data.get(CONF_TYPE), HomeConnectWatcher)(hass, entry)
    # a cycle under way before Home Assistant restarted, to carry on with as it starts
    await watcher.async_load()
    watcher.async_start()
    watcher.async_listen_for_actions()
    watcher.async_start_maintenance()
    entry.runtime_data = watcher
    async_register_device(hass, entry, watcher.name)
    if not entry.data.get(CONF_DASHBOARD_FOUND):
        _choose_dashboard(hass, entry, watcher)
    return True


def _choose_dashboard(hass: HomeAssistant, entry: AppliancesConfigEntry, watcher: ApplianceWatcher) -> None:
    """A dashboard named for the appliance or its type, chosen as it's first set up, once its type is known, to be
    changed or cleared in its settings like one chosen by hand"""
    options = dict(entry.options)
    if not options.get(CONF_DASHBOARD) and (match := matching_dashboard(hass, watcher.name, watcher.appliance_type)):
        options[CONF_DASHBOARD] = match
    hass.config_entries.async_update_entry(entry, data=entry.data | {CONF_DASHBOARD_FOUND: True}, options=options)


async def async_unload_entry(hass: HomeAssistant, entry: AppliancesConfigEntry) -> bool:
    if entry.data.get(CONF_TYPE) == TYPE_DISCOVERY:
        return await hass.config_entries.async_unload_platforms(entry, DISCOVERY_PLATFORMS)
    # the watcher's listeners are removed by the entry's own unload callbacks
    return True


async def async_remove_entry(hass: HomeAssistant, entry: AppliancesConfigEntry) -> None:
    # whatever was kept of its cycle through a restart
    await Store(hass, CYCLE_STORE_VERSION, CYCLE_STORE.format(entry_id=entry.entry_id)).async_remove()
    # what was counted goes with the appliance
    if (tracker := hass.data.get(DATA_MAINTENANCE)) is not None:
        tracker.async_forget(entry.entry_id)

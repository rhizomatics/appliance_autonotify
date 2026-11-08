"""Config flow for Appliance Auto Notify, one config entry per appliance"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_DEVICE_ID, CONF_NAME, CONF_TYPE, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TargetSelector,
    TextSelector,
    TextSelectorConfig,
)

from .compat import vol
from .const import (
    CONF_AUTO_DISCOVER,
    CONF_CUSTOM_TARGET,
    CONF_DASHBOARD,
    CONF_DELIVERIES,
    CONF_END_MESSAGE,
    CONF_END_TITLE,
    CONF_GRACE_PERIOD,
    CONF_LIVE_DETAIL,
    CONF_LIVE_TITLE,
    CONF_MAINTENANCE,
    CONF_MAINTENANCE_PREFIX,
    CONF_MIN_DURATION,
    CONF_NOTIFY_END,
    CONF_NOTIFY_PHASE,
    CONF_NOTIFY_PROGRESS,
    CONF_NOTIFY_START,
    CONF_POWER_ENTITY,
    CONF_REMINDER,
    CONF_REMINDER_REPEATS,
    CONF_START_MESSAGE,
    CONF_START_TITLE,
    CONF_SWITCH_ENTITY,
    CONF_SWITCH_OFF_BUTTON,
    CONF_TARGET,
    CONF_TARGETS,
    CONF_THRESHOLD,
    DEFAULT_END_MESSAGE,
    DEFAULT_GRACE_PERIOD,
    DEFAULT_MIN_DURATION,
    DEFAULT_REMINDER_REPEATS,
    DEFAULT_START_MESSAGE,
    DEFAULT_THRESHOLD,
    DEFAULT_TITLE,
    DISCOVERY_TITLE,
    DOMAIN,
    LIVE_DEFAULTS,
    LIVE_DETAILS,
    LIVE_TITLES,
    MAINTENANCE_ITEMS,
    NAME_PLACEHOLDER,
    PROGRAM_PLACEHOLDER,
    SUPERNOTIFY_MISSING,
    SUPERNOTIFY_PRESENT,
    TYPE_DISCOVERY,
    TYPE_POWER,
    TYPE_VACUUM,
    VACUUM_LIVE_DEFAULTS,
    VACUUM_LIVE_DETAILS,
    VACUUM_SETTLE,
)
from .dashboards import dashboards
from .discovery import find_appliances, plug_switch
from .supernotify_api import deliveries_by_transport, supernotify_available

STEP_POWER = "power"
STEP_DISCOVERY = "discovery"
STEP_SETTINGS = "settings"
SECTION_START = "start"
SECTION_END = "end"
SECTION_NOTIFY = "notify"
SECTION_MAINTENANCE = "maintenance_items"

# a switch or a choice left as it comes isn't a setting either
DEFAULT_CHOICES: dict[str, bool | str] = {
    CONF_NOTIFY_START: False,
    CONF_NOTIFY_END: True,
    CONF_NOTIFY_PROGRESS: False,
    **LIVE_DEFAULTS,
}

DEFAULT_TEXTS: dict[str, str] = {
    CONF_START_TITLE: DEFAULT_TITLE,
    CONF_START_MESSAGE: DEFAULT_START_MESSAGE,
    CONF_END_TITLE: DEFAULT_TITLE,
    CONF_END_MESSAGE: DEFAULT_END_MESSAGE,
}


def supernotify_status(hass: HomeAssistant) -> str:
    return SUPERNOTIFY_PRESENT if supernotify_available(hass) else SUPERNOTIFY_MISSING


def discovery_schema(auto_discover: bool = True) -> vol.Schema:
    return vol.Schema({vol.Required(CONF_AUTO_DISCOVER, default=auto_discover): BooleanSelector()})


async def settings_schema(
    hass: HomeAssistant,
    progress: bool = True,
    phase: bool | None = None,
    settle: bool = False,
    live: bool = True,
    vacuum: bool = False,
    maintenance: dict[str, int] | None = None,
) -> vol.Schema:
    """The settings of an appliance, with maintenance for one with something to maintain, and the cycles between each
    of the items for its type, as `maintenance` has them"""
    fields: dict[vol.Marker, Any] = {
        vol.Required(CONF_NOTIFY_START, default=False): BooleanSelector(),
        vol.Required(CONF_NOTIFY_END, default=True): BooleanSelector(),
    }
    if maintenance is not None:
        fields[vol.Required(CONF_MAINTENANCE, default=False)] = BooleanSelector()
    if phase is not None:
        # only for an appliance with phases, and on or off to begin with by how much they matter for its type
        fields[vol.Required(CONF_NOTIFY_PHASE, default=phase)] = BooleanSelector()
    if progress:
        fields[vol.Required(CONF_NOTIFY_PROGRESS, default=False)] = BooleanSelector()
    if live and supernotify_available(hass):
        # only a Live Activity has a title that changes as the cycle goes on, and a timer, which a vacuum hasn't
        defaults = VACUUM_LIVE_DEFAULTS if vacuum else LIVE_DEFAULTS
        for key, options in (
            (CONF_LIVE_TITLE, LIVE_TITLES),
            (CONF_LIVE_DETAIL, VACUUM_LIVE_DETAILS if vacuum else LIVE_DETAILS),
        ):
            fields[vol.Required(key, default=defaults[key])] = SelectSelector(
                SelectSelectorConfig(options=list(options), mode=SelectSelectorMode.DROPDOWN, translation_key=key)
            )
    notify: dict[vol.Marker, Any] = {}
    end: dict[vol.Marker, Any] = {
        vol.Optional(CONF_END_TITLE): TextSelector(),
        vol.Optional(CONF_END_MESSAGE): TextSelector(TextSelectorConfig(multiline=True)),
    }
    if supernotify_available(hass):
        # a choice of what's there, and not a box to type in, so a notification can't be made to open anything else
        choices = [SelectOptionDict(value=path, label=title) for path, title in dashboards(hass).items()]
        if choices:
            fields[vol.Optional(CONF_DASHBOARD)] = SelectSelector(
                SelectSelectorConfig(options=choices, mode=SelectSelectorMode.DROPDOWN)
            )
        # the same pair of target fields as supernotify.notify itself
        notify[vol.Optional(CONF_TARGET)] = TargetSelector()
        notify[vol.Optional(CONF_CUSTOM_TARGET)] = TextSelector(TextSelectorConfig(multiple=True))
        deliveries = sorted({name for names in (await deliveries_by_transport(hass)).values() for name in names})
        notify[vol.Optional(CONF_DELIVERIES)] = SelectSelector(SelectSelectorConfig(options=deliveries, multiple=True))
        # buttons and reminders go with the end notification, which only Supernotify can give buttons
        end[vol.Optional(CONF_REMINDER)] = NumberSelector(
            NumberSelectorConfig(min=0, max=720, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement=UnitOfTime.MINUTES)
        )
        end[vol.Required(CONF_REMINDER_REPEATS, default=DEFAULT_REMINDER_REPEATS)] = NumberSelector(
            NumberSelectorConfig(min=1, max=20, step=1, mode=NumberSelectorMode.BOX)
        )
    else:
        notify[vol.Optional(CONF_TARGETS)] = EntitySelector(EntitySelectorConfig(domain="notify", multiple=True))
    if settle:
        # a robot vacuum's wait on its dock before its cleaning is over, where its own progress doesn't say
        end[vol.Required(CONF_GRACE_PERIOD, default=VACUUM_SETTLE)] = NumberSelector(
            NumberSelectorConfig(min=1, max=3600, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement=UnitOfTime.SECONDS)
        )
    sections: dict[str, dict[vol.Marker, Any]] = {
        SECTION_START: {
            vol.Optional(CONF_START_TITLE): TextSelector(),
            vol.Optional(CONF_START_MESSAGE): TextSelector(TextSelectorConfig(multiline=True)),
        },
        SECTION_END: end,
        SECTION_NOTIFY: notify,
    }
    if maintenance:
        # 0 for an item not to be tracked
        sections[SECTION_MAINTENANCE] = {
            vol.Required(f"{CONF_MAINTENANCE_PREFIX}{key}", default=every): NumberSelector(
                NumberSelectorConfig(min=0, max=1000, step=1, mode=NumberSelectorMode.BOX)
            )
            for key, every in maintenance.items()
        }
    # all tuning, so out of the way until it's wanted
    # the maintenance items as they come unless changed, so the section needn't be sent
    fields.update({
        (vol.Optional if name == SECTION_MAINTENANCE else vol.Required)(name): section(
            vol.Schema(contents), {"collapsed": True}
        )
        for name, contents in sections.items()
    })
    return vol.Schema(fields)


def sectioned(schema: vol.Schema, values: dict[str, Any]) -> dict[str, Any]:
    """Settings are stored flat, the sections are only for display"""
    shown: dict[str, Any] = {}
    for name, field in schema.schema.items():
        if isinstance(field, section):
            shown[str(name)] = {str(key): values[key] for key in field.schema.schema if key in values}
        elif name in values:
            shown[str(name)] = values[name]
    return shown


def flattened(user_input: dict[str, Any]) -> dict[str, Any]:
    """The settings of a form, with those in sections alongside the rest"""
    settings: dict[str, Any] = {}
    for name, value in user_input.items():
        settings.update(value if isinstance(value, dict) else {name: value})
    return settings


def power_schema(with_name: bool) -> vol.Schema:
    fields: dict[vol.Marker, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME)] = TextSelector()
    fields[vol.Required(CONF_POWER_ENTITY)] = EntitySelector(EntitySelectorConfig(domain="sensor", device_class="power"))
    fields[vol.Required(CONF_THRESHOLD, default=DEFAULT_THRESHOLD)] = NumberSelector(
        NumberSelectorConfig(min=0, step="any", mode=NumberSelectorMode.BOX, unit_of_measurement=UnitOfPower.WATT)
    )
    fields[vol.Required(CONF_GRACE_PERIOD, default=DEFAULT_GRACE_PERIOD)] = NumberSelector(
        NumberSelectorConfig(min=0, max=3600, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement=UnitOfTime.SECONDS)
    )
    fields[vol.Required(CONF_MIN_DURATION, default=DEFAULT_MIN_DURATION)] = NumberSelector(
        NumberSelectorConfig(min=0, max=3600, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement=UnitOfTime.SECONDS)
    )
    fields[vol.Optional(CONF_SWITCH_ENTITY)] = EntitySelector(EntitySelectorConfig(domain="switch"))
    fields[vol.Required(CONF_SWITCH_OFF_BUTTON, default=True)] = BooleanSelector()
    return vol.Schema(fields)


class AppliancesConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    # 2 has the choice of what the title of a Live Activity names in place of the switch for the program in it
    # 3 has a dashboard looked for as an appliance is first set up
    MINOR_VERSION = 3

    def __init__(self) -> None:
        self._device_id: str | None = None
        self._name: str = ""
        # how the cycle of the appliance found is told, where it isn't by a vendor platform
        self._type: dict[str, str] = {}
        # a power monitor found by its name, to be filled in on the form for a look before it's set up
        self._power: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AppliancesOptionsFlow:
        return AppliancesOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Automatic discovery the first time, and from then on an appliance to describe by hand"""
        if any(entry.data.get(CONF_TYPE) == TYPE_DISCOVERY for entry in self._async_current_entries()):
            return await self.async_step_power()
        if user_input is not None:
            await self.async_set_unique_id(TYPE_DISCOVERY)
            self._abort_if_unique_id_configured()
            # the appliances themselves are set up as this entry is, each as its own entry to change or disable
            return self.async_create_entry(title=DISCOVERY_TITLE, data={CONF_TYPE: TYPE_DISCOVERY}, options=user_input)
        configured = self._async_current_ids()
        found = [a.name for a in find_appliances(self.hass) if a.device_id not in configured]
        if found:
            found_text = "Appliances found:\n\n" + "\n".join(f"- {name}" for name in found)
        else:
            found_text = "No appliances could be automatically installed."
        return self.async_show_form(
            step_id="user",
            data_schema=discovery_schema(),
            description_placeholders={"found": found_text, "supernotify": supernotify_status(self.hass)},
        )

    async def async_step_power(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """An appliance not found by itself, with a power monitor to tell when it's running"""
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_POWER_ENTITY])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={CONF_TYPE: TYPE_POWER},
                options={k: v for k, v in user_input.items() if k != CONF_NAME},
            )
        if self._power:
            # looked for only now, since a plug's switch can be added after its sensor
            switch = plug_switch(self.hass, self._power[CONF_POWER_ENTITY])
            suggested = self._power | ({CONF_SWITCH_ENTITY: switch} if switch else {})
            return self.async_show_form(
                step_id=STEP_POWER,
                data_schema=self.add_suggested_values_to_schema(power_schema(with_name=True), suggested),
            )
        return self.async_show_form(step_id=STEP_POWER, data_schema=power_schema(with_name=True))

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """An appliance found with automatic discovery on, so set up without asking"""
        # a discovery of the same appliance may be waiting, and goes once this entry exists
        await self.async_set_unique_id(import_data[CONF_DEVICE_ID], raise_on_progress=False)
        self._abort_if_unique_id_configured()
        data = {k: v for k, v in import_data.items() if k in (CONF_DEVICE_ID, CONF_TYPE)}
        return self.async_create_entry(title=import_data[CONF_NAME], data=data)

    async def async_step_integration_discovery(self, discovery_info: dict[str, Any]) -> ConfigFlowResult:
        """An appliance found with automatic discovery off, or a power monitor named for one, so offered to be added"""
        if CONF_POWER_ENTITY in discovery_info:
            self._power = dict(discovery_info)
            await self.async_set_unique_id(discovery_info[CONF_POWER_ENTITY])
            self._abort_if_unique_id_configured()
            self.context["title_placeholders"] = {"name": discovery_info[CONF_NAME]}
            return await self.async_step_power()
        self._device_id = discovery_info[CONF_DEVICE_ID]
        self._name = discovery_info[CONF_NAME]
        self._type = {CONF_TYPE: discovery_info[CONF_TYPE]} if CONF_TYPE in discovery_info else {}
        await self.async_set_unique_id(self._device_id)
        self._abort_if_unique_id_configured()
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title=self._name, data={CONF_DEVICE_ID: self._device_id} | self._type)
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"name": self._name, "supernotify": supernotify_status(self.hass)},
        )


class AppliancesOptionsFlow(OptionsFlowWithReload):
    def __init__(self) -> None:
        self._settings: dict[str, Any] = {}

    def _name(self) -> str:
        # the name notifications are sent with, which follows the device rather than the entry's title
        watcher = getattr(self.config_entry, "runtime_data", None)
        return watcher.name if watcher is not None else self.config_entry.title

    def _phase_default(self) -> bool | None:
        return getattr(getattr(self.config_entry, "runtime_data", None), "phase_default", None)

    def _maintenance(self) -> dict[str, int] | None:
        """The items for the type of appliance, with their usual cycles apart, or None for an appliance with nothing
        to maintain, whose settings have no maintenance"""
        watcher = getattr(self.config_entry, "runtime_data", None)
        if watcher is None:
            # not running, so with nothing known of it to go by
            return None
        usual = dict(MAINTENANCE_ITEMS.get(watcher.appliance_type or "", {}))
        # by the type, so taking every item out still leaves them there to put back
        if usual or watcher.maintenance_items or self.config_entry.options.get(CONF_MAINTENANCE) is not None:
            return usual
        return None

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self.config_entry.data.get(CONF_TYPE) == TYPE_DISCOVERY:
            return await self.async_step_discovery()
        return await self.async_step_settings()

    async def async_step_discovery(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id=STEP_DISCOVERY,
            data_schema=discovery_schema(self.config_entry.options.get(CONF_AUTO_DISCOVER, True)),
        )

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        name = self._name()
        kind = self.config_entry.data.get(CONF_TYPE)
        vacuum = kind == TYPE_VACUUM
        # as they'll be sent, so there's the real text to edit rather than a template or an empty box
        defaults = {key: text.replace(NAME_PLACEHOLDER, name) for key, text in DEFAULT_TEXTS.items()}
        if user_input is not None:
            # text left as the default isn't a setting, so it goes on following the name of the appliance
            usual = {f"{CONF_MAINTENANCE_PREFIX}{key}": every for key, every in (self._maintenance() or {}).items()}
            unset = (
                defaults
                | DEFAULT_CHOICES
                | usual
                | (VACUUM_LIVE_DEFAULTS if vacuum else {})
                | {
                    CONF_NOTIFY_PHASE: self._phase_default(),
                    CONF_REMINDER_REPEATS: DEFAULT_REMINDER_REPEATS,
                    CONF_GRACE_PERIOD: VACUUM_SETTLE,
                }
            )
            # maintenance left off is only turned down once it had been on, so it's still offered to anyone who
            # hasn't been asked
            if self.config_entry.options.get(CONF_MAINTENANCE) is None:
                unset[CONF_MAINTENANCE] = False
            settings = {
                key: value
                for key, value in flattened(user_input).items()
                # an item at 0 is one left out, not one left as it comes
                if (value or value is False or (key in usual and value == 0)) and value != unset.get(key)
            }
            if self._maintenance() is None:
                # not on the form, so kept as it was
                settings = {
                    key: value for key, value in self.config_entry.options.items() if key.startswith(CONF_MAINTENANCE)
                } | settings
            if self.config_entry.data.get(CONF_TYPE) == TYPE_POWER:
                self._settings = settings
                return await self.async_step_power()
            return self.async_create_entry(data=settings)
        # a power monitored appliance has no progress to report, nor program for a Live Activity, and a robot vacuum's
        # progress, where it has one, is only for the bar
        schema = await settings_schema(
            self.hass,
            progress=kind not in (TYPE_POWER, TYPE_VACUUM),
            phase=self._phase_default(),
            settle=vacuum,
            live=kind != TYPE_POWER,
            vacuum=vacuum,
            maintenance=self._maintenance(),
        )
        shown = dict(self.config_entry.options)
        if shown.get(CONF_DASHBOARD) not in dashboards(self.hass):
            # removed since it was chosen
            shown.pop(CONF_DASHBOARD, None)
        for key, text in defaults.items():
            shown[key] = str(shown.get(key) or text).replace(NAME_PLACEHOLDER, name)
        return self.async_show_form(
            step_id=STEP_SETTINGS,
            data_schema=self.add_suggested_values_to_schema(schema, sectioned(schema, shown)),
            description_placeholders={
                "name": name,
                "supernotify": supernotify_status(self.hass),
                # as it's to be typed, which a translation can't say for itself
                "program_placeholder": PROGRAM_PLACEHOLDER,
            },
        )

    async def async_step_power(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=self._settings | user_input)
        return self.async_show_form(
            step_id=STEP_POWER,
            data_schema=self.add_suggested_values_to_schema(power_schema(with_name=False), self.config_entry.options),
            description_placeholders={"name": self.config_entry.title},
        )

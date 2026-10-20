"""Maintenance of appliances, counted in cycles, or read from how much life a part has left where the appliance's own
integration says, with whatever is due kept on a to-do list and told of once as it falls due"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.const import ATTR_ENTITY_ID, ATTR_FRIENDLY_NAME, ATTR_UNIT_OF_MEASUREMENT, PERCENTAGE
from homeassistant.core import CALLBACK_TYPE, Context, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_point_in_utc_time, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_MAINTENANCE_PREFIX,
    DOMAIN,
    LIFESPAN_DUE,
    LIFESPAN_KEY,
    LIFESPAN_RESET_PREFIX,
    MAINTENANCE_ITEMS,
    MAINTENANCE_MESSAGES,
    MAINTENANCE_NAMES,
    MAINTENANCE_SNOOZE_DAYS,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

_LOGGER = logging.getLogger(__name__)

DATA_MAINTENANCE = f"{DOMAIN}_maintenance"
STORAGE_KEY = f"{DOMAIN}.maintenance"
STORAGE_VERSION = 1
# seconds to gather changes into one write
SAVE_DELAY = 10


@dataclass(frozen=True)
class MaintenanceItem:
    """An item of an appliance's maintenance, due every so many cycles, or once a part's life is down to little"""

    key: str
    name: str
    every: int | None = None
    entity_id: str | None = None
    reset_entity_id: str | None = None


def translated(hass: HomeAssistant, table: Mapping[str, Mapping[str, str]]) -> Mapping[str, str]:
    """The texts in the language of Home Assistant, English for any other"""
    return table.get(hass.config.language.split("-")[0], table["en"])


@callback
def maintenance_items(
    hass: HomeAssistant, appliance_type: str | None, device_id: str | None, options: Mapping[str, Any]
) -> list[MaintenanceItem]:
    """The items an appliance starts with for its type, at the intervals chosen, and one for each part whose life its
    own integration reports, such as a robot vacuum's brushes and filter"""
    names = translated(hass, MAINTENANCE_NAMES)
    items: list[MaintenanceItem] = []
    for key, every in MAINTENANCE_ITEMS.get(appliance_type or "", {}).items():
        cycles = int(options.get(f"{CONF_MAINTENANCE_PREFIX}{key}", every))
        if cycles > 0:
            items.append(MaintenanceItem(key, names.get(key, key), every=cycles))
    if device_id is None:
        return items
    entities = er.async_entries_for_device(er.async_get(hass), device_id)
    resets = {
        entity.translation_key: entity.entity_id
        for entity in entities
        if entity.domain == "button" and entity.translation_key and not entity.disabled
    }
    for entity in entities:
        key = entity.translation_key or ""
        # only a percentage, there being no telling when a part counted any other way is due
        if (
            entity.domain == "sensor"
            and not entity.disabled
            and LIFESPAN_KEY in key
            and entity.unit_of_measurement == PERCENTAGE
        ):
            # the name Home Assistant shows is used where there's a state, this for when there isn't
            fallback = key.replace(LIFESPAN_KEY, "").strip("_").replace("_", " ").capitalize() or key
            items.append(
                MaintenanceItem(
                    entity.entity_id,
                    entity.name or entity.original_name or fallback,
                    entity_id=entity.entity_id,
                    reset_entity_id=resets.get(f"{LIFESPAN_RESET_PREFIX}{key}"),
                )
            )
    return items


class MaintenanceTracker:
    """The maintenance of every appliance it's tracked for, kept across restarts"""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, Any] = {"entries": {}}
        # the appliances tracked, by entry id, with their name and items
        self._appliances: dict[str, tuple[str, list[MaintenanceItem]]] = {}
        self._unsubscribe: dict[str, CALLBACK_TYPE] = {}
        self._listeners: list[Callable[[], None]] = []
        self._cancel_wake: CALLBACK_TYPE | None = None

    async def async_load(self) -> None:
        self._data = await self._store.async_load() or {"entries": {}}

    @callback
    def async_stop(self, *_: Any) -> None:
        """Nothing left waiting as Home Assistant stops"""
        if self._cancel_wake is not None:
            self._cancel_wake()
            self._cancel_wake = None

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        """Told whenever what's due may have changed"""
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            self._listeners.remove(listener)

        return remove

    def _entry(self, entry_id: str) -> dict[str, Any]:
        return self._data["entries"].setdefault(entry_id, {"items": {}})

    def _state(self, entry_id: str, key: str) -> dict[str, Any]:
        return self._entry(entry_id)["items"].setdefault(key, {})

    @callback
    def _changed(self) -> None:
        self._store.async_delay_save(lambda: self._data, SAVE_DELAY)
        self._schedule_wake()
        for listener in list(self._listeners):
            listener()

    @callback
    def async_register(
        self,
        entry_id: str,
        name: str,
        items: list[MaintenanceItem],
        on_due: Callable[[MaintenanceItem], None] | None = None,
    ) -> None:
        """An appliance whose maintenance is tracked, told through `on_due` of a part falling due as it does, and not
        only as a cycle ends, since a vacuum may sit on its dock a long while"""
        self.async_unregister(entry_id)
        self._appliances[entry_id] = (name, items)
        for item in items:
            # replaced while it wasn't being watched
            self._settle(entry_id, item)
        if lifespans := [item.entity_id for item in items if item.entity_id]:

            @callback
            def lifespan_changed(event: Event[EventStateChangedData]) -> None:
                new_state = event.data["new_state"]
                for item in items:
                    if new_state is None or item.entity_id != event.data["entity_id"]:
                        continue
                    # by the reading in the event, since a later one may already be there
                    self._settle(entry_id, item, self._percentage(new_state))
                    state = self._state(entry_id, item.key)
                    if self.due(entry_id, item) and not state.get("told") and on_due is not None:
                        state["told"] = True
                        on_due(item)
                self._changed()

            self._unsubscribe[entry_id] = async_track_state_change_event(self.hass, lifespans, lifespan_changed)
        self._changed()

    @callback
    def async_unregister(self, entry_id: str) -> None:
        if (unsubscribe := self._unsubscribe.pop(entry_id, None)) is not None:
            unsubscribe()
        if self._appliances.pop(entry_id, None) is not None:
            self._changed()

    @callback
    def async_forget(self, entry_id: str) -> None:
        """An appliance removed, along with all it had counted"""
        self.async_unregister(entry_id)
        if self._data["entries"].pop(entry_id, None) is not None:
            self._changed()

    def tracked(self, entry_id: str) -> bool:
        return entry_id in self._appliances

    def offered(self, entry_id: str) -> bool:
        """Whether tracking has been offered on an end notification, which it's offered on only once"""
        return bool(self._data["entries"].get(entry_id, {}).get("offered"))

    @callback
    def async_mark_offered(self, entry_id: str) -> None:
        self._entry(entry_id)["offered"] = True
        # straight away, so it isn't offered again after a restart soon after
        self._store.async_delay_save(lambda: self._data, 0)

    def item(self, entry_id: str, key: str) -> MaintenanceItem | None:
        return next((item for item in self._appliances.get(entry_id, ("", []))[1] if item.key == key), None)

    def name(self, entry_id: str, item: MaintenanceItem) -> str:
        """What the item is called, a part's as Home Assistant shows its entity, without the appliance's name"""
        if item.entity_id is None or (state := self.hass.states.get(item.entity_id)) is None:
            return item.name
        appliance = self._appliances.get(entry_id, ("", []))[0]
        name = str(state.attributes.get(ATTR_FRIENDLY_NAME) or item.name)
        return name.removeprefix(appliance).strip() or name

    def message(self, entry_id: str, item: MaintenanceItem) -> str:
        """What's due, said in the notification and on the list"""
        messages = translated(self.hass, MAINTENANCE_MESSAGES)
        name = self.name(entry_id, item)
        if item.every is None:
            return messages["lifespan"].format(item=name, value=f"{self.lifespan(item) or 0:g}")
        cycles = self.cycles(entry_id, item)
        return messages["cycle" if cycles == 1 else "cycles"].format(item=name, cycles=cycles)

    def lifespan(self, item: MaintenanceItem) -> float | None:
        """The life left of a part, as a percentage"""
        return self._percentage(self.hass.states.get(item.entity_id) if item.entity_id else None)

    @staticmethod
    def _percentage(state: State | None) -> float | None:
        if state is None or state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) != PERCENTAGE:
            return None
        try:
            return float(state.state)
        except ValueError:
            return None

    def cycles(self, entry_id: str, item: MaintenanceItem) -> int:
        return int(self._data["entries"].get(entry_id, {}).get("items", {}).get(item.key, {}).get("cycles", 0))

    def _snoozed(self, state: Mapping[str, Any]) -> bool:
        until = dt_util.parse_datetime(state["snoozed"]) if state.get("snoozed") else None
        return until is not None and until > dt_util.utcnow()

    def _settle(self, entry_id: str, item: MaintenanceItem, value: float | None = None) -> None:
        """A part with plenty of life again has been replaced, however that was done, so is due again only once it
        runs low once more, by the reading given or else the one there is now"""
        value = self.lifespan(item) if value is None else value
        if item.entity_id is not None and value is not None and value > LIFESPAN_DUE:
            state = self._state(entry_id, item.key)
            state.pop("acknowledged", None)
            state.pop("told", None)

    def due(self, entry_id: str, item: MaintenanceItem) -> bool:
        state = self._data["entries"].get(entry_id, {}).get("items", {}).get(item.key, {})
        if self._snoozed(state):
            return False
        if item.every is not None:
            return self.cycles(entry_id, item) >= item.every
        value = self.lifespan(item)
        return value is not None and value <= LIFESPAN_DUE and not state.get("acknowledged")

    def due_items(self) -> list[tuple[str, str, MaintenanceItem]]:
        """Every item due, with the entry id and name of its appliance"""
        due: list[tuple[str, str, MaintenanceItem]] = []
        for entry_id, (name, items) in self._appliances.items():
            for item in items:
                if self.due(entry_id, item):
                    due.append((entry_id, name, item))
        return due

    @callback
    def async_cycle_ended(self, entry_id: str) -> list[MaintenanceItem]:
        """One more cycle counted, returning the items it has made due, which are told of only the once"""
        items = self._appliances.get(entry_id, ("", []))[1]
        newly_due: list[MaintenanceItem] = []
        for item in items:
            state = self._state(entry_id, item.key)
            if item.every is not None:
                state["cycles"] = self.cycles(entry_id, item) + 1
            self._settle(entry_id, item)
            if not self.due(entry_id, item):
                # a count told again once it's due again, as after its cycles are changed, where a part is told
                # again only once it has read as replaced, not whenever its reading drops out
                if item.every is not None:
                    state.pop("told", None)
            elif not state.get("told"):
                state["told"] = True
                newly_due.append(item)
        if items:
            self._changed()
        return newly_due

    def _keys(self, entry_id: str, key: str | None) -> list[str]:
        return [item.key for item in self._appliances.get(entry_id, ("", []))[1] if key in (None, item.key)]

    async def async_done(self, entry_id: str, key: str | None = None, context: Context | None = None) -> None:
        """Maintenance done, the count starting again, and a part reset where its integration has a button for that,
        or else left alone until it's replaced. For all of an appliance's items, only parts that are due, so the
        life of the rest isn't thrown away"""
        for item_key in self._keys(entry_id, key):
            item = self.item(entry_id, item_key)
            # by its reading, so one put off is reset along with the rest
            low = item is not None and (value := self.lifespan(item)) is not None and value <= LIFESPAN_DUE
            if key is None and item is not None and item.entity_id is not None and not low:
                continue
            state = self._state(entry_id, item_key)
            state.pop("snoozed", None)
            state.pop("told", None)
            if item is not None and item.entity_id is None:
                state["cycles"] = 0
                continue
            if item is not None and item.reset_entity_id and self.hass.states.get(item.reset_entity_id) is not None:
                try:
                    await self.hass.services.async_call(
                        "button", "press", {ATTR_ENTITY_ID: item.reset_entity_id}, blocking=True, context=context
                    )
                except HomeAssistantError:
                    _LOGGER.exception("APPLIANCES Resetting %s failed", item.reset_entity_id)
            # until it reads as replaced, which a reset makes it do straight away
            state["acknowledged"] = True
        self._changed()

    @callback
    def async_snooze(self, entry_id: str, key: str | None = None, days: float = MAINTENANCE_SNOOZE_DAYS) -> None:
        """Put off, for one item or all an appliance has, after which it's due, and told of, again"""
        until = (dt_util.utcnow() + timedelta(days=days)).isoformat()
        for item_key in self._keys(entry_id, key):
            state = self._state(entry_id, item_key)
            state["snoozed"] = until
            state.pop("told", None)
        self._changed()

    @callback
    def async_set_cycles(self, entry_id: str, key: str | None, cycles: int) -> None:
        """The cycles since an item was last done, as known from before it was tracked here"""
        for item_key in self._keys(entry_id, key):
            item = self.item(entry_id, item_key)
            if item is None or item.every is None:
                continue
            state = self._state(entry_id, item_key)
            state["cycles"] = cycles
            state.pop("told", None)
            state.pop("snoozed", None)
        self._changed()

    @callback
    def _schedule_wake(self) -> None:
        """The list brought up to date as soon as something put off is due again"""
        if self._cancel_wake is not None:
            self._cancel_wake()
            self._cancel_wake = None
        now = dt_util.utcnow()
        times = [
            until
            for entry in self._data["entries"].values()
            for state in entry.get("items", {}).values()
            if state.get("snoozed") and (until := dt_util.parse_datetime(state["snoozed"])) is not None and until > now
        ]
        if times:
            self._cancel_wake = async_track_point_in_utc_time(self.hass, self._woken, min(times))

    @callback
    def _woken(self, now: datetime) -> None:
        self._cancel_wake = None
        self._changed()

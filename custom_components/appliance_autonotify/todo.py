"""The one to-do list of every appliance's maintenance that's due, held by the entry for automatic discovery: ticking
an item off says it's done, and deleting it puts it off for a month"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.todo import TodoItem, TodoItemStatus, TodoListEntity, TodoListEntityFeature

from .maintenance import DATA_MAINTENANCE, MaintenanceTracker

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

# the list only reflects what the tracker holds, with nothing to fetch
PARALLEL_UPDATES = 0

# between the entry id of the appliance and the key of its item, neither of which has it
UID_SEPARATOR = "|"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([MaintenanceList(hass.data[DATA_MAINTENANCE])])


class MaintenanceList(TodoListEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "maintenance"
    _attr_unique_id = "maintenance"
    _attr_supported_features = TodoListEntityFeature.UPDATE_TODO_ITEM | TodoListEntityFeature.DELETE_TODO_ITEM

    def __init__(self, tracker: MaintenanceTracker) -> None:
        self._tracker = tracker

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._tracker.async_add_listener(self.async_write_ha_state))

    @property
    def todo_items(self) -> list[TodoItem]:
        return [
            TodoItem(
                uid=f"{entry_id}{UID_SEPARATOR}{item.key}",
                summary=f"{name}: {self._tracker.name(entry_id, item)}",
                status=TodoItemStatus.NEEDS_ACTION,
                description=self._tracker.message(entry_id, item),
            )
            for entry_id, name, item in self._tracker.due_items()
        ]

    async def async_update_todo_item(self, item: TodoItem) -> None:
        if item.uid and item.status == TodoItemStatus.COMPLETED:
            entry_id, _, key = item.uid.partition(UID_SEPARATOR)
            await self._tracker.async_done(entry_id, key, self._context)

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        for uid in uids:
            entry_id, _, key = uid.partition(UID_SEPARATOR)
            self._tracker.async_snooze(entry_id, key)

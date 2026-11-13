"""What an appliance of an integration not yet tried on a real appliance does through its first cycles, every state
of every entity made use of as it comes, kept to be downloaded with its diagnostics and looked over"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

if TYPE_CHECKING:
    from collections.abc import Mapping

TRACE_STORE: Final[str] = f"{DOMAIN}.trace.{{entry_id}}"
TRACE_STORE_VERSION: Final[int] = 1
# cycles traced, enough to see one start and end and one more to see it wasn't a fluke
TRACE_CYCLES: Final[int] = 3
# changes kept, the oldest going first, should an appliance chatter through a long cycle
TRACE_LIMIT: Final[int] = 1000
TRACE_SAVE_DELAY: Final[float] = 10
# the role kept with the end of a cycle, as the watcher took it
ENDED: Final[str] = "ended"
FEEDBACK_ISSUE: Final[str] = "beta_feedback"
# where to say how it went, for an integration with no issue of its own
ISSUE_TRACKER: Final[str] = "https://github.com/rhizomatics/appliance_autonotify/issues"


class CycleTrace:
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, TRACE_STORE_VERSION, TRACE_STORE.format(entry_id=entry_id))
        self.events: list[dict[str, Any]] = []
        self.cycles_ended: int = 0
        self.cycles_finished: int = 0

    async def async_load(self) -> None:
        kept = await self._store.async_load() or {}
        self.events = list(kept.get("events") or [])
        self.cycles_ended = int(kept.get("cycles_ended") or 0)
        self.cycles_finished = int(kept.get("cycles_finished") or 0)

    @property
    def recording(self) -> bool:
        return self.cycles_ended < TRACE_CYCLES

    @callback
    def async_start(self, roles: Mapping[str, str]) -> CALLBACK_TYPE | None:
        """Keep every change of the entities given, by entity id with what each is made use of for"""
        if not self.recording or not roles:
            return None

        @callback
        def changed(event: Event[EventStateChangedData]) -> None:
            if not self.recording:
                return
            old, new = event.data["old_state"], event.data["new_state"]
            self._add({
                "role": roles.get(event.data["entity_id"], ""),
                "entity_id": event.data["entity_id"],
                "from": old.state if old is not None else None,
                "to": new.state if new is not None else None,
            })

        return async_track_state_change_event(self.hass, list(roles), changed)

    @callback
    def async_cycle_ended(self, finished: bool) -> bool:
        """The end of a cycle as the watcher took it, so it can be seen against what led up to it, saying whether
        it's the first to have finished"""
        if not self.recording:
            return False
        self.cycles_ended += 1
        self.cycles_finished += finished
        # kept after the change that ended it, which the watcher hears of first, and is told of as it does
        self.hass.loop.call_soon(self._add, {"role": ENDED, "finished": finished})
        return finished and self.cycles_finished == 1

    @callback
    def _add(self, event: dict[str, Any]) -> None:
        self.events.append({"at": dt_util.utcnow().isoformat()} | event)
        del self.events[:-TRACE_LIMIT]
        self._store.async_delay_save(self.as_dict, TRACE_SAVE_DELAY)

    def as_dict(self) -> dict[str, Any]:
        return {"cycles_ended": self.cycles_ended, "cycles_finished": self.cycles_finished, "events": list(self.events)}

    async def async_remove(self) -> None:
        await self._store.async_remove()


def feedback_issue_id(entry_id: str) -> str:
    return f"{FEEDBACK_ISSUE}_{entry_id}"


@callback
def async_ask_feedback(hass: HomeAssistant, entry_id: str, name: str, integration: str, url: str | None) -> None:
    """Ask how the first cycle went, as a repair, with where to say so"""
    ir.async_create_issue(
        hass,
        DOMAIN,
        feedback_issue_id(entry_id),
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        learn_more_url=url or ISSUE_TRACKER,
        translation_key=FEEDBACK_ISSUE,
        translation_placeholders={"name": name, "integration": integration},
    )


@callback
def async_forget_feedback(hass: HomeAssistant, entry_id: str) -> None:
    ir.async_delete_issue(hass, DOMAIN, feedback_issue_id(entry_id))

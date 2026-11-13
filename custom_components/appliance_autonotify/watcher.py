"""Watch one appliance, and notify as its cycle starts, progresses and ends"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import timedelta
from functools import partial
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_DEVICE_ID,
    CONF_TYPE,
    EVENT_HOMEASSISTANT_STOP,
    PERCENTAGE,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import CALLBACK_TYPE, Context, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.translation import async_translate_state
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import DurationConverter, PowerConverter

from .const import (
    ACTION_FINISHED,
    ACTION_MAINTAINED,
    ACTION_MAINTENANCE_LATER,
    ACTION_REMIND,
    ACTION_SWITCH_OFF,
    ACTION_TITLES,
    ACTION_TRACK_MAINTENANCE,
    ANDROID_BUTTONS,
    ANDROID_CHANNEL,
    CAVITY_TEMPERATURE_KEY,
    CONF_CUSTOM_TARGET,
    CONF_DASHBOARD,
    CONF_DELIVERIES,
    CONF_END_MESSAGE,
    CONF_END_TITLE,
    CONF_GRACE_PERIOD,
    CONF_LIVE_DETAIL,
    CONF_LIVE_TITLE,
    CONF_MAINTENANCE,
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
    CYCLE_KEPT_HOURS,
    CYCLE_KEY,
    CYCLE_SAVE_DELAY,
    CYCLE_SETTLE,
    CYCLE_STORE,
    CYCLE_STORE_VERSION,
    DEFAULT_END_MESSAGE,
    DEFAULT_GRACE_PERIOD,
    DEFAULT_ICON,
    DEFAULT_MIN_DURATION,
    DEFAULT_REMINDER_REPEATS,
    DEFAULT_SNOOZE,
    DEFAULT_START_MESSAGE,
    DEFAULT_THRESHOLD,
    DEFAULT_TITLE,
    DOMAIN,
    ENTITY_DOMAINS,
    FAST_PREHEAT_KEY,
    FAST_PREHEAT_PHASE,
    FINISH_TIME_KEY,
    LIVE_DEFAULTS,
    LIVE_DETAIL_PROGRAM,
    LIVE_DETAIL_PROGRAM_STATUS,
    LIVE_DETAIL_TIME,
    LIVE_PROGRAM_STATUS,
    LIVE_SETTLE,
    LIVE_TITLE,
    LIVE_TITLE_NAME,
    LIVE_TITLE_PROGRAM,
    MAINTENANCE_ACTION_TITLES,
    MOBILE_ACTION_EVENT,
    MOBILE_APP_PLATFORM,
    MOBILE_PUSH_TRANSPORT,
    NAME_PLACEHOLDER,
    OVEN_MESSAGE,
    PHASES_NOTIFIED,
    PREHEAT_FINISHED_KEYS,
    PREHEAT_MESSAGE,
    PREHEAT_PHASE,
    PREHEAT_SETTLE,
    PREHEATED_MESSAGE,
    PROGRAM_KEYS,
    PROGRAM_PLACEHOLDER,
    PROGRESS_CHIP,
    PROGRESS_FINAL,
    PROGRESS_FINAL_STEP,
    PROGRESS_KEY,
    PROGRESS_MESSAGE,
    PROGRESS_NOTIFY_STEP,
    PROGRESS_STEP,
    PROGRESS_TICK,
    REMAINING_TIME_KEY,
    STAGE_KEY,
    STAGES_FINISHED,
    STAGES_NONE,
    START_SETTLE,
    STATES_ABANDONED,
    STATES_ACTIVE,
    STATES_EVENT_ON,
    STATES_FINISHED,
    STATES_RUN,
    STATES_SETTLING,
    STUCK_MESSAGES,
    SUPERNOTIFY_DOMAIN,
    TARGET_TEMPERATURE_KEY,
    TEMPERATURE_STEP,
    TOTAL_TIME_KEY,
    TYPE_DISCOVERY,
    TYPE_ICONS,
    TYPE_VACUUM,
    VACUUM_BLIP,
    VACUUM_BLIP_KIND,
    VACUUM_BLIP_SETTLE,
    VACUUM_CLEANING,
    VACUUM_COMPLETE_KIND,
    VACUUM_COMPLETE_SETTLE,
    VACUUM_DONE,
    VACUUM_ERROR,
    VACUUM_HELD_KIND,
    VACUUM_HELD_SETTLE,
    VACUUM_JOB_LEAD,
    VACUUM_LIVE_DEFAULTS,
    VACUUM_MIDWAY_KIND,
    VACUUM_MIDWAY_SETTLE,
    VACUUM_PAUSED,
    VACUUM_PROGRAM_KEYS,
    VACUUM_PROGRESS_KEYS,
    VACUUM_RETURNING,
    VACUUM_SETTLE,
    VACUUM_STATUS_KEYS,
)
from .dashboards import dashboard_url
from .discovery import companions, cycle_entities, integration_name, is_cycle_entity, role_key
from .maintenance import DATA_MAINTENANCE, MaintenanceItem, MaintenanceTracker, maintenance_items, translated
from .platforms import GENERIC, PlatformProfile, profile_for
from .supernotify_api import deliveries_by_transport, supernotify_available
from .trace import CycleTrace, async_ask_feedback
from .words import name_type

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from datetime import datetime

    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


def _later(context: Context) -> Context:
    """A context of its own for what a timer sets off, leading back to whatever set the timer"""
    return Context(parent_id=context.id)


def _time(value: object) -> datetime | None:
    """A time as kept, or None where there's none"""
    return dt_util.parse_datetime(value) if isinstance(value, str) else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _seconds_to(due: datetime) -> float:
    """Seconds till a time, none if it's already past"""
    return max(0.0, (due - dt_util.utcnow()).total_seconds())


class ApplianceWatcher:
    """The notifications of a cycle, for subclasses that know when one starts and ends"""

    live_defaults: dict[str, str] = LIVE_DEFAULTS

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.name: str = entry.title
        self.tag: str = f"appliance_{entry.entry_id}"
        # the end has a tag of its own, so it can be cleared or told again without touching a Live Activity
        self.end_tag: str = f"{self.tag}_end"
        # the type of appliance, such as `washer`, from its name until the appliance itself says
        self.appliance_type: str | None = name_type(hass, self.name)
        self.icon: str = self._name_icon()
        self.cycle_entity_id: str | None = None
        # by translation key, whichever of those made use of the appliance has
        self.entity_ids: dict[str, str] = {}
        # the same, of the same appliance through another integration, for while the first can't be heard from
        self.fallback_cycle_entity_id: str | None = None
        self.fallback_ids: dict[str, str] = {}
        self.notify_start: bool = entry.options.get(CONF_NOTIFY_START, False)
        self.notify_end: bool = entry.options.get(CONF_NOTIFY_END, True)
        self.notify_progress: bool = entry.options.get(CONF_NOTIFY_PROGRESS, False)
        self.live_title: str = entry.options.get(CONF_LIVE_TITLE, self.live_defaults[CONF_LIVE_TITLE])
        self.live_detail: str = entry.options.get(CONF_LIVE_DETAIL, self.live_defaults[CONF_LIVE_DETAIL])
        # the program last known, since an appliance may no longer report one by the time its end is told
        self.last_program: str = ""
        # the program of the cycle just over, kept for its reminders, since an appliance may by then have gone back
        # to the program it starts on, as a Samsung dryer does
        self.program_kept: bool = False
        # whether phases are notified unless chosen otherwise, None for an appliance that reports none
        self.phase_default: bool | None = None
        self.notify_phase: bool = False
        self.running: bool = False
        # the progress last sent, rounded down to the step it was sent for
        self.last_progress_mark: int = 0
        # one notification at a time, so a progress update can't overtake the end and reopen the Live Activity
        self._sending: asyncio.Lock = asyncio.Lock()
        self.reminder: float = entry.options.get(CONF_REMINDER, 0)
        self.reminder_repeats: int = int(entry.options.get(CONF_REMINDER_REPEATS, DEFAULT_REMINDER_REPEATS))
        # the smart plug to switch off from the end notification, which only a power monitored appliance has
        self.switch_entity_id: str | None = None
        self._reminders_sent: int = 0
        self._cancel_reminder: CALLBACK_TYPE | None = None
        # the end of the cycle, waiting to see that the appliance doesn't carry on
        self._cancel_end: CALLBACK_TYPE | None = None
        # when the cycle under way started, not known of one already under way when first watched
        self.started_at: datetime | None = None
        # when the end waited for is due, and the next reminder of it, kept so neither is lost to a restart
        self._end_due: datetime | None = None
        self._reminder_due: datetime | None = None
        # the cycle as kept through a restart of Home Assistant: what was found from before it, what was last kept,
        # and what is to be written, None till anything has changed
        self._store: Store[dict[str, Any]] = Store(hass, CYCLE_STORE_VERSION, CYCLE_STORE.format(entry_id=entry.entry_id))
        self._restored: dict[str, Any] = {}
        self._kept: dict[str, Any] = {}
        self._written: dict[str, Any] | None = None
        # whether maintenance is tracked, None until it's been asked for or turned down
        self.maintenance: bool | None = entry.options.get(CONF_MAINTENANCE)
        # the items there are to track, whether or not they are, so tracking is only offered where there's something
        self.maintenance_items: list[MaintenanceItem] = []
        # tracking offered on the end notification of the cycle just over
        self._offering: bool = False
        # the integration the appliance comes through, and what it does, kept while that's yet to be tried
        self.profile: PlatformProfile = GENERIC
        # and that of each cycle state entity, from either integration for the same appliance
        self._cycle_profiles: dict[str, PlatformProfile] = {}
        self.trace: CycleTrace | None = None

    async def async_load(self) -> None:
        """What was kept of the cycle before Home Assistant restarted, unless too old to carry on from, as when it
        has been off for a day"""
        kept = await self._store.async_load() or {}
        saved_at = _time(kept.get("saved_at"))
        if saved_at is not None and (dt_util.utcnow() - saved_at).total_seconds() < CYCLE_KEPT_HOURS * 3600:
            self._restored = kept
            self._kept = {key: value for key, value in kept.items() if key != "saved_at"}
        # written straight away, rather than a moment later, as the appliance is unloaded or Home Assistant stops
        self.entry.async_on_unload(self._flush)
        self.entry.async_on_unload(self.hass.bus.async_listen(EVENT_HOMEASSISTANT_STOP, self._stopping))

    @callback
    def _restore(self) -> bool:
        """Carry on from what was kept before a restart, saying whether a cycle was under way"""
        kept = self._restored
        self.last_program = kept.get("program") or ""
        self.program_kept = bool(kept.get("program_kept"))
        self.started_at = _time(kept.get("started_at"))
        self._reminders_sent = int(kept.get("reminders_sent") or 0)
        self._offering = bool(kept.get("offering")) and self.maintenance is None
        if (due := _time(kept.get("reminder_due"))) is not None:
            # told straight away if it fell due while Home Assistant was off, once however long that was
            self._remind_at(due, Context())
        return bool(kept.get("running"))

    def _phase_data(self) -> dict[str, Any]:
        """How far the cycle has got, as only some kinds of appliance know"""
        return {}

    def _worth_keeping(self) -> bool:
        return self.running or self._end_due is not None or self._reminder_due is not None

    @callback
    def _save(self) -> None:
        """Keep the cycle through a restart, written a moment later so that changes close together are written once"""
        data: dict[str, Any] = {}
        if self._worth_keeping():
            data = {
                "running": self.running,
                "started_at": _iso(self.started_at),
                "program": self.last_program,
                "program_kept": self.program_kept,
                "end_due": _iso(self._end_due),
                "reminder_due": _iso(self._reminder_due),
                "reminders_sent": self._reminders_sent,
                # the offer to track maintenance, still made by the reminders of the end it was made on
                "offering": self._offering,
                "phase": self._phase_data(),
            }
        if data == self._kept:
            return
        self._kept = data
        # with when it was kept, to know whether it's too old to carry on from
        written = data | {"saved_at": dt_util.utcnow().isoformat()} if data else {}
        self._written = written
        self._store.async_delay_save(lambda: written, CYCLE_SAVE_DELAY)

    async def _flush(self) -> None:
        if self._written is not None:
            await self._store.async_save(self._written)

    async def _stopping(self, event: Event) -> None:
        await self._flush()

    @callback
    def async_start(self) -> None:
        raise NotImplementedError

    async def async_start_trace(self) -> None:
        """Keep what an appliance of an integration in beta does through its first cycles"""
        if not self.profile.beta:
            return
        trace = CycleTrace(self.hass, self.entry.entry_id)
        await trace.async_load()
        self.trace = trace
        if (unsubscribe := trace.async_start(self._traced_roles())) is not None:
            self.entry.async_on_unload(unsubscribe)

    def _traced_roles(self) -> dict[str, str]:
        """The entities made use of, by entity id, with what each is made use of for"""
        return {}

    @property
    def _tracker(self) -> MaintenanceTracker | None:
        return self.hass.data.get(DATA_MAINTENANCE)

    @callback
    def async_start_maintenance(self) -> None:
        """The items for the type of appliance, and those its integration reports the life of, tracked once asked for"""
        self.maintenance_items = maintenance_items(
            self.hass, self.appliance_type, self.entry.data.get(CONF_DEVICE_ID), self.entry.options
        )
        if self.maintenance:
            self._track_maintenance()

    @callback
    def _track_maintenance(self) -> None:
        tracker = self._tracker
        if tracker is None or not self.maintenance_items:
            return
        tracker.async_register(self.entry.entry_id, self.name, self.maintenance_items, self._part_due)
        self.entry.async_on_unload(partial(tracker.async_unregister, self.entry.entry_id))
        if not any(
            entry.data.get(CONF_TYPE) == TYPE_DISCOVERY and not entry.disabled_by
            for entry in self.hass.config_entries.async_entries(DOMAIN)
        ):
            _LOGGER.warning(
                "APPLIANCES Maintenance of %s is tracked, but without the Automatic discovery entry there's no list of it",
                self.name,
            )

    @callback
    def _part_due(self, item: MaintenanceItem) -> None:
        """A part fallen due between cycles, told of straight away"""
        if (tracker := self._tracker) is not None:
            self.entry.async_create_task(self.hass, self._tell_maintenance(tracker, item, Context()))

    @callback
    def async_listen_for_actions(self) -> None:
        """Answer the buttons on the end notification"""
        self.entry.async_on_unload(self.hass.bus.async_listen(MOBILE_ACTION_EVENT, self._action_pressed))
        self.entry.async_on_unload(self._stop_reminding)

    def _keep_running(self) -> None:
        self._end_due = None
        if self._cancel_end is not None:
            self._cancel_end()
            self._cancel_end = None

    @callback
    def _end_at(self, due: datetime, then: Callable[[Context, datetime], Coroutine[Any, Any, None]], context: Context) -> None:
        """Wait to see that the appliance doesn't carry on, till a time kept through a restart"""
        self._end_due = due
        self._cancel_end = async_call_later(self.hass, _seconds_to(due), partial(then, context))

    @callback
    def _end_waited(self) -> None:
        self._cancel_end = None
        self._end_due = None

    def _name_icon(self) -> str:
        return TYPE_ICONS.get(name_type(self.hass, self.name) or "", DEFAULT_ICON)

    @staticmethod
    def _mark(progress: int) -> int:
        """The progress rounded down to the step it's sent for"""
        return progress - progress % (PROGRESS_FINAL_STEP if progress >= PROGRESS_FINAL else PROGRESS_STEP)

    async def _progress_changed(self, event: Event[EventStateChangedData]) -> None:
        await self._progress_now(event.context)

    async def _progress_tick(self, now: datetime) -> None:
        await self._progress_now(Context())

    async def _progress_now(self, context: Context) -> None:
        progress = self._progress()
        if not self.running or progress is None:
            return
        mark = self._mark(progress)
        if mark <= self.last_progress_mark:
            return
        # the first reading only fills in the Live Activity, coming straight after the start notification, as do
        # the steps between those notified and the smaller ones towards the end
        step = PROGRESS_NOTIFY_STEP
        ordinary = self.notify_progress and mark // step > max(self.last_progress_mark, 0) // step
        self.last_progress_mark = mark
        live = supernotify_available(self.hass)
        if not live and not ordinary:
            return
        async with self._sending:
            if not self.running:
                # the cycle ended while this waited its turn
                return
            message = self._progress_message(progress)
            if live and not ordinary:
                # the bar already shows how far along it is, so there's room to say what it's doing
                message = self._phase() or message
            await self._tell(message, ordinary, context, resend=True)

    async def _started(self, context: Context) -> None:
        self.program_kept = False
        self.started_at = dt_util.utcnow()
        # the last cycle's reminders are no use once the next one is under way
        self._stop_reminding()
        self._save()
        async with self._sending:
            # resent, since to Supernotify a second cycle soon after the first is a repeat to be dropped
            await self._tell(self._text(CONF_START_MESSAGE, DEFAULT_START_MESSAGE), self.notify_start, context, resend=True)
            if supernotify_available(self.hass):
                # whatever comes next waits its turn, the first progress being only moments behind the start
                await asyncio.sleep(LIVE_SETTLE)

    async def _tell(self, message: str, ordinary: bool, context: Context, resend: bool = False) -> None:
        """Notify of a cycle under way, either everywhere or with no more than its Live Activity brought up to date"""
        # a Live Activity keeps the title it started with
        title = self._text(CONF_START_TITLE, DEFAULT_TITLE)
        if not supernotify_available(self.hass):
            if ordinary:
                await self._send_message(message, title, context)
        elif ordinary:
            # everywhere, opening or updating the Live Activity on phones as it goes
            await self._supernotify(
                message, title, context, resend=resend, extra_data=self._live_data(), actions=self._tap_actions()
            )
        else:
            data = self._live_data()
            title, message = self._live_title(title, message, timer="when" in data)
            # with nothing to hear, and nothing sent anywhere but to phones
            await self._supernotify(
                message,
                title,
                context,
                mobile_only=True,
                extra_data=data | {"silent": True, "alert_once": True},
                # iOS forgets where a tap goes unless told again on every update
                actions=self._tap_actions(),
            )

    def _live_title(self, title: str, message: str, timer: bool) -> tuple[str, str]:
        """The title of a quiet Live Activity update as chosen, and its message, which needn't say the program again"""
        if self.live_title == LIVE_TITLE_NAME:
            return title, message
        if timer:
            # with a timer there's no message on the iOS Lock Screen, so what it's doing goes in the title
            phase = self._title_phase()
        else:
            # with no timer the message is seen, so the title has only the program, where the message doesn't say it
            phase = self._program()
            if phase and phase in message:
                return title, message
        if not phase or phase in title:
            return title, message
        if message == phase and (progress := self._progress()) is not None:
            message = self._progress_message(progress)
        if self.live_title == LIVE_TITLE_PROGRAM:
            return phase, message
        return LIVE_TITLE.format(title=title, phase=phase), message

    async def _ended(self, finished: bool, context: Context) -> None:
        self.last_program = self._program() or self.last_program
        self.program_kept = True
        title = self._text(CONF_END_TITLE, DEFAULT_TITLE)
        message = self._text(CONF_END_MESSAGE, DEFAULT_END_MESSAGE)
        notify = finished and self.notify_end
        self._save()
        if self.trace is not None and self.trace.async_cycle_ended(finished):
            async_ask_feedback(
                self.hass,
                self.entry.entry_id,
                self.name,
                integration_name(self.hass, self.profile.platform),
                self.profile.issue_url,
            )
        await self._tell_ended(notify, title, message, context)
        if finished:
            await self._maintenance_due(context)

    async def _tell_ended(self, notify: bool, title: str, message: str, context: Context) -> None:
        async with self._sending:
            if not supernotify_available(self.hass):
                if notify:
                    await self._send_message(message, title, context)
                return
            # closing the Live Activity is not a notification in itself, so the end is told separately
            await self._supernotify(
                message,
                title,
                context,
                mobile_only=True,
                extra_data={"mobile_push_notification_tag": self.tag, "mobile_push_clear_notification": True},
            )
            if notify:
                tracker = self._tracker
                # offered once, so anyone who'd want it needn't go looking, and nobody's bothered who wouldn't
                self._offering = (
                    tracker is not None
                    and self.maintenance is None
                    and bool(self.maintenance_items)
                    and not tracker.offered(self.entry.entry_id)
                )
                # the same end message as the last cycle would otherwise be dropped as a duplicate
                await self._tell_end(context, resend=True)
                if tracker is not None and self._offering:
                    tracker.async_mark_offered(self.entry.entry_id)
                self._reminders_sent = 0
                if self.reminder:
                    self._remind_in(self.reminder, context)

    async def _maintenance_due(self, context: Context) -> None:
        """Another cycle counted, and each item it has made due told of, the once"""
        tracker = self._tracker
        if tracker is None or not tracker.tracked(self.entry.entry_id):
            return
        for item in tracker.async_cycle_ended(self.entry.entry_id):
            await self._tell_maintenance(tracker, item, context)

    def _maintenance_tag(self, item: MaintenanceItem) -> str:
        # short, a part's key being its entity id, and iOS keeping only 64 bytes of a tag
        return f"{self.tag}_maintenance_{hashlib.sha256(item.key.encode()).hexdigest()[:8]}"

    async def _tell_maintenance(self, tracker: MaintenanceTracker, item: MaintenanceItem, context: Context) -> None:
        message = tracker.message(self.entry.entry_id, item)
        if not supernotify_available(self.hass):
            await self._send_message(message, self.name, context)
            return
        titles = translated(self.hass, MAINTENANCE_ACTION_TITLES)
        actions = [
            {"action": f"{button}{self.entry.entry_id}_{item.key}", "title": titles[button]}
            for button in (ACTION_MAINTAINED, ACTION_MAINTENANCE_LATER)
        ]
        async with self._sending:
            await self._supernotify(
                message,
                self.name,
                context,
                resend=True,
                actions=actions + self._tap_actions(),
                extra_data={
                    "notification_icon": "mdi:wrench-clock",
                    "mobile_push_notification_tag": self._maintenance_tag(item),
                },
            )

    async def _maintenance_pressed(self, action: str, context: Context) -> bool:
        """The buttons of the notification of an item due, and the one offering to track maintenance at all"""
        if action == f"{ACTION_TRACK_MAINTENANCE}{self.entry.entry_id}":
            # once only, a press left on an old notification not undoing it being turned off since
            if self.entry.options.get(CONF_MAINTENANCE) is None:
                self.maintenance = True
                # nor offered again by its reminders
                self._offering = False
                # tracked from now without a reload, which would drop the reminders of the end just told
                self._track_maintenance()
                self.hass.config_entries.async_update_entry(
                    self.entry, options=dict(self.entry.options) | {CONF_MAINTENANCE: True}
                )
            return True
        tracker = self._tracker
        for button in (ACTION_MAINTAINED, ACTION_MAINTENANCE_LATER):
            prefix = f"{button}{self.entry.entry_id}_"
            if tracker is None or not action.startswith(prefix):
                continue
            item = tracker.item(self.entry.entry_id, action.removeprefix(prefix))
            if item is None:
                return True
            if button == ACTION_MAINTAINED:
                await tracker.async_done(self.entry.entry_id, item.key, context)
            else:
                tracker.async_snooze(self.entry.entry_id, item.key)
            await self._supernotify(
                self.name,
                self.name,
                context,
                mobile_only=True,
                extra_data={
                    "mobile_push_notification_tag": self._maintenance_tag(item),
                    "mobile_push_clear_notification": True,
                },
            )
            return True
        return False

    async def _tell_end(self, context: Context, resend: bool = False) -> None:
        """The end, with buttons to say the appliance has been seen to, to be reminded later, or to switch it off"""
        await self._supernotify(
            self._text(CONF_END_MESSAGE, DEFAULT_END_MESSAGE),
            self._text(CONF_END_TITLE, DEFAULT_TITLE),
            context,
            resend=resend,
            actions=self._end_actions() + self._tap_actions(),
            extra_data={"notification_icon": self.icon, "mobile_push_notification_tag": self.end_tag},
        )

    def _end_actions(self) -> list[dict[str, str]]:
        titles = ACTION_TITLES.get(self.hass.config.language.split("-")[0], ACTION_TITLES["en"])
        buttons = [ACTION_FINISHED, ACTION_REMIND] + ([ACTION_SWITCH_OFF] if self._switchable() else [])
        if self._offering and len(buttons) >= ANDROID_BUTTONS:
            # Android shows only 3, so in place of Remind Later on the one notification it's offered on
            buttons.remove(ACTION_REMIND)
        actions = [{"action": f"{button}{self.entry.entry_id}", "title": titles[button]} for button in buttons]
        if self._offering:
            track = translated(self.hass, MAINTENANCE_ACTION_TITLES)[ACTION_TRACK_MAINTENANCE]
            actions.append({"action": f"{ACTION_TRACK_MAINTENANCE}{self.entry.entry_id}", "title": track})
        return actions

    def _switchable(self) -> bool:
        """Whether there's a smart plug to switch off, one chosen and since removed not being offered"""
        return self.switch_entity_id is not None and self.hass.states.get(self.switch_entity_id) is not None

    def _snooze_minutes(self) -> int:
        return int(self.reminder or DEFAULT_SNOOZE)

    @callback
    def _remind_in(self, minutes: float, context: Context) -> None:
        self._remind_at(dt_util.utcnow() + timedelta(minutes=minutes), context)

    @callback
    def _remind_at(self, due: datetime, context: Context) -> None:
        self._stop_reminding()
        self._reminder_due = due
        self._cancel_reminder = async_call_later(self.hass, _seconds_to(due), partial(self._remind, context))
        self._save()

    @callback
    def _stop_reminding(self) -> None:
        self._reminder_due = None
        if self._cancel_reminder is not None:
            self._cancel_reminder()
            self._cancel_reminder = None

    async def _remind(self, context: Context, now: datetime) -> None:
        self._cancel_reminder = None
        self._reminder_due = None
        self._reminders_sent += 1
        # Supernotify would drop the same message again as a duplicate
        await self._tell_end(_later(context), resend=True)
        if self.reminder and self._reminders_sent < self.reminder_repeats:
            self._remind_in(self.reminder, context)
        self._save()

    async def _action_pressed(self, event: Event) -> None:
        action = str(event.data.get("action") or "")
        if await self._maintenance_pressed(action, event.context):
            return
        if action == f"{ACTION_FINISHED}{self.entry.entry_id}":
            self._stop_reminding()
            self._save()
            await self._supernotify(
                self._text(CONF_END_MESSAGE, DEFAULT_END_MESSAGE),
                self._text(CONF_END_TITLE, DEFAULT_TITLE),
                event.context,
                mobile_only=True,
                extra_data={"mobile_push_notification_tag": self.end_tag, "mobile_push_clear_notification": True},
            )
        elif action == f"{ACTION_REMIND}{self.entry.entry_id}":
            self._remind_in(self._snooze_minutes(), event.context)
        elif action == f"{ACTION_SWITCH_OFF}{self.entry.entry_id}" and self._switchable():
            if self.running:
                # a button left from the last cycle, pressed once the next one has started
                _LOGGER.warning("APPLIANCES %s is running again, so it was left switched on", self.name)
                return
            try:
                await self.hass.services.async_call(
                    "switch", "turn_off", {ATTR_ENTITY_ID: self.switch_entity_id}, blocking=True, context=event.context
                )
            except HomeAssistantError:
                _LOGGER.exception("APPLIANCES Switching off %s failed", self.name)

    def _text(self, key: str, default: str) -> str:
        text = str(self.entry.options.get(key) or default).replace(NAME_PLACEHOLDER, self.name)
        if PROGRAM_PLACEHOLDER not in text:
            return text
        if not self.program_kept:
            self.last_program = self._program() or self.last_program
        # closing up the gap left where there's no program to name
        return " ".join(text.replace(PROGRAM_PLACEHOLDER, self.last_program).split(" ")).strip()

    def _state(self, key: str) -> State | None:
        """The state of one of the appliance's entities, where it has the entity and its state is known, or failing
        that the same entity through another integration"""
        for ids in (self.entity_ids, self.fallback_ids):
            if (state := self._known(ids.get(key))) is not None:
                return state
        return None

    def _known(self, entity_id: str | None) -> State | None:
        state = self.hass.states.get(entity_id) if entity_id else None
        return None if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE) else state

    def _cycle_value(self, state: State | None) -> str | None:
        """A state of the cycle as every integration has it, by the integration whose state it is"""
        if state is None:
            return None
        return self._cycle_profiles.get(state.entity_id, self.profile).cycle_state(state.state)

    def _cycle_state(self) -> State | None:
        """The state of the cycle, from another integration for the same appliance while the first doesn't know it"""
        return self._known(self.cycle_entity_id) or self._known(self.fallback_cycle_entity_id)

    def _number(self, key: str) -> float | None:
        state = self._state(key)
        try:
            return float(state.state) if state is not None else None
        except ValueError:
            return None

    def _progress(self) -> int | None:
        progress = self._number(PROGRESS_KEY)
        return self._timed_progress() if progress is None else int(progress)

    def _progress_message(self, progress: int) -> str:
        return PROGRESS_MESSAGE.format(progress=progress)

    def _phase(self) -> str | None:
        """What the appliance is doing, to say alongside a bar that already shows how far along it is, as the Live
        Activity is chosen to show it, or else whichever of its status and program it reports"""
        program, stage = self._program(), self._stage()
        if self.live_detail == LIVE_DETAIL_PROGRAM:
            return program or stage
        if self.live_detail == LIVE_DETAIL_PROGRAM_STATUS and program and stage and stage != program:
            return LIVE_PROGRAM_STATUS.format(program=program, status=stage)
        return stage or program

    def _stage(self) -> str | None:
        """What the appliance is doing within its cycle, where its integration tells"""
        stage = self._state(STAGE_KEY)
        return self._translated(stage) if stage is not None and stage.state not in STAGES_NONE else None

    def _title_phase(self) -> str | None:
        """What goes beside the name in the title of a Live Activity with a timer: the program, where the stage is
        what the Live Activity says, or else whatever the Live Activity would say"""
        return self._program() if self._stage() is not None else self._phase()

    def _program_state(self) -> State | None:
        """The program under way, or failing that the one chosen, where the appliance reports either"""
        return next((state for key in PROGRAM_KEYS if (state := self._state(key)) is not None), None)

    def _program(self) -> str | None:
        """The program as Home Assistant shows it"""
        state = self._program_state()
        return self._translated(state) if state is not None else None

    def _seconds(self, key: str) -> float | None:
        """A duration the appliance reports, in whatever unit of time, in seconds"""
        state = self._state(key)
        value = self._number(key)
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, UnitOfTime.SECONDS) if state is not None else None
        if value is None or unit not in DurationConverter.VALID_UNITS:
            return None
        return DurationConverter.convert(value, unit, UnitOfTime.SECONDS)

    def _timed_progress(self) -> int | None:
        """How far along the cycle is by the time it has left of the time it takes, for an appliance that reports
        both but not its progress"""
        total = self._seconds(TOTAL_TIME_KEY)
        finish_time = self._finish_time()
        if not total or total <= 0 or finish_time is None:
            return None
        left = (finish_time - dt_util.utcnow()).total_seconds()
        return int(min(max(100 * (1 - left / total), 0), 100))

    def _finish_time(self) -> datetime | None:
        """When the cycle will finish, as the appliance says, or as long from now as it says is left"""
        state = self._state(FINISH_TIME_KEY)
        if state is not None and (finish_time := dt_util.parse_datetime(state.state)) is not None:
            return finish_time
        seconds = self._seconds(REMAINING_TIME_KEY)
        if seconds is None or seconds <= 0:
            return None
        # to the nearest minute, so the countdown stays put from one update to the next unless the appliance has
        # changed its mind
        finish = (dt_util.utcnow() + timedelta(seconds=seconds)).timestamp()
        return dt_util.utc_from_timestamp(round(finish / 60) * 60)

    def _translated(self, state: State) -> str:
        """A state as Home Assistant shows it, in its language"""
        entity = er.async_get(self.hass).async_get(state.entity_id)
        if entity is None:
            return state.state
        return async_translate_state(self.hass, state.state, state.domain, entity.platform, entity.translation_key, None)

    def _tap_actions(self) -> list[dict[str, str]]:
        """Where a tap on the notification goes, if a dashboard has been chosen, as a notification level action
        that Supernotify sends as `url` to iOS and `clickAction` to Android"""
        url = dashboard_url(self.hass, self.entry.options.get(CONF_DASHBOARD))
        return [{"level": "notification", "uri": url}] if url else []

    def _live_data(self) -> dict[str, Any]:
        """Live Activity fields for the mobile app, leaving out whatever the appliance isn't reporting"""
        data: dict[str, Any] = {
            "mobile_push_notification_tag": self.tag,
            "live_update": True,
            "notification_icon": self.icon,
            # Android only, iOS ignores them: a channel of its own so the start sounds, and kept when tapped as
            # a Live Activity is, since otherwise the next update brings it back as a new, sounding, notification
            "channel": ANDROID_CHANNEL,
            "importance": "high",
            "sticky": True,
        }
        progress = self._progress()
        if progress is not None:
            data["progress"] = progress
            data["progress_max"] = 100
        finish_time = self._finish_time()
        if finish_time is not None and self.live_detail == LIVE_DETAIL_TIME:
            data["chronometer"] = True
            data["when"] = int(finish_time.timestamp())
        elif progress is not None:
            # the Android status bar chip shows this in place of the time left, so only with no time to show, and
            # short, since a longer text leaves the chip with only its icon
            data["critical_text"] = PROGRESS_CHIP.format(progress=progress)
        return data

    async def _supernotify(
        self,
        message: str,
        title: str,
        context: Context,
        mobile_only: bool = False,
        resend: bool = False,
        extra_data: dict[str, Any] | None = None,
        actions: list[dict[str, str]] | None = None,
    ) -> None:
        data: dict[str, Any] = {"message": message, "title": title}
        if actions:
            data["actions"] = actions
        if resend:
            # Supernotify's duplicate check ignores digits, so would drop progress updates as repeats
            data["force_resend"] = True
        deliveries: list[str] = list(self.entry.options.get(CONF_DELIVERIES) or [])
        try:
            if mobile_only:
                mobile = (await deliveries_by_transport(self.hass, context)).get(MOBILE_PUSH_TRANSPORT, [])
                deliveries = [d for d in mobile if not deliveries or d in deliveries]
                if not deliveries:
                    _LOGGER.warning("APPLIANCES No mobile push delivery found for %s, Live Activity not updated", self.name)
                    return
                data["delivery_selection"] = "fixed"
                data["force_resend"] = True
            elif deliveries:
                data["delivery_selection"] = "explicit"
            if deliveries:
                data["delivery"] = deliveries
            for key in (CONF_TARGET, CONF_CUSTOM_TARGET):
                if value := self.entry.options.get(key):
                    data[key] = value
            if extra_data:
                data["extra_data"] = extra_data
            await self.hass.services.async_call(SUPERNOTIFY_DOMAIN, "notify", data, blocking=True, context=context)
        except HomeAssistantError:
            _LOGGER.exception("APPLIANCES Supernotify notification failed for %s", self.name)

    async def _send_message(self, message: str, title: str, context: Context) -> None:
        # with none chosen, every phone with the mobile app is told
        targets: list[str] = self.entry.options.get(CONF_TARGETS) or [
            entity.entity_id
            for entity in er.async_get(self.hass).entities.values()
            if entity.domain == "notify" and entity.platform == MOBILE_APP_PLATFORM and not entity.disabled
        ]
        if not targets:
            _LOGGER.warning("APPLIANCES Nothing to notify for %s, choose targets in its settings", self.name)
            return
        try:
            await self.hass.services.async_call(
                "notify",
                "send_message",
                {ATTR_ENTITY_ID: targets, "message": message, "title": title},
                blocking=True,
                context=context,
            )
        except HomeAssistantError:
            _LOGGER.exception("APPLIANCES Notification failed for %s", self.name)


class HomeConnectWatcher(ApplianceWatcher):
    """An appliance whose integration reports the state of its cycle"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        # an oven on its way up to heat, and one that has been there since it was last switched on
        self.preheating: bool = False
        self.preheated: bool = False
        # the temperature the Live Activity last showed, of an oven up to heat
        self.shown_temperature: float | None = None
        # the oven saying it's up to heat, waiting to see that it wasn't being switched off
        self._cancel_preheated: CALLBACK_TYPE | None = None
        # over by its stage while its cycle state still says it's running, so not a new cycle till that says it's over
        self.over_by_stage: bool = False
        # started, and waiting a moment for the program and stage to be reported before that's told
        self.starting: bool = False

    @callback
    def async_start(self) -> None:
        device_id: str = self.entry.data[CONF_DEVICE_ID]
        device = dr.async_get(self.hass).async_get(device_id)
        if device is not None:
            self.name = device.name_by_user or device.name or self.name
        programs: list[str] = []
        translation_keys: list[str] = []
        entity_registry = er.async_get(self.hass)
        for entity in er.async_entries_for_device(entity_registry, device_id):
            key = role_key(entity)
            if key is None or entity.disabled:
                continue
            translation_keys.append(entity.translation_key or "")
            if is_cycle_entity(entity):
                self.cycle_entity_id = entity.entity_id
            elif entity.domain in ENTITY_DOMAINS.get(key, ()):
                self.entity_ids[key] = entity.entity_id
                if key in PROGRAM_KEYS:
                    programs.extend((entity.capabilities or {}).get("options") or [])
        if self.cycle_entity_id is None:
            raise ConfigEntryNotReady(f"No cycle state entity found for {self.name}")
        # the same appliance through another integration, heard from only while this one can't be
        cycles = cycle_entities(self.hass)
        for companion in companions(self.hass, device_id, cycles):
            self.fallback_cycle_entity_id = self.fallback_cycle_entity_id or cycles[companion].entity_id
            for entity in er.async_entries_for_device(entity_registry, companion):
                key = role_key(entity)
                if key is not None and not entity.disabled and entity.domain in ENTITY_DOMAINS.get(key, ()):
                    self.fallback_ids.setdefault(key, entity.entity_id)
        # the type of appliance isn't kept anywhere to be read, but its programs are named for it, or failing that,
        # for an integration with several types, its entities
        cycle = entity_registry.async_get(self.cycle_entity_id)
        self.profile = profile_for(cycle.platform if cycle else None)
        for entity_id in (self.cycle_entity_id, self.fallback_cycle_entity_id):
            if entity_id and (registered := entity_registry.async_get(entity_id)) is not None:
                self._cycle_profiles[entity_id] = profile_for(registered.platform)
        if self.profile.stage_from_cycle:
            self.entity_ids.setdefault(STAGE_KEY, self.cycle_entity_id)
        # or failing that its model, as an integration names it for its type
        model = device.model if isinstance(device, dr.DeviceEntry) and device.model else ""
        appliance_type = self.profile.appliance_type(programs, translation_keys) or name_type(
            self.hass, model.replace("_", " ")
        )
        self.appliance_type = appliance_type or name_type(self.hass, self.name)
        self.icon = TYPE_ICONS.get(appliance_type or "", self._name_icon())
        # the one phase there is to know of is an oven warming up, Home Connect reporting none for anything else
        if CAVITY_TEMPERATURE_KEY in self.entity_ids and TARGET_TEMPERATURE_KEY in self.entity_ids:
            self.phase_default = appliance_type in PHASES_NOTIFIED
            self.notify_phase = self.entry.options.get(CONF_NOTIFY_PHASE, self.phase_default)

        # a cycle under way at startup still has its Live Activity closed when it ends
        state = self._cycle_state()
        self.running = self._cycle_value(state) in STATES_ACTIVE
        # and with no knowing whether its oven has been up to heat, it isn't taken to be warming up
        self.preheated = self.running
        phase: dict[str, Any] = self._restored.get("phase") or {}
        if self._restore():
            # still the cycle under way before Home Assistant restarted, whatever it has done since, so not started again
            self.running = True
            self.preheated = bool(phase.get("preheated", True))
            if (due := _time(self._restored.get("end_due"))) is not None:
                self._end_at(due, self._settled, Context())
        elif phase.get("over_by_stage") or phase.get("starting"):
            # over by its stage while still running, or yet to be told of as started
            self.running = False
            self.over_by_stage = bool(phase.get("over_by_stage"))

        cycle_entity_ids = [e for e in (self.cycle_entity_id, self.fallback_cycle_entity_id) if e]
        self.entry.async_on_unload(async_track_state_change_event(self.hass, cycle_entity_ids, self._cycle_changed))
        self.entry.async_on_unload(self._keep_running)
        self.entry.async_on_unload(self._forget_preheated)
        for keys, listener in (
            ((PROGRESS_KEY,), self._progress_changed),
            ((STAGE_KEY,), self._stage_changed),
            ((CAVITY_TEMPERATURE_KEY, TARGET_TEMPERATURE_KEY), self._temperature_changed),
            (PREHEAT_FINISHED_KEYS, self._preheat_finished),
        ):
            if entity_ids := [ids[key] for ids in (self.entity_ids, self.fallback_ids) for key in keys if key in ids]:
                self.entry.async_on_unload(async_track_state_change_event(self.hass, entity_ids, listener))
        if PROGRESS_KEY not in self.entity_ids and PROGRESS_KEY not in self.fallback_ids and TOTAL_TIME_KEY in self.entity_ids:
            # progress worked out from the time, which moves on with no change of the appliance's to say so
            self.entry.async_on_unload(
                async_track_time_interval(self.hass, self._progress_tick, timedelta(seconds=PROGRESS_TICK))
            )
        if self._restored and state is not None:
            # whatever it has done while Home Assistant was off, such as finishing, as if it were happening now
            value = self._cycle_value(state) or state.state
            self.entry.async_create_task(self.hass, self._cycle_is(value, Context()), eager_start=False)
        self._save()

    def _phase_data(self) -> dict[str, Any]:
        return {"preheated": self.preheated, "over_by_stage": self.over_by_stage, "starting": self.starting}

    def _traced_roles(self) -> dict[str, str]:
        roles = {entity_id: f"fallback_{key}" for key, entity_id in self.fallback_ids.items()}
        roles |= {entity_id: key for key, entity_id in self.entity_ids.items()}
        if self.fallback_cycle_entity_id:
            roles[self.fallback_cycle_entity_id] = f"fallback_{CYCLE_KEY}"
        if self.cycle_entity_id:
            roles[self.cycle_entity_id] = CYCLE_KEY
        return roles

    def _worth_keeping(self) -> bool:
        return super()._worth_keeping() or self.over_by_stage or self.starting

    def _temperatures(self) -> tuple[float, float] | None:
        """How hot the oven is and how hot it's to be, where both are known"""
        current, target = self._number(CAVITY_TEMPERATURE_KEY), self._number(TARGET_TEMPERATURE_KEY)
        return None if current is None or target is None or target <= 0 else (current, target)

    def _preheating(self) -> tuple[float, float] | None:
        """The temperatures of an oven still on its way up to heat, whatever program it's on"""
        temperatures = None if self.preheated or not self.running else self._temperatures()
        return None if temperatures is None or temperatures[0] >= temperatures[1] else temperatures

    def _progress(self) -> int | None:
        temperatures = self._preheating()
        if temperatures is None:
            return super()._progress()
        # an oven without a timer set has no progress to speak of, so the bar is how near it is to its temperature
        return max(0, int(temperatures[0] * 100 / temperatures[1]))

    def _preheat_message(self) -> str | None:
        temperatures = self._preheating()
        if temperatures is None:
            return None
        # a button on the oven for more of its elements to be used, which goes off by itself
        fast = self._state(FAST_PREHEAT_KEY)
        phase = FAST_PREHEAT_PHASE if fast is not None and fast.state == STATE_ON else PREHEAT_PHASE
        return PREHEAT_MESSAGE.format(
            phase=phase, current=f"{temperatures[0]:g}", target=f"{temperatures[1]:g}", unit=self._temperature_unit()
        )

    def _temperature_unit(self) -> str:
        cavity = self._state(CAVITY_TEMPERATURE_KEY)
        return cavity.attributes.get(ATTR_UNIT_OF_MEASUREMENT, "°") if cavity is not None else "°"

    def _progress_message(self, progress: int) -> str:
        return self._preheat_message() or super()._progress_message(progress)

    def _phase(self) -> str | None:
        if message := self._preheat_message():
            return message
        program, current = super()._phase(), self._number(CAVITY_TEMPERATURE_KEY)
        if program is None or current is None:
            return program
        return OVEN_MESSAGE.format(program=program, current=f"{current:g}", unit=self._temperature_unit())

    async def _temperature_changed(self, event: Event[EventStateChangedData]) -> None:
        if not self.running:
            return
        if self.preheated:
            await self._temperature_shown(event.context)
            return
        temperatures = self._temperatures()
        if temperatures is None:
            return
        if temperatures[0] < temperatures[1]:
            if not self.preheating:
                # whatever progress has been shown till now wasn't of this
                self.preheating = True
                self.last_progress_mark = -1
            await self._progress_changed(event)
        elif self.preheating:
            await self._preheated(event.context)
        else:
            # already hot when it was switched on
            self.preheated = True
            self._save()

    async def _preheat_finished(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data["new_state"]
        # only as it happens, since the sensor may still be telling of the last time the oven was heated
        if self.running and not self.preheated and new_state is not None and new_state.state in STATES_EVENT_ON:
            self._forget_preheated()
            self._cancel_preheated = async_call_later(self.hass, PREHEAT_SETTLE, partial(self._preheat_settled, event.context))

    async def _preheat_settled(self, context: Context, now: datetime) -> None:
        self._cancel_preheated = None
        if self.running and not self.preheated and self._cancel_end is None:
            await self._preheated(_later(context))

    @callback
    def _forget_preheated(self) -> None:
        if self._cancel_preheated is not None:
            self._cancel_preheated()
            self._cancel_preheated = None

    async def _temperature_shown(self, context: Context, always: bool = False) -> None:
        """Keep the Live Activity of an oven up to heat to its temperature, give or take a few degrees"""
        current = self._number(CAVITY_TEMPERATURE_KEY)
        shown = self.shown_temperature
        if not always and (current is None or (shown is not None and abs(current - shown) < TEMPERATURE_STEP)):
            return
        self.shown_temperature = current
        async with self._sending:
            if self.running and (message := self._phase()):
                await self._tell(message, False, context)

    async def _preheated(self, context: Context) -> None:
        """The oven is up to heat, and however its temperature then wanders isn't warming up again till it's been off"""
        self.preheated = True
        self.preheating = False
        self._save()
        # back to the progress of the program, for an oven with a timer set
        progress = self._progress()
        self.last_progress_mark = -1 if progress is None else self._mark(progress)
        message = PREHEATED_MESSAGE.replace(NAME_PLACEHOLDER, self.name)
        title = self._text(CONF_START_TITLE, DEFAULT_TITLE)
        async with self._sending:
            if not self.running or not self.notify_phase:
                pass
            elif supernotify_available(self.hass):
                # a notification of its own, so that it isn't lost as the Live Activity moves on
                await self._supernotify(
                    message,
                    title,
                    context,
                    resend=True,
                    extra_data={"notification_icon": self.icon},
                    actions=self._tap_actions(),
                )
            else:
                await self._send_message(message, title, context)
        # which goes straight on to what the oven is now doing
        await self._temperature_shown(context, always=True)

    async def _cycle_changed(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data["new_state"]
        if new_state is None:
            return
        if new_state.entity_id != self.cycle_entity_id and self._known(self.cycle_entity_id):
            # the other integration for the same appliance, while this one can be heard from, is only an echo
            return
        state: str = new_state.state
        _LOGGER.debug("APPLIANCES %s cycle state %s, running: %s", self.name, state, self.running)
        old_state = event.data["old_state"]
        if old_state is not None and old_state.state == state:
            # only its attributes changed, and a cycle over by its stage may still be running till it stops
            return
        if state in (STATE_UNKNOWN, STATE_UNAVAILABLE) and new_state.entity_id == self.cycle_entity_id:
            # can't be heard from, so the other integration for the appliance may already have told of its end
            await self._fallback_over(event.context)
            return
        await self._cycle_is(self._cycle_value(new_state) or state, event.context)

    async def _cycle_is(self, state: str, context: Context) -> None:
        if state in (*STATES_FINISHED, *STATES_SETTLING, *STATES_ABANDONED) and self.over_by_stage:
            self.over_by_stage = False
            self._save()
        if state in STATES_RUN and self.over_by_stage:
            # still running after its stage said it was over, a dryer carrying on as it is, door opened or not
            return
        if state in STATES_RUN:
            # back on within moments of going off, so the same cycle
            self._keep_running()
            self._save()
            if self.running or self.starting:
                return
            # a moment for the program and stage, which may come just after, to be what's told
            self.starting = True
            self._save()
            try:
                await asyncio.sleep(START_SETTLE)
            finally:
                self.starting = False
            cycle = self._cycle_state()
            if self.running or self._cycle_value(cycle) not in STATES_ACTIVE:
                # over, or started by another report, while it waited
                self._save()
                return
            self.running = True
            # unless it's hot already, from not long having been off
            temperatures = self._temperatures()
            self.preheated = temperatures is not None and temperatures[0] >= temperatures[1]
            self.preheating = self._preheating() is not None
            self.shown_temperature = None
            # with no progress yet to open the Live Activity with, the first reading is sent whatever it is, and
            # an oven already warm starts part of the way along
            progress = self._progress()
            self.last_progress_mark = -1 if progress is None else self._mark(progress)
            await self._started(context)
        elif not self.running:
            return
        elif state in STATES_SETTLING:
            if self._cancel_end is None:
                self._end_at(dt_util.utcnow() + timedelta(seconds=CYCLE_SETTLE), self._settled, context)
                self._save()
        elif state in STATES_FINISHED:
            await self._cycle_over(True, context)
        elif state in STATES_ABANDONED:
            await self._cycle_over(False, context)
        # anything else, such as `unavailable` while the vendor cloud is away, leaves the cycle as it was

    async def _fallback_over(self, context: Context) -> None:
        """The end of the cycle, if that's what the other integration for the appliance last said, since it went
        unheard while this one could be heard from. A start isn't taken from it, the cloud often lagging behind"""
        if not self.running:
            return
        stage = self._known(self.fallback_ids.get(STAGE_KEY))
        if stage is not None and stage.state in STAGES_FINISHED:
            await self._over_by_stage(context)
            return
        cycle = self._known(self.fallback_cycle_entity_id)
        value = self._cycle_value(cycle)
        if value in (*STATES_FINISHED, *STATES_SETTLING, *STATES_ABANDONED):
            await self._cycle_is(value, context)

    async def _stage_changed(self, event: Event[EventStateChangedData]) -> None:
        """The appliance moving on within its cycle, such as a dryer from drying to cooling"""
        new_state = event.data["new_state"]
        if not self.running or new_state is None or new_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        if new_state.entity_id != self.entity_ids.get(STAGE_KEY) and self._known(self.cycle_entity_id):
            # the other integration for the same appliance, while this one can be heard from, is only an echo
            return
        if new_state.entity_id in self._cycle_profiles and self._cycle_value(new_state) not in STATES_RUN:
            # a cycle state that's its stage too, which says no more than the cycle state once it isn't running
            return
        if new_state.state in STAGES_FINISHED:
            await self._over_by_stage(event.context)
            return
        if not supernotify_available(self.hass):
            return
        async with self._sending:
            if self.running and (message := self._phase()):
                await self._tell(message, False, event.context)

    async def _over_by_stage(self, context: Context) -> None:
        # done, though it may carry on as it is a while, a dryer tumbling its load now and then
        cycle = self._cycle_state()
        self.over_by_stage = self._cycle_value(cycle) in STATES_ACTIVE
        await self._cycle_over(True, context)

    async def _settled(self, context: Context, now: datetime) -> None:
        self._end_waited()
        await self._cycle_over(True, _later(context))

    async def _cycle_over(self, finished: bool, context: Context) -> None:
        self._keep_running()
        self._forget_preheated()
        self.running = False
        await self._ended(finished, context)


class PowerWatcher(ApplianceWatcher):
    """An appliance known only by the power it draws, running while that is above a threshold"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self.power_entity_id: str = entry.options[CONF_POWER_ENTITY]
        self.threshold: float = entry.options.get(CONF_THRESHOLD, DEFAULT_THRESHOLD)
        self.grace_period: float = entry.options.get(CONF_GRACE_PERIOD, DEFAULT_GRACE_PERIOD)
        self.min_duration: float = entry.options.get(CONF_MIN_DURATION, DEFAULT_MIN_DURATION)
        if entry.options.get(CONF_SWITCH_OFF_BUTTON, True):
            self.switch_entity_id = entry.options.get(CONF_SWITCH_ENTITY)
        # power drawn, but not yet for long enough to count as a cycle
        self.pending: bool = False
        self._drawn_for: float = 0
        self._drawing_since: datetime | None = None
        self._cancel_end: CALLBACK_TYPE | None = None
        self._cancel_start: CALLBACK_TYPE | None = None

    @callback
    def async_start(self) -> None:
        state = self.hass.states.get(self.power_entity_id)
        drawing = self._drawing(state)
        # a cycle under way at startup still has its Live Activity closed when it ends
        self.running = drawing is True
        if state is None and er.async_get(self.hass).async_get(self.power_entity_id) is None:
            # the power monitor is gone, so there's nothing to carry on with
            self._restored = {}
        phase: dict[str, Any] = self._restored.get("phase") or {}
        if self._restore():
            # still the cycle under way before Home Assistant restarted, though it may have stopped since
            self.running = True
            self._end_due = _time(self._restored.get("end_due"))
        elif phase.get("pending"):
            # not yet long enough to count as a cycle, with the time above the threshold counted through the restart
            # if it was drawing power all along, and otherwise only up to when it was last seen to
            self.pending = True
            self._drawn_for = float(phase.get("drawn_for") or 0)
            self._end_due = _time(self._restored.get("end_due"))
            if drawing is True:
                self._drawing_since = _time(phase.get("drawing_since")) or dt_util.utcnow()
        self.entry.async_on_unload(async_track_state_change_event(self.hass, self.power_entity_id, self._power_changed))
        self.entry.async_on_unload(self._keep_running)
        self.entry.async_on_unload(self._stop_counting)
        if drawing is True:
            # drawing power again, the same cycle or one not yet long enough to count, so with no end to wait for
            self._end_due = None
            if self.pending:
                self._count(Context())
        elif drawing is False and (self.running or self.pending):
            # at rest, so the end waited for before the restart, or one from now if it stopped while Home Assistant
            # was off, is due unless it draws power again first
            self._end_at(self._end_due or self._grace_end(), self._grace_over, Context())
        # with the power not yet known, whatever it says first decides, an end waited for being due when it was
        self._save()

    def _phase_data(self) -> dict[str, Any]:
        return {"pending": self.pending, "drawn_for": self._drawn_for, "drawing_since": _iso(self._drawing_since)}

    def _worth_keeping(self) -> bool:
        return super()._worth_keeping() or self.pending

    def _grace_end(self) -> datetime:
        return dt_util.utcnow() + timedelta(seconds=self.grace_period)

    def _drawing(self, state: State | None) -> bool | None:
        """Whether more power than the threshold is drawn, None if the power isn't known"""
        try:
            power = float(state.state) if state is not None else None
        except ValueError:
            power = None
        if state is None or power is None:
            return None
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        if unit in PowerConverter.VALID_UNITS:
            power = PowerConverter.convert(power, unit, UnitOfPower.WATT)
        return power > self.threshold

    async def _power_changed(self, event: Event[EventStateChangedData]) -> None:
        drawing = self._drawing(event.data["new_state"])
        _LOGGER.debug(
            "APPLIANCES %s drawing power %s, running: %s, pending: %s", self.name, drawing, self.running, self.pending
        )
        if drawing is None:
            # `unavailable` while the power monitor is away leaves the cycle as it was
            return
        if drawing:
            self._keep_running()
            if not self.running:
                if not self.pending:
                    self.pending = True
                    self._drawn_for = 0
                if self._drawing_since is None:
                    # time above the threshold adds up across drop outs, so one in the first minute doesn't start it over
                    self._drawing_since = dt_util.utcnow()
                    if self.min_duration - self._drawn_for > 0:
                        self._count(event.context)
                    else:
                        await self._confirmed(event.context)
        elif self.running or self.pending:
            self._stop_counting()
            if self._cancel_end is None:
                # from when it was due before a restart, if it went unseen from then till now
                self._end_at(self._end_due or self._grace_end(), self._grace_over, event.context)
        self._save()

    @callback
    def _count(self, context: Context) -> None:
        """Wait for the time above the threshold to be long enough for a cycle"""
        drawing_for = (dt_util.utcnow() - self._drawing_since).total_seconds() if self._drawing_since else 0
        remaining = self.min_duration - self._drawn_for - drawing_for
        self._cancel_start = async_call_later(self.hass, max(0.0, remaining), partial(self._long_enough, context))

    @callback
    def _keep_running(self) -> None:
        self._end_due = None
        if self._cancel_end is not None:
            self._cancel_end()
            self._cancel_end = None

    @callback
    def _stop_counting(self) -> None:
        """Add up the time above the threshold so far, while it isn't yet a cycle"""
        if self._drawing_since is not None:
            self._drawn_for += (dt_util.utcnow() - self._drawing_since).total_seconds()
            self._drawing_since = None
        if self._cancel_start is not None:
            self._cancel_start()
            self._cancel_start = None

    async def _long_enough(self, context: Context, now: datetime) -> None:
        self._cancel_start = None
        await self._confirmed(_later(context))

    async def _confirmed(self, context: Context) -> None:
        self.pending = False
        self._drawing_since = None
        self.running = True
        await self._started(context)

    async def _grace_over(self, context: Context, now: datetime) -> None:
        self._end_waited()
        if self.pending:
            _LOGGER.debug("APPLIANCES %s drew power for %.0fs, too short for a cycle", self.name, self._drawn_for)
            self.pending = False
            self._drawn_for = 0
            self._save()
            return
        self.running = False
        await self._ended(True, _later(context))


class VacuumWatcher(ApplianceWatcher):
    """A robot vacuum of any make, whose cleaning is the cycle, from setting off till it's back or stopped by itself"""

    live_defaults = VACUUM_LIVE_DEFAULTS

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._cancel_end: CALLBACK_TYPE | None = None
        # what it's waiting to see last, back on its dock or stuck
        self._pending: str | tuple[str, ...] | None = None
        # not yet known whether it was cleaning when Home Assistant started, until it says something telling
        self._unsure = False
        # how long it stays back on its dock before its cleaning is over, where its own progress doesn't say
        self.settle: float = entry.options.get(CONF_GRACE_PERIOD, VACUUM_SETTLE)
        # a percentage on the vacuum, other than its battery, has climbed to 100 during this cleaning, as its progress
        # does where its integration reports one, which a consumable's life left never does, or its own running sensor
        # has gone off
        self._complete = False
        # a running sensor of the vacuum's that came on as it set off and is on still, so its cleaning isn't over
        self._job: str | None = None
        self._runnings: list[str] = []
        self._set_off: datetime | None = None
        # its progress has dropped below 100 since it set off, so isn't what the cleaning before left
        self._progressing = False

    @callback
    def async_start(self) -> None:
        device_id: str = self.entry.data[CONF_DEVICE_ID]
        device = dr.async_get(self.hass).async_get(device_id)
        if device is not None:
            self.name = device.name_by_user or device.name or self.name
        self.cycle_entity_id = next(
            (e.entity_id for e in er.async_entries_for_device(er.async_get(self.hass), device_id) if e.domain == TYPE_VACUUM),
            None,
        )
        if self.cycle_entity_id is None:
            raise ConfigEntryNotReady(f"No vacuum entity found for {self.name}")
        self.appliance_type = "cleaning_robot"
        self.icon = TYPE_ICONS[self.appliance_type]
        # a cleaning under way at startup still has its Live Activity closed when it ends
        state = self.hass.states.get(self.cycle_entity_id)
        self.running = state is not None and state.state not in (*VACUUM_DONE, VACUUM_ERROR, STATE_UNAVAILABLE, STATE_UNKNOWN)
        # with nothing to go by yet, or an error that some integrations report again on reconnecting, whatever it says
        # next tells whether a cleaning was under way
        self._unsure = state is None or state.state in (VACUUM_ERROR, STATE_UNAVAILABLE, STATE_UNKNOWN)
        self.entry.async_on_unload(async_track_state_change_event(self.hass, self.cycle_entity_id, self._activity_changed))
        entities = er.async_entries_for_device(er.async_get(self.hass), device_id)
        percentages = [
            e.entity_id
            for e in entities
            if e.domain == "sensor"
            and e.unit_of_measurement == PERCENTAGE
            and (e.device_class or e.original_device_class) != SensorDeviceClass.BATTERY
        ]
        if percentages:
            self.entry.async_on_unload(async_track_state_change_event(self.hass, percentages, self._percentage_changed))
        self._runnings = [
            e.entity_id
            for e in entities
            if e.domain == "binary_sensor" and (e.device_class or e.original_device_class) == BinarySensorDeviceClass.RUNNING
        ]
        if self._runnings:
            self.entry.async_on_unload(async_track_state_change_event(self.hass, self._runnings, self._running_changed))
            if self.running:
                self._job = self._running_now(None)
        for key, domain, keys in (
            (STAGE_KEY, "sensor", VACUUM_STATUS_KEYS),
            (PROGRAM_KEYS[-1], "select", VACUUM_PROGRAM_KEYS),
            (PROGRESS_KEY, "sensor", VACUUM_PROGRESS_KEYS),
        ):
            if found := next(
                (e.entity_id for e in entities if e.domain == domain and not e.disabled and e.translation_key in keys), None
            ):
                self.entity_ids[key] = found
        if STAGE_KEY in self.entity_ids:
            self.entry.async_on_unload(
                async_track_state_change_event(self.hass, self.entity_ids[STAGE_KEY], self._status_changed)
            )
        self.entry.async_on_unload(self._keep_running)
        if self._restore():
            self._resume(state)
        if self.running:
            # cleaning since before Home Assistant started, with whatever progress it has
            self._progressing = (progress := self._number(PROGRESS_KEY)) is not None and progress < 100
        self._save()

    @callback
    def _resume(self, state: State | None) -> None:
        """Carry on with the cleaning under way before Home Assistant restarted, without telling of it as started, and
        with whatever end it was waiting for, unless it has set off again since"""
        self.running = True
        self._unsure = False
        phase: dict[str, Any] = self._restored.get("phase") or {}
        self._complete = bool(phase.get("complete"))
        self._set_off = _time(phase.get("set_off"))
        self._job = phase.get("job") if phase.get("job") in self._runnings else None
        job = self._known(self._job)
        if job is not None and job.state != STATE_ON:
            # done by its own account while Home Assistant was off
            self._job = None
            self._complete = True
        waiting = phase.get("waiting")
        kind = tuple(waiting) if isinstance(waiting, list) else waiting
        due = _time(self._restored.get("end_due"))
        activity = state.state if state is not None else None
        context = Context()
        if kind is not None and due is not None and self._still_waiting(kind, activity):
            self._wait_till(self._stuck_for_good if kind == VACUUM_ERROR else self._settled, kind, context, due)
        elif activity == VACUUM_ERROR:
            self._wait(self._stuck_for_good, VACUUM_ERROR, context)
        elif activity in VACUUM_DONE:
            # back on its dock while Home Assistant was off, with no knowing how it went back
            if self._job is not None:
                self._wait(self._settled, VACUUM_HELD_KIND, context, VACUUM_HELD_SETTLE)
            elif self._complete:
                self._wait(self._settled, VACUUM_COMPLETE_KIND, context, VACUUM_COMPLETE_SETTLE)
            else:
                self._wait(self._settled, VACUUM_DONE, context, self.settle)
        # cleaning, paused or on its way back is the same cleaning, with nothing yet to wait for

    @staticmethod
    def _still_waiting(kind: str | tuple[str, ...], activity: str | None) -> bool:
        """Whether the vacuum is where it was while waiting for the end, or not yet heard from, as it would be if
        Home Assistant hadn't restarted"""
        if activity in (None, STATE_UNAVAILABLE, STATE_UNKNOWN):
            return True
        if kind == VACUUM_ERROR:
            return activity == VACUUM_ERROR
        # an error back on its dock is for its own app to tell, and paused there isn't setting off again
        return activity in (*VACUUM_DONE, VACUUM_ERROR) or (activity == VACUUM_PAUSED and kind != VACUUM_BLIP_KIND)

    def _phase_data(self) -> dict[str, Any]:
        return {"waiting": self._pending, "complete": self._complete, "job": self._job, "set_off": _iso(self._set_off)}

    async def _status_changed(self, event: Event[EventStateChangedData]) -> None:
        """The vacuum moving on within its cleaning, such as from sweeping to relocating"""
        new_state = event.data["new_state"]
        if not self.running or new_state is None or new_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        await self._tell_status(event.context)

    async def _tell_status(self, context: Context) -> None:
        if not supernotify_available(self.hass):
            return
        async with self._sending:
            if self.running and (message := self._phase()):
                # resent, since it often goes back to what it said before, sweeping again after relocating
                await self._tell(message, False, context, resend=True)

    def _running_now(self, since: datetime | None) -> str | None:
        """Whichever of its running sensors is on as it sets off, having come on with it where that's known"""
        for entity_id in self._runnings:
            state = self.hass.states.get(entity_id)
            if (
                state is not None
                and state.state == STATE_ON
                and (since is None or (since - state.last_changed).total_seconds() <= VACUUM_JOB_LEAD)
            ):
                return entity_id
        return None

    async def _running_changed(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data["new_state"]
        if not self.running or new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        entity_id = event.data["entity_id"]
        if new_state.state == STATE_ON:
            if (
                self._job is None
                and self._set_off is not None
                and (new_state.last_changed - self._set_off).total_seconds() <= VACUUM_JOB_LEAD
            ):
                self._job = entity_id
                self._save()
            return
        if entity_id != self._job:
            return
        _LOGGER.debug("APPLIANCES %s vacuum %s went off", self.name, entity_id)
        self._job = None
        self._complete = True
        activity = self._known(self.cycle_entity_id)
        if activity is not None and activity.state in VACUUM_DONE:
            # already back, and now done by its own account
            self._wait(self._settled, VACUUM_COMPLETE_KIND, event.context, VACUUM_COMPLETE_SETTLE)
        self._save()

    async def _percentage_changed(self, event: Event[EventStateChangedData]) -> None:
        new_state, old_state = event.data["new_state"], event.data["old_state"]
        try:
            value = float(new_state.state) if new_state is not None else None
            before = float(old_state.state) if old_state is not None else None
        except ValueError:
            return
        if value is None or not self.running:
            return
        if value < 100:
            self._complete = False
            if event.data["entity_id"] == self.entity_ids.get(PROGRESS_KEY):
                self._progressing = True
        elif before is not None and before < 100 and not self._complete:
            _LOGGER.debug("APPLIANCES %s vacuum %s reached 100%%", self.name, event.data["entity_id"])
            self._complete = True
            if self._pending in (VACUUM_DONE, VACUUM_MIDWAY_KIND):
                # already back, and now done by its own account
                self._wait(self._settled, VACUUM_COMPLETE_KIND, event.context, VACUUM_COMPLETE_SETTLE)
        self._save()
        if event.data["entity_id"] == self.entity_ids.get(PROGRESS_KEY):
            await self._progress_changed(event)

    def _progress(self) -> int | None:
        """Its progress, once it's no longer the 100 the cleaning before left"""
        return super()._progress() if self._progressing else None

    @callback
    def _keep_running(self) -> None:
        self._pending = None
        self._end_due = None
        if self._cancel_end is not None:
            self._cancel_end()
            self._cancel_end = None

    async def _activity_changed(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data["new_state"]
        if new_state is None:
            return
        state: str = new_state.state
        _LOGGER.debug("APPLIANCES %s vacuum %s, running: %s", self.name, state, self.running)
        if state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            # away with the vendor cloud, which changes nothing
            return
        if self._unsure and state != VACUUM_ERROR:
            self._unsure = False
            if not self.running and state in (VACUUM_CLEANING, VACUUM_PAUSED, VACUUM_RETURNING):
                # cleaning since before Home Assistant started, so already told, and its end still to tell
                self.running = True
                self._job = self._running_now(None)
                self._save()
                return
        if not self.running:
            if state == VACUUM_CLEANING:
                self.running = True
                self._complete = False
                self._progressing = False
                self.last_progress_mark = -1
                self._set_off = new_state.last_changed
                self._job = self._running_now(self._set_off)
                await self._started(event.context)
                # already sweeping, most likely, by the time it's said to be cleaning
                await self._tell_status(event.context)
            return
        old_state = event.data["old_state"]
        if state in VACUUM_DONE:
            if self._job is not None:
                # back, but with its cleaning not over by its own account, as when it recharges to carry on
                if self._pending != VACUUM_HELD_KIND:
                    self._wait(self._settled, VACUUM_HELD_KIND, event.context, VACUUM_HELD_SETTLE)
            elif self._complete:
                # back with its cleaning done by its own account, so nothing to set off again for
                if self._pending != VACUUM_COMPLETE_KIND:
                    self._wait(self._settled, VACUUM_COMPLETE_KIND, event.context, VACUUM_COMPLETE_SETTLE)
            elif old_state is not None and old_state.state == VACUUM_CLEANING:
                if (new_state.last_changed - old_state.last_changed).total_seconds() < VACUUM_BLIP:
                    # back within a moment of setting off, which some integrations report as a vacuum leaves its dock
                    # and then keep to while it cleans, so only believed if nothing more is heard for a long while
                    if self._pending is None:
                        self._wait(self._settled, VACUUM_BLIP_KIND, event.context, VACUUM_BLIP_SETTLE)
                elif self._pending not in (VACUUM_DONE, VACUUM_MIDWAY_KIND):
                    # straight back from cleaning, without saying it was on its way, as when it washes its mop or
                    # fills its tank part way through, so given longer to set off again
                    self._wait(self._settled, VACUUM_MIDWAY_KIND, event.context, VACUUM_MIDWAY_SETTLE)
            elif self._pending not in (VACUUM_DONE, VACUUM_MIDWAY_KIND):
                # over only once it has stayed back
                self._wait(self._settled, VACUUM_DONE, event.context, self.settle)
        elif state == VACUUM_ERROR:
            # stuck only if it stays so, since some integrations report a past error again on reconnecting, while
            # the vacuum carries on, and an error once back on its dock is for its own app to tell
            if self._pending is None:
                self._wait(self._stuck_for_good, VACUUM_ERROR, event.context)
        elif state == VACUUM_PAUSED and self._pending in (
            VACUUM_DONE,
            VACUUM_MIDWAY_KIND,
            VACUUM_COMPLETE_KIND,
            VACUUM_HELD_KIND,
        ):
            # paused on its dock, which some integrations report once one is back, isn't setting off again
            return
        else:
            # cleaning, paused or on its way back is the same cleaning
            self._keep_running()
            self._save()

    @callback
    def _wait(
        self,
        then: Callable[[Context, datetime], Coroutine[Any, Any, None]],
        kind: str | tuple[str, ...],
        context: Context,
        delay: float = VACUUM_SETTLE,
    ) -> None:
        self._wait_till(then, kind, context, dt_util.utcnow() + timedelta(seconds=delay))

    @callback
    def _wait_till(
        self,
        then: Callable[[Context, datetime], Coroutine[Any, Any, None]],
        kind: str | tuple[str, ...],
        context: Context,
        due: datetime,
    ) -> None:
        self._keep_running()
        self._pending = kind
        self._end_at(due, then, context)
        self._save()

    async def _settled(self, context: Context, now: datetime) -> None:
        self._end_waited()
        self._pending = None
        self.running = False
        await self._ended(True, _later(context))

    async def _stuck_for_good(self, context: Context, now: datetime) -> None:
        # stopped where it is, so no end to tell, only that it can't go on without someone
        self._end_waited()
        self._pending = None
        self.running = False
        await self._ended(False, _later(context))
        await self._stuck(_later(context))

    async def _stuck(self, context: Context) -> None:
        stuck = STUCK_MESSAGES.get(self.hass.config.language.split("-")[0], STUCK_MESSAGES["en"])
        message = stuck.replace(NAME_PLACEHOLDER, self.name)
        title = self._text(CONF_START_TITLE, DEFAULT_TITLE)
        async with self._sending:
            if supernotify_available(self.hass):
                await self._supernotify(
                    message,
                    title,
                    context,
                    resend=True,
                    extra_data={"notification_icon": self.icon},
                    actions=self._tap_actions(),
                )
            else:
                await self._send_message(message, title, context)

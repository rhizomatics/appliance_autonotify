"""Constants for Appliance Auto Notify"""

from typing import Final

DOMAIN: Final[str] = "appliance_autonotify"
SUPERNOTIFY_DOMAIN: Final[str] = "supernotify"

CONF_START_TITLE: Final[str] = "start_title"
CONF_START_MESSAGE: Final[str] = "start_message"
CONF_END_TITLE: Final[str] = "end_title"
CONF_END_MESSAGE: Final[str] = "end_message"
# notify entities, used only without Supernotify
CONF_TARGETS: Final[str] = "targets"
# as the `target` and `custom_target` of supernotify.notify
CONF_TARGET: Final[str] = "target"
CONF_CUSTOM_TARGET: Final[str] = "custom_target"
CONF_DELIVERIES: Final[str] = "deliveries"
# whether progress is told with ordinary notifications, the Live Activity is kept up to date regardless
CONF_NOTIFY_PROGRESS: Final[str] = "notify_progress"
# whether the start and the end are told with ordinary notifications, the Live Activity is opened and closed regardless
CONF_NOTIFY_START: Final[str] = "notify_start"
CONF_NOTIFY_END: Final[str] = "notify_end"
# whether the end of a phase, such as an oven getting up to heat, is told with an ordinary notification
CONF_NOTIFY_PHASE: Final[str] = "notify_phase"
# what the title of a Live Activity names, the program going beside the name unless chosen otherwise, since it's
# where the program shows on the iOS Lock Screen once a timer has taken the message's place
CONF_LIVE_TITLE: Final[str] = "live_title"
LIVE_TITLE_NAME_PROGRAM: Final[str] = "name_program"
LIVE_TITLE_PROGRAM: Final[str] = "program"
LIVE_TITLE_NAME: Final[str] = "name"
LIVE_TITLES: Final[tuple[str, ...]] = (LIVE_TITLE_NAME_PROGRAM, LIVE_TITLE_PROGRAM, LIVE_TITLE_NAME)
# what a Live Activity shows in place of its message, the time left where the appliance reports a finish time, or
# the program, for an appliance whose program is always the same and so not worth the title, or its status, what it's
# doing within its cycle, or both of those
CONF_LIVE_DETAIL: Final[str] = "live_detail"
LIVE_DETAIL_TIME: Final[str] = "time_remaining"
LIVE_DETAIL_PROGRAM: Final[str] = "program"
LIVE_DETAIL_STATUS: Final[str] = "status"
LIVE_DETAIL_PROGRAM_STATUS: Final[str] = "program_status"
LIVE_DETAILS: Final[tuple[str, ...]] = (LIVE_DETAIL_TIME, LIVE_DETAIL_PROGRAM, LIVE_DETAIL_STATUS, LIVE_DETAIL_PROGRAM_STATUS)
# a robot vacuum has no time left to show
VACUUM_LIVE_DETAILS: Final[tuple[str, ...]] = (LIVE_DETAIL_PROGRAM_STATUS, LIVE_DETAIL_STATUS, LIVE_DETAIL_PROGRAM)
# the title and what's shown unless chosen otherwise, a vacuum with no timer saying both its cleaning mode and what
# it's doing in its message, so needing no more than its name for a title
LIVE_DEFAULTS: Final[dict[str, str]] = {CONF_LIVE_TITLE: LIVE_TITLE_NAME_PROGRAM, CONF_LIVE_DETAIL: LIVE_DETAIL_TIME}
VACUUM_LIVE_DEFAULTS: Final[dict[str, str]] = {
    CONF_LIVE_TITLE: LIVE_TITLE_NAME,
    CONF_LIVE_DETAIL: LIVE_DETAIL_PROGRAM_STATUS,
}
# the switch the title choice took over from, off being the name only
CONF_PROGRAM_IN_TITLE: Final[str] = "program_in_title"
# path of the dashboard opened by a tap on a notification, the app is opened where it was last if there's none
CONF_DASHBOARD: Final[str] = "dashboard"
# whether a dashboard named for the appliance has been looked for, which is done once, as it's first set up, so
# whatever is chosen after is left alone
CONF_DASHBOARD_FOUND: Final[str] = "dashboard_found"
LOVELACE_DOMAIN: Final[str] = "lovelace"
# the dashboard Home Assistant starts with has no path of its own in the list of them
DEFAULT_DASHBOARD: Final[str] = "lovelace"
DEFAULT_DASHBOARD_TITLE: Final[str] = "Overview"
# the one entry that isn't an appliance, holding whether appliances found are set up without asking
TYPE_DISCOVERY: Final[str] = "discovery"
CONF_AUTO_DISCOVER: Final[str] = "auto_discover"
# an appliance with no integration of its own, known only by the power it draws
TYPE_POWER: Final[str] = "power"
CONF_POWER_ENTITY: Final[str] = "power_entity"
# a robot vacuum, of any make, whose cleaning is a cycle
TYPE_VACUUM: Final[str] = "vacuum"
CONF_THRESHOLD: Final[str] = "threshold"
CONF_GRACE_PERIOD: Final[str] = "grace_period"
CONF_MIN_DURATION: Final[str] = "min_duration"
# the smart plug the appliance is on, offered as a button to switch off once it has finished
CONF_SWITCH_ENTITY: Final[str] = "switch_entity"
# whether that button is offered, for a plug chosen but better left on
CONF_SWITCH_OFF_BUTTON: Final[str] = "switch_off_button"
# watts above which the appliance is running
DEFAULT_THRESHOLD: Final[float] = 1
# seconds at or below the threshold before the cycle is over, so short drop outs are ignored
DEFAULT_GRACE_PERIOD: Final[float] = 60
# seconds above the threshold before it counts as a cycle, so a door opened or a button pressed isn't one
DEFAULT_MIN_DURATION: Final[float] = 0

# English only for the MVP
DISCOVERY_TITLE: Final[str] = "Automatic discovery"
NAME_PLACEHOLDER: Final[str] = "{name}"
# the program under way, as Home Assistant shows it, and nothing at all for an appliance that reports none
PROGRAM_PLACEHOLDER: Final[str] = "{program}"
DEFAULT_TITLE: Final[str] = "{name}"
DEFAULT_START_MESSAGE: Final[str] = "{name} started"
DEFAULT_END_MESSAGE: Final[str] = "{name} is finished"
PROGRESS_MESSAGE: Final[str] = "{progress}% complete"

# minutes after which the end is told again, for as long as nobody says the appliance has been seen to
CONF_REMINDER: Final[str] = "reminder"
# how many times it's told again
CONF_REMINDER_REPEATS: Final[str] = "reminder_repeats"
DEFAULT_REMINDER_REPEATS: Final[int] = 3
# minutes for Remind Later, when no reminder is set
DEFAULT_SNOOZE: Final[int] = 30
# buttons on the end notification, each followed by the entry id of the appliance
ACTION_FINISHED: Final[str] = "APPLIANCE_FINISHED_"
ACTION_REMIND: Final[str] = "APPLIANCE_REMIND_"
ACTION_SWITCH_OFF: Final[str] = "APPLIANCE_SWITCH_OFF_"
# by the language of Home Assistant, English for any other
ACTION_TITLES: Final[dict[str, dict[str, str]]] = {
    "en": {ACTION_FINISHED: "Finished", ACTION_REMIND: "Remind Later", ACTION_SWITCH_OFF: "Switch Off"},
    "it": {ACTION_FINISHED: "Finito", ACTION_REMIND: "Ricordamelo dopo", ACTION_SWITCH_OFF: "Spegni presa"},
}
MOBILE_ACTION_EVENT: Final[str] = "mobile_app_notification_action"
# action buttons Android shows on a notification, any after those being left out
ANDROID_BUTTONS: Final[int] = 3

# whether maintenance is tracked for the appliance, unset until it's been asked for or turned down, so it's offered
# once, on the first end notification, rather than left for someone to go looking for
CONF_MAINTENANCE: Final[str] = "maintenance"
# the cycles between each item of maintenance, by item, as `maintenance_drum_clean`, 0 leaving the item out
CONF_MAINTENANCE_PREFIX: Final[str] = "maintenance_"
# the items each type of appliance starts with, and how many cycles apart, generous since vendors are keen to sell
# cleaning tablets and spares, all to be changed or taken out in its settings
MAINTENANCE_ITEMS: Final[dict[str, dict[str, int]]] = {
    "washer": {"drum_clean": 30, "filter": 50},
    "washer_dryer": {"drum_clean": 30, "filter": 50, "lint_filter": 20},
    "dishwasher": {"filter": 30, "machine_clean": 60},
    "dryer": {"condenser": 30},
}
# an entity of the appliance's own that says how much life a part has left, as a robot vacuum's brushes and filters,
# which is the item instead of a count of cycles, due once it's this low
LIFESPAN_KEY: Final[str] = "lifespan"
LIFESPAN_DUE: Final[float] = 10
# the button the same integration has to reset that part, by the translation key, as Ecovacs has it
LIFESPAN_RESET_PREFIX: Final[str] = "reset_"
# days that later is, for one item or all of an appliance's, after which it's due again
MAINTENANCE_SNOOZE_DAYS: Final[int] = 30
# buttons on the notification of an item due, followed by the entry id and the item, and on the first end
# notification of an appliance whose maintenance isn't tracked, followed by the entry id
ACTION_MAINTAINED: Final[str] = "APPLIANCE_MAINTAINED_"
ACTION_MAINTENANCE_LATER: Final[str] = "APPLIANCE_MAINTENANCE_LATER_"
ACTION_TRACK_MAINTENANCE: Final[str] = "APPLIANCE_TRACK_MAINTENANCE_"
MAINTENANCE_ACTION_TITLES: Final[dict[str, dict[str, str]]] = {
    "en": {ACTION_MAINTAINED: "Done", ACTION_MAINTENANCE_LATER: "In a Month", ACTION_TRACK_MAINTENANCE: "Track Maintenance"},
    "it": {ACTION_MAINTAINED: "Fatto", ACTION_MAINTENANCE_LATER: "Tra un mese", ACTION_TRACK_MAINTENANCE: "Segui manutenzione"},
}
# the name of each item, and what its notification says, by the language of Home Assistant as for the buttons
MAINTENANCE_NAMES: Final[dict[str, dict[str, str]]] = {
    "en": {
        "drum_clean": "Drum clean",
        "filter": "Filter clean",
        "lint_filter": "Lint filter clean",
        "machine_clean": "Machine clean",
        "condenser": "Condenser clean",
    },
    "it": {
        "drum_clean": "Pulizia del cestello",
        "filter": "Pulizia del filtro",
        "lint_filter": "Pulizia del filtro lanugine",
        "machine_clean": "Pulizia della macchina",
        "condenser": "Pulizia del condensatore",
    },
}
MAINTENANCE_MESSAGES: Final[dict[str, dict[str, str]]] = {
    "en": {
        "cycle": "{item}, 1 cycle since the last one",
        "cycles": "{item}, {cycles} cycles since the last one",
        "lifespan": "{item} at {value}%",
    },
    "it": {
        "cycle": "{item}, 1 ciclo dall'ultima",
        "cycles": "{item}, {cycles} cicli dall'ultima",
        "lifespan": "{item} al {value}%",
    },
}

# the text of the Android status bar chip, which shows it in full only up to about 7 characters
PROGRESS_CHIP: Final[str] = "{progress}%"
PREHEAT_PHASE: Final[str] = "Pre-heating"
FAST_PREHEAT_PHASE: Final[str] = "Fast pre-heat"
PREHEAT_MESSAGE: Final[str] = "{phase}, {current} of {target}{unit}"
PREHEATED_MESSAGE: Final[str] = "{name} is pre-heated"
# a robot vacuum that has stopped where it is, stuck or lifted, and won't go on by itself, by the language of Home
# Assistant as for the buttons, English for any other
STUCK_MESSAGES: Final[dict[str, str]] = {"en": "{name} needs help", "it": "{name} ha bisogno di aiuto"}
# the title of a Live Activity with a timer, which iOS shows on the Lock Screen in place of the message
LIVE_TITLE: Final[str] = "{title} · {phase}"
# the program and the status together, as the Live Activity shows them
LIVE_PROGRAM_STATUS: Final[str] = "{program} · {status}"
# what an oven up to heat is doing, and how hot it is
OVEN_MESSAGE: Final[str] = "{program}, {current}{unit}"
SUPERNOTIFY_PRESENT: Final[str] = "Supernotify is installed, so mobile apps will show a Live Activity for each cycle."
SUPERNOTIFY_MISSING: Final[str] = (
    "**Supernotify is not installed.** Only a plain start and end notification can be sent, to every phone with the "
    "Home Assistant app, with no Live Activity. Install Supernotify from HACS for the full experience."
)
# an appliance of an integration not yet tried on a real appliance, as it's offered to be added
BETA_NOTICE: Final[str] = (
    "\n\n**Support for {integration} is new**, written from the integration's source but not yet tried with a real "
    "appliance, so notifications may come at the wrong time or not at all. Once its first cycle is over you'll be "
    "asked how it went."
)
BETA_FOUND: Final[str] = " (new, offered to be added)"

# activities of a robot vacuum, as Home Assistant has them for every make
VACUUM_CLEANING: Final[str] = "cleaning"
VACUUM_PAUSED: Final[str] = "paused"
VACUUM_RETURNING: Final[str] = "returning"
# back where it started, or stopped by itself, the cleaning being over
VACUUM_DONE: Final[tuple[str, ...]] = ("docked", "idle")
VACUUM_ERROR: Final[str] = "error"
# how long a robot vacuum stays on its dock, having said it was on its way back, before its cleaning is over
VACUUM_SETTLE: Final[int] = 600
# how long one stays on its dock having gone straight there from cleaning, as one does part way through to wash its
# mop or fill its tank, which can take over ten minutes, before its cleaning is over
VACUUM_MIDWAY_SETTLE: Final[int] = 30 * 60
VACUUM_MIDWAY_KIND: Final[str] = "midway"
# seconds after setting off within which being back is taken for an integration that reports a vacuum docked as it
# leaves, as Ecovacs does each time one sets off again after washing its mop, and keeps to that while it cleans
VACUUM_BLIP: Final[float] = 5
VACUUM_BLIP_KIND: Final[str] = "blip"
# how long such a report is left before the cleaning is taken to be over, with nothing else heard from the vacuum
VACUUM_BLIP_SETTLE: Final[int] = 3 * 3600
# how long one stays on its dock once its own progress has reached the end of the cleaning, as Roborock reports it,
# before its cleaning is over, there being no more to set off again for
VACUUM_COMPLETE_SETTLE: Final[int] = 30
VACUUM_COMPLETE_KIND: Final[str] = "complete"
# seconds either side of setting off within which a running sensor of the vacuum's coming on is taken for its cleaning,
# as Roborock's Cleaning is, which stays on through a recharge part way through and goes off only once it's over, where
# its mop drying, also a running sensor, only comes on after
VACUUM_JOB_LEAD: Final[float] = 60
# how long one stays on its dock with that still on, recharging to carry on, before its cleaning is over regardless
VACUUM_HELD_SETTLE: Final[int] = 6 * 3600
VACUUM_HELD_KIND: Final[str] = "held"
# translation keys of the enum sensor that says what a vacuum is doing, as Roborock's Status does, sweeping or
# relocating, which the Live Activity says as it goes as an appliance's stage
VACUUM_STATUS_KEYS: Final[tuple[str, ...]] = ("status",)
# translation keys of the select of how a vacuum cleans, as Roborock's Cleaning mode is, vacuuming or mopping or both,
# which is its program
VACUUM_PROGRAM_KEYS: Final[tuple[str, ...]] = ("cleaning_mode",)
# translation keys of a vacuum's progress, as Roborock's Cleaning progress is, which it leaves at 100 from the cleaning
# before till a moment after setting off
VACUUM_PROGRESS_KEYS: Final[tuple[str, ...]] = ("clean_percent",)
# what each entity made use of does, by its translation key as Home Connect has it: the state of the cycle, how far
# along it is, when it will finish, and the program
CYCLE_KEY: Final[str] = "operation_state"
PROGRESS_KEY: Final[str] = "program_progress"
FINISH_TIME_KEY: Final[str] = "program_finish_time"
# selects, unlike the others, of the program under way, and of the one chosen, which is all an oven reports
PROGRAM_KEYS: Final[tuple[str, ...]] = ("active_program", "selected_program")
# what the appliance is doing within its cycle, such as drying then cooling, which Home Connect doesn't report
STAGE_KEY: Final[str] = "stage"
# the same entities as other integrations name them, whichever integration they come from, since it's what an
# entity does that matters, and which entities an appliance has together
ROLE_KEYS: Final[dict[str, str]] = {
    # Samsung washers, dryers and dishwashers, through SmartThings
    **{f"{kind}_machine_state": CYCLE_KEY for kind in ("washer", "dryer", "dishwasher")},
    **{f"{kind}_job_state": STAGE_KEY for kind in ("washer", "dryer", "dishwasher")},
    "completion_time": FINISH_TIME_KEY,
    # and through LocalThings, on the local network
    "machine_state": CYCLE_KEY,
    "progress": STAGE_KEY,
    "progress_percentage": PROGRESS_KEY,
    "finish_time": FINISH_TIME_KEY,
}
# beginnings of translation keys of an entity named per model
ROLE_KEY_PREFIXES: Final[dict[str, str]] = {"washer_cycle_table": "selected_program", "dryer_cycle_table": "selected_program"}
# the type of appliance from the beginning of the translation key of any of its entities, for an integration that
# names its entities for the type of appliance
KEY_TYPE_PREFIXES: Final[dict[str, str]] = {"dishwasher_": "dishwasher", "washer_": "washer", "dryer_": "dryer"}
# an oven warming up has no progress of its own, only how hot it is and how hot it's to be
TARGET_TEMPERATURE_KEY: Final[str] = "setpoint_temperature"
CAVITY_TEMPERATURE_KEY: Final[str] = "oven_current_cavity_temperature"
PREHEAT_FINISHED_KEYS: Final[tuple[str, ...]] = ("preheat_finished", "regular_preheat_finished")
FAST_PREHEAT_KEY: Final[str] = "fast_pre_heat"
# domain, by translation key, of each entity of an appliance that's made use of
ENTITY_DOMAINS: Final[dict[str, str]] = {
    PROGRESS_KEY: "sensor",
    STAGE_KEY: "sensor",
    FINISH_TIME_KEY: "sensor",
    **dict.fromkeys(PROGRAM_KEYS, "select"),
    TARGET_TEMPERATURE_KEY: "number",
    CAVITY_TEMPERATURE_KEY: "sensor",
    **dict.fromkeys(PREHEAT_FINISHED_KEYS, "sensor"),
    FAST_PREHEAT_KEY: "switch",
}
# degrees between Live Activity updates of an oven up to heat, whose temperature never stops wandering
TEMPERATURE_STEP: Final[float] = 5
# seconds before an oven saying it's up to heat is believed, since one switched off says so too, just before it's off
PREHEAT_SETTLE: Final[float] = 3
# an event sensor is `off` until whatever it tells of has happened
STATES_EVENT_ON: Final[tuple[str, ...]] = ("present", "confirmed", "on")

# the states of a cycle, with the words different integrations use for the same thing
STATES_RUN: Final[tuple[str, ...]] = ("run", "active")
# a cycle already under way, so not a new start when `run` follows
STATES_ACTIVE: Final[tuple[str, ...]] = (*STATES_RUN, "pause", "actionrequired")
# the cycle is over, an oven switched off goes straight from `run` to `inactive` without ever being `finished`
STATES_FINISHED: Final[tuple[str, ...]] = ("finished", "inactive", "stop")
# over too unless `run` soon follows, an oven being `ready` for a moment as it starts or has its settings changed
STATES_SETTLING: Final[tuple[str, ...]] = ("ready", "idle")
# stages that mean the cycle is over, though the cycle state may stay running a long while after, as a dryer's does
# while it tumbles its load now and then so it won't crease
STAGES_FINISHED: Final[tuple[str, ...]] = ("finished", "finish", "wrinkle_prevent")
# stages that say nothing of what it's doing
STAGES_NONE: Final[tuple[str, ...]] = ("none", "idle")
# seconds an appliance is left to settle before the cycle is over
CYCLE_SETTLE: Final[float] = 10
# seconds after the cycle starts before it's told of, since an integration may report its program and stage a moment
# after the state of its cycle, as LocalThings does
START_SETTLE: Final[float] = 3
# seconds a Live Activity is left to open before anything more is sent to it, since a push sent straight after the
# start can reach a phone ahead of it, and then be overwritten by the start, with no bar and no program
LIVE_SETTLE: Final[float] = 5
# where a cycle under way is kept through a restart of Home Assistant, one store for each appliance
CYCLE_STORE: Final[str] = f"{DOMAIN}.cycle.{{entry_id}}"
CYCLE_STORE_VERSION: Final[int] = 1
# seconds a change waits to be saved, so a few close together are written once
CYCLE_SAVE_DELAY: Final[float] = 1
# hours after which a cycle kept is too old to carry on from, as when Home Assistant has been off since
CYCLE_KEPT_HOURS: Final[float] = 24
# the cycle is over without finishing, so the Live Activity goes without an end notification
STATES_ABANDONED: Final[tuple[str, ...]] = ("error", "aborting")

# percentage points between Live Activity updates, since mobile platforms throttle frequent ones
PROGRESS_STEP: Final[int] = 5
# percentage points between ordinary notifications of progress, where those are asked for
PROGRESS_NOTIFY_STEP: Final[int] = 10
# from here on the end is in sight and the bar is being watched, so it's kept closer to the appliance
PROGRESS_FINAL: Final[int] = 90
PROGRESS_FINAL_STEP: Final[int] = 2

MOBILE_PUSH_TRANSPORT: Final[str] = "mobile_push"
# Android notification channel of its own, made with sound on the first notification, since a Live Update in the
# app's default channel arrives without a sound
ANDROID_CHANNEL: Final[str] = "Appliances"
# platform of the notify entities used when there's no Supernotify and none have been chosen
MOBILE_APP_PLATFORM: Final[str] = "mobile_app"

DEFAULT_ICON: Final[str] = "mdi:progress-clock"
TYPE_OVEN: Final[str] = "oven"
# the type of a Home Connect appliance, by how its programs are named
APPLIANCE_TYPES: Final[dict[str, str]] = {
    "dishcare_dishwasher_program_": "dishwasher",
    "laundry_care_washer_program_": "washer",
    "laundry_care_washer_dryer_program_": "washer_dryer",
    "laundry_care_dryer_program_": "dryer",
    "cooking_oven_program_": TYPE_OVEN,
    "cooking_hob_program_": "hob",
    "cooking_common_program_hood_": "hood",
    "consumer_products_coffee_maker_program_": "coffee_maker",
    "consumer_products_cleaning_robot_program_": "cleaning_robot",
    "heating_ventilation_air_conditioning_air_conditioner_program_": "air_conditioner",
}
TYPE_ICONS: Final[dict[str, str]] = {
    "dishwasher": "mdi:dishwasher",
    "washer": "mdi:washing-machine",
    "washer_dryer": "mdi:washing-machine",
    "dryer": "mdi:tumble-dryer",
    TYPE_OVEN: "mdi:stove",
    "hob": "mdi:pot-steam",
    "hood": "mdi:fan",
    "coffee_maker": "mdi:coffee-maker",
    "cleaning_robot": "mdi:robot-vacuum",
    "air_conditioner": "mdi:air-conditioner",
    # types known only from the name
    "microwave": "mdi:microwave",
    "kettle": "mdi:kettle",
}
# the types whose phases are worth a notification unless it's turned off, an oven up to heat being waited
# for where a dishwasher starting to rinse isn't
PHASES_NOTIFIED: Final[tuple[str, ...]] = (TYPE_OVEN,)
# a power monitor is offered as an appliance when its name says it's one of these, appliances that run in cycles
# worth being told of, where a kettle or a coffee maker is done in a minute or two
CYCLE_TYPES: Final[tuple[str, ...]] = ("dishwasher", "washer", "washer_dryer", "dryer", TYPE_OVEN)
# platforms whose power sensors are estimated or worked out from others, so never the appliance's own measurement,
# such as the standby draw Powercalc adds to a smart plug's device
DERIVED_POWER_PLATFORMS: Final[tuple[str, ...]] = (
    "powercalc",
    "template",
    "integration",
    "utility_meter",
    "group",
    "min_max",
    "statistics",
    "derivative",
    "filter",
)

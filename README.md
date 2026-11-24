# Appliance Auto Notify

[![Rhizomatics Open Source](https://img.shields.io/badge/rhizomatics%20open%20source-lightseagreen)](https://github.com/rhizomatics) [![managed by hq](https://raw.githubusercontent.com/rhizomatics/hq/main/assets/badge-managed-by-hq.svg)](https://hq.rhizomatics.org.uk/) [![Home Assistant Marketplace][marketplacebadge]][marketplace]
[![CI](https://github.com/rhizomatics/appliance_autonotify/actions/workflows/ci.yml/badge.svg)](https://github.com/rhizomatics/appliance_autonotify/actions/workflows/ci.yml)
[![Github Deploy](https://github.com/rhizomatics/appliance_autonotify/actions/workflows/deploy.yml/badge.svg?branch=main)](https://github.com/rhizomatics/appliance_autonotify/actions/workflows/deploy.yml)
![Coverage](https://raw.githubusercontent.com/rhizomatics/appliance_autonotify/refs/heads/badges/badges/coverage.svg)
![Tests](https://raw.githubusercontent.com/rhizomatics/appliance_autonotify/refs/heads/badges/badges/tests.svg)

![Logo](https://appliance-autonotify.rhizomatics.org.uk/assets/images/icon.png)
Automatic notifications for household appliances in Home Assistant, with no automations or YAML.

When a dishwasher, washing machine, oven or other appliance starts a cycle, you're told it started, your phone shows a [Live Activity](https://companion.home-assistant.io/docs/notifications/live-activities) with progress and time remaining while it runs, and you're told when it finishes, and if you like, how long it ran, the energy it used and what that cost.

![Example Dishwasher Progress](https://appliance-autonotify.rhizomatics.org.uk/assets/images/dishwasher_progress.png)

## Supported Appliances

### Automatically Discovered and Configured

- **Bosch**, **Neff** and **Siemens**
  - Connected with the Home Assistant [Home Connect](https://www.home-assistant.io/integrations/home_connect/) integration
  - Dishwashers through [Home Connect Local](https://github.com/chris-mc1/homeconnect_local_hass), with its other appliances new and in beta
- **Robot Vacuums**
  - Any using the [Vacuum Integration](https://www.home-assistant.io/integrations/vacuum/), including popular brands like **Ecovacs** and **Roborock**
- **Samsung**
   - Washers, dryers and dishwashers through [SmartThings](https://www.home-assistant.io/integrations/smartthings/) or [LocalThings](https://github.com/mbillow/localthings)
- **LG**
  - Washers and dryers through [LG ThinQ](https://www.home-assistant.io/integrations/lg_thinq/).
  - Dishwasher support is new and in beta
- **Miele**
   - Appliances using [Miele Integration](https://www.home-assistant.io/integrations/miele/) is new and in beta

### Manually Added

- **Power Monitors**
  - Use these to monitor any appliance - even an ancient one can drive a Live Activity on a phone based on power usage.

### Others

See [New Integrations](docs/how_it_works.md#new-integrations).

Any other appliance can be added by hand if it has a power monitor, such as a smart plug, and there's an option to submit your appliance data to the developers to help get it supported.

![Pizza Time](https://appliance-autonotify.rhizomatics.org.uk/assets/images/pizza_time.png)

## What You Need

- Home Assistant 2026.5 or later
- An appliance set up with the Home Connect, SmartThings or LocalThings integration, a robot vacuum of any make, or one with a power sensor
- [Supernotify](https://supernotify.rhizomatics.org.uk), installed from Marketplace, for Live Activities and for anything beyond a plain notification.
  - Optional, however without Supernotify, it only sends a start and an end notification, to every phone with the Home Assistant app unless you choose other notify entities.
  - `v2.14.0` recommended as minimum, though most features will work with earlier releases
- Home Assistant companion app installed on an Apple mobile device, minimum iOS 17.2, or on an Android one, where a
  [Live Update](https://companion.home-assistant.io/docs/notifications/live-activities) needs Android 16 or later, and earlier versions show an ordinary notification with a progress bar.


## Install

[![Open in Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=rhizomatics&repository=appliance_autonotify&category=integration)

1. Use the button above, or in Home Assistant Marketplace (previously *HACS*) search for *Appliance Auto Notify* and restart Home Assistant
   - Appliance Auto Notify is in the default marketplace catalogue, so no need to add any custom repository
2. In *Settings*, *Devices & services*, choose *Add integration* and pick *Appliance Auto Notify*
3. Leave *Set up appliances automatically* on, and submit

That's all. Every appliance with a cycle Home Assistant reports is set up straight away, and so is any you add later. Each is listed on the integration's page, alongside *Automatic discovery*, and notifies with no further settings.

To stop the notifications for an appliance, disable it rather than delete it, since a deleted appliance is found and set up again.

### Appliance Not Found?

If an appliance with its own integration isn't found, its integration may name its entities or states in a way that isn't known yet. In *Settings*, *Devices & services*, open *Appliance Auto Notify*, and on *Automatic discovery* choose ⋮ then *Download diagnostics*. It lists each device that looks like an appliance but wasn't found to be one, with its make, model, integration, and its entities' keys, options and states. Names, areas and entity ids are left out, since it's meant to be shared. [Open an issue](https://github.com/rhizomatics/appliance_autonotify/issues) asking for the integration to be supported and attach the file.

Meanwhile, an appliance with a smart plug or other power monitor can be added by its power, see [Power Monitored Appliances](#power-monitored-appliances).

### Removing

1. In *Settings*, *Devices & services*, open *Appliance Auto Notify* and delete *Automatic discovery* first, so the
   appliances aren't found and set up again, then delete each appliance. A cycle it was keeping through restarts is
   deleted with it
2. Remove *Appliance Auto Notify* in Marketplace and restart Home Assistant

It adds no automations, scripts or YAML of its own, so there is nothing else to clear up.

### Choosing Appliances Yourself

Turn *Set up appliances automatically* off, on the first screen or later from the settings of *Automatic discovery*, and appliances are instead offered as *Discovered* on the *Devices & services* page. Choose *Add* to set one up, or *Ignore* on any you don't want.

### Robot Vacuums

A robot vacuum of any make, through whichever integration Home Assistant has for it, is found and set up like the other appliances.

Cleaning is the cycle: it starts as the vacuum sets off, and ends once it has been back on its dock, or stopped by itself, for 10 minutes after saying it was on its way back. That wait is *Wait on the dock* in the *End message* settings of the vacuum, to raise for one that goes back part way through
to wash its mop or empty its bin, or lower for one that never does. A vacuum that goes straight to its dock from cleaning, as one does part way through to wash its mop or fill its tank, is given 30 minutes to set off again
before its cleaning is taken to be over.

Where the vacuum reports its own progress, as Roborock does, its cleaning is over 30 seconds after it's back on its dock with its progress at 100%, rather than waiting. Any percentage of the vacuum's
other than its battery that climbs to 100 during a cleaning is taken for its progress, so one that doesn't reach 100, such as a brush's life left, makes no difference.

Where the vacuum has a sensor of its own for whether it's cleaning, as Roborock's *Cleaning* is, that is followed instead: back on its dock with it still on is the same cleaning, for as long as 6 hours, as when it
recharges part way through to carry on, and once it goes off the cleaning is over 30 seconds after it's back. Any *running* sensor of the vacuum's that comes on within a minute of it setting off is taken for this, so
one that only comes on once it's back, such as its mop drying, makes no difference.

Paused, or on its way back, it's still the same cleaning too, and paused once
back on its dock is still the end. A cleaning under way when Home Assistant restarts still has its end told. One that stays in error for 10 minutes while out is told of with a notification of its own, *Bruno needs help*, rather than the end, since some integrations
report a past error again for a while as they reconnect, with the vacuum carrying on.

Where the vacuum's integration reports them, as Roborock's does, its *Cleaning mode* is its program, its *Status*, such as sweeping or relocating, is its status, and its *Cleaning progress* fills the bar of the Live Activity,
once it has dropped from the 100% left by the cleaning before. A vacuum has no time left to show, so its Live Activity says what it's doing in its message, such as "Vac and mop · Sweeping", and "Returning" on its way back to its dock, whether or not it has a status of its own.

### Power Monitored Appliances

An appliance with no supported integration can be added if a sensor measures the power it draws.

1. On the integration's page, choose *Add service*
2. Give the appliance a name, and choose its power sensor

A power monitor named for a washing machine, dryer, dishwasher or oven, in English or in the language of Home Assistant, such as a smart plug called *Washing machine*, *Waschmaschine* or *Lavatrice*, is found by itself and offered as *Discovered*, with its sensor and plug already filled in. It's never set up without asking, even with *Set up appliances automatically* on, since a name is only a guess, and the threshold is worth checking first. Estimated or derived power sensors, such as Powercalc's, are left out.

| Setting         | Default    | What it does                                                                              |
| --------------- | ---------- | ----------------------------------------------------------------------------------------- |
| Power threshold | 1 W        | The appliance is running while it draws more than this                                    |
| Grace period    | 60 seconds | How long power must stay at or below the threshold before the cycle is over, so short drop outs are ignored |
| Minimum running time | 0 seconds | How long power must have been above the threshold before it counts as a cycle, so a door opened or a button pressed is ignored |
| Smart plug      | None       | The switch the appliance is plugged into, offered as a button on the end notification to switch it off |

Raise the grace period for appliances that pause mid-cycle, such as a washing machine soaking. Set a minimum running time, 60 seconds or so, for appliances that draw a little power when their door is opened or a button pressed, such as a
dishwasher whose light comes on, so that isn't notified as a cycle. Time above the threshold adds up across drop outs shorter than the grace period, so a cycle that pauses as it starts still counts.

## Settings

Nothing needs changing for notifications to work. Each appliance on the integration's page has settings:

- *Notify Start* and *Notify End* switches
 - the start off and the end on by default
- *Notify phases* switch
  -  on by default for ovens
- *Notify progress* switch
  - off by default, switch on to get the percentage or ETA regularly notified
- *Notify offline after*
  - minutes the appliance must be unavailable, as when it has dropped off Wi-Fi and its integration can't reach it, before you're told it's offline, such as "Dishwasher is offline since 23:10", and then told when it's back, such as "Dishwasher is back online after 9 h 20 min", in place of the first
  - 0 by default, for none, since an appliance switched off at the wall is offline too. Choose it for one that's always left on, so it can't go quiet without a word
  - a power monitored appliance is offline when its smart plug's power sensor is unavailable
- *Live Activity timer*, and what the *Live Activity shows*
  - The timer counts down the time left, where the appliance reports when it will finish, on by default
  - Tick any of the *Program*, such as "Intensive 70ºC", the *Phase*, such as "Drying" or "Relocating", and the *State*, such as "Paused" or "Returning", all ticked by default
  - Supernotify required for these options
- *Dashboard to open*
  - when a notification or the Live Activity is tapped.
  - Can be any Home Assistant dashboard, use one for all appliances, or create a dashboard just for that appliance and hide it from the app side panel so it doesn't clutter up the ap
  - Set when the appliance is added to a dashboard named for it, such as "Dishwasher", or for its type, such as "Washing Machine" for a washer, by its title or its path, so long as there's only one that matches. Change it or clear it like any other setting, it isn't set again

With *Notify start* or *Notify end* off, that notification isn't sent, but the Live Activity is still opened and closed, silently and on phones only. The dashboard is a choice of those in Home Assistant, never a URL to type in, so a notification can't be made to open anything else.

| Section              | What it does                                                                                 |
| -------------------- | -------------------------------------------------------------------------------------------- |
| Start message        | The title and message sent when the appliance starts, shown as they'll be sent, such as "Dishwasher started". Clear a box to go back to the usual wording. `{program}` is replaced by the program under way, as Home Assistant shows it, such as "Eco 50ºC", and by nothing for an appliance that reports none. `{start_time}` is replaced by the time it started, such as 11:29, here and in the end message, see [What a Cycle Came To](#what-a-cycle-came-to) |
| End message          | The same for when it finishes, such as "Dishwasher is finished". `{duration}`, `{energy}` and `{cost}` are replaced by how long it ran, the energy it used and what that cost, see [What a Cycle Came To](#what-a-cycle-came-to). With Supernotify, also a *Reminder*, see below |
| Notification targets | With Supernotify, *Targets* is the same choice of entities, devices, areas, floors and labels as any Supernotify notification, *Custom targets* is for those outside Home Assistant, such as e-mail addresses or phone numbers, and *Deliveries* limits notifications to those chosen. Leave them empty for Supernotify to choose. Without Supernotify, *Targets* is a choice of notify entities, and left empty means every phone with the Home Assistant app |

What the *Live Activity shows* is whichever of the program, the phase and the state are ticked, each only where the appliance reports it and has something to say:

- **Program**, such as "Eco 50ºC", worth unticking for an appliance that's always on the same one, a dishwasher, say, and worth keeping for one that isn't, such as an oven
- **Phase**, the part of the cycle it's in, such as a pre-rinse, a dryer drying then cooling, an oven pre-heating, or a robot vacuum relocating
- **State**, only when it's more than running, such as paused, waiting for something to be done, or a robot vacuum returning to its dock

Any that says no more than another is left out, such as a vacuum's status of "Returning home" beside its "Returning".

With the timer, the time left counts down on the Lock Screen of an iPhone in place of the message, so what's shown goes in the title beside the name, such as "Dishwasher · Eco 50ºC · Main wash", as much as fits: the program is left out first, then the phase, while the state, there least often and most worth knowing when it is, stays. The message has the progress, such as "40% complete". Turn the timer off to have the name alone as the title, and what's shown in the message, where there's room for all of it.

## Notifications

Nothing is polled: notifications go out as the appliance's own entities change. Their usual wording, and their buttons, are in the language of Home Assistant where there's a translation (English, Chinese, Dutch, French, German, Hindi, Italian, Polish and Spanish), such as "Spülmaschine ist fertig", and in English for any other. See [What Gets Sent](docs/how_it_works.md#what-gets-sent) for each notification and Live Activity update, with and without Supernotify.

### What a Cycle Came To

The end message can say how long the cycle ran, the energy it used and what that cost, by putting these in it, in the *End message* section of the appliance's settings:

| Placeholder    | Replaced by                                                   | Needs                                                                       |
| -------------- | ------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `{start_time}` | When it started, such as "11:29", in Home Assistant's time zone. In the start message too | Nothing                                          |
| `{duration}`   | How long it ran, such as "1 h 40 min"                         | Nothing                                                                     |
| `{energy}`     | The energy it used, such as "0.74 kWh"                        | An energy meter on the appliance, or on its smart plug for one that's power monitored |
| `{cost}`       | What that energy cost, such as "€0.19"                        | The meter, and a grid price set on Home Assistant's *Energy* dashboard, as a number or an entity |

For example, an end message of

```text
📌 {name} is finished
⏱ {duration}
⚡ {energy}
💰 {cost}
```

is sent as

```text
📌 Washer is finished
⏱ 50 min
⚡ 0.74 kWh
💰 €0.19
```

Each is replaced by nothing where it isn't known, such as the energy of an appliance with no meter, and a line left with nothing but its emoji, as "⚡" would be, is left out altogether. So is an energy or cost that rounds to nothing, such as 0.004 kWh. A reminder of the end says the same again, and so does one sent after Home Assistant has restarted.

The duration is written in the language of Home Assistant, such as "1 Std. 40 Min." in German, and the cost in its currency, written as the language writes it, such as "$0.45" or "0,45 €". See [Cycle Totals](docs/how_it_works.md#cycle-totals) for how each is worked out.

### Buttons on the End Notification

With Supernotify, the end notification has buttons:

| Button         | What it does                                                                                 |
| -------------- | -------------------------------------------------------------------------------------------- |
| Finished       | Acknowledges and clears the notification, and stops any reminder                                              |
| Remind Later   | Sends the end notification again later, after the *Reminder* minutes or, with none set, 30   |
| Switch Off     | Only for a power monitored appliance with a *Smart plug* chosen, and the *Switch Off button* setting left on. Switches it off, unless a new cycle has started since |

With a *Reminder* set in the *End message* section, the end notification is sent again after that many minutes, up to the *Reminder repeats* times, 3 unless changed, until *Finished* is pressed or the next cycle starts. Supernotify adds the buttons of its own scenarios after these, and Android shows only the first 3.

### Maintenance

Nothing is tracked until it's asked for. For an appliance with something to maintain, the first end notification has one more button, *Track Maintenance*, which turns it on, as does *Track maintenance* in its settings. Either way it's offered only the once. Where the end notification already has three buttons, which is all Android shows, it takes the place of *Remind Later* on that one notification.

![Switch on Maintenance](./assets/images/track_maint.png)

Once on, each finished cycle is counted, and the appliance starts with a set of items for its type, each due after a number of cycles, to change or take out (0) in the *Maintenance* section of its settings:

| Appliance       | Items, and cycles apart                         |
| --------------- | ----------------------------------------------- |
| Washing machine | Drum clean 30, filter clean 50                  |
| Washer dryer    | Drum clean 30, filter clean 50, lint filter 20  |
| Dishwasher      | Filter clean 30, machine clean 60               |
| Dryer           | Condenser clean 30                              |

An appliance whose integration reports how much life a part has left as a percentage, such as the brushes and filters of an Ecovacs robot vacuum, has an item for each of those instead, due once it's down to 10%, and told of as soon as it is, whether or not the vacuum is cleaning.

Whatever is due is on the one *Appliance maintenance* to-do list, held by the *Automatic discovery* entry, and is told of with a notification as it falls due, the once:

| Where                | What it does                                                                                |
| -------------------- | ------------------------------------------------------------------------------------------- |
| Done, or ticked off  | Counts from 0 again. A part is reset with its integration's own button where it has one, and otherwise left off the list until it reads as replaced |
| In a Month, or deleted from the list | Put off for 30 days, after which it's due, and told of, again             |

The *Reset maintenance* action says it's done without the notification, or sets the cycles since it was last done, such as for an appliance already counted another way, and *Snooze maintenance* puts it off, for one item or all of an appliance's. Done for all of them resets only the parts that are due, so the life of the rest is kept.

### Oven Pre-heating

An oven with no timer set has no progress to report, so while it warms up, on any program, the bar is its
temperature as a percentage of the one it's set to, and the message is the two of them, such as "Pre-heating, 150 of 200°C", or "Fast pre-heat" in place of "Pre-heating" while that is on.

Once the oven is as hot as asked for, or reports that pre-heating is finished, "Oven is pre-heated" is sent
everywhere as a notification of its own, unless *Notify phases* is off. The Live Activity stays until the oven is
switched off, and goes straight on to the program and the temperature, such as "Pizza setting, 200°C", updated
whenever the temperature has moved by 5 degrees. From then on the oven isn't taken to be warming up again,
however its temperature wanders, until it has been off. With a timer set, the bar then goes on to the progress
of the program.

All of this depends on Home Connect telling Home Assistant the temperature the oven is set to, as its *Setpoint
temperature* entity, or reporting that pre-heating is finished. Neither can be relied on:

- An oven started with its own knobs or buttons, rather than from the Home Connect app or Home Assistant, often leaves *Setpoint temperature* unavailable for the whole cycle, even though Home Connect itself knows it
- Many ovens send *Pre-heat finished* only now and then, or not at all

When neither is there, the oven is shown with its program and temperature as it heats, such as "Hot air, 150°C", with no pre-heating bar and no "Oven is pre-heated" notification. Whether the *Setpoint temperature* entity has a value while the oven is heating shows whether yours is affected.

### Icons

The icon of a notification follows the type of appliance: dishwasher, washer, dryer, washer dryer, oven, hob, hood, coffee maker, cleaning robot or air conditioner. A power monitored appliance has none to go by, so its name is used instead, as in "Washer" or "Kettle".

## Known Limits

- On a Samsung phone, the status bar chip, the Now Bar and the appliance's colour only show with the developer option
  *Live notifications for all apps* turned on. See [Android and iOS](docs/mobile_platforms.md) for everything each platform shows
- On Android the notifications go in their own *Appliances* channel, made with sound the first time, since a Live Update in the app's usual channel is silent. Its sound can be changed in the phone's settings for the Home Assistant app, and is kept from then on

- Pre-heating is the only phase of a Home Connect appliance's cycle there is to tell of, since Home Connect reports none for a dishwasher or washer, such as pre-wash or rinse
- An appliance with a stage but no progress, such as a Samsung one through SmartThings, has its Live Activity brought up to date only as its stage changes, so its time remaining may lag a change of its finish time until then

- If the appliance never reports the end of its cycle, the Live Activity stays on the phone until dismissed
- A cycle under way survives a Home Assistant restart: it isn't told of as started again, and the wait to see that it's over, or for a reminder, carries on from where it was, unless Home Assistant has been off for more than a day. A power monitored appliance that stopped while Home Assistant was off has its end told without `{duration}`, there being no knowing when it stopped, though the energy it used and its cost are still told
- An appliance that stops without saying it has finished or been switched off is taken to be finished 10 seconds later, in case it carries on, as an oven does when its settings are changed
- An oven has no pre-heating bar until Home Connect first reports its temperature, which isn't known after a restart of Home Assistant until the oven is next heating
- An oven started from its own controls often has no pre-heating bar or pre-heated notification at all, since Home Connect may then never give Home Assistant the temperature it's set to, see [Oven Pre-heating](#oven-pre-heating)
- Progress, time remaining and the program are only shown where the appliance reports them, so never for a power monitored appliance
- A robot vacuum that goes back to its dock to recharge part way through, saying it's on its way back as it does at the end, has two cleanings told if it charges for longer than its *Wait on the dock*, unless it has a sensor for whether it's cleaning, since otherwise there's no telling that dock from the last
- A robot vacuum whose integration never says it's on its way back is told to be finished 30 minutes after it's back on its dock
- Some integrations, such as Ecovacs, report a robot vacuum docked within a second of setting off and keep to that while it cleans, so being docked that soon is only believed after 3 hours with nothing else heard, which is when one stopped just as it set off is told to be finished
- An oven still warming up when Home Assistant restarts is still shown as pre-heating, and told of once up to heat, unless it got there while Home Assistant was off. One switched on while Home Assistant was off isn't shown as pre-heating, since there's no knowing whether it has been up to heat, only with its program and temperature
- An oven with no timer set reports its progress as 100%, so that is what the bar shows once it's up to heat

## Troubleshooting

Appliance Auto Notify logs a warning, starting `APPLIANCES`, whenever something stops a notification being sent. Look in *Settings*, *System*, *Logs*, and search for `APPLIANCES`.

### Appliance not found

See [Appliance Not Found?](#appliance-not-found), and download the diagnostics of *Automatic discovery* to attach to an issue.

### Appliance stuck on *Retrying setup*

An appliance's entry is set up only once its cycle state sensor is there, or a robot vacuum's vacuum entity. Until then the entry shows *Retrying setup*, and the log says `No cycle state entity found` or `No vacuum entity found`. This is normal for a minute or two while Home Assistant starts and the appliance's own integration connects, so it sorts itself out. If it doesn't:

- Check that the appliance's own integration is loaded and its device is online
- Check that its status sensor, such as *Operation state* or *Current status*, hasn't been disabled. A disabled entity is ignored
- If the appliance has been removed from its integration, a repair in *Settings*, *System*, *Repairs* offers to remove it here too. If it's been added again as a new device, remove the old one, so the new device is found

### Nothing sent

Notifications go through [Supernotify](https://supernotify.rhizomatics.org.uk) if it's installed, and through the notify entities of the Home Assistant app if not.

- `Nothing to notify for …, choose targets in its settings`, also raised as a repair: without Supernotify, no *Targets* are chosen and no phone has the Home Assistant app set up for notifications. Install the app on a phone and sign in, or choose notify entities under *Notification targets* in the appliance's settings
- `No mobile push delivery found for …, Live Activity not updated`: Supernotify has no mobile push delivery, or none left after the *Deliveries* chosen in the appliance's settings, so the Live Activity can't be updated. Add a mobile push delivery to Supernotify, or include it in *Deliveries*
- `Supernotify notification failed for …`: Supernotify raised an error, which follows in the log. Check its configuration
- If there's no warning, check that *Notify start* or *Notify end* is on as wanted. With them off, only the Live Activity is updated, silently, and only on phones
- If the appliance's own entities are *Unavailable*, its integration can't reach it, often because it has dropped off Wi-Fi, so there's nothing to notify of. Reconnect it from its own app. *Notify offline after* tells you when this happens

## Known Issues

Both of these have been seen on an iPhone, and neither has a confirmed cause yet.

### Progress bar behind the appliance

The progress bar of the Live Activity can fall well behind, such as showing 40% while the appliance is at 74%.

The likely cause is iOS. Progress is sent with `silent: true`, so that the phone doesn't alert every 5%, and the
[Companion App](https://companion.home-assistant.io/docs/notifications/live-activities) sends silent updates at a
lower priority, which iOS may delay, batch or drop. This is a theory, since it hasn't been tested by sending the
updates without `silent`.

Turning on *Notify progress* sends each update as an ordinary notification, without `silent`, so is worth
trying if the bar matters more than the interruptions.

### Seconds shown as dashes

The time remaining sometimes has dashes in place of the seconds, such as `52:--` or `1:30:--`, on the Lock Screen
while the Dynamic Island shows a full countdown at the same moment.

The same finish time is sent however it ends up shown, and the Companion App has no setting for the format of the
timer, so this is down to the phone. The likely reason is that the Lock Screen is redrawn less often while it's
dimmed or always-on, so drops the seconds. This is also a theory, and nothing has been found that changes it.

## Other Apps

- [Camera AutoNotify](https://camera-autonotify.rhizomatics.org.uk) - Instant notifications for Frigate (and other camera systems coming) with no config, no blueprints, no YAML, no automations.
- [AutoArm](https://autoarm.rhizomatics.org.uk) - Automatically arm and disarm Home Assistant alarm control panels using physical buttons, presence, calendars, sun and more
- [Remote Logger](https://remote-logger.rhizomatics.org.uk) - OpenTelemetry (OTLP) and Syslog event capture for Home Assistant
- [Supernotify](https://supernotify.rhizomatics.org.uk) - Unified notification for easy multi-channel messaging, including powerful chime and security camera integration.

[marketplace]: https://www.home-assistant.io/integrations/marketplace
[marketplacebadge]: https://img.shields.io/badge/Home%20Assistant-Marketplace-blue.svg

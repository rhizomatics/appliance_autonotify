# How it Works

What goes on behind the notifications, for the curious, and for anyone adding an integration or reporting an issue.

## What Gets Sent

Nothing is polled. Each appliance is followed through the state changes of its own entities, or its power sensor, as Home Assistant reports them, and a notification goes out as soon as one of those says a cycle has started,
moved on or finished.

| When                                   | With Supernotify                                                    | Without             |
| -------------------------------------- | ------------------------------------------------------------------- | ------------------- |
| Cycle starts                           | A Live Activity opened silently on phones. With *Notify start* on, a start notification everywhere, which opens the Live Activity too | Nothing, or with *Notify start* on, a start notification |
| Every 5% of progress                   | Silent update of the Live Activity, on phones only, with the program under way as its message, such as "Eco 50ºC". With *Notify progress* on, a notification everywhere instead at every 10%, which updates the Live Activity too | Nothing, or with *Notify progress* on, a notification |
| Every 2% of progress, from 90%         | Silent update of the Live Activity, on phones only                  | Nothing             |
| Oven warming up                        | Silent update of the Live Activity as the oven warms, see below      | Nothing, or with *Notify progress* on, a notification |
| Oven up to heat                        | "Oven is pre-heated" everywhere, unless *Notify phases* is off       | The same notification, unless *Notify phases* is off |
| Cycle finishes                         | Live Activity closed, then an end notification everywhere, unless *Notify end* is off | End notification, unless *Notify end* is off |
| Cycle is aborted, or fails             | Live Activity closed, with no end notification                      | Nothing             |

Pausing and resuming an appliance counts as the same cycle. An appliance that is switched off, like an oven,
counts as finished.

## Appliances Through Other Integrations

An appliance is found by what its entities do, not by the integration they come from: a sensor of the state of its cycle, whose states include one of a cycle under way, along with whichever of its stage, progress, finish time or time left, and program the integration reports. Integrations that work alike often name these differently, and use different words for the same states, `run` or `active` for a cycle under way and `stop` or `finished` for its end, so those are kept as shared lists of the names and states known, which is all another integration with the same kind of entities needs.

Where an integration goes its own way, it has a profile of its own, used before the shared lists and only for its own entities, so its names can't be mistaken for another integration's. A profile can give:

- Its own names for the entities, as Home Connect Local's `sensor_operation_state`
- Its own states of a cycle, each taken for one of the shared ones, as Miele's `in_use` is `run`
- The cycle state as the stage too, where one state says both, as LG ThinQ's *Rinsing* does
- What else an appliance must have to have a cycle, where every device has the same cycle state, as a Miele fridge has
- How its programs are named, to tell the type of appliance

Progress is worked out from the time, where an appliance reports none: the time the cycle takes, or has taken, against the time it has left. The type of appliance is taken from its programs, or else its entities, then its model, as *Washing machine* or `DEVICE_WASHER`, and failing all of those its name.

A stage that means the cycle is over ends it there, such as a dryer's *Wrinkle prevent*, when it only tumbles its load now and then so it won't crease, though its cycle state stays running for as long as that goes on, and running on from there isn't a new cycle until the cycle state has said it's over.

The same appliance through two integrations, as a Samsung one is through SmartThings and LocalThings, which share its `id`, is set up once, through the integration that reaches it on the local network rather than through the vendor's cloud, or failing that the one that tells more of its cycle. The other is only listened to while the first can't be
heard from, though an end it told meanwhile still counts once the first goes quiet. An appliance already set up through one isn't offered again when the other is added, and one offered through the cloud is offered through the local network instead once that's found.

## New Integrations

Where an integration names its entities or states its own way, or has more to tell than others, what's different is written down for it, and the rest is taken to work as it does for any other. Support for an integration written from its source, before it has been tried with a real appliance in a home, is *new*:

| Integration | Appliances | Issue |
| ----------- | ---------- | ----- |
| [Home Connect Local](https://github.com/chris-mc1/homeconnect_local_hass) | Bosch, Siemens, Neff | [#28](https://github.com/rhizomatics/appliance_autonotify/issues/28) |
| [LG ThinQ](https://www.home-assistant.io/integrations/lg_thinq/) | LG washers, dryers, dishwashers | [#27](https://github.com/rhizomatics/appliance_autonotify/issues/27) |
| [Miele](https://www.home-assistant.io/integrations/miele/) | Miele washers, dryers, dishwashers, ovens | [Issues](https://github.com/rhizomatics/appliance_autonotify/issues) |

LG ThinQ has one state for both whether the appliance is running and what it's doing, such as *Rinsing*, which is shown as its status, and reports no progress, so it's worked out from the time the cycle takes and the time left, and moved on each minute.

Miele gives every appliance the same status, a fridge's as much as a washer's, so only one with a program phase too is taken to have a cycle. Its progress is worked out from the time the program has taken and the time it has left.

An appliance through a new integration is never set up automatically, it's offered as *Discovered*, saying that support is new. Once added, what it reports through its first three cycles is kept, and once the first has finished a repair asks how it went. Download the diagnostics of the appliance, from its entry under *Appliance Auto Notify* on the *Devices & services* page, and add them to the issue, whether it went well or not, since it takes a cycle on a real appliance to know.

## The Appliance's Device

From Home Assistant 2026.8, each appliance gets a device of its own, listed under it on the integration's page with its model and area. It
shares the identifiers of the device the appliance already has, from Home Connect, SmartThings, LocalThings or the
vacuum's integration, so each shows the other under *Linked devices*, with the integration's icon, as Home Assistant
does for the same hardware through two integrations, such as a camera through UniFi and ONVIF. Appliances are still
found by what their entities do, not by their integration, and the device is only where the appliance is shown.

A power monitored appliance's device is *connected via* the smart plug, since the plug is other hardware, and has no
device to link to if its power sensor has none.

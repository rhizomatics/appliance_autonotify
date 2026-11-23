# Mobile Platforms

## Android and iOS

### What the phone shows, and why the payload looks like it does

One payload is sent to every phone, through Supernotify's `mobile_push` delivery, and each Companion App picks out the fields it knows. This page covers what each platform does with every field the integration sends or could send, where the result shows up, what the user can change on the phone, and the limits on delivery, so that both get the
most out of one payload without anything platform specific in the code.

## Sources

- Companion App source, as of October 2026:
  - [home-assistant/android](https://github.com/home-assistant/android): `MessagingManager.kt`, `NotificationFunctions.kt`
  - [home-assistant/iOS](https://github.com/home-assistant/iOS), app version 2026.10.0: `HandlerLiveActivity.swift`,
    `HALiveActivityAttributes.swift`, `LiveActivityRegistry.swift` and the widget views in
    `Sources/Extensions/Widgets/LiveActivity/`
- Home Assistant Core `mobile_app` and the push relay [home-assistant/mobile-apps-fcm-push](https://github.com/home-assistant/mobile-apps-fcm-push)
- Supernotify's source, `transports/mobile_push.py` especially
- Platform docs:
  - Android: [Live Updates](https://developer.android.com/develop/ui/views/notifications/live-update) and
    [Wear OS Live Updates](https://developer.android.com/training/wearables/notifications/live-updates), with the
    AOSP source of Android 16 QPR2 for the status bar chip
  - Apple: [Displaying live data](https://developer.apple.com/documentation/activitykit/displaying-live-data-with-live-activities)
    and [ActivityKit push notifications](https://developer.apple.com/documentation/activitykit/starting-and-updating-live-activities-with-activitykit-push-notifications)
- Companion docs: [Live Activities and Live Updates](https://companion.home-assistant.io/docs/notifications/live-activities),
  [Basic notifications](https://companion.home-assistant.io/docs/notifications/notifications-basic) and
  [Notification details](https://companion.home-assistant.io/docs/notifications/notification-details)
- Tests by hand on a Samsung Galaxy S26 Ultra, Android 16 / One UI 8, Home Assistant 2026.9.4, with Supernotify,
  in October 2026. Results from these are marked *Tested*. There was no iPhone to hand, so iOS results come from
  the source and docs only

Where the Companion docs and the app source disagree, the source is followed and the difference is noted.

## At a glance

| | Android 16+ | Android 7 to 15 | iOS 17.2+ | iOS 18+ |
| --- | --- | --- | --- | --- |
| What a cycle shows | A Live Update: pill on the Lock Screen and in the shade, and a status bar chip | An ordinary notification with progress bar and timer | A Live Activity on the Lock Screen and in the Dynamic Island | The same, and on Apple Watch. CarPlay from iOS 26 |
| Progress bar | Yes | Yes | Yes | Yes |
| Time left, counting down by itself | Yes | Yes | Yes | Yes |
| Start alerts | Yes, with sound, in its own channel | Yes | Yes. Whether with sound is not known | The same |
| Updates quiet | `alert_once` | `alert_once` | `silent` | `silent` |
| Stays when tapped | With `sticky` | With `sticky` | Always | Always |
| Can be swiped away | Yes | Yes | Yes | Yes |
| Closed at the end | `clear_notification` | `clear_notification` | `clear_notification` | `clear_notification` |

## How a payload reaches the phone

- **Android**: Home Assistant passes the data to the relay, which sends an FCM data message. The app builds an
  ordinary notification from every field it knows. On Android 16 or later, `live_update` also makes it ongoing and
  asks for it to be promoted to a Live Update. Core has no Android specific logic for `live_update`.
- **iOS**: Core picks the token and whether it's a start, an update or an end (`mobile_app/live_activity`), and the
  relay builds the ActivityKit push. Updates go to the activity's own push token once the app has reported it.
  Until then, each one is sent as another push-to-start, which always alerts and ignores `silent`, so the first
  quiet update straight after the start may alert as well. `clear_notification` with the tag ends it, with an alert
  of its own carrying the title. The app's field names were chosen to mirror Android's, so the same payload works
  on both.
- **Local push**: on the home network, Core sends over the app's own connection first, and falls back to the relay
  after 10 seconds without a confirmation.
  - Android handles it exactly like a push from the relay.
  - On iOS the extension that receives local push can't start a Live Activity, so it is queued until the app is next
    open, while Core falls back to the relay after the 10 seconds. A second start for the same tag is merged, and
    the app keeps the newest activity.
  - Local push doesn't count towards the relay's daily limit.

| Stage | Android | iOS (17.2+) |
| --- | --- | --- |
| Start | Notification with `tag`, promoted on Android 16+ | Live Activity started by push-to-start |
| Update | Same `tag` replaces the notification | Same `tag` updates the activity through its own token |
| End | `message: clear_notification` with the `tag` cancels it | `message: clear_notification` with the `tag` ends the activity at once |

## Field by field

**Sent** is what the integration sends after this change.

| Field | Android | iOS | Sent | Notes |
| --- | --- | --- | --- | --- |
| `tag` | Notification id, same tag replaces | Activity id. Only `[A-Za-z0-9_-]`, at most 64 characters, or the activity is refused | Yes, as Supernotify's `mobile_push_notification_tag` | `appliance_<entry_id>` fits |
| `live_update` | Ongoing, and promoted on Android 16+ | Starts or updates a Live Activity | Yes | |
| `title` | Set on every notification | Shown as the latest one sent, though the docs still say it is fixed at the start | Yes, the start title on the start and every update, with what the *Live Activity shows* after it in quiet updates that have a timer, as much as fits | An older iOS app keeps the title it started with |
| `message` | Body text | Body text, replaced by the timer on the Lock Screen | Yes | In quiet updates what the *Live Activity shows*, or the percentage when there's nothing to show or when, with a timer, it's in the title |
| `progress`, `progress_max` | `setProgress()` | Bar and percentage, only with both set | Yes, when reported | *Tested* |
| `chronometer`, `when` | Counts down to `when`, then up into negatives | Counts down to `when`, then up | Yes, when a finish time is reported, unless *Live Activity timer* is off | *Tested*, see Time left |
| `when_relative` | `when` as seconds from now | The same, and a negative value counts up to a stop | No | Home Connect gives an absolute time |
| `critical_text` | Status bar chip text, which wins over the timer | Trailing value: wins over the percentage, loses to the timer in the Dynamic Island | Yes, the percentage, only when there's no finish time | *Tested*, see Status bar chip |
| `notification_icon` | Small icon, a white MDI glyph, in the status bar and chip | Icon on every view | Yes, from the appliance name | |
| `notification_icon_color` | Accent colour, read before `color` | Icon, icon box and progress bar colour. HA blue when unset | No | *Tested*: on One UI, with the developer option below, colours the chip and tints the pill. Without it, no effect. See Options |
| `color` | Accent colour, when `notification_icon_color` isn't set | Not used by Live Activities | No | |
| `icon_url` | Large icon, on the right | On ordinary notifications, makes it a communication notification with the image as sender avatar | No | *Tested*, see Icons |
| `image` | Big picture, which stops promotion | Attachment | No | Promotion only allows no style, BigText, Call, Metric or Progress styles |
| `url` | Not read | Opens on a tap. Needed on every update | Yes, with a dashboard chosen, by Supernotify from a notification level action | |
| `clickAction` | Opens on a tap, `/` when missing | Not read | Yes, with a dashboard chosen, by Supernotify from a notification level action | |
| `silent` | Not read | Quiet update at push priority 5, which doesn't use the update budget but may be delayed | Yes, on progress only updates | No effect on a start |
| `alert_once` | Sound only on the first post of a tag | Not read | Yes, on progress only updates | *Tested* |
| `channel` | Channel, made on first use | Not read | Yes, `Appliances` | *Tested*, see Sound |
| `importance` | Channel importance, fixed once the channel exists | Not read | Yes, `high` | Never `min`, which stops promotion |
| `sticky` | Without it, a tap dismisses the notification | Not read | Yes | *Tested*, see Tapping |
| `persistent` | Ongoing, needs `tag` | Not read | No | Already ongoing on Android 16+. Would stop Android 7 to 15 users swiping it away |
| `timeout` | Removes the notification after so many seconds | Not read | No | |
| `group` | Groups notifications. A group summary can't be promoted | Thread | No | |
| `visibility` | Lock Screen privacy, `public`, `private` or `secret` | Not read | No | |
| `priority`, `ttl` | FCM priority and time to live | Not read | No | Through Supernotify they need other names, see Delivery |
| `relevance_score` | Not read | Orders several activities. The highest takes the Dynamic Island | No | See Options |
| `progress_bar_color`, `progress_bar_direction`, `background_color`, `text_color` | Not read | Appearance | No | A countdown bar drains by default, a progress bar fills |

## Where it shows

### Android 16, One UI 8 (*Tested*)

- **Lock Screen and shade**: a pill with the app icon on the left, then the title with the timer beside it,
  then the bar and the message. This is all there is without the developer option below.
- **Status bar chip**: the small icon and one of these, in this order:
  1. `critical_text`;
  2. the countdown, when `chronometer` and `when` are set;
  3. nothing more.

  There is one chip at a time, for the Live Update created last. An update to an older one doesn't take the chip
  back, whether quiet or with a sound. Only clearing it and posting it again does, which alerts like a new start
  and on iOS uses up the push-to-start budget, so it isn't done. With two appliances running, the chip shows the
  one that started last. When its Live Update goes, another takes its place. The chip hides while the Home
  Assistant app is open.
- **Now Bar**: the Live Update also shows in the Now Bar at the bottom of the Lock Screen, with the app icon, the
  title and the message. Several take turns there.
- **Colour**: the chip is coloured with `notification_icon_color`, and the pill's background is tinted with it.
  Stock Android uses theme colours for the chip.
- The status bar chip, the Now Bar and the colour all need the developer option *Live notifications for all apps*,
  see below. *Tested* both ways.
- **AOD**: not checked.
- **Watch**: *Tested* on a Galaxy Watch Ultra. Both a Live Update and an ordinary notification reach the watch, but
  only while the phone is locked: Galaxy Wearable doesn't pass notifications on while the phone is in use, which is
  its default. How the watch showed the bar and timer wasn't recorded. From Wear OS 7, Android can bridge Live
  Updates as such, though "OEMs can set their own configuration", and the Companion's Wear app has nothing for them.

### iOS (source)

| Where | What it shows |
| --- | --- |
| Lock Screen, and the banner on iPhones without a Dynamic Island | Icon in a tinted box, title, message or timer, the trailing value, and the bar |
| StandBy | The Lock Screen view, scaled up |
| Dynamic Island, compact | Icon, and the timer, else `critical_text`, else the percentage |
| Dynamic Island, minimal | Icon |
| Dynamic Island, expanded | Icon, title, message, trailing value and bar |
| Apple Watch Smart Stack (iOS 18+) and CarPlay (iOS 26+) | A layout of its own: icon, title, message, trailing value, and the bar or timer |
| Mac, paired with the iPhone | Apple shows the Dynamic Island views there. Nothing specific in the app. Not checked which versions |

## Behaviour that differs, and what the payload does about it

### Sound

*Tested*: a Live Update in the Companion's default `General` channel arrives silently, even as a new tag without
`alert_once`. An ordinary notification in the same channel sounds, and so does the same Live Update in a new channel
with `importance: high`. Neither Android's docs nor its source has a rule that explains this, so it may be One UI's.

Android fixes a channel's sound and importance when it is made, and only the user can change them afterwards, so
the name `Appliances` must not change, or a new channel is made beside it.

On iOS a push-to-start always alerts, though the relay's alert has no `sound` key, so whether it makes a sound is not
known. Updates alert only without `silent`.

### Tapping

*Tested*: without `sticky`, a tap opens Home Assistant and dismisses the Live Update. The next progress update then
posts it as a new notification, which sounds. With `sticky: true` it stays, as a Live Activity does on iOS. Either
can still be swiped away.

### Status bar chip

*Tested*: the chip shows `critical_text` in place of the timer when both are set. The countdown is the more useful of
the two, so `critical_text` is only sent with no finish time, as the percentage. Android shows the whole text only up
to about 7 characters, and a longer one can leave the chip with only its icon, so a program name such as
"Intensive 70ºC" won't do. The program stays in the message instead.

On iOS this costs nothing. With a timer, the Dynamic Island shows the timer anyway. Without one, the percentage is
also what iOS shows when there's no `critical_text`.

### Time left

*Tested*: once `when` has passed, Android carries on counting into negative times such as `-37:09`, and iOS counts up.
That only happens here if a cycle runs on past its finish time without Home Connect moving it, since every update
sends the latest finish time.

### Title

Android sets the title on every notification. iOS used to keep the one the activity started with, and the docs
still say so, but the current app shows the latest. The integration always sends the start title.

### Icons

The small icon (`notification_icon`) is the one both platforms show. On One UI the big icon on the left of the pill
is always the app's own, and `icon_url` only adds an image on the right, so it isn't sent.

## What the user can change on the phone

| Setting | Platform | Effect |
| --- | --- | --- |
| Home Assistant app → Notifications → *Appliances* | Android | Sound, vibration and importance of every appliance notification, kept from then on |
| Live Updates per app (`ACTION_MANAGE_APP_PROMOTED_NOTIFICATIONS`) | Android 16 | Turning it off leaves ordinary notifications |
| Galaxy Wearable → Notifications | Galaxy Watch | Home Assistant must be on. By default the watch gets nothing while the phone is in use |
| Developer options → *Live notifications for all apps* | One UI 8 | *Tested* both ways: without it there's no status bar chip, no Now Bar and no colour for Home Assistant, though the pill, bar and timer show. Samsung gives apps the chip and the Now Bar through its own allowlist, so this is the only way for Home Assistant. One UI 8.5 is said to add a Live notifications settings page |
| Settings → Home Assistant → Live Activities | iOS | Off, and no Live Activity starts, silently |
| Settings → Home Assistant → More Frequent Updates | iOS | Raises the update budget. The app asks for it |
| Companion app → Settings → Live Activities | iOS | Shows both settings above, the activities running, and ends them all |
| iPad | iOS | Apple lists iPad as supported, and nothing in the app's start path rules it out. The Companion docs contradict themselves. Not tested |

## Delivery limits and reliability

- **The relay allows 500 pushes a day per phone**, reset at midnight UTC. Live Activity starts, updates and ends
  all count, as does every Android push except commands like `clear_notification`. Local push doesn't count.
  - A cycle uses about 18 per phone, so several cycles a day are fine.
  - When the limit is reached, the phone gets one "Notifications Rate Limited" push. After that Core only logs a
    warning, which Supernotify doesn't see, so no snooze or repair follows.
- **Android FCM priority is `normal` by default**, which a dozing phone may hold back. The fix is FCM priority
  `high`, optionally with `ttl: 0`, which means deliver now or drop, so an update the phone can't take at once is
  lost.
  - Through Supernotify these must be `mobile_push_critical_priority: high` and `mobile_push_critical_ttl: 0`.
  - A `priority` key in the data is taken as Supernotify's own priority and never reaches the phone.
- **iOS budgets**:
  - Updates at priority 10 use an hourly budget.
  - Push-to-start has a budget of its own, and starts fail silently once it's used up, recovering over minutes to
    hours.
  - Activities end after 8 hours, and can stay on the Lock Screen 4 hours more.
  - The app marks an activity stale 2 seconds after its finish time, or 30 minutes after its last update when it has
    no timer.
  - A payload is limited to 4 KB.
- *Tested*: a few pushes were sent without any error and never reached the app at all: some progress updates,
  and one update that the app's own notification history shows was never received. No limit was reached, and
  nothing in Core's log explains it.
- *Tested*, on One UI: three times, the second of two Live Updates closed a few seconds apart stayed on screen, pill
  and chip, with the option for all apps on and off. The app's notification history shows each `clear_notification`
  was received. A later update with the same tag also reached the app but didn't change what was shown, so what stays
  is no longer the app's notification but something left behind by One UI, which only a swipe removes. A possible
  cause in the app was also looked at: when cancelling, it treats a notification left alone in a group it doesn't
  recognise as that group's and cancels the group instead. That isn't confirmed. Two appliances finishing within
  seconds of each other could hit this.

## Supernotify

- **`mobile_push_*` keys** are Supernotify's own, turned into the Companion's fields. Every other key in
  `extra_data` is passed on. The relay sends Android only the keys it knows, as strings, so `url`, `silent` and
  `relevance_score` never reach it, and each app ignores what's left of the other's. There's no way to send a field
  to one platform only, and no need.
- **Priority**: `critical` is the only priority that changes anything on Android. It switches to the alarm stream
  channel with FCM priority `high`. On iOS each priority sets an interruption level, which applies to ordinary
  notifications only: the relay's Live Activity pushes never set one.
- **Action buttons**: actions from the `action_groups` of enabled scenarios are added to every push, so they show
  as buttons on the Android Live Update. Limiting the scenarios with `constrain_scenarios` in the call leaves them
  out, as can a delivery's `data_keys_select`.
- **Repeats**: Supernotify's duplicate check ignores digits, so `force_resend` is needed for progress updates, and
  is sent.

## What gets sent

A start, as Supernotify is asked to send it:

```yaml
action: supernotify.notify
data:
  title: Dishwasher
  message: Dishwasher started
  extra_data:
    mobile_push_notification_tag: appliance_01K...
    live_update: true
    notification_icon: mdi:dishwasher
    channel: Appliances              # Android
    importance: high                 # Android
    sticky: true                     # Android
    progress: 0                      # when progress is reported
    progress_max: 100
    chronometer: true                # when a finish time is reported
    when: 1791566212
    # critical_text: "0%"            # only with progress and no finish time
  actions:                           # with a dashboard chosen
    - level: notification            # sent as url to iOS and clickAction to Android
      uri: /dashboard-kitchen
```

Progress updates are of two kinds:

- **Quiet**, the usual: `silent: true` for iOS and `alert_once: true` for Android, with what the appliance is doing as
  the message, such as the program, or an oven's temperature, else the percentage, to mobile push deliveries only.
- **Ordinary**, at each 10% with *Notify progress* on: "N% complete" as the message, to every delivery, without
  `silent` or `alert_once`.

With *Notify start* off, as it is unless changed, the start is sent as a quiet update too, to phones only. It still alerts on the phone,
though: `alert_once` only quiets later posts of a tag on Android, and a push-to-start on iOS always alerts.

The end is `mobile_push_clear_notification: true` with the same tag and the end title, then an ordinary end
notification with the appliance's icon, which is left out if the cycle was aborted or failed, or *Notify end* is
off.

## Options

Possible settings, each worth having only if someone asks for it.

| Option | Now | Why |
| --- | --- | --- |
| Colour per appliance | None, so HA blue | *Tested*: tells the chip and the pill apart on One UI with the developer option, and colours the icon and bar on iOS. Could be chosen from the name, like the icon |
| Progress steps | 5%, then 2% from 90% | Fewer updates on iOS, finer on Android |
| FCM priority `high` for updates | Off | For phones that hold back updates while dozing. Not yet shown to be needed |
| `relevance_score` | None | With two appliances running, the one finishing first could take the Dynamic Island |
| `persistent` | Off | Stops Android 7 to 15 users swiping the notification away |

## Open questions

1. **Doze.** No delay was seen with the screen off for a few minutes. A real cycle with the phone left alone
   would show whether the bar falls behind, and whether FCM priority `high` is worth sending.
2. **Lost pushes and left over Live Updates.** Some pushes never reached the app, with no error anywhere, and on One UI
   a Live Update closed straight after another can stay on screen. The cause of neither is known. The Companion's
   *Active notification count* sensor lists the notifications the app still has, by tag, so would tell the two
   apart.
3. **Companion App.** Two changes there would help every integration:
   - **Android 16's `ProgressStyle`**: segments for a cycle's phases, points at the changes, and the appliance's icon
     travelling along the bar. HA already uses a version of the Android libraries that has it.
   - **Docs**: on iOS, the title updates and `critical_text` wins over the percentage.

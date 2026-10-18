---
title: What's New
---
# 0.9.0
## ✨ Enhancements
- Power monitors automatically detected and icons assigned for common usage, for example if its a 'Washing Machine Plug'
## 📝 Other changes
- With a dashboard chosen, where a tap on a notification goes is now sent as a Supernotify [notification level action](https://supernotify.rhizomatics.org.uk/usage/mobile_actions/#notification-level-actions)
  - Supernotify sends as `url` to iOS and `clickAction` to Android.
  - Supernotify can also use this tap-thru URL for other notifications that support it, including *HTML5 Push*, *gotify* and *ntfy*
  - Needs Supernotify 2.14.0 or later. Earlier versions will
  ignore the URL, but everything else work
- Supernotify `2.14.0` is the recommended minimum version.
  - Recent versions also have changes not to log when AutoNotify sends scenarios that haven't been configured.


# 0.8.3
## 🐛 Fixes
- Cross compatibility with `voluptuous` and `probatio` to be
able to support Home Assistant from 2026.4 to 2026.10
- Automated build now covers the full range of HA versions

# 0.8.2
## 🐛 Fixes
- Consistent naming as `appliance_autonotify`. No functional change.

# 0.8.1
## ✨ Enhancements
- Original Home Assistant [context](https://data.home-assistant.io/docs/context/) now propagated onto all downstream notification calls, so can be traced easily for example in State history

# 0.8.0
## ✨ Enhancements
- The progress bar of the Live Activity is updated every 5%, rather than every 10%. Notifications of progress, where *Notify progress* is on, are still every 10%
- *Notify start* is now off unless switched on, so the start only opens the Live Activity, silently and on phones. An appliance whose switch has never been changed follows the new default, so switch it on to keep the start notification, which is otherwise no longer sent at all without Supernotify
- *Program in title* switch in the settings of each appliance, with Supernotify, on unless changed. The program is shown beside the name on a Live Activity with a time left, such as "Dishwasher · Intensive 70ºC", since the iOS Lock Screen shows the timer in place of the message, which is where the program was. Switch it off for program names too long to fit
- `{program}` template variable available in *Advanced* to customize the title or message of the start and the end is replaced by the program, as Home Assistant shows it in state view
## 🐛 Fixes
- The Live Activity is no longer left with no progress bar and no program name until the next step of progress. The first progress came within moments of the start, and could reach a phone ahead of it, so is now held back for 5 seconds

# 0.7.1
## ✨ Enhancements
- Action buttons now at the end of a cycle, to mark it as finished (you've emptied the dishwasher, taken out the pie), remind later, or for switchable power monitors only, switch off the plug
- The buttons are now *Finished*, *Remind Later* and *Switch Off*
- *Reminder repeats* setting for how many times the end is sent again, 3 unless changed
- *Switch Off button* setting for a power monitored appliance, to leave the button off the end notification for a smart plug that should stay on. The button is also left off where the smart plug chosen no longer exists
  - Actions can be tuned in the integration settings page
  - Supernotify is required for actions (`notify.send_message` maxes out at a message field)

# 0.7.0
## ✨ Enhancements
- Power monitored appliances can now have a minimum time to run, as well as wattage, to trigger start of a cycle
- Action buttons now to acknowledge end of a cycle or ask for reminder later, e.g. to empty the washing machine
## 🐛 Fixes
- An appliance that is `ready` for a moment and then running again, as an oven is when it starts or has its settings changed, is the same cycle rather than one finished and another started. One left `ready` is finished after 10 seconds
- The start and end notifications are no longer dropped by Supernotify as repeats when a cycle follows soon after another, which left the second cycle with no Live Activity
- An oven switched off before it's up to heat is no longer told of as pre-heated, Home Connect reporting pre-heating finished as it goes off

# 0.6.1
## 📝 Other changes
Package naming consistency and auto build

# 0.6.0
## ✨ Enhancements
- *Notify start* and *Notify end* switches in the settings of each appliance, both on by default. With either off, the Live Activity is still opened and closed, silently and on phones only
- *Notify phases* switch in the settings of an oven, on by default, for the notification that it's up to heat
- The icon follows the type of Home Connect appliance, whatever it has been named, and is on the end notification as well as the Live Activity
- The program an appliance is set to is used where it reports none under way, as an oven does
- An oven warming up, on any program, has a progress bar of its temperature against the one it's set to, with "Pre-heating" or "Fast pre-heat" and both temperatures as the message. Once up to heat "Oven is pre-heated" is sent as a notification of its own, the Live Activity goes on to the program and temperature, such as "Pizza setting, 200°C", and it isn't taken to be warming up again until it has been off

# 0.5.0
## 📝 Other changes
Preparation for HACS release

# 0.4.0
## ✨ Enhancements
- Progress bar updated every 2% for the last 10% of the cycle
- Live Activity updates have the program under way as their message, where the appliance reports one
- *Dashboard to open* in the settings of each appliance, chosen from the dashboards in Home Assistant, for a tap on a notification or the Live Activity
## 📝 Other changes
- Add icons

# 0.3.1
## ✨ Enhancements
- *Notify progress* switch in the settings of each appliance, above the sections and off by default, to be sent a notification every 10% of the cycle. The Live Activity is silently updated either way

# 0.3.0
## ✨ Enhancements
- Simpler install: one screen with a switch for automatic discovery, on by default, which sets up every appliance found now and later with no settings to fill in
- *Automatic discovery* is listed on the integration's page with the appliances, where the switch can be changed
- With automatic discovery off, a discovered appliance is added with a single confirmation
- A power monitored appliance is added with one form, from *Add service*
- Settings are in three closed sections: start message, end message and notification targets
- Titles and messages are shown as they'll be sent, "Dishwasher started", with no `{name}` template
- Without Supernotify, targets are optional, defaulting to every phone with the Home Assistant app

# 0.2.2
## ✨ Enhancements
- Progress bar updated as soon after creation as possible, when the appliance first reports it

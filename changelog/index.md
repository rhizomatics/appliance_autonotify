# 0.6.1

Source: https://appliances-autonotify.rhizomatics.org.uk/changelog/

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

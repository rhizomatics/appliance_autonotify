
# Home Assistant Integration

Follow the [policy from HQ on Home Assistant usage](./rfcs/index.md).

# Auto Notify vs Supernotify

Logic and config belongs in Auto Notify where its unique to the domain.

Any logic that is specific to appliance types, or integration platforms like Home Connect, should not be in Supernotify.

## Pass the Facts On

Auto Notify passes what it knows as facts to Supernotify as `data` on each `supernotify.notify` call, such as the
appliance details, phase, state, ETA, priority and manually selected scenarios.
Supernotify's scenario conditions can then
match those facts, as `notification_data`, when deciding how a notification is delivered
rather than matching the wording of the message, which changes with phrasing
and with translation.

Supernotify needs no knowledge of what the facts mean, so this keeps domain logic out of it while still letting
delivery depend on the domain.

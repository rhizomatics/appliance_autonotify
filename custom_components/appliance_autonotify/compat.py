"""Schema validation library, for the range of Home Assistant versions supported

Home Assistant 2026.10 replaced voluptuous with probatio, aliasing `voluptuous` to it at runtime
so that `import voluptuous` carries on working. Earlier versions, supported here until they are
more than 6 months old, only have voluptuous.

Home Assistant 2026.8 also gave each device a single config entry, with devices of different entries linked by the
identifiers and connections they share. Before that, the same identifiers would add the entry to the appliance's own
device, so an appliance's device is only made where devices are linked, and earlier versions go without it.

So voluptuous is still what is imported at runtime, whichever library that turns out to be, while
type checking is against probatio, since that is what the current Home Assistant type hints expect.
"""

from typing import TYPE_CHECKING

from homeassistant.helpers import device_registry as dr

if TYPE_CHECKING:
    import probatio as vol
else:
    import voluptuous as vol

# only there once a device belongs to a single config entry
LINKED_DEVICES: bool = hasattr(dr.DeviceRegistry, "async_get_device_by_identifier")


def all_devices(registry: dr.DeviceRegistry) -> list[dr.DeviceEntry]:
    """Every device, which iterating the registry's devices gives in later releases, where before it gave their ids, the
    mapping now deprecated"""
    return [
        device if isinstance(device, dr.DeviceEntry) else registry.devices[device]  # type: ignore[index,unused-ignore]
        for device in registry.devices
    ]


__all__ = ["LINKED_DEVICES", "all_devices", "vol"]

"""The device of each appliance's entry, alongside the device Home Assistant already has for it"""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.appliance_autonotify.compat import LINKED_DEVICES
from custom_components.appliance_autonotify.const import DOMAIN
from tests.ha_testing import MockConfigEntry

from .conftest import add_appliance, setup_watcher

pytestmark = pytest.mark.skipif(not LINKED_DEVICES, reason="Home Assistant before devices were linked")


def entry_device(hass: HomeAssistant, entry: MockConfigEntry) -> dr.DeviceEntry:
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1
    return devices[0]


async def test_device_is_linked_to_the_appliance(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    registry = dr.async_get(hass)
    kitchen = ar.async_get(hass).async_create("Kitchen")
    registry.async_update_device(appliance.device_id, area_id=kitchen.id, manufacturer="Bosch", model="SMV6ZCX42E")
    entry = await setup_watcher(hass, appliance)

    device = entry_device(hass, entry)
    assert device.id != appliance.device_id
    assert (device.name, device.manufacturer, device.model, device.area_id) == (
        "Dishwasher",
        "Bosch",
        "SMV6ZCX42E",
        kitchen.id,
    )
    # the same hardware, by the identifier they have in common, so each is a linked device of the other
    assert device.identifiers == {("home_connect", "BOSCH-1")}
    assert {d.id for d in registry.async_get_devices(identifiers=device.identifiers)} == {
        device.id,
        appliance.device_id,
    }

    # and the same one again once reloaded
    assert await hass.config_entries.async_reload(entry.entry_id)
    assert entry_device(hass, entry).id == device.id


async def test_device_goes_with_its_entry(hass: HomeAssistant) -> None:
    appliance = add_appliance(hass)
    entry = await setup_watcher(hass, appliance)
    device_id = entry_device(hass, entry).id

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert dr.async_get(hass).async_get(device_id) is None
    # leaving the appliance's own
    assert dr.async_get(hass).async_get(appliance.device_id) is not None


async def setup_power(hass: HomeAssistant, plug: bool) -> tuple[MockConfigEntry, str | None]:
    plug_id: str | None = None
    if plug:
        source = MockConfigEntry(domain="shelly")
        source.add_to_hass(hass)
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=source.entry_id, identifiers={("shelly", "plug-1")}, name="Washer Plug"
        )
        plug_id = device.id
        er.async_get(hass).async_get_or_create(
            "sensor", "shelly", "plug-1-power", suggested_object_id="washer_power", device_id=device.id
        )
    # once the sensor is registered, which would otherwise be given another entity id
    hass.states.async_set("sensor.washer_power", "0", {"unit_of_measurement": "W"})
    entry = MockConfigEntry(
        domain=DOMAIN, title="Washer", data={"type": "power"}, options={"power_entity": "sensor.washer_power"}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, plug_id


async def test_power_monitored_device_is_connected_through_the_plug(hass: HomeAssistant) -> None:
    entry, plug_id = await setup_power(hass, plug=True)

    device = entry_device(hass, entry)
    # other hardware, so not linked, but what the appliance is connected through
    assert device.name == "Washer"
    assert device.identifiers == {(DOMAIN, entry.entry_id)}
    assert device.via_device_id == plug_id
    assert device.manufacturer is None


async def test_power_monitored_device_without_a_plug(hass: HomeAssistant) -> None:
    entry, _ = await setup_power(hass, plug=False)

    device = entry_device(hass, entry)
    assert (device.name, device.identifiers, device.via_device_id) == ("Washer", {(DOMAIN, entry.entry_id)}, None)

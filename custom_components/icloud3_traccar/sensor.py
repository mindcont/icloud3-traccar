"""A separate status entity, with no credentials, names or coordinates."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([StatusSensor(hass.data[DOMAIN][entry.entry_id], entry.entry_id)])


class StatusSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "sync_status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:map-marker-check"
    _attr_should_poll = False

    def __init__(self, coordinator, entry_id):
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry_id}_sync_status"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)}, "name": "iCloud3 Traccar",
            "manufacturer": "iCloud3", "model": "Optional Traccar bridge",
        }

    async def async_added_to_hass(self):
        self.coordinator.notify = self.async_write_ha_state

    async def async_will_remove_from_hass(self):
        self.coordinator.notify = lambda: None

    @property
    def native_value(self):
        if not self.coordinator.config["enabled"]:
            return "disabled"
        return self.coordinator.data["connection"]

    @property
    def extra_state_attributes(self):
        return self.coordinator.status()

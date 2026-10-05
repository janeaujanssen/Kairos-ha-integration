from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    async_add_entities([DummySetpointSensor(entry)])


class DummySetpointSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Dummy Setpoint"
    _attr_should_poll = False
    _attr_native_value = 20.0

    def __init__(self, entry: ConfigEntry) -> None:
        self._attr_unique_id = entry.entry_id
        start_time = datetime.now().astimezone()
        self._forecast = [
            {
                "time": (start_time + timedelta(hours=hours)).isoformat(),
                "forecast_value": value,
            }
            for hours, value in ((1, 18.5), (2, 19.0), (3, 19.4))
        ]

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return {"forecast": self._forecast}
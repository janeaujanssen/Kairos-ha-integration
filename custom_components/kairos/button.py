"""Button entity to run a Kairos optimization manually."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import KairosCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up the run optimization button."""
    runtime: KairosCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([KairosRunOptimizationButton(runtime, entry)])


class KairosRunOptimizationButton(ButtonEntity):
    """Run an immediate optimization for this config entry."""

    _attr_has_entity_name = True
    _attr_name = "Run optimization"

    def __init__(self, runtime: KairosCoordinator, entry: ConfigEntry) -> None:
        self.runtime = runtime
        self._attr_unique_id = f"{entry.entry_id}_run_optimization"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_system")},
            name="Kairos",
            manufacturer="Kairos",
            configuration_url=runtime.config["api_url"],
        )

    async def async_press(self) -> None:
        """Run an optimization immediately."""
        await self.runtime.async_run_optimization()

"""Switches that include or exclude an asset from the optimization."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, ENABLEABLE_ASSET_TYPES
from .coordinator import KairosCoordinator
from .entity import KairosInput


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: Any
) -> None:
    runtime: KairosCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        KairosEnabledSwitch(runtime, entry, asset)
        for asset in runtime.assets
        if asset["asset_type"] in ENABLEABLE_ASSET_TYPES
    )


class KairosEnabledSwitch(KairosInput, SwitchEntity):
    """Whether the asset is part of the optimization."""

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(
        self, runtime: KairosCoordinator, entry: ConfigEntry, asset: dict[str, Any]
    ) -> None:
        super().__init__(
            runtime, entry, asset, "enabled", "Enabled", True, lambda state: state == "on"
        )

    @property
    def is_on(self) -> bool:
        return self._value

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._set(False)

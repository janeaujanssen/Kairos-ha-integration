"""Round-trip distance input for EV batteries."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import KairosCoordinator
from .entity import KairosInput


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: Any
) -> None:
    runtime: KairosCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        KairosRoundTripDistance(runtime, entry, asset)
        for asset in runtime.assets
        if asset["asset_type"] == "ev_battery"
    )


class KairosRoundTripDistance(KairosInput, NumberEntity):
    """Expected round-trip distance of the EV."""

    _attr_native_unit_of_measurement = "km"
    _attr_device_class = NumberDeviceClass.DISTANCE
    _attr_native_min_value = 0
    _attr_native_max_value = 10000
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(
        self, runtime: KairosCoordinator, entry: ConfigEntry, asset: dict[str, Any]
    ) -> None:
        # A value configured before this became an entity is the initial state.
        super().__init__(
            runtime,
            entry,
            asset,
            "round_trip_distance",
            "Round-Trip Distance",
            float(asset.get("round_trip_distance", 100)),
            float,
        )

    @property
    def native_value(self) -> float:
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        self._set(value)

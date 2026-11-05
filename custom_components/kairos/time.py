"""Time-of-day inputs for controllable loads and EV batteries."""

from __future__ import annotations

from datetime import time
from typing import Any

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import KairosCoordinator
from .entity import KairosInput

# asset type -> (key, name, default HH:MM)
_TIMES = {
    "controllable_load": (
        ("earliest_start_time", "Earliest Start Time", "00:00"),
        ("latest_finish_time", "Latest Finish Time", "23:59"),
    ),
    "ev_battery": (
        ("expected_departure_time", "Expected Departure Time", "09:00"),
        ("expected_arrival_time", "Expected Arrival Time", "18:00"),
    ),
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: Any
) -> None:
    runtime: KairosCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        KairosTime(runtime, entry, asset, key, name, default)
        for asset in runtime.assets
        for key, name, default in _TIMES.get(asset["asset_type"], ())
    )


class KairosTime(KairosInput, TimeEntity):
    def __init__(
        self,
        runtime: KairosCoordinator,
        entry: ConfigEntry,
        asset: dict[str, Any],
        key: str,
        name: str,
        default: str,
    ) -> None:
        # A value configured before these became entities is the initial state.
        super().__init__(
            runtime,
            entry,
            asset,
            key,
            name,
            time.fromisoformat(asset.get(key, default)),
            time.fromisoformat,
        )

    @property
    def native_value(self) -> time:
        return self._value

    async def async_set_value(self, value: time) -> None:
        self._set(value)

"""Run start time input for controllable loads."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import KairosCoordinator
from .entity import KairosInput


def _parse(state: str) -> datetime:
    parsed = dt_util.parse_datetime(state)
    if parsed is None:
        raise ValueError(state)
    return parsed


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: Any
) -> None:
    runtime: KairosCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        KairosRunStartTime(runtime, entry, asset)
        for asset in runtime.assets
        if asset["asset_type"] == "controllable_load"
    )


class KairosRunStartTime(KairosInput, DateTimeEntity):
    """Set by the user's automation to the time the device was last turned on."""

    def __init__(
        self, runtime: KairosCoordinator, entry: ConfigEntry, asset: dict[str, Any]
    ) -> None:
        super().__init__(
            runtime, entry, asset, "run_start_time", "Run Start Time", None, _parse
        )

    @property
    def native_value(self) -> datetime | None:
        return self._value

    async def async_set_value(self, value: datetime) -> None:
        self._set(value)

"""Shared entity helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_API_URL, DOMAIN
from .coordinator import KairosCoordinator


def system_device_info(entry: ConfigEntry, runtime: KairosCoordinator) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_system")},
        name="Kairos",
        manufacturer="Kairos",
        configuration_url=runtime.config[CONF_API_URL],
    )


class KairosInput(RestoreEntity):
    """Config entity created by Kairos; its value is read from runtime.inputs when requesting."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        runtime: KairosCoordinator,
        entry: ConfigEntry,
        asset: dict[str, Any],
        key: str,
        name: str,
        default: Any,
        parse: Callable[[str], Any],
    ) -> None:
        self.runtime = runtime
        self._input = (asset["id"], key)
        self._parse = parse
        self._attr_unique_id = f"{entry.entry_id}_{asset['id']}_{key}"
        self._attr_name = f"{asset['name']} {name}"
        self._attr_device_info = system_device_info(entry, runtime)
        runtime.inputs.setdefault(self._input, default)

    @property
    def _value(self) -> Any:
        return self.runtime.inputs[self._input]

    def _set(self, value: Any) -> None:
        self.runtime.inputs[self._input] = value
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore the last value so it survives restarts."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None or last.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        try:
            self.runtime.inputs[self._input] = self._parse(last.state)
        except (TypeError, ValueError):
            pass

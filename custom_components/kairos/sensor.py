"""Sensors exposing Kairos optimization schedules and diagnostics."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_TIME_STEP_MINUTES, DOMAIN, DEFAULT_TIME_STEP_MINUTES
from .coordinator import KairosCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up schedule and diagnostic sensors."""
    runtime: KairosCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        KairosStatusSensor(runtime, entry),
        KairosObjectiveSensor(runtime, entry),
        KairosApiResponseSensor(runtime, entry),
    ]
    for asset in runtime.assets:
        if asset["asset_type"] in (
            "grid",
            "controllable_load",
            "home_battery",
            "ev_battery",
            "dhw_tank",
            "building_thermal_mass",
        ):
            entities.append(KairosSetpointSensor(runtime, entry, asset))
        if asset["asset_type"] == "building_thermal_mass":
            entities.append(KairosModeSensor(runtime, entry, asset))
    async_add_entities(entities)


class KairosSensor(CoordinatorEntity, SensorEntity):
    """Base entity bound to the shared Kairos coordinator."""

    _attr_has_entity_name = True

    def __init__(self, runtime: KairosCoordinator, entry: ConfigEntry) -> None:
        super().__init__(runtime.coordinator)
        self.runtime = runtime
        self.entry = entry

    def _device_info(self, asset: dict[str, Any] | None = None) -> DeviceInfo:
        identifier = asset["id"] if asset else "system"
        name = asset["name"] if asset else "Kairos"
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry.entry_id}_{identifier}")},
            name=name,
            manufacturer="Kairos",
            configuration_url=self.runtime.config["api_url"],
        )


class KairosSetpointSensor(KairosSensor):
    """Current power setpoint with the complete scheduled horizon."""

    _attr_native_unit_of_measurement = "W"

    def __init__(
        self, runtime: KairosCoordinator, entry: ConfigEntry, asset: dict[str, Any]
    ) -> None:
        super().__init__(runtime, entry)
        self.asset = asset
        self._attr_unique_id = f"{entry.entry_id}_{asset['id']}_setpoint"
        self._attr_name = f"{asset['name']} setpoint"
        self._attr_device_info = self._device_info(asset)

    @property
    def native_value(self) -> float | None:
        schedule = self.runtime.coordinator.data["assets"].get(self.asset["id"], {}).get(
            "schedule", []
        )
        point = _active_point(
            schedule,
            self.runtime.config.get(
                CONF_TIME_STEP_MINUTES, DEFAULT_TIME_STEP_MINUTES
            ),
        )
        return point.get("value") if point else None

    @property
    def available(self) -> bool:
        schedule = self.runtime.coordinator.data["assets"].get(self.asset["id"], {}).get(
            "schedule", []
        )
        return _active_point(
            schedule,
            self.runtime.config.get(
                CONF_TIME_STEP_MINUTES, DEFAULT_TIME_STEP_MINUTES
            ),
        ) is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.runtime.coordinator.data
        return {
            "schedule": self.runtime.coordinator.data["assets"]
            .get(self.asset["id"], {})
            .get("schedule", []),
            "time_step_minutes": self.runtime.config.get("time_step_minutes", 15),
            "optimization_id": data.get("last_run"),
            "optimized_at": data.get("last_run"),
        }


class KairosModeSensor(KairosSensor):
    """Building thermal-mass control mode derived from signed power."""

    def __init__(
        self, runtime: KairosCoordinator, entry: ConfigEntry, asset: dict[str, Any]
    ) -> None:
        super().__init__(runtime, entry)
        self.asset = asset
        self._attr_unique_id = f"{entry.entry_id}_{asset['id']}_mode"
        self._attr_name = f"{asset['name']} mode"
        self._attr_device_info = self._device_info(asset)

    @property
    def native_value(self) -> str | None:
        schedule = self.runtime.coordinator.data["assets"].get(self.asset["id"], {}).get(
            "schedule", []
        )
        point = _active_point(
            schedule,
            self.runtime.config.get(
                CONF_TIME_STEP_MINUTES, DEFAULT_TIME_STEP_MINUTES
            ),
        )
        if point is None:
            return None
        value = point["value"]
        return "charge" if value > 0 else "discharge" if value < 0 else "neutral"

    @property
    def available(self) -> bool:
        schedule = self.runtime.coordinator.data["assets"].get(self.asset["id"], {}).get(
            "schedule", []
        )
        return _active_point(
            schedule,
            self.runtime.config.get(
                CONF_TIME_STEP_MINUTES, DEFAULT_TIME_STEP_MINUTES
            ),
        ) is not None


class KairosStatusSensor(KairosSensor):
    """Diagnostic state for the latest optimization cycle."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, runtime: KairosCoordinator, entry: ConfigEntry) -> None:
        super().__init__(runtime, entry)
        self._attr_unique_id = f"{entry.entry_id}_status"
        self._attr_name = "Status"
        self._attr_device_info = self._device_info()

    @property
    def native_value(self) -> str:
        return self.runtime.coordinator.data.get("status", "error")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.runtime.coordinator.data
        return {
            "last_run": data.get("last_run"),
            "duration": data.get("duration"),
            "consecutive_failures": data.get("consecutive_failures", 0),
        }


class KairosObjectiveSensor(KairosSensor):
    """Objective cost from the latest successful optimization."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, runtime: KairosCoordinator, entry: ConfigEntry) -> None:
        super().__init__(runtime, entry)
        self._attr_unique_id = f"{entry.entry_id}_objective_cost"
        self._attr_name = "Objective cost"
        self._attr_device_info = self._device_info()

    @property
    def native_value(self) -> float | None:
        return self.runtime.coordinator.data.get("objective_cost")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "optimization_id": self.runtime.coordinator.data.get("last_run")
        }


class KairosApiResponseSensor(KairosSensor):
    """Expose the latest optimization attempt and any API response."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, runtime: KairosCoordinator, entry: ConfigEntry) -> None:
        super().__init__(runtime, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_api_response"
        self._attr_name = "Last optimization attempt"
        self._attr_device_info = self._device_info()

    @property
    def native_value(self) -> str:
        data = self.runtime.coordinator.data
        if data.get("last_api_status") is not None:
            return f"HTTP {data['last_api_status']}"
        response = data.get("last_api_response")
        if isinstance(response, dict):
            status = response.get("status")
            if isinstance(status, str):
                return f"API {status}" if status.casefold() == "error" else status
            return "Response received"
        if data.get("last_error"):
            return "Request error"
        return "No response"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.runtime.coordinator.data
        return {
            "http_status": data.get("last_api_status"),
            "api_request": data.get("last_api_request"),
            "api_response": data.get("last_api_response"),
            "error": data.get("last_error"),
        }


def _active_point(
    schedule: list[dict[str, Any]], time_step_minutes: int
) -> dict[str, Any] | None:
    """Return the schedule value for the current time step, or None if expired."""
    now = dt_util.utcnow()
    last_time = dt_util.parse_datetime(schedule[-1].get("time", "")) if schedule else None
    if last_time is not None and now >= last_time + timedelta(minutes=time_step_minutes):
        return None
    active: dict[str, Any] | None = None
    for point in schedule:
        point_time = dt_util.parse_datetime(point.get("time", ""))
        if point_time is None:
            continue
        if point_time > now:
            if active is None:
                active = point
            else:
                break
        else:
            active = point
    return active

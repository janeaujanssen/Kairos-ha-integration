"""Sensors exposing Kairos optimization schedules and diagnostics."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_TIME_STEP_MINUTES, DOMAIN
from .coordinator import KairosCoordinator
from .entity import system_device_info

# Inputs, not optimized assets: the optimizer returns no schedule for them.
_NO_SETPOINT_ASSET_TYPES = ("solar", "base_load")

# Optimizer forecasts per asset type: (forecast key, name suffix, unit).
_STORAGE_FORECASTS = (
    ("energy_demand", "Energy Demand Forecast", "Wh"),
    ("passive_discharge_power", "Passive Discharge Power Forecast", "W"),
)
_FORECAST_SENSORS = {
    "grid": (
        ("import_price", "Import Price Forecast", "price/kWh"),
        ("export_price", "Export Price Forecast", "price/kWh"),
    ),
    "solar": (("power", "Production Power Forecast", "W"),),
    "base_load": (("power", "Power Forecast", "W"),),
    "home_battery": _STORAGE_FORECASTS,
    "ev_battery": _STORAGE_FORECASTS,
    "dhw_tank": _STORAGE_FORECASTS,
    "building_thermal_mass": (*_STORAGE_FORECASTS, ("cop", "COP Forecast", None)),
}
# Building thermal mass model parameters returned by the optimizer: (response key, name suffix, unit).
_THERMAL_PARAMETER_SENSORS = (
    ("heat_loss_coefficient", "Heat Loss Coefficient", "W/°C"),
    ("reference_cop", "Reference COP", None),
    ("reference_outdoor_temperature", "Reference Outdoor Temperature", "°C"),
    ("cop_outdoor_temperature_coefficient", "COP Outdoor Temperature Coefficient", "COP/°C"),
)


def _device_class(unit: str | None) -> SensorDeviceClass | None:
    """Device class for units Home Assistant accepts; rate units get none."""
    return {
        "W": SensorDeviceClass.POWER,
        "°C": SensorDeviceClass.TEMPERATURE,
    }.get(unit)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Any,
) -> None:
    """Set up schedule, forecast and diagnostic sensors."""
    runtime: KairosCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        KairosObjectiveSensor(runtime, entry),
        KairosApiResponseSensor(runtime, entry),
    ]
    for asset in runtime.assets:
        if asset["asset_type"] not in _NO_SETPOINT_ASSET_TYPES:
            entities.append(KairosSetpointSensor(runtime, entry, asset))
        if asset["asset_type"] == "building_thermal_mass":
            entities.append(KairosModeSensor(runtime, entry, asset))
            entities.extend(
                KairosThermalParameterSensor(runtime, entry, asset, key, suffix, unit)
                for key, suffix, unit in _THERMAL_PARAMETER_SENSORS
            )
        for key, suffix, unit in _FORECAST_SENSORS.get(asset["asset_type"], ()):
            entities.append(KairosForecastSensor(runtime, entry, asset, key, suffix, unit))
    async_add_entities(entities)


class KairosSensor(CoordinatorEntity, SensorEntity):
    """Base entity bound to the shared Kairos coordinator."""

    _attr_has_entity_name = True

    def __init__(self, runtime: KairosCoordinator, entry: ConfigEntry) -> None:
        super().__init__(runtime.coordinator)
        self.runtime = runtime
        self._attr_device_info = system_device_info(entry, runtime)


class KairosScheduleSensor(KairosSensor):
    """Current value of one asset's schedule, unavailable once the schedule runs out."""

    _schedule_key: str

    def __init__(
        self, runtime: KairosCoordinator, entry: ConfigEntry, asset: dict[str, Any]
    ) -> None:
        super().__init__(runtime, entry)
        self.asset = asset

    def _points(self) -> list[dict[str, Any]]:
        return (
            self.runtime.coordinator.data["assets"]
            .get(self.asset["id"], {})
            .get(self._schedule_key, [])
        )

    def _active_point(self) -> dict[str, Any] | None:
        return _active_point(self._points(), self.runtime.config[CONF_TIME_STEP_MINUTES])

    @property
    def native_value(self) -> float | str | None:
        point = self._active_point()
        return point["value"] if point else None

    @property
    def available(self) -> bool:
        return self._active_point() is not None


class KairosSetpointSensor(KairosScheduleSensor):
    """Current power setpoint with the complete scheduled horizon."""

    _schedule_key = "schedule"
    _attr_native_unit_of_measurement = "W"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, runtime: KairosCoordinator, entry: ConfigEntry, asset: dict[str, Any]
    ) -> None:
        super().__init__(runtime, entry, asset)
        self._attr_unique_id = f"{entry.entry_id}_{asset['id']}_setpoint"
        self._attr_name = f"{asset['name']} Power Setpoint"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"forecast": self._points()}


class KairosModeSensor(KairosScheduleSensor):
    """Building thermal mass heat pump mode: charge (+dT), neutral or discharge (-dT)."""

    _schedule_key = "mode"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["charge", "neutral", "discharge"]

    def __init__(
        self, runtime: KairosCoordinator, entry: ConfigEntry, asset: dict[str, Any]
    ) -> None:
        super().__init__(runtime, entry, asset)
        self._attr_unique_id = f"{entry.entry_id}_{asset['id']}_mode"
        self._attr_name = f"{asset['name']} Mode"


class KairosForecastSensor(KairosScheduleSensor):
    """Optimizer forecast for one asset; state is the current step, Forecast holds the horizon."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        runtime: KairosCoordinator,
        entry: ConfigEntry,
        asset: dict[str, Any],
        key: str,
        suffix: str,
        unit: str | None,
    ) -> None:
        super().__init__(runtime, entry, asset)
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{asset['id']}_{key}_forecast"
        self._attr_name = f"{asset['name']} {suffix}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = _device_class(unit)

    def _points(self) -> list[dict[str, Any]]:
        return self.runtime.coordinator.data["forecasts"].get(self.asset["id"], {}).get(
            self._key, []
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"forecast": self._points()}


class KairosThermalParameterSensor(KairosSensor):
    """Building thermal mass model parameter exactly as the optimizer reports it."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        runtime: KairosCoordinator,
        entry: ConfigEntry,
        asset: dict[str, Any],
        key: str,
        suffix: str,
        unit: str | None,
    ) -> None:
        super().__init__(runtime, entry)
        self.asset = asset
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{asset['id']}_{key}_parameter"
        self._attr_name = f"{asset['name']} {suffix}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = _device_class(unit)

    @property
    def native_value(self) -> float | None:
        parameters = self.runtime.coordinator.data["thermal_parameters"]
        return parameters.get(self.asset["id"], {}).get(self._key)


class KairosObjectiveSensor(KairosSensor):
    """Objective cost from the latest successful optimization."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, runtime: KairosCoordinator, entry: ConfigEntry) -> None:
        super().__init__(runtime, entry)
        self._attr_unique_id = f"{entry.entry_id}_objective_cost"
        self._attr_name = "Objective Cost"

    @property
    def native_value(self) -> float | None:
        return self.runtime.coordinator.data.get("objective_cost")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"optimization_id": self.runtime.coordinator.data.get("last_run")}


class KairosApiResponseSensor(KairosSensor):
    """Expose the latest optimization attempt and any API response."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, runtime: KairosCoordinator, entry: ConfigEntry) -> None:
        super().__init__(runtime, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_api_response"
        self._attr_name = "Last Optimization Attempt"

    @property
    def native_value(self) -> str:
        data = self.runtime.coordinator.data
        if data.get("last_api_status") is not None:
            return f"HTTP {data['last_api_status']}"
        response = data.get("last_api_response")
        if isinstance(response, dict):
            return f"API {response.get('status')}"
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
            "thermal_history": data.get("last_thermal_history"),
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

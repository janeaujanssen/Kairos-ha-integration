"""Build validated API requests from Home Assistant entities and asset settings."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
import math
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util


class EntityDataError(ValueError):
    """A required Home Assistant value is unavailable or invalid."""


def _state(hass: HomeAssistant, entity_id: str, label: str) -> State:
    entity = hass.states.get(entity_id)
    if entity is None or entity.state in ("unknown", "unavailable"):
        raise EntityDataError(f"{label} entity {entity_id} is unavailable.")
    return entity


def _number(state: State, label: str) -> float:
    try:
        value = float(state.state)
    except (TypeError, ValueError) as err:
        raise EntityDataError(f"{label} entity {state.entity_id} is not numeric.") from err
    if not (-1e15 < value < 1e15):
        raise EntityDataError(f"{label} entity {state.entity_id} is outside the valid range.")
    return value


def _power(hass: HomeAssistant, entity_id: str, label: str) -> float:
    state = _state(hass, entity_id, label)
    value = _number(state, label)
    unit = state.attributes.get("unit_of_measurement")
    multipliers = {"W": 1, "kW": 1000, "MW": 1_000_000}
    if unit not in multipliers:
        raise EntityDataError(
            f"{label} entity {entity_id} must use W, kW, or MW (got {unit!r})."
        )
    return value * multipliers[unit]


def _temperature(hass: HomeAssistant, entity_id: str, label: str) -> float:
    state = _state(hass, entity_id, label)
    value = _number(state, label)
    unit = state.attributes.get("unit_of_measurement")
    if unit in ("°C", "C"):
        return value
    if unit in ("°F", "F"):
        return (value - 32) * 5 / 9
    raise EntityDataError(
        f"{label} entity {entity_id} must use Celsius or Fahrenheit (got {unit!r})."
    )


def _soc(hass: HomeAssistant, entity_id: str, label: str) -> float:
    state = _state(hass, entity_id, label)
    value = _number(state, label)
    unit = state.attributes.get("unit_of_measurement")
    if unit == "%":
        value /= 100
    if not 0 <= value <= 1:
        raise EntityDataError(f"{label} entity {entity_id} must be between 0 and 100%.")
    return value


def _forecast(
    hass: HomeAssistant,
    entity_id: str | None,
    attribute: str | None,
    current_value: float,
    steps: int,
    label: str,
    conversion: str,
    start_time: datetime,
    step_minutes: int,
    required: bool = False,
) -> list[float]:
    if not entity_id or not attribute:
        if required:
            raise EntityDataError(f"{label} forecast entity and attribute are required.")
        return [current_value] * steps
    state = _state(hass, entity_id, label)
    raw = state.attributes.get(attribute)
    if not isinstance(raw, (list, tuple)) or not raw:
        raise EntityDataError(
            f"Forecast attribute {attribute!r} on {entity_id} is missing or empty."
        )

    values: list[float] = []
    timed_values: list[tuple[datetime, float]] = []
    has_timestamps = False
    unit = state.attributes.get("unit_of_measurement")
    for point in raw:
        point_time: datetime | None = None
        if isinstance(point, dict):
            time_value = next(
                (
                    point[key]
                    for key in (
                        "time",
                        "datetime",
                        "period_start",
                        "start_time",
                        "timestamp",
                        "date",
                    )
                    if key in point
                ),
                None,
            )
            if time_value is not None:
                has_timestamps = True
                point_time = dt_util.parse_datetime(str(time_value))
                if point_time is None:
                    raise EntityDataError(
                        f"Forecast attribute {attribute!r} on {entity_id} contains an invalid timestamp."
                    )
                if point_time.tzinfo is None:
                    point_time = point_time.replace(
                        tzinfo=dt_util.as_local(start_time).tzinfo
                    )
                point_time = dt_util.as_utc(point_time)
            point_value = next(
                (
                    point[key]
                    for key in (
                        "value",
                        "power",
                        "price",
                        "forecast_value",
                        "pv_estimate",
                        "estimate",
                        "watts",
                        "consumption",
                    )
                    if key in point
                ),
                None,
            )
        else:
            point_value = point
        try:
            value = float(point_value)
        except (TypeError, ValueError) as err:
            raise EntityDataError(
                f"Forecast attribute {attribute!r} on {entity_id} contains a non-numeric point."
            ) from err
        if not math.isfinite(value):
            raise EntityDataError(
                f"Forecast attribute {attribute!r} on {entity_id} contains an invalid number."
            )
        if conversion == "power":
            multipliers = {"W": 1, "kW": 1000, "MW": 1_000_000}
            if unit not in multipliers:
                raise EntityDataError(
                    f"Forecast entity {entity_id} must use W, kW, or MW."
                )
            value *= multipliers[unit]
        elif conversion == "price":
            value = _convert_price(value, unit, entity_id)
        values.append(value)
        if point_time is not None:
            timed_values.append((point_time, value))

    if has_timestamps:
        if len(timed_values) != len(values):
            raise EntityDataError(
                f"Forecast attribute {attribute!r} on {entity_id} mixes timed and untimed points."
            )
        timed_values.sort(key=lambda item: item[0])
        start_utc = dt_util.as_utc(start_time)
        aligned: list[float] = []
        index = 0
        for step in range(steps):
            target = start_utc + timedelta(minutes=step * step_minutes)
            while index + 1 < len(timed_values) and timed_values[index + 1][0] <= target:
                index += 1
            if target < timed_values[0][0]:
                aligned.append(timed_values[0][1])
            else:
                aligned.append(timed_values[index][1])
        return aligned

    return (values + [values[-1]] * steps)[:steps]


def _convert_price(value: float, unit: Any, entity_id: str) -> float:
    normalized = str(unit or "").strip().casefold()
    normalized = normalized.replace("€", "eur").replace("$", "usd").replace("£", "gbp")
    normalized = normalized.replace(" ", "").replace("per", "/")
    if normalized.endswith("ct/kwh") or normalized.endswith("c/kwh"):
        return value / 100_000
    if normalized.endswith("/kwh") or normalized.endswith("kwh"):
        return value / 1000
    if normalized.endswith("/mwh") or normalized.endswith("mwh"):
        return value / 1_000_000
    if normalized.endswith("/wh") or normalized.endswith("wh"):
        return value
    raise EntityDataError(
        f"Forecast entity {entity_id} needs a price-per-energy unit such as EUR/kWh."
    )


def _daily_datetime(value: str, now: datetime) -> str:
    """Resolve an HH:MM EV time to its next local occurrence."""
    try:
        parsed = time.fromisoformat(value)
    except ValueError as err:
        raise EntityDataError(f"Expected a daily time in HH:MM format, got {value!r}.") from err
    candidate = datetime.combine(now.date(), parsed, tzinfo=now.tzinfo)
    if candidate < now:
        candidate += timedelta(days=1)
    return candidate.isoformat()


def _schedule_datetime(value: str, now: datetime) -> str:
    """Resolve a configured date-time or daily HH:MM value."""
    try:
        parsed = dt_util.parse_datetime(value)
    except (TypeError, ValueError):
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=now.tzinfo)
        return parsed.isoformat()
    return _daily_datetime(value, now)


def build_request(
    hass: HomeAssistant, config: dict[str, Any], assets: list[dict[str, Any]]
) -> dict[str, Any]:
    """Create the physical-input request accepted by POST /optimize."""
    now = dt_util.now()
    time_step_minutes = int(config["time_step_minutes"])
    steps = round(config["horizon_hours"] * 60 / time_step_minutes)
    now_utc = dt_util.as_utc(now)
    interval_seconds = time_step_minutes * 60
    aligned_timestamp = (
        int(now_utc.timestamp()) // interval_seconds * interval_seconds
    )
    request_start = dt_util.as_local(
        datetime.fromtimestamp(aligned_timestamp, tz=timezone.utc)
    )
    result: dict[str, Any] = {
        "timestamp": request_start.isoformat(),
        "time_step_duration_hours": time_step_minutes / 60,
        "horizon_hours": config["horizon_hours"],
        "grid": {},
        "base_load": {},
        "pv": [],
        "controllable_loads": [],
        "storage": [],
    }
    for asset in assets:
        common = {"id": asset["id"], "name": asset["name"]}
        kind = asset["asset_type"]
        if kind == "grid":
            grid_power = _power(hass, asset["power_entity"], "Grid power")
            if not asset.get("positive_means_import", True):
                grid_power = -grid_power
            result["grid"] = {
                **common,
                "current_power": grid_power,
                "max_import_power": asset["max_import_power"],
                "max_export_power": asset["max_export_power"],
                "import_price_forecast": _forecast(
                    hass,
                    asset["import_price_entity"],
                    asset.get("import_price_forecast_attribute", "forecast"),
                    0,
                    steps,
                    "Import price",
                    "price",
                    required=True,
                    start_time=request_start,
                    step_minutes=time_step_minutes,
                ),
                "export_price_forecast": _forecast(
                    hass,
                    asset["export_price_entity"],
                    asset.get("export_price_forecast_attribute", "forecast"),
                    0,
                    steps,
                    "Export price",
                    "price",
                    required=True,
                    start_time=request_start,
                    step_minutes=time_step_minutes,
                ),
            }
        elif kind in ("pv", "base_load"):
            current_power = _power(hass, asset["power_entity"], kind.replace("_", " "))
            forecast = _forecast(
                hass,
                asset.get("power_forecast_entity", asset["power_entity"]),
                asset.get("power_forecast_attribute"),
                current_power,
                steps,
                f"{kind.replace('_', ' ')} power",
                "power",
                required=kind == "pv",
                start_time=request_start,
                step_minutes=time_step_minutes,
            )
            model = {**common, "current_power": current_power, "power_forecast": forecast}
            if kind == "pv":
                result["pv"].append(model)
            else:
                result["base_load"] = model
        elif kind == "controllable_load":
            current_power = (
                _power(hass, asset["power_entity"], "Controllable load")
                if asset.get("power_entity")
                else 0
            )
            result["controllable_loads"].append(
                {
                    **common,
                    "current_power": current_power,
                    "average_power": asset["average_power"],
                    "energy_demand": asset["energy_demand"],
                    "earliest_start_time": _schedule_datetime(
                        asset["earliest_start_time"], now
                    ),
                    "latest_finish_time": _schedule_datetime(
                        asset["latest_finish_time"], now
                    ),
                }
            )
        elif kind in ("home_battery", "ev_battery"):
            model = {
                **common,
                "storage_type": kind,
                "current_soc": _soc(hass, asset["soc_entity"], "Battery state of charge"),
                **{
                    key: asset[key]
                    for key in (
                        "energy_capacity",
                        "min_soc",
                        "max_soc",
                        "max_charge_power",
                        "max_discharge_power",
                        "charge_efficiency",
                        "discharge_efficiency",
                        "passive_discharge_power",
                    )
                },
            }
            if kind == "ev_battery":
                model.update(
                    {
                        "vehicle_efficiency": asset["vehicle_efficiency"],
                        "round_trip_distance": asset["round_trip_distance"],
                        "expected_departure_time": _daily_datetime(
                            asset["expected_departure_time"], now
                        ),
                        "expected_arrival_time": _daily_datetime(
                            asset["expected_arrival_time"], now
                        ),
                    }
                )
            result["storage"].append(model)
        elif kind == "dhw_tank":
            result["storage"].append(
                {
                    **common,
                    "storage_type": kind,
                    "tank_volume": asset["tank_volume"],
                    "min_water_temperature": asset["min_water_temperature"],
                    "max_water_temperature": asset["max_water_temperature"],
                    "current_water_temperature": _temperature(
                        hass, asset["water_temperature_entity"], "Water temperature"
                    ),
                    "min_comfort_temperature": asset["min_comfort_temperature"],
                    "heat_loss_coefficient": asset["heat_loss_coefficient"],
                    "heat_pump_electric_power": asset["heat_pump_electric_power"],
                    "heat_pump_cop": asset["heat_pump_cop"],
                    "morning_peak_energy_demand": asset["morning_peak_energy_demand"],
                    "evening_peak_energy_demand": asset["evening_peak_energy_demand"],
                    "morning_peak_time": asset["morning_peak_time"],
                    "evening_peak_time": asset["evening_peak_time"],
                }
            )
        elif kind == "building_thermal_mass":
            result["storage"].append(
                {
                    **common,
                    "storage_type": kind,
                    "floor_area": asset["floor_area"],
                    "thermal_mass_coefficient": asset["thermal_mass_coefficient"],
                    "default_weather_compensation_temperature": asset[
                        "default_weather_compensation_temperature"
                    ],
                    "current_indoor_temperature": _temperature(
                        hass,
                        asset["indoor_temperature_entity"],
                        "Indoor temperature",
                    ),
                    "max_comfort_temperature": asset["max_comfort_temperature"],
                    "heating_rate": asset["heating_rate"],
                    "cooldown_rate": asset["cooldown_rate"],
                    "heat_pump_cop_charge": asset["heat_pump_cop_charge"],
                    "heat_pump_cop_default": asset["heat_pump_cop_default"],
                }
            )
    return result

"""Build API requests from Home Assistant entities and asset settings."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
import math
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util

from .const import (
    CONF_GRID_PEAK_PENALTY,
    CONF_HORIZON_HOURS,
    CONF_RELATIVE_MIP_GAP,
    CONF_SWITCHING_PENALTY,
    CONF_TIME_LIMIT_S,
    CONF_TIME_STEP_MINUTES,
    ENABLEABLE_ASSET_TYPES,
)
from .forecasts import async_forecast_base_load, history_power
from .thermal import async_derive_thermal_model

_PRICE_PER_KWH_TO_PER_WH = 1 / 1000


def _state(hass: HomeAssistant, entity_id: str | None) -> State | None:
    if not entity_id:
        return None
    entity = hass.states.get(entity_id)
    if entity is None or entity.state in ("unknown", "unavailable"):
        return None
    return entity


def _number(state: State | None) -> float | None:
    if state is None:
        return None
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _temperature(hass: HomeAssistant, entity_id: str | None) -> float | None:
    state = _state(hass, entity_id)
    value = _number(state)
    if value is None or state is None:
        return None
    unit = state.attributes.get("unit_of_measurement")
    if unit in ("°C", "C"):
        return value
    if unit in ("°F", "F"):
        return (value - 32) * 5 / 9
    return None


def _soc(hass: HomeAssistant, entity_id: str | None) -> float | None:
    state = _state(hass, entity_id)
    value = _number(state)
    if value is None or state is None:
        return None
    if state.attributes.get("unit_of_measurement") == "%":
        value /= 100
    if not 0 <= value <= 1:
        return None
    return value


def _forecast(
    hass: HomeAssistant,
    entity_id: str | None,
    attribute: str | None,
    steps: int,
    scale: float,
    start_time: datetime,
    step_minutes: int,
) -> list[float | str | None]:
    """Return one forecast value per time step, multiplied by `scale`.

    Definitions: 
    Input data (points): one entry of the attribute list, a dict holding a time and a value.
    - Time: the timestamp of a point. Naive times are read as local time.
    - Value: the number of a point.

    Output data (steps): one forecast value per slot, starting at the request start and repeating every `step_minutes`.

    Rules:
    1. Checking imported data
    - If the entity or attribute is not set, or the attribute is missing or empty: every step is None.
    - If a point has no valid time: the time for that point is None.
    - If a point has no valid value: the value for that point is None.
    2. Creating forecast steps
    - If any point has time None: every step gets value 'Timestamps invalid'.
    - Otherwise each step uses the latest point at or before its time, or the first point if the step is earlier than all of them.
    - Scale: each numeric step value is multiplied by `scale` after it is chosen.
    """
    # 1. Checking imported data
    if not entity_id or not attribute:
        return [None] * steps
    # The forecast attribute stays valid while the entity state is unknown or unavailable.
    state = hass.states.get(entity_id)
    raw = state.attributes.get(attribute) if state is not None else None
    if not isinstance(raw, (list, tuple)) or not raw:
        return [None] * steps

    # Each point is (time in UTC, value); the value stays unscaled until the end.
    timed_values: list[tuple[datetime, float | None]] = []
    for point in raw:
        point = point if isinstance(point, dict) else {}
        # The time is the first field that parses as a datetime; the value is the first other finite number.
        time_key = None
        point_time: datetime | None = None
        for key, item in point.items():
            try:
                point_time = dt_util.parse_datetime(str(item))
            except (TypeError, ValueError):
                point_time = None
            if point_time is not None:
                time_key = key
                break
        if point_time is None:
            # Any point without a valid time invalidates the whole forecast.
            return ["Timestamps invalid"] * steps
        if point_time.tzinfo is None:
            point_time = point_time.replace(tzinfo=dt_util.as_local(start_time).tzinfo)
        value: float | None = None
        for key, item in point.items():
            if key == time_key:
                continue
            try:
                number = float(item)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                value = number
                break
        timed_values.append((dt_util.as_utc(point_time), value))

    # 2. Creating forecast steps
    timed_values.sort(key=lambda item: item[0])
    start_utc = dt_util.as_utc(start_time)
    aligned: list[float | str | None] = []
    index = 0
    for step in range(steps):
        target = start_utc + timedelta(minutes=step * step_minutes)
        # Move to the latest point at or before the target; earlier steps keep the first point.
        while index + 1 < len(timed_values) and timed_values[index + 1][0] <= target:
            index += 1
        value = timed_values[index][1]
        aligned.append(None if value is None else value * scale)
    return aligned


def _clock_time(value: str | time | None) -> str | None:
    """Format a configured time as the daily HH:MM the API expects."""
    try:
        if value is None:
            return None
        if isinstance(value, str):
            value = time.fromisoformat(value)
        return value.strftime("%H:%M")
    except ValueError:
        return None


async def build_request(
    hass: HomeAssistant,
    config: dict[str, Any],
    assets: list[dict[str, Any]],
    inputs: dict[tuple[str, str], Any],
    thermal_history: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Create the physical-input request accepted by POST /optimize; thermal_history is filled per asset id."""
    step_minutes = config[CONF_TIME_STEP_MINUTES]
    horizon_hours = config[CONF_HORIZON_HOURS]
    steps = round(horizon_hours * 60 / step_minutes)
    interval_seconds = step_minutes * 60
    aligned_timestamp = int(dt_util.utcnow().timestamp()) // interval_seconds * interval_seconds
    request_start = dt_util.as_local(
        datetime.fromtimestamp(aligned_timestamp, tz=timezone.utc)
    )

    def forecast(entity_id: str | None, attribute: str | None, scale: float = 1):
        return _forecast(
            hass, entity_id, attribute, steps, scale, request_start, step_minutes
        )

    result: dict[str, Any] = {
        "timestamp": request_start.isoformat(),
        "time_step_duration": step_minutes / 60,
        "planning_horizon": horizon_hours,
        "solver_time_limit": config[CONF_TIME_LIMIT_S],
        "relative_mip_gap": config[CONF_RELATIVE_MIP_GAP],
        "storage_switching_penalty": config[CONF_SWITCHING_PENALTY],
        "grid_peak_penalty": config[CONF_GRID_PEAK_PENALTY],
        "grid": {},
        "solar": [],
        "base_load": {},
        "controllable_loads": [],
        "storage": [],
    }
    for asset in assets:
        kind = asset["asset_type"]
        if kind in ENABLEABLE_ASSET_TYPES and not inputs.get((asset["id"], "enabled"), True):
            continue
        common = {"id": asset["id"], "name": asset["name"]}
        if kind == "grid":
            result["grid"] = {
                **common,
                "max_grid_import_power": asset["max_import_power"],
                "max_grid_export_power": asset["max_export_power"],
                "grid_import_price_forecast": forecast(
                    asset.get("import_price_entity"),
                    asset.get("import_price_forecast_attribute"),
                    _PRICE_PER_KWH_TO_PER_WH,
                ),
                "grid_export_price_forecast": forecast(
                    asset.get("export_price_entity"),
                    asset.get("export_price_forecast_attribute"),
                    _PRICE_PER_KWH_TO_PER_WH,
                ),
            }
        elif kind == "solar":
            result["solar"].append(
                {
                    **common,
                    "power_forecast": forecast(
                        asset.get("power_forecast_entity"),
                        asset.get("power_forecast_attribute"),
                    ),
                }
            )
        elif kind == "base_load":
            result["base_load"] = {
                **common,
                "power_forecast": await async_forecast_base_load(
                    hass,
                    asset["power_entity"],
                    request_start,
                    step_minutes,
                    steps,
                    history_power(state) if (state := _state(hass, asset["power_entity"])) else None,
                ),
            }
        elif kind == "controllable_load":
            load = {
                **common,
                "average_power": asset["average_power"],
                "energy_demand": asset["average_power"] * asset["runtime_h"],
                "earliest_start_time": _clock_time(inputs[(asset["id"], "earliest_start_time")]),
                "latest_finish_time": _clock_time(inputs[(asset["id"], "latest_finish_time")]),
            }
            run_start_time = inputs[(asset["id"], "run_start_time")]
            if run_start_time is not None:
                load["run_start_time"] = run_start_time.isoformat()
            result["controllable_loads"].append(load)
        elif kind in ("home_battery", "ev_battery"):
            model = {
                **common,
                "storage_type": kind,
                "current_soc": _soc(hass, asset.get("soc_entity")),
                **{
                    key: asset.get(key)
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
                        # km/kWh -> km/Wh
                        "vehicle_efficiency": asset["vehicle_efficiency"] / 1000,
                        "round_trip_distance": inputs[(asset["id"], "round_trip_distance")],
                        **{
                            key: datetime.combine(
                                request_start.date(),
                                inputs[(asset["id"], key)],
                                tzinfo=request_start.tzinfo,
                            ).isoformat()
                            for key in ("expected_departure_time", "expected_arrival_time")
                        },
                    }
                )
            result["storage"].append(model)
        elif kind == "dhw_tank":
            result["storage"].append(
                {
                    **common,
                    "storage_type": kind,
                    "current_water_temperature": _temperature(
                        hass, asset.get("water_temperature_entity")
                    ),
                    **{
                        key: asset.get(key)
                        for key in (
                            "tank_volume",
                            "min_water_temperature",
                            "max_water_temperature",
                            "min_comfort_temperature",
                            "heat_loss_coefficient",
                            "heat_pump_electric_power",
                            "morning_peak_energy_demand",
                            "evening_peak_energy_demand",
                        )
                    },
                    "heat_pump_coefficient_of_performance": asset.get("heat_pump_cop"),
                    "morning_demand_peak_time": _clock_time(asset.get("morning_peak_time")),
                    "evening_demand_peak_time": _clock_time(asset.get("evening_peak_time")),
                }
            )
        elif kind == "building_thermal_mass":
            current_indoor = _temperature(hass, asset.get("indoor_temperature_entity"))
            # A non-zero configured heat loss coefficient overrides the derived one.
            derived = await async_derive_thermal_model(
                hass,
                asset,
                current_indoor,
                heat_loss_needed=not asset["heat_loss_coefficient"],
                history_rows=thermal_history.setdefault(asset["id"], []),
            )
            result["storage"].append(
                {
                    **common,
                    "storage_type": kind,
                    "indoor_temperature": current_indoor,
                    "outdoor_temperature_forecast": forecast(
                        asset.get("outdoor_temperature_entity"),
                        asset.get("outdoor_temperature_forecast_attribute"),
                    ),
                    **{
                        key: asset.get(key)
                        for key in (
                            "min_room_temperature",
                            "max_room_temperature",
                            "min_comfort_temperature",
                            "max_comfort_temperature",
                            "heat_loss_coefficient",
                            "floor_area",
                            "thermal_mass_coefficient",
                            "heating_rate",
                            "cooldown_rate",
                            "plus_dt_flow_offset",
                            "minus_dt_flow_offset",
                            "cop_flow_temperature_sensitivity",
                        )
                    },
                    **derived,
                }
            )
    return result

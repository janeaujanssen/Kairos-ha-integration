"""Derive building thermal mass parameters from Home Assistant recorder history."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from functools import partial
from statistics import fmean
from typing import Any

from homeassistant.components.recorder import history
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util

from .forecasts import history_power

_HISTORY_WINDOW = timedelta(days=14)
_MIN_HOURS = 6
_MIN_RUNNING_POWER = 100  # W electric; below this the heat pump counts as off
_INDOOR_BAND = 1.0  # °C around the current indoor temperature


def _history_temperature(state: State) -> float | None:
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    unit = state.attributes.get("unit_of_measurement")
    if unit in ("°F", "F"):
        return (value - 32) * 5 / 9
    return value if unit in ("°C", "C") else None


def _hourly(
    states: list[Any], convert: Callable[[State], float | None]
) -> dict[datetime, float]:
    buckets: dict[datetime, list[float]] = defaultdict(list)
    for state in states:
        value = convert(state) if isinstance(state, State) else None
        if value is not None:
            # last_updated, not last_changed: steady sensors only write new samples without changing state.
            buckets[state.last_updated.replace(minute=0, second=0, microsecond=0)].append(value)
    return {hour: fmean(values) for hour, values in buckets.items()}


def fit_heat_loss(
    indoor: Mapping[datetime, float],
    outdoor: Mapping[datetime, float],
    thermal: Mapping[datetime, float],
    thermal_mass: float,
) -> float:
    """Heat loss coefficient [W/°C] from the hourly balance P = C*dT/dt + U*(Tin - Tout)."""
    xs: list[float] = []
    ys: list[float] = []
    for hour in sorted(indoor.keys() & outdoor.keys() & thermal.keys()):
        following = indoor.get(hour + timedelta(hours=1))
        if following is None:
            continue
        xs.append((indoor[hour] + following) / 2 - outdoor[hour])
        ys.append(thermal[hour] - thermal_mass * (following - indoor[hour]))
    denominator = sum(x * x for x in xs)
    coefficient = sum(x * y for x, y in zip(xs, ys)) / denominator if denominator else 0
    if len(xs) < _MIN_HOURS:
        raise ValueError(
            f"Not enough indoor, outdoor and thermal power history to derive the heat loss coefficient: "
            f"{len(xs)} usable hours, {_MIN_HOURS} needed."
        )
    if coefficient <= 0:
        raise ValueError(
            f"The heat loss coefficient derived from the history is not positive ({coefficient:.1f} W/°C) "
            "- the history does not show the building losing heat."
        )
    return coefficient


def fit_cop(
    current_indoor: float,
    indoor: Mapping[datetime, float],
    outdoor: Mapping[datetime, float],
    electric: Mapping[datetime, float],
    thermal: Mapping[datetime, float],
) -> tuple[float, float, float]:
    """Return (reference COP, reference outdoor temperature, COP per °C of outdoor temperature)."""
    # Only hours near the current indoor temperature, so the flow temperature level is comparable.
    points = [
        (outdoor[hour], thermal[hour] / electric[hour])
        for hour in indoor.keys() & outdoor.keys() & electric.keys() & thermal.keys()
        if electric[hour] >= _MIN_RUNNING_POWER
        and abs(indoor[hour] - current_indoor) <= _INDOOR_BAND
    ]
    if len(points) < _MIN_HOURS:
        raise ValueError(
            f"Not enough heat pump history to derive the COP: {len(points)} usable hours, "
            f"{_MIN_HOURS} needed."
        )
    reference_outdoor = fmean(x for x, _ in points)
    reference_cop = fmean(y for _, y in points)
    variance = sum((x - reference_outdoor) ** 2 for x, _ in points)
    covariance = sum((x - reference_outdoor) * (y - reference_cop) for x, y in points)
    return reference_cop, reference_outdoor, covariance / variance if variance else 0.0


async def async_derive_thermal_model(
    hass: HomeAssistant,
    asset: dict[str, Any],
    current_indoor: float | None,
    heat_loss_needed: bool,
) -> dict[str, float]:
    """Derive the history-based request fields of a building thermal mass asset."""
    if current_indoor is None:
        raise ValueError("The indoor temperature is unavailable.")
    entity_ids = [
        asset["indoor_temperature_entity"],
        asset["outdoor_temperature_entity"],
        asset["electric_power_entity"],
        asset["thermal_power_entity"],
    ]
    now = dt_util.now()
    states = await hass.async_add_executor_job(
        partial(
            history.get_significant_states,
            hass,
            now - _HISTORY_WINDOW,
            end_time=now,
            entity_ids=entity_ids,
            significant_changes_only=False,
        )
    )
    indoor, outdoor = (_hourly(states.get(e, []), _history_temperature) for e in entity_ids[:2])
    electric, thermal = (_hourly(states.get(e, []), history_power) for e in entity_ids[2:])

    reference_cop, reference_outdoor, cop_coefficient = fit_cop(
        current_indoor, indoor, outdoor, electric, thermal
    )
    model = {
        "reference_cop": reference_cop,
        "reference_outdoor_temperature": reference_outdoor,
        "cop_outdoor_temperature_coefficient": cop_coefficient,
    }
    if heat_loss_needed:
        model["heat_loss_coefficient"] = fit_heat_loss(
            indoor, outdoor, thermal, asset["floor_area"] * asset["thermal_mass_coefficient"]
        )
    return model

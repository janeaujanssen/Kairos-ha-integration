"""Forecast household base load from Home Assistant recorder history."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import partial
import math
from statistics import fmean

from homeassistant.components.recorder import history
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util

_HISTORY_WINDOW = timedelta(weeks=4)
_POWER_MULTIPLIERS = {"W": 1, "kW": 1000, "MW": 1_000_000}


def _history_power(state: State) -> float | None:
    """Return a history state's power in watts, or None if it is unusable."""
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    multiplier = _POWER_MULTIPLIERS.get(state.attributes.get("unit_of_measurement"))
    if multiplier is None or not (-1e15 < value < 1e15):
        return None
    watts = value * multiplier
    return watts if math.isfinite(watts) else None


async def async_forecast_base_load(
    hass: HomeAssistant,
    entity_id: str,
    start_time: datetime,
    step_minutes: int,
    steps: int,
    current_power: float,
) -> list[float]:
    """Average matching weekday/time-slot readings from the previous four weeks."""
    now = dt_util.now()
    states_by_entity = await hass.async_add_executor_job(
        partial(
            history.get_significant_states,
            hass,
            now - _HISTORY_WINDOW,
            end_time=now,
            entity_ids=[entity_id],
            significant_changes_only=False,
        )
    )

    daily_slot_values: dict[tuple[date, int, int], list[float]] = defaultdict(list)
    for state in states_by_entity.get(entity_id, []):
        if not isinstance(state, State):
            continue
        watts = _history_power(state)
        if watts is None:
            continue
        local_time = dt_util.as_local(state.last_changed)
        slot = (local_time.hour * 60 + local_time.minute) // step_minutes
        daily_slot_values[(local_time.date(), local_time.weekday(), slot)].append(watts)

    weekly_slot_averages: dict[tuple[int, int], list[float]] = defaultdict(list)
    for (_, weekday, slot), values in daily_slot_values.items():
        weekly_slot_averages[(weekday, slot)].append(fmean(values))

    start_utc = dt_util.as_utc(start_time)
    forecast: list[float] = []
    for step in range(steps):
        target = dt_util.as_local(
            start_utc + timedelta(minutes=step * step_minutes)
        )
        slot = (target.hour * 60 + target.minute) // step_minutes
        readings = weekly_slot_averages.get((target.weekday(), slot))
        forecast.append(fmean(readings) if readings else current_power)
    return forecast

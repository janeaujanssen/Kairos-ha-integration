"""Coordinate optimization cycles, schedule persistence, and failure reporting."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import hashlib
import json
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .api import KairosApi, KairosApiError
from .const import (
    CONF_API_URL,
    CONF_ASSETS,
    CONF_FAILURE_THRESHOLD,
    CONF_OPTIMIZATION_STEPS,
    CONF_REQUEST_TIMEOUT,
    CONF_TIME_STEP_MINUTES,
    DEFAULT_SETTINGS,
    DOMAIN,
)
from .request import build_request

_LOGGER = logging.getLogger(__name__)


class KairosCoordinator:
    """Own the optimization scheduler and its result data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.config = {**DEFAULT_SETTINGS, **entry.data, **entry.options}
        self.assets = self.config[CONF_ASSETS]
        # Values of the entities created by Kairos, keyed by (asset id, input key).
        self.inputs: dict[tuple[str, str], Any] = {}
        self._store: Store[dict[str, Any]] = Store(
            hass, 1, f"{DOMAIN}_{entry.entry_id}_schedule"
        )
        self._failures = 0
        self._last_run: str | None = None
        self._objective_cost: float | None = None
        self._last_api_request: dict[str, Any] | None = None
        self._last_api_response: Any = None
        self._last_api_status: int | None = None
        self._last_error: str | None = None
        self._schedules: dict[str, Any] = {}
        self._forecasts: dict[str, Any] = {}
        self._thermal_parameters: dict[str, Any] = {}
        self._rejected_payload_fingerprint: str | None = None
        self._last_optimized_slot: int | None = None
        self._force_update = False
        self._cancel_tick: Callable[[], None] | None = None
        self.api = KairosApi(
            async_get_clientsession(hass),
            self.config[CONF_API_URL],
            self.config[CONF_REQUEST_TIMEOUT],
        )
        self.coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_method=self._async_update_data,
        )

    async def async_setup(self) -> None:
        """Restore the last schedule."""
        saved = await self._store.async_load()
        if saved:
            self._schedules = saved.get("assets", {})
            self._forecasts = saved.get("forecasts", {})
            self._thermal_parameters = saved.get("thermal_parameters", {})
            self._last_run = saved.get("optimized_at")
            self._objective_cost = saved.get("objective_cost")
        self.coordinator.data = self._sensor_data()

    async def async_start(self) -> None:
        """Run the initial optimization, once the input entities have restored their values."""
        if not self._configuration_ready():
            return
        await self.coordinator.async_refresh()
        self._schedule_next_tick()

    async def async_unload(self) -> None:
        """Persist the most recent valid schedule on unload."""
        if self._cancel_tick is not None:
            self._cancel_tick()
            self._cancel_tick = None
        await self._persist()

    async def async_run_optimization(self) -> None:
        """Force the coordinator to run an optimization immediately."""
        self._force_update = True
        try:
            await self.coordinator.async_refresh()
        finally:
            self._force_update = False

    def _configuration_ready(self) -> bool:
        """Return whether required inputs are configured."""
        kinds = {asset["asset_type"] for asset in self.assets}
        return {"grid", "base_load"}.issubset(kinds)

    def _schedule_next_tick(self) -> None:
        """Schedule the next refresh just after an aligned optimization boundary."""
        interval_seconds = self.config[CONF_TIME_STEP_MINUTES] * 60
        now = dt_util.utcnow()
        next_epoch = (
            (int(now.timestamp()) // interval_seconds + 1) * interval_seconds + 1
        )
        delay = max(0, next_epoch - now.timestamp())
        self._cancel_tick = async_call_later(
            self.hass, delay, self._handle_schedule_tick
        )

    def _claim_optimization_slot(self) -> bool:
        """Return whether the current time slot starts an optimization run."""
        step_seconds = self.config[CONF_TIME_STEP_MINUTES] * 60
        slot = int(dt_util.utcnow().timestamp()) // step_seconds
        every = int(self.config[CONF_OPTIMIZATION_STEPS])
        due = (
            self._force_update
            or self._last_optimized_slot is None
            or (slot % every == 0 and slot != self._last_optimized_slot)
        )
        if due:
            self._last_optimized_slot = slot
        return due

    @callback
    def _handle_schedule_tick(self, _now: datetime) -> None:
        """Refresh entities at each time step; optimize only when due."""
        del _now
        self.hass.async_create_task(self.coordinator.async_refresh())
        self._schedule_next_tick()

    def _sensor_data(self) -> dict[str, Any]:
        return {
            "assets": self._schedules,
            "forecasts": self._forecasts,
            "thermal_parameters": self._thermal_parameters,
            "objective_cost": self._objective_cost,
            "last_run": self._last_run,
            "last_api_request": self._last_api_request,
            "last_api_response": self._last_api_response,
            "last_api_status": self._last_api_status,
            "last_error": self._last_error,
        }

    async def _async_update_data(self) -> dict[str, Any]:
        """Build and submit one snapshot, retaining schedules on failure."""
        if not self._claim_optimization_slot():
            return self._sensor_data()
        self._last_api_request = None
        self._last_api_response = None
        self._last_api_status = None
        self._last_error = None
        payload: dict[str, Any] | None = None
        try:
            payload = await build_request(
                self.hass, self.config, self.assets, self.inputs
            )
            fingerprint = _payload_fingerprint(payload)
            if (
                fingerprint == self._rejected_payload_fingerprint
                and not self._force_update
            ):
                return self._sensor_data()
            self._last_api_request = payload
            result = await self.api.async_optimize(payload)
            self._last_api_response = result

            status = result.get("status")
            if status in ("Optimal", "Feasible"):
                self._schedules = result["assets"]
                self._forecasts = result.get("forecasts", {})
                self._thermal_parameters = result.get("building_thermal_mass", {})
                self._last_run = payload["timestamp"]
                self._objective_cost = result.get("objective_cost")
                self._failures = 0
                await self._persist()
                ir.async_delete_issue(self.hass, DOMAIN, "optimization_failed")
            elif status == "Infeasible":
                self._failures += 1
                _LOGGER.error("Kairos returned an infeasible schedule.")
                self._report_failure("Optimizer returned an infeasible schedule.")
            else:
                raise KairosApiError(
                    f"Kairos returned unsupported status {status!r}.",
                    response=result,
                )
        except (KairosApiError, ValueError) as err:
            self._failures += 1
            self._last_error = str(err)
            if isinstance(err, KairosApiError):
                self._last_api_status = err.status_code
                self._last_api_response = err.response
                if err.status_code == 400 and payload is not None:
                    self._rejected_payload_fingerprint = _payload_fingerprint(payload)
            _LOGGER.error("Kairos optimization failed: %s", err)
            self._report_failure(str(err))
            entity_id = er.async_get(self.hass).async_get_entity_id(
                "sensor", DOMAIN, f"{self.entry.entry_id}_last_api_response"
            )
            log_data = {"name": "Kairos", "message": f"Optimization failed: {err}"}
            if entity_id:
                log_data["entity_id"] = entity_id
            else:
                log_data["domain"] = DOMAIN
            await self.hass.services.async_call("logbook", "log", log_data)
        return self._sensor_data()

    async def _persist(self) -> None:
        await self._store.async_save(
            {
                "assets": self._schedules,
                "forecasts": self._forecasts,
                "thermal_parameters": self._thermal_parameters,
                "optimized_at": self._last_run,
                "objective_cost": self._objective_cost,
            }
        )

    def _report_failure(self, detail: str) -> None:
        if self._failures >= self.config[CONF_FAILURE_THRESHOLD]:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                "optimization_failed",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="optimization_failed",
                translation_placeholders={"detail": detail},
            )


def _payload_fingerprint(payload: dict[str, Any]) -> str:
    """Hash input values while ignoring the per-request timestamp."""
    stable_payload = {key: value for key, value in payload.items() if key != "timestamp"}
    canonical = json.dumps(stable_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()

"""Coordinate optimization cycles, schedule persistence, and failure reporting."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import hashlib
import json
import logging
from time import monotonic
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
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
    CONF_HORIZON_HOURS,
    CONF_REQUEST_TIMEOUT,
    CONF_TIME_STEP_MINUTES,
    CONF_UPDATE_INTERVAL,
    DEFAULT_FAILURE_THRESHOLD,
    DEFAULT_HORIZON_HOURS,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_TIME_STEP_MINUTES,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from .request import build_request

_LOGGER = logging.getLogger(__name__)


class KairosCoordinator:
    """Own the optimization scheduler and its result data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.config = {**entry.data, **entry.options}
        self.assets = self.config[CONF_ASSETS]
        self._store: Store[dict[str, Any]] = Store(
            hass, 1, f"{DOMAIN}_{entry.entry_id}_schedule"
        )
        self._failures = 0
        self._last_run: str | None = None
        self._duration: float | None = None
        self._status = "error"
        self._objective_cost: float | None = None
        self._last_api_request: dict[str, Any] | None = None
        self._last_api_response: Any = None
        self._last_api_status: int | None = None
        self._last_error: str | None = None
        self._schedules: dict[str, Any] = {}
        self._last_optimization_monotonic: float | None = None
        self._rejected_payload_fingerprint: str | None = None
        self._force_update = False
        self._cancel_tick: Callable[[], None] | None = None
        self.api = KairosApi(
            async_get_clientsession(hass),
            self.config[CONF_API_URL],
            self.config.get(CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT),
        )
        self.coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_method=self._async_update_data,
        )

    async def async_setup(self) -> None:
        """Restore the last schedule and run an initial optimization."""
        saved = await self._store.async_load()
        if saved:
            self._schedules = saved.get("assets", {})
            self._last_run = saved.get("optimized_at")
            self._objective_cost = saved.get("objective_cost")
            self._status = saved.get("status", "error")
        self.coordinator.data = self._sensor_data()
        if not self._configuration_ready():
            self._status = "not_configured"
            self.coordinator.data = self._sensor_data()
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
        interval_minutes = min(
            self.config.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
            self.config.get(CONF_TIME_STEP_MINUTES, DEFAULT_TIME_STEP_MINUTES),
        )
        interval_seconds = interval_minutes * 60
        now = dt_util.utcnow()
        next_epoch = (
            (int(now.timestamp()) // interval_seconds + 1) * interval_seconds + 1
        )
        delay = max(0, next_epoch - now.timestamp())
        self._cancel_tick = async_call_later(
            self.hass, delay, self._handle_schedule_tick
        )

    @callback
    def _handle_schedule_tick(self, _now: datetime) -> None:
        """Refresh entities and optimize if their configured interval is due."""
        del _now
        self.hass.async_create_task(self.coordinator.async_refresh())
        self._schedule_next_tick()

    def _sensor_data(self) -> dict[str, Any]:
        return {
            "assets": self._schedules,
            "status": self._status,
            "objective_cost": self._objective_cost,
            "last_run": self._last_run,
            "duration": self._duration,
            "consecutive_failures": self._failures,
            "last_api_request": self._last_api_request,
            "last_api_response": self._last_api_response,
            "last_api_status": self._last_api_status,
            "last_error": self._last_error,
        }

    async def _async_update_data(self) -> dict[str, Any]:
        """Build and submit one snapshot, retaining schedules on failure."""
        started = monotonic()
        interval_seconds = (
            self.config.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL) * 60
        )
        if (
            not self._force_update
            and self._last_optimization_monotonic is not None
            and started - self._last_optimization_monotonic < interval_seconds
        ):
            return self._sensor_data()

        self._last_optimization_monotonic = started
        self._last_run = dt_util.now().isoformat()
        self._last_api_request = None
        self._last_api_response = None
        self._last_api_status = None
        self._last_error = None
        payload: dict[str, Any] | None = None
        try:
            settings = {
                "time_step_minutes": self.config.get(
                    CONF_TIME_STEP_MINUTES, DEFAULT_TIME_STEP_MINUTES
                ),
                "horizon_hours": self.config.get(
                    CONF_HORIZON_HOURS, DEFAULT_HORIZON_HOURS
                ),
            }
            payload = await build_request(self.hass, settings, self.assets)
            fingerprint = _payload_fingerprint(payload)
            if (
                fingerprint == self._rejected_payload_fingerprint
                and not self._force_update
            ):
                return self._sensor_data()
            self._last_api_request = payload
            result = await self.api.async_optimize(payload)
            self._last_api_response = result
            self._last_optimization_monotonic = monotonic()
            self._duration = monotonic() - started
            self._last_run = payload["timestamp"]

            status = result.get("status")
            if status in ("Optimal", "Feasible"):
                self._schedules = result["assets"]
                self._status = status.casefold()
                self._objective_cost = result.get("objective_cost")
                self._failures = 0
                await self._persist()
                ir.async_delete_issue(self.hass, DOMAIN, "optimization_failed")
            elif status == "Infeasible":
                self._status = "infeasible"
                self._objective_cost = result.get("objective_cost")
                self._failures += 1
                _LOGGER.error("Kairos returned an infeasible schedule.")
                self._report_failure("Optimizer returned an infeasible schedule.")
                await self._persist()
            else:
                raise KairosApiError(
                    f"Kairos returned unsupported status {status!r}.",
                    response=result,
                )
        except KairosApiError as err:
            self._duration = monotonic() - started
            self._status = "error"
            self._failures += 1
            self._last_error = str(err)
            if isinstance(err, KairosApiError):
                self._last_api_status = err.status_code
                self._last_api_response = err.response
            if (
                isinstance(err, KairosApiError)
                and err.status_code == 400
                and payload is not None
            ):
                self._rejected_payload_fingerprint = _payload_fingerprint(payload)
            _LOGGER.error("Kairos optimization failed: %s", err)
            self._report_failure(str(err))
        return self._sensor_data()

    async def _persist(self) -> None:
        await self._store.async_save(
            {
                "assets": self._schedules,
                "optimized_at": self._last_run,
                "objective_cost": self._objective_cost,
                "status": self._status,
            }
        )

    def _report_failure(self, detail: str) -> None:
        threshold = self.config.get(
            CONF_FAILURE_THRESHOLD, DEFAULT_FAILURE_THRESHOLD
        )
        if self._failures >= threshold:
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

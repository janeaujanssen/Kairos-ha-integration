"""Config flow for Kairos."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from aiohttp import ClientError, ClientSession, ClientTimeout
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    ASSET_TYPES,
    CONF_API_URL,
    CONF_ASSETS,
    CONF_FAILURE_THRESHOLD,
    CONF_HORIZON_HOURS,
    CONF_REQUEST_TIMEOUT,
    CONF_TIME_STEP_MINUTES,
    CONF_UPDATE_INTERVAL,
    DEFAULT_API_URL,
    DEFAULT_FAILURE_THRESHOLD,
    DEFAULT_HORIZON_HOURS,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_TIME_STEP_MINUTES,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)

_ASSET_LABELS = {
    "grid": "Grid connection",
    "pv": "PV system",
    "base_load": "Household base load",
    "controllable_load": "Controllable load",
    "home_battery": "Home battery",
    "ev_battery": "EV battery",
    "dhw_tank": "DHW tank",
    "building_thermal_mass": "Building thermal mass",
}

_STATIC_FIELDS: dict[str, float] = {
    "max_import_power": 11000,
    "max_export_power": 11000,
    "energy_capacity": 10000,
    "min_soc": 0.1,
    "max_soc": 0.9,
    "max_charge_power": 5000,
    "max_discharge_power": 5000,
    "charge_efficiency": 0.95,
    "discharge_efficiency": 0.95,
    "passive_discharge_power": 0,
    "average_power": 1500,
    "energy_demand": 1800,
    "tank_volume": 300,
    "min_water_temperature": 20,
    "max_water_temperature": 60,
    "min_comfort_temperature": 40,
    "heat_loss_coefficient": 4,
    "heat_pump_electric_power": 3000,
    "heat_pump_cop": 3,
    "morning_peak_energy_demand": 150,
    "evening_peak_energy_demand": 180,
    "floor_area": 100,
    "thermal_mass_coefficient": 200,
    "default_weather_compensation_temperature": 20,
    "max_comfort_temperature": 21,
    "heating_rate": 0.6,
    "cooldown_rate": 0.1,
    "heat_pump_cop_charge": 2.5,
    "heat_pump_cop_default": 3,
    "vehicle_efficiency": 0.005,
    "round_trip_distance": 100,
}

_BOUNDED_FIELDS = {
    "min_soc": (0, 1),
    "max_soc": (0, 1),
    "charge_efficiency": (0, 1),
    "discharge_efficiency": (0, 1),
}
_TEMPERATURE_FIELDS = {
    "min_water_temperature",
    "max_water_temperature",
    "min_comfort_temperature",
    "default_weather_compensation_temperature",
    "max_comfort_temperature",
}

_ASSET_ENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    "grid": ("power_entity", "import_price_entity", "export_price_entity"),
    "pv": ("power_entity", "power_forecast_entity"),
    "base_load": ("power_entity",),
    "controllable_load": (),
    "home_battery": ("soc_entity",),
    "ev_battery": ("soc_entity",),
    "dhw_tank": ("water_temperature_entity",),
    "building_thermal_mass": ("indoor_temperature_entity",),
}

_ASSET_STATIC_FIELDS: dict[str, tuple[str, ...]] = {
    "grid": ("max_import_power", "max_export_power"),
    "pv": (),
    "base_load": (),
    "controllable_load": ("average_power", "energy_demand"),
    "home_battery": (
        "energy_capacity",
        "min_soc",
        "max_soc",
        "max_charge_power",
        "max_discharge_power",
        "charge_efficiency",
        "discharge_efficiency",
        "passive_discharge_power",
    ),
    "ev_battery": (
        "energy_capacity",
        "min_soc",
        "max_soc",
        "max_charge_power",
        "max_discharge_power",
        "charge_efficiency",
        "discharge_efficiency",
        "passive_discharge_power",
        "vehicle_efficiency",
        "round_trip_distance",
    ),
    "dhw_tank": (
        "tank_volume",
        "min_water_temperature",
        "max_water_temperature",
        "min_comfort_temperature",
        "heat_loss_coefficient",
        "heat_pump_electric_power",
        "heat_pump_cop",
        "morning_peak_energy_demand",
        "evening_peak_energy_demand",
    ),
    "building_thermal_mass": (
        "floor_area",
        "thermal_mass_coefficient",
        "default_weather_compensation_temperature",
        "max_comfort_temperature",
        "heating_rate",
        "cooldown_rate",
        "heat_pump_cop_charge",
        "heat_pump_cop_default",
    ),
}


def _slugify(value: str) -> str:
    """Return a stable API asset identifier from its display name."""
    slug = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    return slug or "asset"


def _entity_selector() -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig())


def _asset_schema(
    asset_type: str, defaults: dict[str, Any] | None = None
) -> vol.Schema:
    """Build the asset form schema for setup and later asset management."""
    defaults = defaults or {}

    def required(key: str) -> vol.Required:
        if key in defaults:
            return vol.Required(key, default=defaults[key])
        return vol.Required(key)

    fields: dict[Any, Any] = {required("name"): selector.TextSelector()}
    for key in _ASSET_ENTITY_FIELDS[asset_type]:
        fields[required(key)] = _entity_selector()
    if asset_type == "controllable_load":
        entity_key = (
            vol.Optional("power_entity", default=defaults["power_entity"])
            if "power_entity" in defaults
            else vol.Optional("power_entity")
        )
        fields[entity_key] = _entity_selector()
    for key in _ASSET_STATIC_FIELDS[asset_type]:
        bounds = _BOUNDED_FIELDS.get(key)
        minimum = (
            bounds[0]
            if bounds
            else -50
            if key in _TEMPERATURE_FIELDS
            else 0
        )
        if bounds:
            number_selector = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=minimum,
                    max=bounds[1],
                    step=0.01,
                    mode=selector.NumberSelectorMode.BOX,
                )
            )
        else:
            number_selector = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=minimum,
                    step=0.01,
                    mode=selector.NumberSelectorMode.BOX,
                )
            )
        fields[vol.Required(key, default=defaults.get(key, _STATIC_FIELDS[key]))] = (
            number_selector
        )

    if asset_type == "grid":
        fields[vol.Required("positive_means_import", default=defaults.get("positive_means_import", True))] = (
            selector.BooleanSelector()
        )
        for key in (
            "import_price_forecast_attribute",
            "export_price_forecast_attribute",
        ):
            fields[vol.Required(key, default=defaults.get(key, "forecast"))] = (
                selector.TextSelector()
            )
    if asset_type == "pv":
        fields[vol.Required("power_forecast_attribute", default=defaults.get("power_forecast_attribute", "forecast"))] = (
            selector.TextSelector()
        )
    elif asset_type == "base_load":
        key = (
            vol.Optional(
                "power_forecast_attribute",
                default=defaults["power_forecast_attribute"],
            )
            if "power_forecast_attribute" in defaults
            else vol.Optional("power_forecast_attribute")
        )
        fields[key] = selector.TextSelector()
    if asset_type == "ev_battery":
        for key, default in (
            ("expected_departure_time", "09:00"),
            ("expected_arrival_time", "18:00"),
        ):
            fields[vol.Required(key, default=defaults.get(key, default))] = (
                selector.TextSelector()
            )
    if asset_type == "dhw_tank":
        for key, default in (
            ("morning_peak_time", "07:00"),
            ("evening_peak_time", "19:00"),
        ):
            fields[vol.Required(key, default=defaults.get(key, default))] = (
                selector.TextSelector()
            )
    if asset_type == "controllable_load":
        fields[required("earliest_start_time")] = selector.TextSelector()
        fields[required("latest_finish_time")] = selector.TextSelector()

    return vol.Schema(fields)


async def _check_api(hass: HomeAssistant, api_url: str, timeout: int) -> None:
    """Verify that the configured Kairos endpoint is healthy."""
    session: ClientSession = async_get_clientsession(hass)
    async with session.get(
        f"{api_url.rstrip('/')}/health", timeout=ClientTimeout(total=timeout)
    ) as response:
        response.raise_for_status()
        health = await response.json()
    if not isinstance(health, dict) or health.get("status") not in (
        "healthy",
        "degraded",
    ):
        raise ValueError("The health endpoint returned an unexpected response.")


class KairosConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up the Kairos API connection and optimization settings."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Configure the API and global optimization settings."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api_url = user_input[CONF_API_URL].rstrip("/")
            parsed = urlparse(api_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                errors["base"] = "invalid_url"
            elif user_input[CONF_REQUEST_TIMEOUT] >= user_input[CONF_UPDATE_INTERVAL] * 60:
                errors["base"] = "timeout_too_long"
            elif user_input[CONF_UPDATE_INTERVAL] % user_input[CONF_TIME_STEP_MINUTES]:
                errors["base"] = "interval_not_multiple"
            else:
                try:
                    await _check_api(
                        hass=self.hass,
                        api_url=api_url,
                        timeout=user_input[CONF_REQUEST_TIMEOUT],
                    )
                except (ClientError, TimeoutError, ValueError):
                    errors["base"] = "cannot_connect"
                else:
                    await self.async_set_unique_id(api_url.casefold())
                    self._abort_if_unique_id_configured()
                    settings = {
                        **user_input,
                        CONF_API_URL: api_url,
                        CONF_UPDATE_INTERVAL: int(user_input[CONF_UPDATE_INTERVAL]),
                        CONF_TIME_STEP_MINUTES: int(user_input[CONF_TIME_STEP_MINUTES]),
                        CONF_HORIZON_HOURS: int(user_input[CONF_HORIZON_HOURS]),
                        CONF_REQUEST_TIMEOUT: int(user_input[CONF_REQUEST_TIMEOUT]),
                        CONF_FAILURE_THRESHOLD: int(user_input[CONF_FAILURE_THRESHOLD]),
                    }
                    return self.async_create_entry(
                        title="Kairos",
                        data={**settings, CONF_ASSETS: []},
                    )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_API_URL, default=DEFAULT_API_URL
                ): selector.TextSelector(),
                vol.Required(
                    CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=1440, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_TIME_STEP_MINUTES, default=DEFAULT_TIME_STEP_MINUTES
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=1440, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_HORIZON_HOURS, default=DEFAULT_HORIZON_HOURS
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=168, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_REQUEST_TIMEOUT, default=DEFAULT_REQUEST_TIMEOUT
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=300, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_FAILURE_THRESHOLD, default=DEFAULT_FAILURE_THRESHOLD
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=20, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(
        _config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Expose global timing settings as entry options."""
        return KairosOptionsFlow()


class KairosOptionsFlow(config_entries.OptionsFlow):
    """Manage global settings and energy assets after setup."""

    def __init__(self) -> None:
        super().__init__()
        self._asset_type: str | None = None
        self._editing_id: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Show available maintenance operations."""
        del user_input
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "settings",
                "add_asset",
                "edit_asset",
                "remove_asset",
            ],
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Update global settings."""
        if user_input is not None:
            if user_input[CONF_UPDATE_INTERVAL] % user_input[CONF_TIME_STEP_MINUTES]:
                return self.async_show_form(
                    step_id="settings",
                    data_schema=self._options_schema(),
                    errors={"base": "interval_not_multiple"},
                )
            if user_input[CONF_REQUEST_TIMEOUT] >= user_input[CONF_UPDATE_INTERVAL] * 60:
                return self.async_show_form(
                    step_id="settings",
                    data_schema=self._options_schema(),
                    errors={"base": "timeout_too_long"},
                )
            return self.async_create_entry(
                title="", data={**self.config_entry.options, **user_input}
            )

        return self.async_show_form(
            step_id="settings",
            data_schema=self._options_schema(),
        )

    async def async_step_add_asset(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Select a new asset type."""
        if user_input is not None:
            self._asset_type = user_input["asset_type"]
            return await self.async_step_add_asset_config()
        labels = {asset_type: _ASSET_LABELS[asset_type] for asset_type in ASSET_TYPES}
        return self.async_show_form(
            step_id="add_asset",
            data_schema=vol.Schema({vol.Required("asset_type"): vol.In(labels)}),
        )

    async def async_step_add_asset_config(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Configure and save a new asset."""
        assert self._asset_type is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            asset = {**user_input, "asset_type": self._asset_type}
            asset["id"] = _slugify(asset["name"])
            assets = self._assets()
            if any(item["id"] == asset["id"] for item in assets):
                errors["base"] = "duplicate_asset_name"
            elif (
                self._asset_type in ("grid", "base_load")
                and any(item["asset_type"] == self._asset_type for item in assets)
            ):
                errors["base"] = "duplicate_required_asset"
            else:
                assets.append(asset)
                return self._save_assets(assets)
        return self.async_show_form(
            step_id="add_asset_config",
            data_schema=_asset_schema(self._asset_type),
            errors=errors,
            description_placeholders={"asset_type": _ASSET_LABELS[self._asset_type]},
        )

    async def async_step_edit_asset(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Select an asset to edit."""
        assets = self._assets()
        if user_input is not None:
            self._editing_id = user_input["asset_id"]
            self._asset_type = next(
                item["asset_type"] for item in assets if item["id"] == self._editing_id
            )
            return await self.async_step_edit_asset_config()
        return self.async_show_form(
            step_id="edit_asset",
            data_schema=vol.Schema(
                {
                    vol.Required("asset_id"): vol.In(
                        {item["id"]: item["name"] for item in assets}
                    )
                }
            ),
        )

    async def async_step_edit_asset_config(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Save edits while retaining the asset's stable API identifier."""
        assert self._asset_type is not None
        assert self._editing_id is not None
        assets = self._assets()
        original = next(item for item in assets if item["id"] == self._editing_id)
        errors: dict[str, str] = {}
        if user_input is not None:
            updated = {**original, **user_input, "id": self._editing_id}
            if any(
                item["id"] != self._editing_id
                and _slugify(item["name"]) == _slugify(updated["name"])
                for item in assets
            ):
                errors["base"] = "duplicate_asset_name"
            else:
                assets = [
                    updated if item["id"] == self._editing_id else item
                    for item in assets
                ]
                return self._save_assets(assets)
        return self.async_show_form(
            step_id="edit_asset_config",
            data_schema=_asset_schema(self._asset_type, original),
            errors=errors,
            description_placeholders={"asset_type": _ASSET_LABELS[self._asset_type]},
        )

    async def async_step_remove_asset(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Remove an optional asset, retaining the required grid and base load."""
        assets = [
            item
            for item in self._assets()
            if item["asset_type"] not in ("grid", "base_load")
        ]
        if not assets:
            return self.async_abort(reason="no_optional_assets")
        if user_input is not None:
            removed_id = user_input["asset_id"]
            return self._save_assets(
                [item for item in self._assets() if item["id"] != removed_id]
            )
        return self.async_show_form(
            step_id="remove_asset",
            data_schema=vol.Schema(
                {
                    vol.Required("asset_id"): vol.In(
                        {item["id"]: item["name"] for item in assets}
                    )
                }
            ),
        )

    def _assets(self) -> list[dict[str, Any]]:
        return list(
            self.config_entry.options.get(
                CONF_ASSETS, self.config_entry.data[CONF_ASSETS]
            )
        )

    def _save_assets(self, assets: list[dict[str, Any]]) -> config_entries.FlowResult:
        return self.async_create_entry(
            title="",
            data={**self.config_entry.options, CONF_ASSETS: assets},
        )

    def _options_schema(self) -> vol.Schema:
        settings = {**self.config_entry.data, **self.config_entry.options}
        return vol.Schema(
            {
                vol.Required(
                    CONF_UPDATE_INTERVAL,
                    default=settings.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=1440, step=1, mode=selector.NumberSelectorMode.BOX
                        )
                ),
                vol.Required(
                    CONF_TIME_STEP_MINUTES,
                    default=settings.get(
                        CONF_TIME_STEP_MINUTES, DEFAULT_TIME_STEP_MINUTES
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=1440, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_HORIZON_HOURS,
                    default=settings.get(CONF_HORIZON_HOURS, DEFAULT_HORIZON_HOURS),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=168, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_REQUEST_TIMEOUT,
                    default=settings.get(CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=300, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_FAILURE_THRESHOLD,
                    default=settings.get(CONF_FAILURE_THRESHOLD, DEFAULT_FAILURE_THRESHOLD),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=20, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
            }
        )

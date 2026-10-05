"""Constants for the Kairos integration."""

from homeassistant.const import Platform

DOMAIN = "kairos"
PLATFORMS = [Platform.SENSOR]

CONF_API_URL = "api_url"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_TIME_STEP_MINUTES = "time_step_minutes"
CONF_HORIZON_HOURS = "horizon_hours"
CONF_REQUEST_TIMEOUT = "request_timeout"
CONF_FAILURE_THRESHOLD = "failure_threshold"
CONF_ASSETS = "assets"

DEFAULT_API_URL = "http://kairos:8000"
DEFAULT_UPDATE_INTERVAL = 15
DEFAULT_TIME_STEP_MINUTES = 15
DEFAULT_HORIZON_HOURS = 24
DEFAULT_REQUEST_TIMEOUT = 60
DEFAULT_FAILURE_THRESHOLD = 3

ASSET_TYPES = (
    "grid",
    "pv",
    "base_load",
    "controllable_load",
    "home_battery",
    "ev_battery",
    "dhw_tank",
    "building_thermal_mass",
)

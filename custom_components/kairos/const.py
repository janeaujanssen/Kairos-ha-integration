"""Constants for the Kairos integration."""

from homeassistant.const import Platform

DOMAIN = "kairos"
PLATFORMS = [Platform.BUTTON, Platform.SENSOR]

CONF_API_URL = "api_url"
CONF_TIME_STEP_MINUTES = "time_step_minutes"
CONF_OPTIMIZATION_STEPS = "optimization_steps"
CONF_HORIZON_HOURS = "horizon_hours"
CONF_REQUEST_TIMEOUT = "request_timeout"
CONF_FAILURE_THRESHOLD = "failure_threshold"
CONF_TIME_LIMIT_S = "time_limit_s"
CONF_RELATIVE_MIP_GAP = "relative_mip_gap"
CONF_SWITCHING_PENALTY = "switching_penalty"
CONF_GRID_PEAK_PENALTY = "grid_peak_penalty"
CONF_ASSETS = "assets"

DEFAULT_API_URL = "http://192.168.1.50:8000"
DEFAULT_TIME_STEP_MINUTES = 15
DEFAULT_OPTIMIZATION_STEPS = 1
DEFAULT_HORIZON_HOURS = 24
DEFAULT_REQUEST_TIMEOUT = 60
DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_TIME_LIMIT_S = 10
DEFAULT_RELATIVE_MIP_GAP = 0.0
DEFAULT_SWITCHING_PENALTY = 0.1
DEFAULT_GRID_PEAK_PENALTY = 0.1

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

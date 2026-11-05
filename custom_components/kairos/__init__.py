"""Home Assistant integration for the Kairos optimization API."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er

from .const import CONF_ASSETS, DOMAIN, PLATFORMS
from .coordinator import KairosCoordinator


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate asset inputs to match the data flow architecture."""
    if entry.version > 4:
        return False

    data = {**entry.data}
    options = {**entry.options}
    for settings in (data, options):
        assets = settings.get(CONF_ASSETS)
        if not isinstance(assets, list):
            continue
        migrated_assets = []
        for asset in assets:
            migrated = {**asset}
            kind = migrated.get("asset_type")
            if entry.version < 2:
                if kind == "controllable_load":
                    energy_demand = migrated.pop("energy_demand", None)
                    if energy_demand is not None:
                        average_power = migrated.get("average_power", 0)
                        migrated["runtime_h"] = (
                            energy_demand / average_power if average_power else 0
                        )
                if kind == "ev_battery" and "vehicle_efficiency" in migrated:
                    migrated["vehicle_efficiency"] *= 1000
            if entry.version < 3:
                # Times and distances are now entities; the stored values seed them.
                if kind == "building_thermal_mass":
                    migrated.pop("heat_pump_cop_charge", None)
                    migrated.pop("heat_pump_cop_default", None)
                    migrated.setdefault("heat_loss_coefficient", 0)
                    migrated["cooldown_rate"] = -abs(migrated.get("cooldown_rate", 0.03))
                migrated.pop("run_started_at", None)
            if entry.version < 4 and kind == "pv":
                migrated["asset_type"] = "solar"
            migrated_assets.append(migrated)
        settings[CONF_ASSETS] = migrated_assets

    if entry.version < 3:
        registry = er.async_get(hass)
        for suffix in ("status", "base_load_forecast"):
            if entity_id := registry.async_get_entity_id(
                "sensor", DOMAIN, f"{entry.entry_id}_{suffix}"
            ):
                registry.async_remove(entity_id)

    hass.config_entries.async_update_entry(
        entry, data=data, options=options, version=4
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Kairos from a config entry."""
    coordinator = KairosCoordinator(hass, entry)
    await coordinator.async_setup()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.async_start()

    async def handle_run_optimization(call: ServiceCall) -> None:
        """Run an optimization immediately."""
        del call
        for active_coordinator in hass.data.get(DOMAIN, {}).values():
            await active_coordinator.async_run_optimization()

    if not hass.services.has_service(DOMAIN, "run_optimization"):
        hass.services.async_register(DOMAIN, "run_optimization", handle_run_optimization)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration after its global options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Kairos config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False

    coordinator: KairosCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
    await coordinator.async_unload()
    if not hass.data[DOMAIN]:
        hass.data.pop(DOMAIN)
        hass.services.async_remove(DOMAIN, "run_optimization")
    return True

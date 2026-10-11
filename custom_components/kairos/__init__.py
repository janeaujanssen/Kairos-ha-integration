"""Home Assistant integration for the Kairos optimization API."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import CONF_ASSETS, DOMAIN, PLATFORMS
from .coordinator import KairosCoordinator


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate asset inputs to match the Kairos app's names and units."""
    if entry.version > 1:
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
            if migrated.get("asset_type") == "controllable_load":
                energy_demand = migrated.pop("energy_demand", None)
                if energy_demand is not None:
                    average_power = migrated.get("average_power", 0)
                    migrated["runtime_h"] = (
                        energy_demand / average_power if average_power else 0
                    )
            if migrated.get("asset_type") == "ev_battery":
                efficiency = migrated.get("vehicle_efficiency")
                if efficiency is not None:
                    migrated["vehicle_efficiency"] = efficiency * 1000
            migrated_assets.append(migrated)
        settings[CONF_ASSETS] = migrated_assets

    hass.config_entries.async_update_entry(
        entry, data=data, options=options, version=2
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Kairos from a config entry."""
    coordinator = KairosCoordinator(hass, entry)
    await coordinator.async_setup()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

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

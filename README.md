# Kairos Home Assistant Integration

Kairos connects Home Assistant to the [Kairos energy optimization API](https://github.com/janeaujanssen/Kairos). It sends a snapshot of configured energy assets to `POST /optimize` and exposes the returned schedules as Home Assistant sensors. The integration never controls physical devices; use your own automations to apply setpoints.

## Features

- Configures the Kairos API URL and verifies it through `GET /health`.
- Collects grid, PV, base-load, controllable-load, battery, DHW tank, and building thermal-mass inputs from Home Assistant.
- Converts common HA units to the physical units required by the API (W, price/Wh, fractional SoC, and °C).
- Periodically optimizes with configurable time step, horizon, timeout, and failure threshold. Forecast points with timestamps are aligned to the configured grid; untimestamped numeric arrays are treated as already step-aligned and held at their last value if shorter than the horizon.
- Exposes schedule sensors, a thermal-mass mode sensor, optimization status, and objective cost.
- Keeps following the last valid schedule when an optimization fails and persists schedules across Home Assistant restarts.
- Provides the `kairos.run_optimization` action for an immediate run.

## Install through HACS

1. Open HACS > Integrations > the three-dot menu > **Custom repositories**.
2. Add `https://github.com/janeaujanssen/Kairos-ha-integration` with category **Integration**.
3. Download **Kairos Energy Optimization**, restart Home Assistant, then add Kairos from **Settings > Devices & services**.

## Setup

Setup is split into two stages:

1. Add **Kairos Energy Optimization** and enter the API URL and global settings. The default is `http://192.168.50.11:8000`; change it if the Kairos API is hosted elsewhere. The URL must be reachable from Home Assistant and respond to `GET /health`. The integration does not assume that `http://kairos:8000` resolves. For an add-on or standalone container exposing port `8000`, use the host IP and port or the add-on's actual network hostname.
2. Open **Settings > Devices & services > Kairos Energy Optimization > Configure**. Choose **Add an asset**, select its type, and fill in its entity selectors and parameters. Add one grid connection and one household base load before optimizing; other assets are optional. Assets can be added, edited, and removed later from the same Configure menu.

The integration entry can be created before any devices are configured. Its status remains `not_configured` until both required assets have been added; it will not send incomplete requests to the API.

Set the update interval and time step in minutes, the planning horizon in hours, and the request timeout. The timeout must be shorter than the update interval, and the update interval must be a multiple of the time step.

For each asset, select the relevant state entities and enter physical limits and parameters. Forecast attributes are read from the selected entity; forecast values are normalized to one numeric value per time step. A missing base-load forecast is held at its current value. PV and grid price forecasts must be present.

The selected grid power entity is normalized to the API convention: positive means import and negative means export. Select whether the source entity itself reports positive import or positive export. Power entities must use W, kW, or MW; price forecast entities need a price-per-energy unit such as EUR/kWh; SoC may be a fraction or percent; temperatures may be °C or °F.

## Entities and automation

For each scheduled grid, controllable load, or storage asset, Kairos creates a setpoint sensor with a `schedule` attribute containing timestamped `{time, value}` points. The sensor state advances through the schedule and becomes unavailable when its schedule expires. Building thermal mass also has a mode sensor (`charge`, `neutral`, or `discharge`). System diagnostics include:

- `sensor.kairos_status` — `not_configured`, `optimal`, `feasible`, `infeasible`, or `error`, with failure count and timing attributes.
- `sensor.kairos_objective_cost` — objective value of the latest valid optimization.

Use a Home Assistant automation to translate each setpoint to device-specific services. For example, a positive battery setpoint can select charge mode and set charge power; a negative value can select discharge mode and use its absolute value. Treat unavailable states as a signal not to issue a new command.

Run an optimization manually from **Developer Tools > Actions** with:

```yaml
action: kairos.run_optimization
```

The integration does not ship dashboards or device-control automations. For API behavior and the full architecture, see the [Kairos Home Assistant integration architecture](https://github.com/janeaujanssen/Kairos/blob/main/kairos/architecture/ha_integration_architecture.md).

## Manual install

Copy `custom_components/kairos` into the `custom_components` directory in your Home Assistant configuration, restart Home Assistant, and add **Kairos Energy Optimization** from **Settings > Devices & services**.

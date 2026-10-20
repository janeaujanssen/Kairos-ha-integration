# Kairos Home Assistant Integration

Kairos connects Home Assistant to the [Kairos energy optimization API](https://github.com/janeaujanssen/Kairos). It sends a snapshot of configured energy assets to `POST /optimize` and exposes the returned schedules as Home Assistant sensors. The integration never controls physical devices; use your own automations to apply setpoints.

## Features

- Configures the Kairos API URL and verifies it through `GET /health`.
- Collects grid, PV, base-load, controllable-load, battery, DHW tank, and building thermal-mass inputs from Home Assistant.
- Converts common HA units to the physical units required by the API (W, price/Wh, fractional SoC, and °C).
- Periodically optimizes with configurable time step, horizon, timeout, and failure threshold. Forecast points with timestamps are aligned to the configured grid; untimestamped numeric arrays are treated as already step-aligned and held at their last value if shorter than the horizon.
- Exposes schedule sensors, a thermal-mass mode sensor, optimization status, and objective cost.
- Groups all Kairos output entities under one Kairos device in Home Assistant.
- Keeps following the last valid schedule when an optimization fails and persists schedules across Home Assistant restarts.
- Provides the `kairos.run_optimization` action for an immediate run.

## Install through HACS

1. Open HACS > Integrations > the three-dot menu > **Custom repositories**.
2. Add `https://github.com/janeaujanssen/Kairos-ha-integration` with category **Integration**.
3. Download **Kairos Energy Optimization**, restart Home Assistant, then add Kairos from **Settings > Devices & services**.

## Setup

Setup is split into two stages:

1. Add **Kairos Energy Optimization** and enter the API URL and global settings. The default is `http://192.168.50.11:8000`; change it if the Kairos API is hosted elsewhere. The URL must be reachable from Home Assistant and respond to `GET /health`. The integration does not assume that `http://kairos:8000` resolves. For an add-on or standalone container exposing port `8000`, use the host IP and port or the add-on's actual network hostname.
2. Open **Settings > Devices & services > Kairos Energy Optimization > Configure**. Choose **Add an asset**, select its type, and fill in its entity selectors and parameters. Add one grid connection and one household base load for normal automatic optimization; other assets are optional. Assets can be added, edited, and removed later from the same Configure menu.

The integration entry can be created before any devices are configured. Automatic optimization remains paused until both required assets (grid and base load) have been added. You can still call `kairos.run_optimization` manually to send the currently configured assets to the API and see its validation response. The diagnostic entity **Last optimization attempt** summarizes the result; its `api_request` attribute contains the JSON payload sent to the API, its `api_response` attribute contains the API response when one was received, and its `error` attribute contains communication errors.

Set the update interval and time step in minutes, the planning horizon in hours, the request timeout, and solver settings. The solver settings match the Kairos API: time limit in seconds, relative MIP gap as a fraction from 0 to 1, storage switching penalty, and grid peak penalty. The request timeout must exceed the solver time limit and remain shorter than the update interval; the update interval must be a multiple of the time step.

For each asset, select the relevant state entities and enter physical limits and parameters. A controllable load uses average power and runtime in hours to derive its energy demand; it can optionally select a timestamp entity for **Run start time**, which your automation sets when the device turns on. EV vehicle efficiency is entered in km/kWh, matching the Kairos app. Forecast attributes are read from the selected entity; forecast values are normalized to one numeric value per time step. The household base-load forecast is generated automatically by averaging recorded power readings from the same weekday and time slot over the previous four weeks. If no matching history is available for a forecast step, that step uses the current power reading. No forecast entity or attribute is needed for the base load. When you call the optimization action, unavailable or invalid entity readings and forecasts are sent as `null` values so the API can validate the request.

The selected grid power entity is normalized to the API convention: positive means import and negative means export. Select whether the source entity itself reports positive import or positive export. Power entities must use W, kW, or MW; price forecast entities need a price-per-energy unit such as EUR/kWh; SoC may be a fraction or percent; temperatures may be °C or °F.

## Configuration inputs

### General settings

| Name | Type | Description |
|---|---|---|
| Kairos API URL | Parameter | Base URL of the Kairos API including the port, for example http://192.168.1.50:8000. |
| Schedule time step [min] | Parameter | Length of each schedule slot, from 1 to 1440 minutes. Default 15. |
| Optimize every N time steps | Parameter | Run the optimization at every Nth time step, from 1 to 1440. 1 runs it at every time step. Default 1. |
| Planning horizon [h] | Parameter | How far ahead the schedule is planned, from 1 to 168 hours. Default 24. |
| Request timeout [s] | Parameter | Maximum wait for one API response, from 1 to 3601 seconds. Must be longer than the solver time limit and shorter than the time step. Default 60. |
| Failures before repair issue | Parameter | Failed optimization runs before a repair issue is shown in Home Assistant, from 1 to 20. Default 3. |
| Solver time limit [s] | Parameter | Maximum solver run time per optimization, from 1 to 3600 seconds. Default 10. |
| Relative MIP gap [0-1] | Parameter | Stop once the best schedule is within this relative gap of the best bound, from 0 to 1. Set to 0 to require the solver to prove optimality. Default 0. |
| Storage switching penalty [cost per mode change] | Parameter | Softly discourages storage mode changes between time steps. Set to 0 to allow switching freely. Default 0.1. |
| Grid peak penalty [relative weight] | Parameter | Dimensionless weight. At 0.40 currency/kWh with 15-minute steps, 0.1 means the optimizer can accept up to 1 cent higher energy cost for a 1 kW lower grid peak. Set to 0 to disable. Default 0.1. |

### Grid

| Name | Type | Description |
|---|---|---|
| Name | Parameter | |
| Grid import price forecast [currency/kWh] | Entity | |
| Grid import price forecast attribute [currency/kWh] | Parameter | |
| Grid export price forecast [currency/kWh] | Entity | |
| Grid export price forecast attribute [currency/kWh] | Parameter | |
| Maximum grid import power [W] | Parameter | |
| Maximum grid export power [W] | Parameter | |

### Solar

| Name | Type | Description |
|---|---|---|
| Name | Parameter | |
| Solar production power forecast [W] | Entity | |
| Solar production power forecast attribute [W] | Parameter | |

### Base load

| Name | Type | Description |
|---|---|---|
| Name | Parameter | |
| Base load power (+/- sensor) [W] | Entity | The household's electrical power draw excluding every device modelled in Kairos (e.g. Home Battery and EV Battery charging, DHW Tank and Building Thermal Mass heat pumps, Controllable Loads). For the heat pump, only the power offsets w.r.t. the default weather compensation power need to be excluded. |

### Controllable load

| Name | Type | Description |
|---|---|---|
| Name | Parameter | |
| Run start time [timestamp entity] | Entity | Set by your automation to the time the device was turned on. |
| Earliest start time | Parameter | |
| Latest finish time | Parameter | |
| Average power [W] | Parameter | |
| Runtime [h] | Parameter | |

### Home battery

| Name | Type | Description |
|---|---|---|
| Name | Parameter | |
| Current state of charge (SoC) [0-1] | Entity | |
| Energy capacity [Wh] | Parameter | |
| Minimum state of charge (SoC) [0-1] | Parameter | |
| Maximum state of charge (SoC) [0-1] | Parameter | |
| Maximum charge power [W] | Parameter | |
| Maximum discharge power [W] | Parameter | |
| Charge efficiency [0-1] | Parameter | |
| Discharge efficiency [0-1] | Parameter | |
| Passive discharge power [W] | Parameter | |

### EV battery

| Name | Type | Description |
|---|---|---|
| Name | Parameter | |
| Current state of charge (SoC) [0-1] | Entity | |
| Energy capacity [Wh] | Parameter | |
| Minimum state of charge (SoC) [0-1] | Parameter | |
| Maximum state of charge (SoC) [0-1] | Parameter | |
| Maximum charge power [W] | Parameter | |
| Maximum discharge power [W] | Parameter | |
| Charge efficiency [0-1] | Parameter | |
| Discharge efficiency [0-1] | Parameter | |
| Passive discharge power [W] | Parameter | |
| Vehicle efficiency [km/kWh] | Parameter | |
| Round-trip distance [km] | Parameter | |
| Expected departure time | Parameter | |
| Expected arrival time | Parameter | |

### DHW tank

| Name | Type | Description |
|---|---|---|
| Name | Parameter | |
| Current water temperature [°C] | Entity | |
| Tank volume [L] | Parameter | |
| Minimum water temperature [°C] | Parameter | |
| Maximum water temperature [°C] | Parameter | |
| Minimum comfort temperature [°C] | Parameter | |
| Heat loss coefficient [W/°C] | Parameter | |
| Heat pump electric power [W] | Parameter | |
| Heat pump coefficient of performance (COP) | Parameter | |
| Morning peak energy demand [Wh] | Parameter | |
| Evening peak energy demand [Wh] | Parameter | |
| Morning demand peak time | Parameter | |
| Evening demand peak time | Parameter | |

### Building thermal mass

| Name | Type | Description |
|---|---|---|
| Name | Parameter | |
| Current indoor temperature [°C] | Entity | |
| Floor area [m²] | Parameter | |
| Thermal mass coefficient [Wh/m²/°C] | Parameter | |
| Default weather compensation temperature [°C] | Parameter | |
| Maximum comfort temperature [°C] | Parameter | |
| Heating rate (+dT) [°C/h] | Parameter | |
| Cooldown rate (-dT) [°C/h] | Parameter | |
| Heat pump COP in charge mode | Parameter | |
| Heat pump COP in default mode | Parameter | |

## Entities and automation

For each scheduled grid, controllable load, or storage asset, Kairos creates a setpoint sensor with a `schedule` attribute containing timestamped `{time, value}` points. The sensor state advances through the schedule and becomes unavailable when its schedule expires. Building thermal mass also has a mode sensor (`charge`, `neutral`, or `discharge`). System diagnostics include:

- `sensor.kairos_status` — `not_configured`, `optimal`, `feasible`, `infeasible`, or `error`, with failure count and timing attributes.
- `sensor.kairos_objective_cost` — objective value of the latest valid optimization.
- `sensor.kairos_household_base_load_forecast` — current forecast value in W, with the full timestamped forecast horizon in its `forecast` attribute.

Use a Home Assistant automation to translate each setpoint to device-specific services. For example, a positive battery setpoint can select charge mode and set charge power; a negative value can select discharge mode and use its absolute value. Treat unavailable states as a signal not to issue a new command.

Run an optimization manually from **Developer Tools > Actions** with:

```yaml
action: kairos.run_optimization
```

The integration does not ship dashboards or device-control automations. For API behavior and the full architecture, see the [Kairos Home Assistant integration architecture](https://github.com/janeaujanssen/Kairos/blob/main/kairos/architecture/ha_integration_architecture.md).

## Manual install

Copy `custom_components/kairos` into the `custom_components` directory in your Home Assistant configuration, restart Home Assistant, and add **Kairos Energy Optimization** from **Settings > Devices & services**.

## Example Home Assistant template for solar forecast
```yaml
- template:
  - triggers:
      - trigger: homeassistant
        event: start
      - trigger: time_pattern
        hours: "/1"

    actions:
      - action: forecast_solar.get_forecast
        data:
          config_entry: 01KRR7KQDK8SPG5WZF7SDH2QAS
          resolution: raw
        response_variable: solar

    sensor:
      - name: Solar Forecast
        unit_of_measurement: W
        state: "{{ solar.watts.values() | list | first | float(0) }}"
        attributes:
          forecast: >
            {% set ns = namespace(items=[]) %}
            {% for t, v in solar.watts.items() %}
              {% set ns.items = ns.items + [{
                'time': t,
                'value': v
              }] %}
            {% endfor %}
            {{ ns.items }}
```
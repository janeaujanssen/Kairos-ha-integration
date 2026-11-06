# Kairos Home Assistant Integration

Kairos connects Home Assistant to the [Kairos energy optimization API](https://github.com/janeaujanssen/Kairos). It sends a snapshot of configured energy assets to `POST /optimize` and exposes the returned schedules as Home Assistant sensors. The integration never controls physical devices; use your own automations to apply setpoints. Inputs and outputs follow the [data flow architecture](https://github.com/janeaujanssen/Kairos/blob/main/kairos/architecture/data_flow_architecture.md).

## Entities created by Kairos

Inputs (config entities, created per asset; values are restored after a restart):

| Entity | Assets |
|---|---|
| `<Asset> Enabled` switch | Solar, Controllable Load, Home Battery, EV Battery, DHW Tank, Building Thermal Mass |
| `<Asset> Run Start Time` datetime | Controllable Load. Your automation should set it to the time the device was last turned on. |
| `<Asset> Earliest Start Time`, `Latest Finish Time` time | Controllable Load |
| `<Asset> Round-Trip Distance` number, `Expected Departure Time`, `Expected Arrival Time` time | EV Battery |

Outputs:

- `<Asset> Power Setpoint` sensor (all assets except Solar and Base Load, which the optimizer does not schedule) with a `forecast` attribute holding the scheduled time and value pairs. It becomes `unavailable` when the schedule runs out.
- `<Asset> Mode` sensor (Building Thermal Mass): `charge` (+dT), `neutral` or `discharge` (-dT).
- Optimizer forecast sensors (diagnostic category, so they appear under the device's Diagnostic section): the forecast the optimizer used, with the time and value pairs in a `forecast` attribute. Grid: `Import Price Forecast`, `Export Price Forecast`. Solar: `Production Power Forecast`. Base Load: `Power Forecast`. Every storage asset: `Energy Demand Forecast`, `Passive Discharge Power Forecast`. Building Thermal Mass also: `COP Forecast`.
- `Objective Cost` and `Last Optimization Attempt` diagnostic sensors, and a `Run optimization` button. The `Last Optimization Attempt` attributes include `thermal_history`: the hourly indoor/outdoor temperature and heat pump electric/thermal power used to derive the heat loss coefficient and COP, per Building Thermal Mass asset. Building Thermal Mass also has diagnostic sensors `Heat Loss Coefficient`, `Reference COP`, `Reference Outdoor Temperature` and `COP Outdoor Temperature Coefficient`, passed 1:1 from the API response.

## Building Thermal Mass history

The reference COP and the COP outdoor temperature coefficient are derived from the last 14 days of recorder history of the indoor temperature, outdoor temperature, electric power and thermal power entities. The heat loss coefficient is derived from the same history unless a non-zero value is configured.


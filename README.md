# Dummy Forecast Setpoint

A Home Assistant custom integration that creates a sensor named **Dummy Setpoint** with fixed demo data.

The sensor's state is always `20.0`. Its `forecast` attribute contains three dummy points with `time` and `forecast_value` keys. The selected entity in the setup form is only used to identify the config entry; the sensor does not read it or change when it changes.

Example sensor attributes:

```yaml
forecast:
  - time: "<setup time plus 1 hour>"
    forecast_value: 18.5
  - time: "<setup time plus 2 hours>"
    forecast_value: 19.0
  - time: "<setup time plus 3 hours>"
    forecast_value: 19.4
```

## Files

- `hacs.json`: Names the repository for HACS.
- `custom_components/dummy_forecast_setpoint/__init__.py`: Forwards integration setup and unload operations to the sensor platform.
- `custom_components/dummy_forecast_setpoint/config_flow.py`: Displays the setup form and lets the user select an entity for the config entry.
- `custom_components/dummy_forecast_setpoint/const.py`: Defines the integration domain, configuration key, and supported platform.
- `custom_components/dummy_forecast_setpoint/manifest.json`: Declares Home Assistant integration metadata, version, and dependencies.
- `custom_components/dummy_forecast_setpoint/sensor.py`: Creates the Dummy Setpoint sensor and its fixed sample forecast data.
- `custom_components/dummy_forecast_setpoint/strings.json`: Supplies the setup form's user-facing labels and messages.
- `README.md`: Describes the integration and explains HACS and manual installation.

## Install through HACS

1. Open HACS > Integrations > the three-dot menu > **Custom repositories**.
2. Add the public GitHub repository URL (`https://github.com/<OWNER>/<REPOSITORY>`) with category **Integration**.
3. Find **Dummy Forecast Setpoint** in HACS and download it.
4. Restart Home Assistant, then add the integration from Settings > Devices & services.

Replace `<OWNER>/<REPOSITORY>` with the GitHub account and repository name after this project is published. The repository must contain `hacs.json` and the `custom_components/dummy_forecast_setpoint` directory at its root.

## Manual install

Copy `custom_components/dummy_forecast_setpoint` into the `custom_components` directory of your Home Assistant configuration, restart Home Assistant, then add **Dummy Forecast Setpoint** from Settings > Devices & services.
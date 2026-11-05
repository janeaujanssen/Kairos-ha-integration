# Kairos Home Assistant Integration

Kairos connects Home Assistant to the [Kairos energy optimization API](https://github.com/janeaujanssen/Kairos). It sends a snapshot of configured energy assets to `POST /optimize` and exposes the returned schedules as Home Assistant sensors. The integration never controls physical devices; use your own automations to apply setpoints.


# Thermal Storage Optimizer 1.1.0

This backward-compatible feature release adds forecast-driven planning inputs, a
second dashboard card, and several planner and controller fixes. No config-entry
migration is required; the stored schema version is unchanged.

Highlights:

- New bundled `custom:thermal-storage-day-chart-card` showing today and tomorrow on
  one time axis: electricity price, the planned firing window, detected firing, and
  planned versus actual use/reserve of the tank. It is fed by the new
  `get_day_chart` response action and recorder history.
- Hourly outdoor-temperature forecasts from the selected weather entity drive
  per-interval heat demand.
- Optional learned heating curve and temperature-dependent COP per
  outdoor-temperature bin.
- Optional supplementary electric heater inputs, used for the effective COP.
- Minimum output dwell now applies to contiguous release windows, so 15-minute
  market resolution no longer prevents every allocation.
- Manual **Use tank** and **Reserve tank** selections apply immediately, and dwell
  is measured from the last actual change rather than from integration load.
- The decision reason shows the next release in local time.

See the [changelog](../CHANGELOG.md) for the complete list.

Upgrade notes:

- Restart Home Assistant after updating. The new card is a separate frontend module
  whose path is registered at startup, so reloading the integration is not enough.
- Clear the browser or companion-app frontend cache if the dashboard reports
  `Custom element not found: thermal-storage-day-chart-card` after the restart.

Safety behavior is unchanged from 1.0.0: active control is opt-in; every load first
requests physical OFF; invalid data, missing plans, faults, unload, and removal
request OFF. Independent thermal, pressure, circulation, flow, and freeze protection
must work without Home Assistant.

Known limitations:

- Automated tests validate Home Assistant 2026.9.1 only.
- The day-chart card was verified against a mocked frontend, not yet on a field
  installation. Tomorrow stays empty until its prices are published, only the next
  firing session is planned, and past rows require the recorder.
- Installation-specific entity mappings, electrical polarity, and physical safety
  behavior still require supervised field commissioning.

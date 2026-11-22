# Changelog

All notable changes use [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
categories. Releases follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2026-11-22

### Added

- Bundled `custom:thermal-storage-day-chart-card` dashboard card showing today
  and tomorrow on one time axis: electricity price, the planned firing window,
  detected firing, and planned versus actual use/reserve of the tank. It is fed
  by the new `get_day_chart` response action and recorder history.
- Hourly outdoor-temperature forecasts from the selected weather entity now drive
  per-interval heat demand. The forecast is bias-corrected toward the measured
  outdoor temperature over the first six hours and falls back to the measured value
  when unavailable, malformed, or stale. Diagnostics and the plan summary report
  the forecast state and per-interval outdoor temperature.
- Optional learned heating curve: with **Learn temperature-dependent curves**
  enabled, the supply target is learned per outdoor-temperature bin from the
  configured entities and applied per forecast interval. Bins are bounded, aged
  out after 30 days, exposed on a new **Learned temperature curves** diagnostic
  entity, persisted across restarts, and cleared by the reset action.
- Temperature-dependent COP learned from the measured-COP entity per
  outdoor-temperature bin (sampled only while the heat pump runs when its
  electrical power is configured). Each forecast interval uses the learned COP for
  its own forecast outdoor temperature, a learned Carnot efficiency extrapolates
  beyond the observed range, and the fixed or calibrated value remains the last
  fallback. The COP source entity gains `learned_curve` and
  `carnot_extrapolation` states.
- Optional supplementary electric heater inputs (electrical power, or output
  share with a rated power option). With the heat-pump electrical power and the
  measured COP, the planner uses the system's effective COP, learns the heater's
  heat share per outdoor-temperature bin, reports the learned balance point in
  diagnostics, and exposes the current heater heat share as a diagnostic sensor.

### Fixed

- Input freshness is now measured from the last report instead of the last
  change. A healthy sensor that kept reporting the same value for longer than the
  stale limit, such as a steady supply setpoint or an idle heat pump's power, was
  marked stale; for a required input this put the controller in fault fallback.
- The planner's decision reason now shows the next release in Home Assistant's
  local time, rounded up to the whole minute, instead of a raw UTC timestamp with
  microseconds that looked like a time in the past and changed the entity state
  on every replan. A reused plan no longer produces a reason starting with a
  dangling semicolon.
- Manual **Use tank** and **Reserve tank** selections now apply immediately
  instead of being held by minimum dwell, and dwell is measured from the last
  actual use/reserve change rather than from integration load. Previously no
  reserve command, manual or automatic, could take effect during the first dwell
  period (30 minutes by default) after every restart, reload, or saved option.
  Auto still observes dwell, and startup grace and the high-temperature override
  are unchanged.
- Minimum output dwell now applies to contiguous release windows instead of
  each price period. With 15-minute market resolution and the default 30-minute
  dwell, every period was shorter than the dwell and no tank energy was ever
  allocated. A chain of consecutive periods is now laid out as one window with
  the partial release at its front, a lone period that can never reach the dwell
  yields its energy to a broad peak, and reserve gaps shorter than the dwell
  drop the smaller release.

## [1.0.0] - 2026-09-08

### Added

- Deterministic manual-installation archive and tag-driven release workflow.
- CI for all tests, Ruff formatting/linting, strict mypy, package validation, and
  Home Assistant Hassfest validation.
- Install, upgrade, compatibility, removal, release, backup, and rollback guidance.
- Explicit tests for every supported config-entry version and persisted-state removal.

### Changed

- Declared the single-config-entry constraint in the integration manifest.
- Config-entry migrations now reject unsupported schemas and distinguish legacy
  pre-control entries from entries containing an explicit active-control choice.
- Removal now deletes the saved plan, calibration, controller mode, and charging-
  advisor stores after Home Assistant unloads the integration safely.
- Removed the unused custom-integration `strings.json`; complete runtime translations
  remain in `translations/en.json` and `translations/sv.json`.

### Safety

- Fresh installs and pre-actuation config entries default to dry-run.
- Upgrades from actuation-capable entries retain the explicit permission setting but
  still request physical OFF and reapply startup grace on reload/restart.
- Physical safety remains independent of Home Assistant. Physical output OFF is the
  intentional fault, load, unload, restart, and removal fallback.

## [0.8.0] - 2026-09-08

### Added

- Bounded adaptive energy-model calibration and measured-savings validation.

Earlier milestone builds were development snapshots rather than maintained releases.

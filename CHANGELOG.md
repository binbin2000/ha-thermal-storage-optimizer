# Changelog

All notable changes use [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
categories. Releases follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

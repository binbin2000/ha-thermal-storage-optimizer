# Thermal Storage Optimizer 1.0.0

This is the first maintainable manual-installation release. It packages the completed
planning, dry-run, supervisory output control, stove-charging advice, diagnostics,
field-validation, and bounded adaptive-calibration milestones without adding new
product behavior.

Release hardening adds deterministic packaging, automated quality gates, explicit
config-entry compatibility checks, full lifecycle coverage, and removal cleanup.
See [installation and lifecycle](installation.md), [compatibility](compatibility.md),
and [backup and rollback](backup-rollback.md) before upgrading.

Important safety behavior is unchanged: active control is opt-in; every load first
requests physical OFF; reload/restart reapplies startup grace; invalid data, missing
plans, faults, unload, and removal request OFF. OFF must be verified at the actual
installation as normal local shunt/tank operation. Independent thermal, pressure,
circulation, flow, and freeze protection must work without Home Assistant.

Known limitations:

- Automated tests validate Home Assistant 2026.9.1 only.
- HACS distribution is not enabled because no public repository identity, issue
  tracker, code owner, or Home Assistant Brands entry has been declared.
- No redistribution license has been selected; the project owner must add one before
  treating this as a public open-source release.
- Installation-specific entity mappings, electrical polarity, and physical safety
  behavior still require supervised field commissioning.

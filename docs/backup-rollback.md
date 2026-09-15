# Disable, backup, rollback, and physical fail-safe

## Fast disable

For an orderly stop, select **Disabled** and verify **Reserve output active** is off
and the physical shunt input has returned to normal local control. Then turn off
**Allow physical output control** in integration options. Reloading or removing the
integration requests OFF, but software confirmation is not proof against a stuck
relay. If behavior is unsafe or unclear, de-energize/bypass the reserve relay using
the installation's approved physical procedure and operate the heating system under
its local controller.

Do not use output inversion as an emergency workaround. It changes normal logical
mapping, while fault fallback intentionally remains physical OFF.

## Backup

Before installation, upgrade, tuning, or active commissioning:

1. Create and verify a Home Assistant backup containing configuration and custom
   integrations; copy it off the Home Assistant host.
2. Record the integration version, Home Assistant version, config/options screenshots
   or export, selected entity IDs, price unit/currency, layer volumes, thresholds,
   firing windows, output polarity, and physical OFF test result.
3. Save diagnostics and a bounded plan summary. Diagnostics redact identifiers, so
   retain the separate private entity mapping securely.
4. Keep a copy of the previously working
   `custom_components/thermal_storage_optimizer` directory/version.

Runtime stores contain the last valid plan, persisted user mode, and bounded active
firing/notification continuity. They are not a substitute for configuration backup.
Milestone 8 stores bounded adaptive calibration separately from the last valid plan.

## Rollback

1. Select Disabled, revoke active-control permission, verify physical OFF, and stop
   any commissioning trial.
2. Restore the previous integration directory/version or the verified Home Assistant
   backup, then restart Home Assistant.
3. Confirm the integration requests OFF on load and repeats startup grace. Recheck
   entity mapping, migrations, inputs, diagnostics, and a dry-run price cycle before
   considering active control again.
4. If rollback compatibility is uncertain, remove the integration config entry only
   after recording its settings; keep the physical output de-energized and re-add in
   dry-run. Never restore old runtime storage as a way to force an output state.

The `reset_learned_state` action clears bounded calibration samples and learned
parameters. It never clears the plan, user mode,
safety/controller state, or firing-session continuity.

Config-entry schema downgrades are not guaranteed. If the older integration rejects a
newer entry, restore the matching full Home Assistant backup rather than editing
`.storage` by hand. See the [installation and lifecycle guide](installation.md) for
the version 1.0.0 upgrade and removal sequence.

## Physical fail-safe expectation

The intended installation is wired so loss of Home Assistant, integration operation,
relay power, or command leaves the reserve input de-energized: no −50 °C offset and
normal local shunt/tank use. Independent stove/boiler overtemperature, pressure,
circulation, emergency cooling, heat-pump minimum-flow/volume, and freeze protection
must function without Home Assistant. Where the real installation cannot meet that
expectation, active control is not ready for commissioning.

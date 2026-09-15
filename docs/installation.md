# Installation, upgrade, and removal

## Manual installation

Release assets contain a deterministic archive named
`thermal_storage_optimizer-<version>.zip`. Back up Home Assistant first, stop Home
Assistant, and extract the archive at the Home Assistant configuration root. The
result must be:

```text
<config>/custom_components/thermal_storage_optimizer/manifest.json
```

Alternatively, copy the repository's
`custom_components/thermal_storage_optimizer` directory to the same location. Do not
copy `tests`, `dev`, caches, or repository scripts into Home Assistant. Start Home
Assistant, then use **Settings → Devices & services → Add integration** and select
**Thermal Storage Optimizer**. No YAML is required and only one entry is supported.

New entries start with **Allow physical output control** off. Complete configuration
and field validation in dry-run before considering supervised active control.

## Upgrade

1. Record the current integration and Home Assistant versions, configuration, output
   polarity, diagnostics, and a verified physical-OFF result. Create an off-host Home
   Assistant backup and retain the previous integration directory/archive.
2. Select **Disabled**, turn off active-control permission, and verify the actual
   reserve output is de-energized before replacing files.
3. Stop Home Assistant and replace the entire integration directory with the new
   release payload. Do not merge old and new source files.
4. Start Home Assistant and inspect logs, entry status, entity availability, plan
   status, restored mode, and output state. Re-run a dry-run forecast cycle.

Config entries from schema versions 1 through 6 migrate forward explicitly. Entries
from versions before physical actuation existed are forced to dry-run. Versions 4 and
newer preserve an existing explicit active-control choice, avoiding an unannounced
change to commissioned behavior; nevertheless, every setup/reload/restart first
requests physical OFF and applies startup grace. Unknown newer or invalid config-entry
schemas are rejected rather than guessed. Downgrades may require backup restoration.

## Reload and restart

An integration reload unloads subscriptions, entities, and actions and requests OFF,
then performs a fresh setup. A Home Assistant restart follows the same startup safety
sequence. User mode and bounded runtime state may be restored, but output state and
dwell time are never assumed. Verify OFF and startup grace after both operations.

## Removal

1. Select **Disabled**, revoke active-control permission, and physically verify OFF.
2. Remove Thermal Storage Optimizer from **Settings → Devices & services**.
3. The unload requests OFF and Home Assistant removes the config entry; the integration
   then deletes its private plan, calibration, controller-mode, and advisor stores.
4. Stop Home Assistant and delete
   `<config>/custom_components/thermal_storage_optimizer` if the code is no longer
   needed, then restart. Removing software is not proof that a relay is safe; use the
   approved physical bypass/de-energization procedure if state is unclear.

## HACS status

This release is prepared and supported for manual installation only. HACS remains a
future distribution option. Do not add this repository as a HACS custom repository
until it has a public GitHub location, documentation and issue-tracker URLs, named
code ownership, a chosen redistribution license, Home Assistant Brands assets,
required `hacs.json`, and passing HACS validation. This avoids shipping placeholder
ownership or publishing metadata.

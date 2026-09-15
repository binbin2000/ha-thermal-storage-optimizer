# Local Home Assistant test environment

This configuration runs a separate Home Assistant instance against the custom
integration in this repository. It uses only simulated local entities and does
not connect to or control production equipment. The launcher contains a narrow
compatibility layer for native Windows because Home Assistant Core officially
targets Linux, macOS, and Windows through WSL. Voice processing and camera
acceleration are intentionally unavailable in this harness; neither is used by
Thermal Storage Optimizer.

From the repository root, validate the configuration:

```powershell
.\scripts\start_home_assistant.ps1 -Check
```

Start Home Assistant and open its UI:

```powershell
.\scripts\start_home_assistant.ps1 -OpenUi
```

On first launch, create a local test user. Then go to **Settings > Devices &
services > Add integration**, search for **Thermal Storage Optimizer**, and use
these required entities:

| Integration field | Test entity |
| --- | --- |
| Tank top | `sensor.tso_tank_top` |
| Tank middle | `sensor.tso_tank_middle` |
| Tank bottom | `sensor.tso_tank_bottom` |
| Return temperature | `sensor.tso_return_temperature` |
| Supply target | `sensor.tso_supply_target` |
| Outdoor temperature | `sensor.tso_outdoor_temperature` |
| Price forecast | `sensor.tso_price_forecast` |
| Reserve output | `input_boolean.tso_reserve_output` |

Optional test entities are also available for electrical power, measured COP,
flow rate, and the stove charging pump. Change their backing controls under
**Settings > Devices & services > Helpers** to test live updates. The expected
healthy result is a `ready` input status, a `full_forecast` plan status, and an
enabled data-valid diagnostic entity. The development price entity deliberately
mixes one-hour, half-hour, 90-minute, and five-hour periods.

For Milestone 7, also verify that the config-entry diagnostics download redacts
the `sensor.tso_*` and output IDs, and exercise `recalculate` and
`get_plan_summary` from **Developer tools > Actions**. The latter must return no
more than its requested interval limit. Add the standard-card dashboard from
`docs/dashboard-example.yaml` after replacing its example entity IDs with those
created in this test instance. Follow `docs/field-scenarios.md`; all output and
notification failures must use fake/local entities only.

Stop the server with Ctrl+C. Runtime state, logs, and the copied integration are
ignored by version control. To reset only this test instance, stop Home
Assistant and remove `.storage` from this directory.

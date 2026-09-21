# Thermal Storage Optimizer

Thermal Storage Optimizer is a Home Assistant custom integration intended to
plan when heat in a hydronic accumulator tank is most valuable. Version 1.0.0
is the first maintainable, SemVer release and includes deterministic manual
packaging, explicit config-entry migrations, lifecycle cleanup, and automated
release-quality checks. New installations remain in dry-run; upgrades preserve
only active-control choices made in actuation-capable versions.

Home Assistant is not a safety controller. Independent stove, boiler,
overtemperature, pressure, circulation, and freeze protection must remain in
place.

## Installation with HACS

1. In HACS, open **Integrations**, select the three-dot menu, and choose
   **Custom repositories**.
2. Add `https://github.com/binbin2000/ha-thermal-storage-optimizer` with the
   category **Integration**.
3. Find **Thermal Storage Optimizer** in HACS and select **Download**.
4. Restart Home Assistant.
5. In **Settings → Devices & services**, select **Add integration** and search
   for **Thermal Storage Optimizer**.

The integration requires Home Assistant 2026.9.1 or newer. HACS installs the
files under `custom_components/thermal_storage_optimizer` and manages future
updates.

## Manual installation

The current compatibility floor is Home Assistant 2026.9.1, the latest stable
release selected for this milestone.

1. Extract the release archive at the Home Assistant configuration root, or
   copy `custom_components/thermal_storage_optimizer` into its matching
   directory.
2. Restart Home Assistant.
3. In **Settings → Devices & services**, select **Add integration** and search
   for **Thermal Storage Optimizer**.

No YAML configuration is required. Only one instance can be configured.
Select the required tank, heating-system, outdoor, price-forecast, and reserve
output entities in the setup flow. Optional weather, indoor, heat-pump, stove,
flow, and notification entities can be added at the same time or later through
**Reconfigure**. The input freshness thresholds are tuning values under
**Options**. Model defaults are a 500 L tank split equally across the three
temperature sensors, a 3 °C minimum useful delta above return temperature,
30 kWh calibrated usable capacity, a 0.1 kWh trend deadband, a 0.3 kW/K heat-
loss coefficient, 17 °C balance temperature, fixed COP 3.0, 0.995 hourly
retention, 0.85 forecast confidence, and a 0.05 currency/kWh-heat economic
deadband. Price multiplier and additive variable electricity cost are also
configurable. Controller defaults are dry-run, non-inverted output, an 85 °C
forced-use threshold with 5 °C hysteresis, a five-minute startup grace, and a
30-minute minimum dwell. Change these installation-specific assumptions before
relying on the estimates. The three effective layer volumes must sum to the
total tank volume.

Read the complete [installation, upgrade, reload, restart, and removal guide](docs/installation.md)
before changing an existing installation. Also review the [compatibility statement](docs/compatibility.md),
[configuration reference](docs/configuration.md),
[release notes](docs/release-notes-1.0.0.md), [changelog](CHANGELOG.md), and
[backup/rollback procedure](docs/backup-rollback.md).

## Development

Python 3.14.2 or newer is required by the target Home Assistant release. On a
clean checkout:

```shell
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python scripts/run_tests.py
.venv/Scripts/python -m ruff format --check .
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m mypy
```

On macOS or Linux, replace `.venv/Scripts/python` with `.venv/bin/python`.
The Home Assistant and test dependencies are pinned to the repository's
compatibility floor so config-flow and lifecycle tests are reproducible.

### Local Home Assistant test instance (Windows)

The repository includes an isolated Home Assistant configuration with
simulated thermal-system entities. It does not connect to production equipment.

```powershell
.\scripts\start_home_assistant.ps1 -Check
.\scripts\start_home_assistant.ps1 -OpenUi
```

The first start may download Home Assistant's UI dependencies. Complete the
local onboarding at `http://127.0.0.1:8123`, add **Thermal Storage Optimizer**,
and select the `sensor.tso_*` test entities. The complete entity mapping and
test procedure are in [`dev/home-assistant/README.md`](dev/home-assistant/README.md).

## Architecture

Home Assistant adapters and entities live in
`custom_components/thermal_storage_optimizer`. Raw Home Assistant states are
converted into immutable typed snapshots by a pure normalization layer. Input
problems are explicit (`missing`, `unknown`, `unavailable`, `stale`,
`non_numeric`, `incompatible_unit`, or invalid state/timestamp) and are exposed
through concise status and data-valid diagnostics. State subscriptions and a
lightweight freshness check update those diagnostics and are removed on unload.
Temperatures are normalized to °C, power to kW, energy to kWh, and volume flow
to L/min. Missing unit metadata is rejected for dimensional measurements rather
than guessed. Invalid optional measurements remain visible in diagnostics but
do not make the required input set invalid.

The three-layer model converts litre-kelvin to kWh using 0.001163. Usable
energy is measured above return temperature plus the configured useful delta;
high-grade energy is measured above the current supply target. Both are clipped
at zero. SOC is usable energy divided by calibrated usable capacity and is
bounded to 0–100%. All five thermal temperatures must be present for an energy
estimate. Normal top-to-bottom stratification reports good confidence; an
inverted layer order remains calculable but reports degraded confidence.

The integration exposes usable energy, high-grade energy, and SOC alongside
diagnostic sensors for reference temperature, tank stratification, confidence,
data quality, energy trend, next-hour heat demand, estimated COP, and COP
source. Trend compares consecutive usable-energy estimates using the configured
deadband. The demand diagnostic is the transparent one-hour result of
`H × max(T_balance − T_outdoor, 0)`. A valid measured COP is preferred when
configured; otherwise the validated fixed value is used with lower confidence.
Usable, high-grade, target, and remaining tank energy use Home Assistant's
`energy_storage`/`measurement` contract because these values legitimately rise
and fall; they are not cumulative utility meters. Forecast health and model
quality entities are diagnostic, while decisions, control state, tank state,
and charging advice remain visible operational entities.

The price input can be Home Assistant's official Nord Pool `Current price`
sensor. The adapter uses the official response action to fetch timestamped today
and tomorrow periods, converts the returned currency/MWh price to currency/kWh,
and preserves the actual 60- or 15-minute resolution. Generic timestamped
`prices` attributes and custom Nord Pool `raw_today`/`raw_tomorrow` attributes
are also supported. Bare numeric arrays remain rejected because their intervals
and DST behavior cannot be inferred safely. See
[`docs/price-forecast-adapter.md`](docs/price-forecast-adapter.md).

For each variable-duration interval, the planner calculates heat demand,
selects measured or fallback COP, divides marginal electricity cost by COP,
and discounts the result for storage retention and confidence. It sorts
eligible intervals by adjusted avoided heat cost, allocates tank energy up to
each interval's heat demand, and uses chronological order for ties. The
economic deadband leaves energy unallocated when a known opportunity is not
materially better than the horizon baseline, so a short pre-publication
forecast is not treated as an instruction to empty the tank. A new source token
or final timestamp replaces the plan; malformed or delayed updates continue the
last valid timestamp-checked plan across restarts.

Forecast end, coverage, last optimization, next release, expected avoided cost,
plan status, reason, and the binary dry-run recommendation are exposed as
entities. Plan-status attributes contain at most three interval summaries; the
full plan is persisted privately rather than placed in recorder-heavy entity
attributes.

Physical actuation remains separate from planning. The controller keeps planner
recommendation, user mode, and actuation permission independent. `Auto`, `Use
tank`, `Reserve tank`, and `Disabled` select requested behavior; only **Allow
physical output control** grants service calls beyond fail-safe OFF requests.
Selecting Auto on a fresh or migrated entry therefore cannot energize output.

For the intended installation, non-inverted mapping means output OFF is normal
shunt-curve/tank use and output ON applies the −50 °C reserve offset. Inversion
reverses normal use/reserve calls, but load, unload, invalid data, missing plan,
recoverable exception, and service-failure fallback always request physical
OFF. Any valid tank layer at the configured high limit forces use immediately,
including in manual Reserve mode; hysteresis prevents premature release. Normal
changes observe minimum dwell, while forced use and fail-safe OFF do not.

The Milestone 6 charging advisor turns unmet high-value forecast demand into a
manual stove-firing recommendation. Its target is capped by calibrated usable
capacity, per-layer temperature targets, the forced-use margin, and residual
burn-down heat. It schedules the fuel phase inside weekday-specific preferred
windows (15:00–23:00 by default); morning and other out-of-window advice stays
disabled unless explicitly permitted. Live sensors show energy added, smoothed
session-local power, remaining energy/time, expected completion, and residual
completion. Notifications and manual session actions have no controller or
reserve-output actuation path. See the
[charging advisor guide](docs/charging-advisor.md).

Milestone 8 diagnostics are available from the config-entry diagnostics download.
Configured entity/notification identifiers are redacted; normalized semantic
inputs, validation issues, model outputs, a maximum 12-interval plan preview,
controller state, and advisor summary remain available. Raw price-provider arrays
and notification error details are excluded.

Additional Home Assistant actions are registered under
`thermal_storage_optimizer`:

- `recalculate` refreshes available provider data and rebuilds the plan from the
  current inputs. It grants no actuation permission and bypasses no safety rule.
- `get_plan_summary` returns a response with 12 future intervals by default and a
  hard maximum of 48, suitable for inspection/export without recorder attributes.
- `reset_learned_state` clears only bounded local calibration samples and learned
  values. It never clears plan, mode, safety, or active firing-session continuity.

Bounded adaptive calibration is disabled by default. When explicitly enabled it
uses throttled Home Assistant state changes, retains at most 2,016 observations in
memory and at most 96 samples per persisted calibration feature, and never queries
Recorder. Every learned scalar exposes value, physical bounds, confidence, sample
count, provenance, last-update time, and fallback reason. Values below the configured
confidence gate immediately select the existing deterministic setting. See the
[adaptive calibration and validation guide](docs/adaptive-calibration.md).

Use the [standard-card dashboard example](docs/dashboard-example.yaml), then follow
the [staged field-validation guide](docs/field-validation.md). Synthetic scenario
definitions and test traceability are in [field scenarios](docs/field-scenarios.md),
and recovery procedures are in [backup and rollback](docs/backup-rollback.md).

Read the [operating and safety guide](docs/operating-safety.md) before enabling
active control. Planner separation remains documented in
[ADR 0001](docs/adr/0001-separate-planning-and-actuation.md).

The integration also bundles the `custom:thermal-storage-plan-card` dashboard card.
It loads the recorder-independent plan action directly and displays the complete
known forecast as a proportional timeline: use/reserve bands, allocated tank energy,
heat demand, electricity price, the current-time marker, and day boundaries. Select
an interval for exact values or expand the initially collapsed detail table. The card
refreshes when plan status or the last-optimization sensor changes and provides a
manual **Recalculate** action. Override the two entity IDs in the dashboard YAML if
Home Assistant assigned non-default names.

## Roadmap

- [x] Milestone 1: repository foundation and integration skeleton
- [x] Milestone 2: entity configuration, validation, and normalized inputs
- [x] Milestone 3: thermal energy, heat demand, and COP models
- [x] Milestone 4: price adapter and dry-run rolling optimizer
- [x] Milestone 5: fail-safe, explicitly enabled shunt actuation
- [x] Milestone 6: stove charging advisor and live firing guidance
- [ ] Milestone 7: diagnostics and automated scenarios implemented; field validation pending
- [ ] Milestone 8: adaptive models tested; measured-savings validation pending
- [x] Milestone 9: source/archive validation and automated installation tests

Detailed acceptance criteria remain in
`Thermal_Storage_Optimizer_Codex_Plan.md`. Implementation and automated verification
are distinct from field acceptance. Dry-run commissioning, supervised operation,
Linux Home Assistant installation, comfort preservation, and measured savings
remain to be accepted on the actual installation. Version 1.0.0 does not establish
those field outcomes.

## Rolling dispatch and model limits

Allocation refreshes when tank energy, temperatures, COP, confidence, or learned
model inputs change, and at the configured planning interval (1-60 minutes,
default 15). The last valid prices are retained separately; a malformed or shorter
publication does not prevent allocating against those prices with current inputs.
Saved prices and the reservation deadline survive restart.

Each allocation is delivered during a bounded window ending at its price interval
boundary. Scheduled callbacks update control at window boundaries. New windows
must satisfy minimum dwell, and observed tank energy protects heat committed to
later intervals; that budget stop takes priority over dwell in Auto. Manual use
and the independent high-temperature override can consume reserved heat. Dispatch
still depends on estimated demand and sensor update latency and requires field
commissioning.

Only positive marginal avoided heat costs qualify for economic release. A
24-hour reservation deadline persists across publications, after which positive
flat-price periods become eligible even without clearing the relative deadband.
A short forecast alone does not cause a dump. Allocation divides delivered heat
by retention to account for stored energy consumed; losses are conservatively
charged through each interval's end. Retained energy is expressed as an equivalent
at the optimization timestamp.

Output-active reports the observed entity state (unknown when unavailable).
Commands have a 30-second acknowledgement allowance, checked on subsequent input
or timer evaluation (normally within one minute). Persistent disagreement raises
a latched fault and requests OFF. After investigating, select a mode again to
retry. A successful service call does not establish physical relay confirmation.

Charging power is net tank storage gain. The target includes planned discharge
before firing begins, including manual/forced use, without adding building demand
again during firing. Forecast outdoor temperature currently repeats the measured
outdoor temperature; selecting a weather entity validates availability but does
not yet apply its hourly forecast. High-grade energy remains diagnostic.

Learned values fall back when required evidence disappears or becomes anomalous.
Maximum evidence ages are one day for COP/building demand, seven days for capacity,
and 30 days for stove-session parameters. Feature timestamps persist independently;
unchanged samples cannot refresh a fit's age. See the
[scope-review implementation record](docs/scope-review-implementation-2026-09-08.md).

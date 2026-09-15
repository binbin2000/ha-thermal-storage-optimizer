# Scope compliance review — 2026-09-08

## Verdict

The project has substantial implementation across all nine milestones, but it does **not yet meet the complete scope**. The strongest gaps concern rolling replanning, realizing energy allocations through a binary output, economic edge cases, and reconciliation of commanded versus observed output state. The README's statement that all milestones are complete is stronger than the evidence supports.

This review used the complete `Thermal_Storage_Optimizer_Codex_Plan.md` and prompt pack, implementation, tests, packaging, and commissioning documentation. No production equipment was controlled. Application source was not modified. P1 means fix before relying on automatic operation; P2 means a material requirement or release-quality correction.

## Verification

| Check | Result |
| --- | --- |
| Full existing test suite | 141 passed in 16.73 seconds |
| Ruff lint | Passed |
| Mypy | Passed; 26 source files |
| Ruff formatting | Failed: `tests/test_release.py`, string-membership assertion around line 27 |
| Package source/version validation | Passed; 31 files |
| Existing distribution ZIP compared byte-for-byte with package sources | Does not match; details below |
| Additional in-memory behavioral probes | Confirmed stale-plan reuse, negative avoided cost, complete flat-price reservation, and loss-free energy allocation despite retention losses |

Local tests used Python 3.14.2 and the repository's Windows test wrapper. Live Linux Home Assistant commissioning, remote CI/Hassfest results, browser interaction, and actual monetary savings were not verified. This workspace has no Git repository metadata, so commit history and release provenance could not be checked.

## Findings

### 1. P1 — Output state can diverge from the controller without correction

**Location:** `custom_components/thermal_storage_optimizer/controller.py:449`, especially lines 462 and 502. **Scope:** sections 4.4 and 7; Milestone 5.

The controller compares its desired output with `self.output_active`, which is updated after a service call. It does not compare against the normalized state of the configured output entity. A manual change, another automation, or a device resetting after a reconnect can therefore leave the actual output opposite to the requested state. Re-evaluation with an unchanged decision issues no corrective call. The output-active entity reflects the cached command rather than confirmation.

The code-path probe confirmed zero service calls for an unchanged OFF decision and OFF cache; the method never consults actual output state. This is a software finding, not a physical relay test.

**Correction:** Reconcile desired state with observed entity state, allow a bounded acknowledgement period, and expose persistent disagreement as a fault. Test external ON while use/fallback remains requested and external OFF while reserve remains requested.

### 2. P1 — The plan does not roll forward when energy or demand changes

**Location:** `custom_components/thermal_storage_optimizer/coordinator.py:488`. **Scope:** sections 4.3 and 6; Milestone 4.

When the price publication key is unchanged, `_update_plan` returns the existing plan before using the updated tank energy, outdoor temperature, supply target, or model parameters. The minute timer refreshes snapshots but does not periodically rebuild the allocation. Only a changed publication or explicit recalculate action gets past this branch; there is no configurable periodic planning trigger.

A direct probe changed available energy from 10 to 1 kWh and outdoor temperature to -15 °C. The method returned the identical plan, still declaring 10 kWh available. A stove charge after publication has the corresponding opposite problem: new heat is not allocated automatically.

**Correction:** Preserve the last valid price forecast separately from the allocation. Replan against those prices on material input changes and a configurable timer while retaining deliberate horizon-continuation behavior.

### 3. P1 — Partial interval allocations are not enforced by binary control

**Location:** `custom_components/thermal_storage_optimizer/optimizer.py:55` and `:129`. **Scope:** sections 2 and 4.3–4.4.

Any positive allocation becomes USE_TANK for the whole interval. There is no release budget, estimated stop time, or discharge tracking that ends use when that allocation has been delivered. For example, allocating 1 kWh to an earlier interval with 5 kWh demand while reserving 3 kWh for a later expensive interval can consume the entire 4 kWh tank during the earlier interval. Minimum dwell adds another constraint that the planner does not consider.

**Correction:** Make the dispatch plan realizable through the binary actuator, including dwell constraints and an allocation stop condition. Add a chronological closed-loop tank simulation that verifies later allocations remain deliverable, rather than testing the static allocation table alone.

### 4. P1 — Negative marginal heat costs can cause economically harmful release

**Location:** `custom_components/thermal_storage_optimizer/optimizer.py:119`. **Scope:** section 2; negative-price validation in Milestones 4 and 7.

Eligibility is relative to the cheapest interval and has no positive-value condition. With marginal heat costs of -1 and -0.2 per kWh, a 0.05 deadband, and 10 kWh stored, the optimizer allocates all 10 kWh to the second interval and reports **-2.0** expected avoided cost. Using stored heat there increases modeled electricity cost compared with using the heat pump. The advisor already filters positive values, so the two paths disagree.

**Correction:** Exclude non-positive economic discharge value unless an independent thermal override requires use. Add all-negative and mixed near-zero forecasts, including variable electricity additions.

### 5. P2 — Flat-price forecasts can reserve heat indefinitely

**Location:** `custom_components/thermal_storage_optimizer/optimizer.py:119`. **Scope:** section 5 explicitly prohibits indefinite reservation caused by the horizon.

Every interval must beat the minimum forecast value by the deadband. A 35-hour constant positive-value forecast with 10 kWh stored allocates zero heat. Repeating such publications repeats the reservation. Existing tests explicitly accept flat-price reservation but do not bound how long it lasts.

**Correction:** Add a bounded continuation value or retention policy. Distinguish avoiding a dump at a shortened horizon from preserving heat forever despite positive avoided cost and storage losses. Verify several consecutive publications with a changing tank state.

### 6. P2 — Storage losses affect ranking but not energy feasibility

**Location:** `custom_components/thermal_storage_optimizer/forecast.py` and `optimizer.py:129`. **Scope:** sections 2 and 4.3.

Retention discounts economic value, but the allocation subtracts delivered heat directly from today's stored energy. With 10 kWh available and 50% retention at a future interval, the probe allocated 10 kWh there although only 5 kWh can remain. The same error is smaller but still present with default retention.

**Correction:** Explicitly distinguish stored-energy expenditure from delivered energy and enforce a chronological energy balance. Validate conservation under losses and partial allocations.

### 7. P2 — Charging calculations mix net power with additional building demand

**Location:** `custom_components/thermal_storage_optimizer/advisor.py:339`, `:349`, and `:365`. **Scope:** section 4.6; Milestone 6.

`initial_power` is defined and calibrated as the net increase of stored tank energy. The advisor estimates a session duration from that net power, adds building demand during that duration to the energy target, and then schedules the enlarged target using the same net power. Under the documented net-power definition this counts the simultaneous building load twice. Predicted intervening discharge is also hardcoded to zero.

**Correction:** Choose one consistent energy balance: net storage power with a net storage target, or gross stove power minus building heat and losses. Derive intervening discharge from the actual dispatch plan. Test active building demand, manual use, and forced use before the charging deadline.

### 8. P2 — Learned parameters do not immediately fall back when measurements become unsuitable

**Location:** `custom_components/thermal_storage_optimizer/adaptive.py:56`, `:384`, and `:543`. **Scope:** Milestone 8 and prompt 8.

Parameter selection checks bounds, confidence, sample count, and fallback reason, but not measurement availability or age. Rejected observations leave existing parameters intact; missing meter deltas leave the previous samples available for recalibration. A previously trusted COP or demand fit can remain selected after its supporting measurements disappear. `last_updated` is exposed but is not a validity gate.

**Correction:** Define per-feature observation-health and age rules, invalidate affected learned values when the required evidence is unavailable or anomalous, and verify deterministic fallback after a previously successful calibration.

### 9. P2 — Release completion claims do not match the deliverable

**Locations:** `tests/test_release.py:27`, `dist/thermal_storage_optimizer-1.0.0.zip`, and `README.md` roadmap. **Scope:** Milestone 9.

Formatting currently fails. The existing release ZIP lacks `frontend.py` and `frontend/thermal-storage-plan-card.js`, and its `__init__.py` and `manifest.json` differ from current sources. The package check validates source files and versions; it does not establish that the existing archive matches them. This does not prove the older ZIP cannot load, but it does mean it does not deliver the currently documented feature set.

**Correction:** After functional fixes, format the assertion, rebuild the archive, compare packaged contents with sources, and install-test that exact archive. Update milestone claims to distinguish implementation, automated verification, and field acceptance.

## Requirements coverage

| Area | Assessment |
| --- | --- |
| HA integration, config/reconfigure/options, normalized inputs, units, translations | Substantially implemented and covered by passing tests |
| Three-layer energy, SOC, fixed/measured COP, basic heat demand | Implemented; physical assumptions still require commissioning |
| Timestamped prices, variable resolution, saved plans, restart | Implemented, but rolling allocation and economic behavior need findings 2–6 resolved |
| Manual modes, opt-in control, high-limit override, grace, dwell, service fallback | Implemented; observed-output reconciliation and realizable dispatch remain gaps |
| Charging target, preferred windows, live guidance, notifications | Implemented; energy accounting needs correction |
| Diagnostics, bounded plan export, documentation | Substantially implemented |
| Adaptive models | Implemented with bounds and metadata; fallback behavior is incomplete |
| Packaging and maintainability | Tooling exists; formatting and existing archive need correction |
| Demonstrated savings without comfort degradation | Not established by the available evidence; synthetic tests and a commissioning guide are not field validation |

Weather selection currently validates availability but does not feed forecast temperatures into planning; current outdoor temperature is repeated across intervals. That is a permissible initial fallback, but the UI/documentation should state its effect clearly. High-grade energy is exposed diagnostically rather than used as a forecast constraint. These are useful subsequent model improvements once the concrete dispatch defects are resolved.

## Suggested order

1. Reconcile actual output state and implement rolling, realizable dispatch.
2. Correct negative/flat-price policy and energy conservation under losses.
3. Correct charging accounting and adaptive fallback; add regression tests for each finding.
4. Repeat quality checks and validate the rebuilt installation artifact.
5. Complete the documented dry-run and supervised field gates before claiming the project's cost/comfort success criterion.

# Thermal Storage Optimizer — Codex prompt pack

Use these prompts sequentially. For every milestone, give Codex access to `Thermal_Storage_Optimizer_Codex_Plan.md` as the authoritative specification. Do not run the next prompt until the current milestone meets its acceptance criteria.

---

## Prompt 1 — Repository foundation and integration skeleton

```text
Implement Milestone 1 of the Thermal Storage Optimizer project.

Read the complete `Thermal_Storage_Optimizer_Codex_Plan.md` system specification and inspect the existing repository before changing anything. Follow current Home Assistant custom-integration conventions supported by the repository's target Home Assistant version.

Scope for this milestone:
- Create an installable custom integration with domain `thermal_storage_optimizer`.
- Add manifest, config entry setup/unload, config flow, initial reconfigure/options scaffolding, a device entry, and one diagnostic status sensor.
- Add English and Swedish UI strings.
- Add a clean source structure that can later contain pure energy, forecast, optimizer, and controller modules.
- Configure or extend the repository's tests, linting, and typing without adding unnecessary heavy dependencies.
- Add a README covering installation, development, and the milestone roadmap.
- Add a short architecture decision record explaining why planning/recommendation is separated from physical actuation.

Do not implement energy calculations, price parsing, optimization, or physical shunt control yet. Active control must not exist in this milestone.

Before finishing:
1. Run all relevant tests, formatting, linting, and type checks available in the repository.
2. Fix failures caused by your changes.
3. Report changed files, commands run, test results, assumptions, and remaining risks.
4. Update the milestone checklist but do not start Milestone 2.
```

---

## Prompt 2 — Entity configuration, validation, and normalized input layer

```text
Implement Milestone 2 of the Thermal Storage Optimizer project on top of the completed Milestone 1.

Read `Thermal_Storage_Optimizer_Codex_Plan.md`, the Milestone 2 acceptance criteria, current repository state, and existing tests before coding. Preserve the separation between raw Home Assistant entity access and pure domain logic.

Scope:
- Extend the config/reconfigure flows with entity selectors for the required tank top, tank middle, tank bottom, return temperature, supply target, outdoor temperature, price forecast, and digital reserve-output entities.
- Add optional entity selectors described in the system specification.
- Put entity references in config-entry data and tuning values in options.
- Implement typed normalized input models and an adapter that validates Home Assistant states, timestamps, and units.
- Handle unknown, unavailable, missing, stale, non-numeric, and incompatible-unit values explicitly.
- Expose concise data-valid and status/diagnostic entities.
- Subscribe to relevant state changes using current Home Assistant patterns and clean up subscriptions on unload.
- Add complete tests for configuration, reconfiguration, successful normalization, invalid data, startup ordering, and recovery.

Do not implement tank energy calculations, price allocation, optimization, or output actuation. The configured reserve output must never be called in this milestone.

Run and report all relevant tests and quality checks. Fix regressions, update documentation and the milestone checklist, and stop after Milestone 2.
```

---

## Prompt 3 — Thermal energy, heat demand, and COP models

```text
Implement Milestone 3 of the Thermal Storage Optimizer project.

Read `Thermal_Storage_Optimizer_Codex_Plan.md` and use the normalized input layer completed in Milestone 2. Keep all mathematical models pure, typed, deterministic, and independently testable.

Scope:
- Implement the three-layer accumulator energy model from the system specification.
- Calculate total usable energy relative to return temperature plus configurable minimum useful delta.
- Calculate high-grade energy relative to the supply target.
- Calculate a bounded state-of-charge value using configurable/calibrated usable capacity.
- Add a conservative confidence/data-quality result and basic charging/discharging/idle trend detection.
- Implement the initial building heat-demand model based on heat-loss coefficient, balance temperature, outdoor temperature, and interval duration.
- Implement a COP model interface with a validated fixed-COP fallback and room for a future temperature-dependent model.
- Expose the specified energy, high-grade energy, SOC, and supporting diagnostic sensors.
- Add unit tests for exact known examples, sensor stratification, temperatures below reference, invalid volumes, missing values, boundary temperatures, and invalid COP settings.

Do not parse the real price forecast, create an optimization plan, or actuate the shunt output in this milestone.

Run all tests and repository quality checks. Update README/configuration documentation and the milestone checklist. Report assumptions and stop after Milestone 3.
```

---

## Prompt 4 — Price adapter and dry-run rolling optimizer

```text
Implement Milestone 4 of the Thermal Storage Optimizer project: price normalization and a dry-run rolling optimizer.

Read `Thermal_Storage_Optimizer_Codex_Plan.md`. First inspect the configured price entity format or repository fixtures. If the real entity schema is not present, implement a clearly isolated adapter interface plus representative fixtures, document the exact sample state/attributes still needed, and do not guess silently.

Requirements:
- Normalize forecast items to typed intervals with timezone-aware start, end, duration, and marginal electricity cost per kWh.
- Support variable interval duration and variable forecast length. Never assume 24 values or hourly prices.
- Normalize declared units and support configurable multiplier and additive variable costs.
- Detect new publication using source changes and/or the final forecast timestamp; do not depend on an exact 13:00 trigger.
- Model the known publication behavior: prices normally arrive around 13:00 local time and extend through 23:59:59 the following day, giving about 34–35 hours at publication and about 11 hours before the next update.
- Build forecast heat demand, COP, avoided heat cost, retention/confidence adjustment, and an explainable greedy allocation of available tank energy to the highest-value demand intervals.
- Apply an economic deadband.
- Persist and restore the last valid plan. Validate restored timestamps before use.
- Between the shortened pre-publication horizon and receipt of new prices, continue the saved plan rather than treating the horizon boundary as an instruction to empty the tank.
- Expose recommendation, forecast end, coverage, last optimization, next release, expected savings, and concise reason/status entities.
- Keep the full plan out of frequently recorded entity attributes. Provide a bounded diagnostics representation.
- Add extensive pure unit tests and Home Assistant integration tests, including delayed/malformed forecasts, missing future values, restart, timezones, DST, and price updates.

This milestone is dry-run only. Under no circumstances call the configured digital reserve-output entity.

Run all quality checks, fix failures, update documentation and milestone status, explain the resulting allocation algorithm, and stop after Milestone 4.
```

---

## Prompt 5 — Supervisory controller and fail-safe shunt actuation

```text
Implement Milestone 5 of the Thermal Storage Optimizer project: the supervisory controller and explicit opt-in shunt actuation.

Read `Thermal_Storage_Optimizer_Codex_Plan.md` and treat this milestone as safety-sensitive. Read the full safety requirements and all existing planner/input behavior before coding. Preserve dry-run as the default for new and migrated configurations.

Implement:
- A deterministic controller state machine with final states and precedence exactly described in the system specification.
- User modes Auto, Use tank, Reserve tank, and Disabled.
- Separate dry-run versus active-control permission. Enabling Auto must not by itself grant output actuation on a fresh installation.
- Configurable output inversion. For the intended installation, output OFF/de-energized means normal shunt curve/tank use and output ON means the predefined −50 °C offset/tank reserve.
- High-temperature forced-use with hysteresis, non-bypassable by manual reserve.
- Startup grace period, minimum dwell time, anti-chatter behavior, and clear exceptions for immediate forced use.
- Output calls using the current Home Assistant service/entity APIs without blocking the event loop.
- On invalid input, missing valid plan, unload, recoverable exception, or service failure, request output OFF where Home Assistant remains able to do so and expose a clear fault/fallback state.
- Transition logging and concise user-facing decision reasons.
- Comprehensive state-machine, service-call, restart, unload, failure, hysteresis, and dwell-time tests using fake entities only.

Do not add new optimization features or learning in this milestone. Do not weaken independent physical safety requirements. Run all tests and quality checks, update the operating/safety documentation and milestone checklist, and stop after Milestone 5.
```

---

## Prompt 6 — Stove charging advisor and live firing guidance

```text
Implement Milestone 6 of the Thermal Storage Optimizer project: the human-in-the-loop stove charging advisor and live firing guidance.

Read `Thermal_Storage_Optimizer_Codex_Plan.md`, especially section 4.6, and inspect the completed energy model, rolling optimizer, persistence, and controller before coding. Keep the charging advisor independent from safety-critical shunt control. It may recommend manual firing but must never attempt to control the stove.

Implement:
- Configurable preferred firing windows per weekday, defaulting to 15:00–23:00, plus minimum/maximum session duration, notification lead time, quiet hours, and an explicit option for exceptional out-of-window recommendations. Morning recommendations must be disabled by default.
- A pure charging-target calculation based on current tank energy, forecast high-cost heat demand, predicted intervening discharge, storage losses, safe remaining tank capacity, maximum configured layer temperatures, forced-use threshold margin, and residual-burn allowance.
- A pure scheduling function that returns recommended duration, earliest useful start, latest start, required completion time, target additional kWh, feasibility, confidence, and reason. Prefer charging close enough to the expensive period to reduce storage losses while staying within the preferred user window.
- An initial configurable effective net stove-to-tank charging power. Detect active sessions using configured charging-pump state, stove temperature, positive tank-energy slope, and/or a manual integration action.
- During active firing, calculate energy added, smoothed net charging power, remaining target energy, estimated minimum remaining time, expected completion, confidence, and whether residual heat should complete the target without more fuel.
- Guard all time estimates against zero/negative power, sparse data, simultaneous tank discharge, sensor noise, stale data, and target changes after a new price plan.
- Expose the charging-advisor entities listed in section 4.6.
- Add configurable Home Assistant notification delivery. Send at most one initial recommendation per planning cycle unless a material change occurs. Prefer a live sensor and a replaceable/throttled progress notification rather than repeated messages. Support acknowledge/snooze/dismiss only where the chosen Home Assistant notification mechanism supports it.
- Provide Swedish and English messages equivalent to:
  1. “Elda cirka 1 tim 45 min i dag. Börja mellan 17:30 och 20:45 och var klar senast 22:30. Målet är att lagra ytterligare 9,2 kWh inför morgondagens dyra timmar. Beräknad undvikbar elkostnad: 8 kr.”
  2. “Fortsätt elda i minst cirka 35 minuter. 6,4 av 9,2 kWh har laddats. Beräknat mål nås cirka 20:25.”
  3. “Dagens planerade laddmål är uppnått. Ingen ytterligare ved behövs för energimålet. Följ alltid kaminens ordinarie eldning och säkerhetsinstruktioner.”
- Label financial output as estimated avoided electricity cost unless configured wood cost, energy content, and stove efficiency justify a separate estimated net-saving value.
- Persist only bounded session/notification state required for restart recovery.
- Add comprehensive tests for sufficient initial charge, empty tank, safe-capacity cap, maximum layer temperature, flat/negative/high prices, no useful heat demand, preferred-window scheduling, forbidden morning recommendation, infeasible duration, delayed price publication, charging detection, noisy slopes, changing charge rate, simultaneous discharge, residual heat, restart, deduplication, snooze, notification failure, and separation from controller safety.

Do not implement adaptive learning beyond a smoothed session-local charging-rate estimate; long-term learning belongs to Milestone 8. Do not change controller safety precedence or energize/de-energize the shunt merely because a notification succeeds or fails.

Run the complete test and quality suite, update configuration and commissioning documentation, update the milestone checklist, report assumptions and limitations, and stop after Milestone 6.
```

---

## Prompt 7 — Diagnostics, usability, and field-validation release

```text
Implement Milestone 7 of the Thermal Storage Optimizer project: diagnostics, usability, and field-validation readiness.

Read `Thermal_Storage_Optimizer_Codex_Plan.md`. Do not change the core economic model or safety precedence unless an existing tested defect requires it. Focus on making behavior observable, explainable, and safely commissionable.

Scope:
- Implement current Home Assistant diagnostics support with appropriate redaction.
- Add integration actions for forced recalculation, obtaining/exporting a bounded current plan summary, and resetting only non-critical learned/calibration state if such state exists.
- Review and rationalize the exposed entities, names, units, device classes, state classes, categories, availability, and translations.
- Provide concise decision and fault explanations.
- Add an example Home Assistant dashboard configuration using standard cards; do not build a custom frontend card.
- Add a staged field-validation guide: install, dry-run observation, calculation verification, charging-advisor validation, output test, limited automatic trial, and normal operation.
- Add multi-day simulated scenarios for low/flat/high/negative prices, weather changes, different tank stratification, stove charging, firing recommendations, delayed/malformed price publication, missing sensors, notification/output failure, and Home Assistant restart.
- Document disable, rollback, backup, and physical fail-safe expectations.

Run the full test and quality suite. Resolve failures, update all user/developer documentation and the milestone checklist, summarize field-validation risks, and stop after Milestone 7.
```

---

## Prompt 8 — Adaptive energy model and measured-savings validation

```text
Implement Milestone 8 of the Thermal Storage Optimizer project: bounded adaptive calibration and performance validation.

Read `Thermal_Storage_Optimizer_Codex_Plan.md` and preserve the completed deterministic implementation as the always-available fallback. Do not introduce cloud services, opaque AI models, or unbounded learning.

Scope:
- Define a bounded observation model using relevant Home Assistant state changes. Avoid direct recorder-database dependence for real-time control and avoid unbounded storage growth.
- Calibrate usable tank capacity and/or layer weighting from identifiable charge/discharge cycles when data quality is sufficient.
- Improve the building heat-demand model from observations while bounding all parameters to physically plausible configured ranges.
- If measured electrical and produced heat energy are available, add optional COP calibration; otherwise retain the configured COP model.
- Calibrate effective net stove-to-tank charging power and residual-burn energy from clearly detected firing sessions, with bounded values and confidence.
- Learn typical firing start times and session durations locally as a soft preference only; explicit configured firing windows and the default prohibition on morning recommendations must always take precedence.
- Attach confidence, sample count, last-updated time, and fallback reason to every learned parameter.
- Version and persist calibration data safely, with migration and reset support.
- Ensure low confidence, missing data, anomalies, or failed calibration immediately fall back to the deterministic model without unsafe output transitions.
- Add estimated-versus-observed reports and clearly distinguish modeled savings from measured savings.
- Add tests using fixed synthetic and historical-style datasets for convergence, bad data, insufficient data, restart, reset, bounds, and fallback.

Do not change controller safety precedence. Run the complete regression suite and quality checks, update documentation and the milestone checklist, and report whether the available measurements are sufficient for each adaptive feature. Stop after Milestone 8.
```

---

## Prompt 9 — Packaging and maintainable release

```text
Implement Milestone 9 of the Thermal Storage Optimizer project: packaging and maintainable release.

Read `Thermal_Storage_Optimizer_Codex_Plan.md` and inspect the complete repository, current Home Assistant custom-integration requirements, and all existing tests before making release changes.

Scope:
- Add or finalize semantic versioning, changelog, release notes, installation, upgrade, backup, rollback, removal, and compatibility documentation.
- Validate config-entry versions and implement explicit migrations where required.
- Add CI for the repository's full automated tests, formatting, linting, typing, and applicable Home Assistant validation tools.
- Prepare manual-installation packaging.
- If the repository is intended for HACS distribution, add only the currently required HACS metadata and validation; otherwise document HACS as a future option rather than adding unused files.
- Test clean install, upgrade from representative prior config entries, integration reload, Home Assistant restart, removal, dry-run default, and active-control preservation rules.
- Review dependency versions and remove unused dependencies/files.
- Perform a final safety review confirming that physical safety remains independent and output OFF is the intended fallback.

Do not add new product features. Run all checks, fix release-blocking issues, update the milestone checklist, and provide a concise release-readiness report with any remaining limitations.
```

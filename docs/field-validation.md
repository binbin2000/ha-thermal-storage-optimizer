# Staged field validation and commissioning

Treat every stage as a gate. Record timestamps, relevant entity values,
diagnostics, observed physical behavior, and a pass/fail decision. Do not advance
on an unexplained discrepancy. The integration is an economic supervisory
controller, never a substitute for independent stove, boiler, tank-temperature,
pressure, circulation, heat-pump-flow, or freeze protection.

## Before installation

- Record all selected entity IDs, native units, tank sensor positions and effective
  volumes, price currency/unit, output polarity, approved tank temperatures, and
  the physical fail-safe behavior.
- Back up Home Assistant and the current integration directory as described in
  [backup and rollback](backup-rollback.md).
- Prove independently that relay power loss and output OFF return the shunt to
  safe normal local control. Do not proceed if the physical state is ambiguous.
- Keep **Allow physical output control** off. Configure no notification target yet.

## Stage 1 — Install and input validation

1. Install/restart and add the integration through the UI.
2. Confirm every required and optional source on the integration device page.
3. Require `Data valid = on`, `Status = ready`, and plausible timestamps/units.
4. Download diagnostics. Confirm entity identifiers and notification details are
   redacted, while normalized values, issues, model output, plan, controller, and
   advisor state are present.
5. Introduce one supervised unavailable test sensor if safe to do so. Require an
   explicit input issue and physical output OFF; then restore it and verify recovery.

Pass gate: no unexplained invalid, stale, unit, or timestamp issue; active control
remains off.

## Stage 2 — Dry-run observation

Observe at least three complete price-publication cycles, including the low-coverage
period before tomorrow's prices arrive. Use the example
[dashboard](dashboard-example.yaml) and export a plan from **Developer tools →
Actions → Thermal Storage Optimizer: Get bounded plan summary**. Twelve intervals
are returned by default and at most 48; the complete plan is not stored in entity
attributes.

For every decision change, record usable/high-grade energy, price coverage, plan
status, planner explanation, operating-state explanation, mode, and output-active
state. `recalculate` may be used to rebuild from current inputs, but must not
change controller precedence or energize an output in dry-run.

Pass gate: use/reserve advice is economically intelligible, saved-plan continuity
is clear during delayed publication, and no physical ON command occurs.

## Stage 3 — Calculation verification

At several stable tank states, independently calculate each layer as
`0.001163 × effective litres × max(layer °C − (return °C + useful delta), 0)`.
Sum the layers and compare with usable energy. Repeat against supply target for
high-grade energy. Check a strongly stratified, nearly mixed, cold, and hot tank.

Independently calculate one hour of demand as
`H × max(balance temperature − outdoor temperature, 0)` and marginal heat cost as
`variable electricity cost / COP`. Confirm price multiplier/addition and currency
before interpreting avoided cost. Establish an installation-specific tolerance;
investigate sensor placement or volume assumptions rather than hiding a mismatch.

Pass gate: sign, units, layer contribution, COP source, demand response, and
economic ranking agree with the independent calculation.

## Stage 4 — Charging-advisor validation

Observe several recommendations without firing. Check preferred weekday windows,
latest start/completion, maximum duration, safe layer caps, residual-burn allowance,
confidence, and that flat/negative opportunities do not create spurious avoided
cost. Morning advice must remain absent unless exceptionally allowed.

During one normally operated, continuously supervised firing session, use the
manual start/stop tracking actions only if automatic detection is unavailable.
Compare tank energy added, smoothed net charge power, remaining energy/time, and
completion against temperature development. A “no more wood needed” message only
means the economic target is covered; always follow the stove manual and normal
burn-down procedure. Test notification deduplication, snooze, dismissal, and a
delivery failure; none may affect shunt control.

Pass gate: advice is feasible and conservative, estimates never become negative,
safe capacity is never exceeded, and notification behavior is isolated.

## Stage 5 — Supervised output test

Arrange attendance by a person able to operate the heating system. Keep normal
physical protections active. Verify the selected output entity and polarity at the
terminals/controller, not only in Home Assistant.

1. With active control still off, confirm integration load/unload and Home Assistant
   restart request OFF.
2. Enable active control only for this test. Select **Reserve tank** and confirm the
   expected −50 °C shunt-offset input and adequate heat-pump flow/volume.
3. Select **Use tank**, then **Disabled**, and confirm OFF returns normal local shunt
   control.
4. Repeat a normal command change inside minimum dwell and confirm chatter is held.
5. Raise only a simulated/test temperature if possible; otherwise use a carefully
   supervised natural crossing. Confirm high temperature forces immediate use even
   from manual Reserve.
6. Test a non-production output-service failure if possible. Treat a failed OFF call
   as an unknown physical state requiring immediate physical inspection.

Pass gate: measured physical behavior matches mapping, every fallback is OFF, and
independent protections remain effective.

## Stage 6 — Limited automatic trial

Return to Auto and run a short, attended trial during representative weather and
price variation. Start with conservative capacity/confidence and an extended dwell.
Define comfort and switch-count abort limits in advance. Review each transition,
heat-pump behavior, indoor/supply temperatures, tank depletion, advisor behavior,
and avoided-cost estimate. Disable immediately on unexplained output, comfort loss,
rapid cycling, high temperature, stale inputs, or conflict with local controls.

Pass gate: the controller follows explained plan decisions, comfort and hydraulic
requirements remain satisfied, and switching remains within the agreed limit.

## Stage 7 — Normal operation

Enable unattended Auto only after all signed gates pass. Keep the decision, fault,
coverage, data-valid, and output entities on a dashboard. Review after changes to
sensors, price provider, heating curve, stove behavior, tank plumbing, relay wiring,
Home Assistant, or integration version. Periodically repeat OFF/fail-safe and backup
checks. Milestone 8 compares modeled and observed heat when paired energy data is
available. Monetary savings remain explicitly modeled unless a defensible measured
counterfactual is available; the current entity set does not provide one.

## Principal field risks

- Wrong output entity or polarity can reserve/release heat at the wrong time.
- A Home Assistant OFF request is not proof that a stuck relay physically opened.
- Sensor placement and assumed layer volumes can materially misstate useful energy.
- Delayed prices, weather simplification, hot-water draws, and fixed COP can change
  real value and depletion versus the forecast.
- Stove residual heat and simultaneous building load can bias charge-time estimates.
- Notification delivery and mobile actions vary by platform.
- Home Assistant, networking, integration, or power failure must be tolerated by
  de-energized hardware behavior and independent physical protection.

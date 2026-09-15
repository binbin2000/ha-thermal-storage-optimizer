# Supervisory controller operating and safety guide

## Safety boundary

Thermal Storage Optimizer is an economic supervisory controller, not a safety
controller. Independent stove, boiler, tank overtemperature, pressure,
circulation, heat-pump flow/volume, and freeze-protection functions must remain
installed, enabled, tested, and capable of operating without Home Assistant.
Never use this integration to weaken or replace them.

The stove charging advisor is human-in-the-loop only. Its recommendations,
manual session services, and notification results cannot energize/de-energize
the stove, charging pump, or shunt. “No more wood needed” refers only to the
economic energy target; it never means to extinguish a fire or depart from the
stove manufacturer's operating procedure.

The preferred relay design is de-energized for normal local shunt control and
tank use. Loss of Home Assistant, relay power, or integration operation should
therefore return the system to its normal local behavior. Confirm this wiring
and polarity at the installation before active control is permitted.

## Permission and modes

Mode and actuation permission are deliberately independent:

- **Auto** follows the valid current or saved optimization plan.
- **Use tank** requests normal tank use.
- **Reserve tank** requests the predefined −50 °C offset, but cannot override
  forced high-temperature use.
- **Disabled** stops control decisions and requests physical output OFF.
- **Allow physical output control** is the separate explicit opt-in. It defaults
  to off for fresh and migrated entries. Without it, every mode is dry-run and
  the output stays de-energized apart from explicit OFF safety requests.

For the intended non-inverted installation, OFF means normal curve/tank use and
ON means reserve/−50 °C offset. Output inversion reverses normal logical mapping
for other wiring arrangements. Safety fallback remains physical OFF regardless
of inversion.

## Decision precedence

The final states follow this order:

1. Independent physical protection acts outside the integration.
2. `FORCED_USE` applies when any valid tank layer reaches the high threshold.
3. `WAITING_FOR_DATA` or `FAULT_FALLBACK` applies for invalid required input,
   missing valid plan, or output/controller failure.
4. `DISABLED` applies when valid inputs and a valid plan exist but the user has
   disabled the controller.
5. Manual Use/Reserve requests apply.
6. Auto uses the plan, or reports `COLD_OR_EMPTY` when no usable heat remains.
7. Minimum dwell holds ordinary command changes to prevent chatter.

Forced use is immediate and bypasses dwell. It remains latched until all valid
tank-layer readings are at or below the high threshold minus hysteresis. Manual
Reserve cannot bypass it. Invalid input and fault fallback also request OFF
immediately rather than waiting for dwell.

At every integration load/restart, the output is first requested OFF. Reserve
cannot energize until all required inputs are valid, a current or applicable
saved plan exists, active control is explicitly permitted, and startup grace
has elapsed. Every restart starts a new grace period. User mode is restored,
but physical output state and dwell are not assumed across restart.

## Commissioning checklist

The authoritative staged procedure, pass gates, abort criteria, dashboard, and
risk summary are in the [field-validation guide](field-validation.md). Complete
the [backup and rollback procedure](backup-rollback.md) before an output test.
The condensed safety checks below remain mandatory.

1. Leave active control off and observe several complete price cycles.
2. Verify every input entity, unit, freshness limit, and plan status.
3. Independently confirm the tank's approved temperature limits and select a
   conservative forced-use threshold and hysteresis.
4. Supervise a manual relay test and prove physical OFF returns the shunt to its
   normal local curve and tank use.
5. Verify whether output inversion is required. The intended installation uses
   non-inverted mapping: OFF = use, ON = reserve.
6. Verify startup, invalid-sensor, missing-plan, Home Assistant restart, and
   integration unload all request OFF.
7. Verify a tank-layer high-temperature crossing immediately overrides manual
   Reserve, and hysteresis prevents rapid release/re-entry.
8. Verify minimum dwell prevents ordinary use/reserve chatter.
9. Only then enable active control for a limited, attended period. Review the
   operating-state and decision-reason entities after every transition.
10. Separately commission the advisor in observation-only use: check preferred
    windows, maximum layer targets, residual allowance, and quiet hours over
    several price cycles.
11. During an attended normal firing, compare tank-energy increase and the live
    remaining-time sensor. Treat lowered confidence from simultaneous discharge
    or noisy sensors conservatively until placement and thresholds are verified.

If an output service call fails, the controller exposes `FAULT_FALLBACK`, logs
the failure, and makes a best-effort OFF request. A failed OFF call can mean the
physical state is unknown; treat that as an installation fault and rely on the
independent protections and de-energizing hardware design.

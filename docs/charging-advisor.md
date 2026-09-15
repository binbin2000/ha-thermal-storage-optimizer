# Stove charging advisor and commissioning

## Safety and control boundary

The advisor recommends a manual action; it never controls the stove or charging
pump. Its runtime is downstream of the economic plan and separate from the
supervisory shunt controller. Notification success, failure, acknowledgement,
snooze, dismissal, and manual firing-session services do not change controller
mode, precedence, dwell, forced-use behavior, or reserve-output state.

Completion advice means no additional wood is needed for the calculated energy
target. Always follow the stove's ordinary firing, burn-down, circulation, and
safety instructions. Do not extinguish a fire because of an advisor message.

## Configuration

All options have conservative runtime defaults, so migrated entries remain
non-actuating. Configure these under the integration options:

- `preferred_firing_windows`: weekday mapping using English weekday names and
  `HH:MM-HH:MM` values. Comma-separated windows are accepted. Every omitted day
  defaults to `15:00-23:00`; an end at or before the start crosses midnight.
- Minimum/maximum firing duration: 30/240 minutes by default.
- Notification lead time: 60 minutes by default.
- Quiet hours: 23:00–07:00 by default. Equal endpoints disable quiet hours.
- Exceptional out-of-window recommendations: disabled by default. This is the
  explicit permission required for morning recommendations when no normal
  prior window can meet the deadline.
- Initial effective net charging power: 6 kW. Measure net tank-energy increase,
  not the stove nameplate output.
- Detection thresholds: stove flow temperature 55 °C and positive tank-energy
  slope 1 kW by default. A configured active charging pump is also sufficient.
- Per-layer maximum targets: 80 °C by default. The lower of each layer limit and
  forced-use threshold minus its 3 °C margin bounds charging.
- Residual-burn allowance: 1 kWh by default.
- Minimum avoided-cost threshold, progress interval, material-change threshold,
  snooze duration, quiet hours, and advice language.
- Optional wood cost per kg, energy content in kWh/kg, and stove-to-tank
  efficiency. All three must be valid before estimated net saving is exposed.

Select a `notify` entity or legacy `notify.service` as the optional target.
Mobile-app legacy targets support acknowledge, snooze, and dismiss actions.
Other targets receive messages without unsupported actions. Progress uses one
tagged/replaced notification where supported and is throttled; live entities
remain the primary progress display.

## Calculation behavior

The target combines forecast heat demand in materially higher-cost,
positive-value intervals with predicted intervening/session use and storage
losses, then subtracts current usable energy. It is clamped by calibrated
remaining capacity and temperature-derived safe capacity. Expected residual
heat reduces fuel-phase duration but remains in total additional target energy.

Flat prices do not create an arbitrage opportunity. Negative-cost periods are
not treated as avoided electricity cost. No recommendation is exposed when
demand is absent, current charge is sufficient, safe capacity is unavailable,
the avoided-cost threshold is not met, confidence is insufficient, or the
session cannot fit before demand in an allowed window.

During firing, net power uses only positive, timestamped tank-energy slopes
outside a noise deadband. A median of recent slopes feeds a session-local
exponential smoother. Zero/negative power, large sample gaps, stale data,
simultaneous tank discharge, or insufficient samples lower confidence and can
withhold completion time instead of emitting a negative or infinite estimate.
When bounded adaptation is explicitly enabled, clean completed sessions can calibrate
this value; low-confidence or anomalous sessions retain the configured fallback.

Financial output is labelled **estimated avoided electricity cost**. The
separate **estimated net saving** entity stays unavailable unless all fuel
inputs are configured, because avoided heat-pump cost alone is not profit.

## Services and entities

The integration registers `start_firing`, `stop_firing`,
`acknowledge_recommendation`, `snooze_recommendation`, and
`dismiss_recommendation` services under `thermal_storage_optimizer`. Manual
start/stop only changes session detection.

Milestone 7 also registers `recalculate`, bounded response action
`get_plan_summary`, and `reset_learned_state`. The reset action reports no change
because this release has no long-term learned/calibration values; it does not
clear the session, plan, controller mode, or any safety-related state.

The eleven section 4.6 entities are exposed: charge recommended, duration,
earliest/latest start, completion deadline, target/remaining energy, remaining
time, net charge power, human-readable advice, and stove firing. Additional
financial sensors distinguish avoided cost from net saving.

## Commissioning sequence

1. Leave shunt active control disabled and notifications unconfigured.
2. Enter approved layer limits and a forced-use margin below the controller's
   independent threshold. Confirm a hot layer removes the recommendation.
3. Review several full price publications. Confirm advice uses the correct
   weekday window and no morning recommendation is produced.
4. Configure realistic net charging power and minimum/maximum session lengths.
5. During supervised normal firing, compare energy added, smoothed power,
   remaining time, and residual completion with tank behavior. Tune only the
   initial value and detection/noise thresholds; do not infer long-term values.
6. Test restart during a session, deduplication, snooze/dismiss, quiet hours,
   delayed price publication, and notification failure. Verify reserve-output
   requests remain governed solely by the controller safety guide.
7. Configure notification delivery last and observe before acting on advice.

Limitations: forecast demand is the Milestone 3 weather/load model;
intervening discharge cannot know unmodeled hot-water draws; capacity assumes
each sensor's configured effective layer volume; notification replacement and
actions vary by platform; and no long-term stove-rate, residual-energy, or
household-pattern learning is implemented.

Use the complete [field-validation procedure](field-validation.md) for dry-run,
advisor, notification-failure, and supervised firing pass gates.

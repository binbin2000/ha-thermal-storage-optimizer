# Configuration reference

Thermal Storage Optimizer is configured entirely through the Home Assistant user
interface. No YAML configuration is required, and only one integration instance is
supported.

There are two places to change configuration:

- **Settings → Devices & services → Thermal Storage Optimizer → Reconfigure** changes
  the Home Assistant entities used as inputs and the reserve output.
- **Settings → Devices & services → Thermal Storage Optimizer → Configure** changes
  model, planner, controller, charging-advisor, and calibration options. Saving these
  options reloads the integration.

New installations start in dry-run. Selecting **Auto** mode does not allow output
commands unless **Allow physical output control** is also enabled.

## Entity configuration

### Required entities

| Option | Accepted entity | Purpose |
| --- | --- | --- |
| Tank top temperature | Temperature sensor | Temperature represented by the top tank layer. |
| Tank middle temperature | Temperature sensor | Temperature represented by the middle tank layer. |
| Tank bottom temperature | Temperature sensor | Temperature represented by the bottom tank layer. |
| Return temperature | Temperature sensor | Heating-system return temperature. The usable-energy reference is this value plus the configured minimum useful delta. |
| Supply target temperature | Temperature sensor | Current requested heating supply temperature; used to calculate high-grade energy. |
| Outdoor temperature | Temperature sensor | Current outdoor temperature used by the heat-demand model. |
| Price forecast or Nord Pool current-price sensor | Sensor | Timestamped electricity prices. The official Nord Pool current-price sensor, generic timestamped `prices`, and custom `raw_today`/`raw_tomorrow` attributes are supported. Bare numeric arrays are rejected. |
| Digital reserve output | `switch` or `input_boolean` | Applies the installation's normal-use/reserve request. It is never energized unless physical output control is explicitly enabled. |

Temperature, power, energy, and flow inputs must include compatible unit metadata.
The integration normalizes them to °C, kW, kWh, and L/min respectively. Required
inputs that are missing, stale, unavailable, non-numeric, or have incompatible units
make the required input set invalid.

### Optional entities

| Option | Accepted entity | Purpose |
| --- | --- | --- |
| Actual supply temperature | Temperature sensor | Additional observed supply temperature. |
| Indoor temperature | Temperature sensor | Additional indoor-condition measurement. |
| Weather forecast | `weather` entity | Validates weather availability. The current release still repeats measured outdoor temperature in forecast demand calculations rather than applying hourly weather forecasts. |
| Heat-pump electrical power | Power sensor | Instantaneous heat-pump electrical consumption for diagnostics and calibration evidence. |
| Heat-pump electrical energy | Energy sensor | Cumulative electrical energy; pair with produced heat energy for adaptive COP calibration. |
| Heat-pump produced heat energy | Energy sensor | Cumulative delivered heat used by adaptive calibration and validation. |
| Measured COP | Sensor | Preferred COP when its state is valid; otherwise the fixed or calibrated fallback is used. |
| Stove charging pump | `binary_sensor`, `switch`, or `input_boolean` | One possible signal that a manual stove-firing session is active. |
| Stove flow temperature | Temperature sensor | Detects firing when it exceeds the configured stove threshold. |
| Tank/radiator flow rate | Volume-flow-rate sensor | Optional flow measurement for diagnostics. |
| Notification target | `notify` entity | Delivers charging-advisor recommendations and progress. Supported mobile-app targets may also show acknowledge, snooze, and dismiss actions. |

An invalid optional measurement is reported in diagnostics but does not invalidate the
required input set.

## Model and planner options

| Option | Default | Allowed range | Effect |
| --- | ---: | ---: | --- |
| Measurement stale after | 3,600 s | 60–86,400 s | Maximum age of temperature and optional measurement updates. |
| Price forecast stale after | 129,600 s (36 h) | 3,600–259,200 s | Maximum age of a price publication before it is rejected. |
| Total tank volume | 500 L | 1–10,000 L | Physical tank volume. It must equal the sum of the three effective layer volumes. |
| Top layer effective volume | 166.67 L | 0.1–10,000 L | Water volume represented by the top sensor. |
| Middle layer effective volume | 166.67 L | 0.1–10,000 L | Water volume represented by the middle sensor. |
| Bottom layer effective volume | 166.67 L | 0.1–10,000 L | Water volume represented by the bottom sensor. |
| Minimum useful temperature delta | 3 °C | 0–30 °C | Added to return temperature to form the usable-energy reference. |
| Calibrated usable capacity | 30 kWh | 0.1–500 kWh | Energy corresponding to 100% state of charge. |
| Energy trend deadband | 0.1 kWh | 0–20 kWh | Changes at or below this amount are classified as idle. |
| Building heat-loss coefficient | 0.3 kW/K | 0–10 kW/K | Heat demand per kelvin below the balance temperature. |
| Building balance temperature | 17 °C | −20–35 °C | Outdoor temperature at or above which modeled space-heating demand is zero. |
| Fixed COP fallback | 3.0 | 0.1–15 | Used when no valid measured or sufficiently confident calibrated COP is available. |
| Price multiplier | 1.0 | 0–100 | Multiplies the normalized source price before additions. |
| Additive variable cost | 0 currency/kWh | −100–100 | Adds variable tax, grid, or supplier cost in the source price's currency per kWh. |
| Hourly storage retention | 0.995 | 0.9–1.0 | Fraction of stored-energy value retained for each hour into the future. |
| Forecast confidence | 0.85 | 0–1 | Conservative discount applied to forecast value. |
| Economic deadband | 0.05 currency/kWh heat | 0–100 | Minimum advantage over the horizon baseline before tank energy is allocated. |
| Planning interval | 15 min | 1–60 min | Periodic plan refresh interval; relevant state changes can also trigger a refresh. |

The next-hour demand model is `heat-loss coefficient × max(balance temperature −
outdoor temperature, 0)`. Tank energy is calculated from the configured effective
layer volumes; the calibrated usable capacity is a separate scale used for state of
charge and capacity limits.

## Controller and safety options

| Option | Default | Allowed range | Effect |
| --- | ---: | ---: | --- |
| Allow physical output control | Off | On/off | Explicitly permits service calls to the reserve output. Leave off for dry-run. |
| Invert normal use/reserve output mapping | Off | On/off | Off means physical output off requests normal tank use and on requests reserve. Enable only for installations with reversed logic. Fail-safe fallback always requests physical off. |
| Forced-use high-temperature threshold | 85 °C | 20–120 °C | Any valid tank layer at or above this value immediately forces tank use. |
| Forced-use hysteresis | 5 °C | 0.5–30 °C | Keeps forced use latched until every valid layer is this far below the threshold. Must be lower than the threshold. |
| Startup grace period | 300 s | 0–3,600 s | Prevents the reserve output from energizing after a load, reload, or restart. |
| Minimum output dwell time | 1,800 s | 0–14,400 s | Prevents output chatter. Forced high-temperature use and fail-safe off remain immediate. |

Home Assistant is not a safety controller. Independent boiler/stove,
overtemperature, pressure, circulation, and freeze protection must remain in place.
Confirm the output polarity and a physical-off result before enabling control.

## Charging-advisor options

The charging advisor recommends manual stove firing. It does not control the stove or
charging pump, and none of its notification or session actions grant output-control
permission.

| Option | Runtime default | Allowed range or format | Effect |
| --- | ---: | ---: | --- |
| Preferred firing windows by weekday | 15:00–23:00 every day | Weekday mapping | Limits ordinary firing recommendations to preferred local-time windows. |
| Minimum worthwhile firing duration | 30 min | 1–720 min | Suppresses shorter recommendations. Must not exceed the maximum. |
| Maximum firing duration | 240 min | 1–720 min | Maximum planned fuel phase. |
| Notification lead time | 60 min | 0–1,440 min | How far before the latest start a recommendation may be sent. |
| Quiet hours start / end | 23:00 / 07:00 | Local times | Suppresses notifications in this interval. Equal endpoints disable quiet hours. |
| Allow exceptional out-of-window recommendations | Off | On/off | Allows a recommendation outside preferred windows when no normal window can meet the deadline. |
| Initial effective net charging power | 6 kW | 0–100 kW | Fallback rate of net tank-energy increase; use measured net storage gain, not stove nameplate output. |
| Active stove temperature threshold | 55 °C | 0–150 °C | Stove-flow temperature that indicates firing. |
| Charging slope detection threshold | 1 kW | 0–100 kW | Positive tank-energy slope that can indicate firing. |
| Maximum top/middle/bottom temperature | 80 °C each | 20–120 °C | Per-layer charging target limits. |
| Forced-use threshold margin | 3 °C | 0–30 °C | Keeps advisor targets below the independent forced-use threshold. |
| Residual-burn energy allowance | 1 kWh | 0–50 kWh | Heat expected after the active fuel phase. |
| Minimum estimated avoided electricity cost | 0 currency | 0–1,000 | Suppresses recommendations below this modeled value. |
| Progress notification interval | 15 min | 1–1,440 min | Minimum interval between progress notifications. |
| Material target-change threshold | 1 kWh | 0–100 kWh | Change required to treat a recommendation target as materially different. |
| Default snooze duration | 60 min | 1–1,440 min | Default notification snooze period. |
| Advice language | English | `auto`, `en`, or `sv` | Language used for advisor text. |
| Wood cost | Not configured | 0–1,000 currency/kg | Optional fuel-cost input. |
| Wood energy content | Not configured | 0.1–20 kWh/kg | Optional fuel-energy input. |
| Stove-to-tank efficiency | Not configured | 0.01–1.0 | Optional delivered-energy fraction. |

All three wood-related options must be valid before **Estimated net saving** is
available. Otherwise the integration exposes only the modeled avoided electricity
cost.

Preferred windows are entered as an object using lowercase English weekday names.
A day can contain one window or comma-separated windows. An end time at or before the
start time crosses midnight. Omitted weekdays use the default 15:00–23:00 window.
For example:

```json
{
  "monday": "16:00-22:00",
  "tuesday": "06:30-08:00,16:00-22:00",
  "saturday": "14:00-23:30"
}
```

## Adaptive calibration options

Adaptive calibration is local, bounded, and disabled by default. A learned value is
used only when it is within the configured physical bounds and reaches the confidence
gate; otherwise the deterministic option above remains active.

| Option | Default | Allowed range | Effect |
| --- | ---: | ---: | --- |
| Enable bounded adaptive calibration | Off | On/off | Enables use of sufficiently confident learned values. |
| Minimum calibration confidence | 0.70 | 0.50–1.00 | Confidence required before a learned value can replace its configured fallback. |
| Learned usable capacity minimum / maximum | 10 / 80 kWh | 1–500 kWh | Bounds learned usable capacity. |
| Learned heat-loss coefficient minimum / maximum | 0.05 / 2.0 kW/K | 0–10 kW/K | Bounds learned building heat loss. |
| Learned balance temperature minimum / maximum | 10 / 24 °C | −20–35 °C | Bounds learned balance temperature. |
| Learned COP minimum / maximum | 1.0 / 7.0 | 0.1–15 | Bounds learned COP. |
| Learned charging power minimum / maximum | 1 / 30 kW | 0.1–100 kW | Bounds learned net charging power. |
| Learned residual energy minimum / maximum | 0 / 10 kWh | 0–50 kWh | Bounds learned residual-burn energy. |

Every minimum must be less than or equal to its corresponding maximum. Calibration
needs suitable optional meters and clean observations; enabling it does not make
insufficient data usable. See [Adaptive calibration and performance validation](adaptive-calibration.md)
for the evidence required by each learned feature.

## Validation and safe editing

Home Assistant rejects the options form when:

- the three effective layer volumes do not sum to the total tank volume (within
  0.01 L);
- forced-use hysteresis is greater than or equal to the forced-use threshold;
- minimum firing duration exceeds maximum firing duration;
- a calibration minimum exceeds its corresponding maximum; or
- preferred firing-window syntax is invalid.

After changing entities or options, verify the integration status, data-valid sensor,
plan status, controller reason, and actual reserve-output state. Perform commissioning
with physical output control disabled before relying on estimates or enabling active
control. See [Operating and safety](operating-safety.md) and
[Field validation](field-validation.md) for the full procedure.

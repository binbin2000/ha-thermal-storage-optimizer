# Thermal Storage Optimizer

## System specification, architecture, milestone goals, and acceptance criteria

**Target platform:** Home Assistant custom integration  
**Integration domain:** `thermal_storage_optimizer`  
**Working name:** Thermal Storage Optimizer  
**Primary installation:** `/config/custom_components/thermal_storage_optimizer/`  
**Language:** Source code and developer documentation in English; UI translations in English and Swedish.

---

## 1. Purpose

Thermal Storage Optimizer is a Home Assistant custom integration that decides whether heat stored in a hydronic accumulator tank should be used immediately or reserved for a later period when using the heat pump would be more expensive.

The first installation consists of:

- A 500-litre stratified accumulator tank.
- Three temperature sensors: tank top, tank middle, and tank bottom.
- A water-jacketed stove that charges the accumulator tank.
- An air-to-water heat pump.
- A shunt controller downstream of the tank.
- A heat-pump connection based on the “Bosch model”: the heat pump can heat the building while the tank shunt is closed, without compromising required heat-pump flow or system volume.
- A digital shunt input that applies a predefined −50 °C heating-curve offset.
- Normal digital input state: the shunt follows the same heating curve as the heat pump, and stored tank heat is used by default.
- Active digital input state: the −50 °C offset closes the shunt, reserving tank heat while the heat pump supplies the building.
- If tank heat is insufficient while the tank is enabled, the heat pump tops up the heat.

The integration must run entirely inside Home Assistant. It must not require AppDaemon, Node-RED, a separate Docker container, or an external optimization service.

The integration is an economic supervisory controller. It must never replace independent boiler, stove, overtemperature, pressure, circulation, or freeze-protection functions.

---

## 2. Desired outcome

At any point in time, the integration shall answer:

> Is one unit of usable heat in the accumulator tank worth more if used now, or if retained for a forecast future heating period?

The decision must be based primarily on the avoided marginal cost of heat-pump heat, not merely the raw electricity spot price.

For forecast interval \(t\):

\[
C_{heat,t} = \frac{P_{electricity,t}}{COP_t}
\]

Where:

- \(C_{heat,t}\) is the marginal cost of one kWh of heat from the heat pump.
- \(P_{electricity,t}\) is the configurable variable electricity cost per kWh, including relevant variable additions.
- \(COP_t\) is the estimated heat-pump COP for that interval.

The optimizer shall allocate the available tank energy to forecast intervals where it avoids the greatest heat-pump cost, subject to heat demand, storage losses, temperature usefulness, uncertainty, and safety overrides.

---

## 3. Scope

### 3.1 MVP scope

The MVP shall:

- Be installed as a Home Assistant custom integration.
- Be configured through the Home Assistant UI using a config flow and options flow.
- Read existing Home Assistant entities rather than communicate directly with physical devices.
- Estimate usable thermal energy from three tank temperature sensors.
- Normalize electricity-price forecast periods from an existing Home Assistant entity.
- Support a variable forecast horizon and timestamp-based price periods.
- Forecast basic building heat demand.
- Estimate heat-pump COP using a configurable first-stage model.
- Produce a rolling use/reserve plan.
- Initially support a dry-run/recommendation mode.
- After explicit enablement, control the configured digital shunt-offset entity.
- Recommend when and for how long the user should fire the water-jacketed stove to charge the tank for forecast high-cost periods.
- During an active firing session, continuously estimate the minimum remaining firing/charging time needed to reach the economic energy target.
- Respect configured preferred firing windows, initially 15:00–23:00, and never recommend charging beyond configured safe tank-temperature and energy limits.
- Deliver bounded, actionable Home Assistant notifications for recommended charging, progress, and completion.
- Provide manual modes, safety overrides, diagnostics, decision explanations, and fail-safe behavior.
- Persist the last valid plan and the minimum state required across Home Assistant restarts.
- Include automated tests for calculations, decisions, configuration, and failure modes.

### 3.2 Later scope

Later versions may:

- Calibrate usable tank capacity from observed charge/discharge cycles.
- Learn the building heat-loss model from historical data.
- Learn or calibrate COP from measured heat and electrical energy.
- Estimate tank losses and stratification more accurately.
- Support intentional heat-pump charging of the tank if later requested.
- Coordinate with indoor-temperature preheating or other flexible loads.
- Present a richer forecast visualization through a custom dashboard card.

### 3.3 Explicitly out of scope for the initial project

- Replacing physical stove or boiler safety controls.
- Direct control of safety valves, circulation safety functions, or emergency cooling.
- Direct electrical-price retrieval from an external market API.
- Intentional heat-pump charging of the accumulator tank for electricity arbitrage.
- Cloud services or external machine-learning services.
- A custom Lovelace card before the core integration is stable.

---

## 4. Functional architecture

The integration shall be divided into six logical layers.

### 4.1 Input adapters

Read and validate configured Home Assistant entities:

**Required inputs**

- Tank top temperature.
- Tank middle temperature.
- Tank bottom temperature.
- Heating-system return temperature.
- Heating-supply target temperature or equivalent heating-curve target.
- Outdoor temperature.
- Electricity-price forecast entity.
- Digital shunt-offset output entity.

**Optional inputs**

- Actual heating supply temperature.
- Indoor temperature.
- Weather forecast entity.
- Heat-pump electrical power or energy.
- Heat-pump produced heat energy.
- Measured or externally calculated COP.
- Stove charging-pump state.
- Stove flow temperature.
- Tank/radiator flow rate.
- Notification target.

Input adapters must isolate source-specific formats from the calculation and control logic. Core energy and optimizer code must operate on typed, normalized data models, not raw Home Assistant states or attributes.

### 4.2 Thermal state estimator

Calculate:

- Estimated total usable tank energy in kWh thermal.
- High-grade tank energy capable of directly meeting the current supply target.
- Tank state of charge.
- Current charging/discharging/idle tendency.
- Data quality and confidence.

Initial three-layer approximation:

\[
E_{usable} = 0.001163 \sum_i V_i \max(T_i - T_{reference}, 0)
\]

Where:

- \(V_i\) is the configured effective volume of tank layer \(i\), initially approximately 166.7 litres per sensor for a 500-litre tank.
- \(T_i\) is top, middle, or bottom temperature.
- \(T_{reference}\) is normally the measured heating-system return temperature plus a configurable minimum useful delta.
- `0.001163` converts litre-kelvin to kWh for water.

High-grade energy shall be calculated separately relative to the current or forecast supply target. The initial model is deliberately approximate and must be replaceable without changing entity or controller contracts.

### 4.3 Forecast and optimization planner

Build a sequence of normalized forecast intervals. Each interval shall contain at least:

- Start timestamp.
- End timestamp.
- Duration.
- Normalized electricity cost per kWh.
- Forecast outdoor temperature or best available substitute.
- Forecast heat demand in kWh thermal.
- Estimated COP.
- Marginal heat-pump heat cost.
- Storage-retention factor.
- Forecast confidence.
- Recommended tank-use state.
- Expected tank-energy allocation.

Initial heat-demand model:

\[
Q_{demand,t} = H \max(T_{balance} - T_{out,t}, 0) \Delta t
\]

Where:

- \(H\) is the configurable building heat-loss coefficient in kW/K.
- \(T_{balance}\) is the configurable balance temperature.
- \(\Delta t\) is interval duration in hours.

The first optimizer may use a transparent greedy allocation algorithm:

1. Estimate currently usable tank energy.
2. Calculate potential avoided heat-pump cost for every interval.
3. Adjust future value for tank losses and forecast uncertainty.
4. Limit usable tank heat in each interval by forecast heat demand.
5. Allocate available energy to the intervals with the highest adjusted avoided cost.
6. Apply an economic deadband so small differences do not cause unnecessary reservation.
7. Convert the current interval’s allocation into a binary use/reserve recommendation.
8. Recalculate on material input changes and at a periodic interval.

The planner must remain independent from the physical output controller and must be testable with pure Python fixtures.

### 4.4 Supervisory controller

The controller converts the recommendation into a final operating state.

Control modes exposed to the user:

- `Auto`: follow optimization subject to overrides.
- `Use tank`: request normal shunt operation.
- `Reserve tank`: request −50 °C offset, subject to non-bypassable thermal safety overrides.
- `Disabled`: stop active optimization and leave the offset output de-energized.

Final operating states:

- `USE_TANK`
- `RESERVE_TANK`
- `FORCED_USE`
- `COLD_OR_EMPTY`
- `WAITING_FOR_DATA`
- `FAULT_FALLBACK`
- `DISABLED`

Control precedence, highest first:

1. Independent physical safety systems, outside this integration.
2. Integration thermal protection: force tank use at configured high temperature.
3. Invalid/stale/unavailable input fallback.
4. Disabled mode.
5. Manual use/reserve request.
6. Automatic optimized recommendation.
7. Minimum dwell time and anti-chatter logic.

The output mapping must be configurable because installations may invert the relay logic. In the intended installation:

- Output OFF/de-energized = no offset = tank use/default local control.
- Output ON/energized = −50 °C offset = tank reserve.

### 4.5 Home Assistant presentation

The integration should create a Home Assistant device and expose entities similar to:

| Entity | Purpose |
| --- | --- |
| `sensor.thermal_storage_energy` | Estimated usable energy, kWh |
| `sensor.thermal_storage_high_grade_energy` | Energy directly capable of meeting target, kWh |
| `sensor.thermal_storage_soc` | Estimated usable state of charge, % |
| `sensor.thermal_storage_heat_cost_now` | Current marginal heat-pump heat cost |
| `sensor.thermal_storage_future_peak_value` | Highest relevant future heat value |
| `sensor.thermal_storage_expected_savings` | Estimated saving from current plan |
| `sensor.thermal_storage_next_release` | Next planned tank-use time |
| `sensor.thermal_storage_operating_state` | Final controller state |
| `sensor.thermal_storage_decision_reason` | Concise human-readable explanation |
| `sensor.thermal_storage_forecast_end` | Final timestamp in current forecast |
| `sensor.thermal_storage_forecast_coverage` | Remaining valid coverage in hours |
| `sensor.thermal_storage_last_optimization` | Last successful plan calculation |
| `sensor.thermal_storage_plan_status` | Full forecast, saved plan, waiting, or invalid |
| `binary_sensor.thermal_storage_release_recommended` | Planner recommendation |
| `binary_sensor.thermal_storage_data_valid` | Required data validity |
| `binary_sensor.thermal_storage_output_active` | Actual reserve-output command |
| `select.thermal_storage_mode` | Auto, Use tank, Reserve tank, Disabled |
| `switch.thermal_storage_optimizer` | Enable/disable automatic planning if useful |

Do not place the complete 34-hour plan in frequently changing entity attributes because that can unnecessarily enlarge the recorder database. Expose concise current/next values and make the full plan available through diagnostics or a dedicated integration action.

### 4.6 Human-in-the-loop stove charging advisor

The water-jacketed stove is the controllable charging source, but charging is performed manually by a person. The integration shall therefore convert the economic plan into an understandable firing recommendation rather than attempting to control the stove.

The advisor shall answer three questions:

1. Is additional stored heat economically useful within the known forecast?
2. Within the household’s normal firing pattern, when should firing occur and for how long?
3. Once firing has begun, how much longer should the user continue adding useful heat to reach the calculated target without aiming for unreasonable tank temperatures?

#### Preferred firing pattern

The initial model shall use configured preferred firing windows per weekday. The default preferred window is 15:00–23:00. The model shall support:

- Earliest normal start time.
- Latest normal finish time.
- Maximum preferred session duration.
- Minimum worthwhile session duration.
- Notification lead time.
- Optional permission for recommendations outside the normal window when the economic opportunity occurs earlier.
- Optional quiet hours.

Morning firing is considered unusual and shall not be recommended by default. A future adaptive model may learn typical start times and session lengths locally from detected firing sessions, but configured limits always take precedence.

#### Charging target

The target must be an **energy target**, not simply “heat the whole tank to maximum temperature.” It shall be calculated from:

- Current usable tank energy.
- Forecast heat demand during selected high-cost intervals.
- Expected tank discharge before those intervals.
- Expected heat use by the building during the firing session.
- Storage losses.
- Estimated net charging power into the tank.
- Maximum usable tank energy.
- Maximum allowed temperature for each configured tank layer.
- High-temperature forced-use threshold and safety margin.
- Expected residual heat added after the user stops adding wood.

The planned additional charge is:

\[
E_{charge,target} = \min(E_{economically\ useful}, E_{safe\ capacity}) - E_{current}
\]

The result must be clamped to zero. No recommendation shall be sent when the tank already contains enough useful energy, the expected benefit is below configured thresholds, or the required charge cannot fit within safe configured capacity.

The initial estimated firing duration is:

\[
t_{fire} = \frac{E_{charge,target}}{P_{charge,net}}
\]

`P_charge,net` is the effective net rate at which energy stored in the tank increases while the stove is firing. The initial value may be configured manually. Later it may be calibrated from tank-energy change during detected firing sessions, while accounting for simultaneous building heat use when possible.

#### Selecting the recommendation window

The planner shall find a feasible interval inside the preferred firing window that:

- Allows the required duration to complete before the stored heat is needed.
- Minimizes unnecessary storage time and tank losses.
- Does not conflict with predicted forced tank discharge.
- Gives a latest useful start time and a required completion time.
- Does not recommend a session longer than the configured maximum without clearly reporting that the full target cannot be reached in one normal session.

Example notification:

> Elda cirka 1 tim 45 min i dag. Börja mellan 17:30 och 20:45 och var klar senast 22:30. Målet är att lagra ytterligare 9,2 kWh inför morgondagens dyra timmar. Beräknad undvikbar elkostnad: 8 kr.

“Savings” shall be described as **estimated avoided electricity cost** unless wood cost and stove efficiency are configured and included. If fuel economics are enabled, the integration may additionally show estimated net saving.

#### Detecting and tracking an active firing session

An active session may be detected from one or more configured signals:

- Stove charging pump state.
- Stove flow temperature above a threshold.
- A sustained positive tank-energy rate above a threshold.
- A manual Home Assistant action indicating that firing has started.

During a detected session, the integration shall update:

- Energy added during the session.
- Remaining energy to the current target.
- Smoothed effective net charging power.
- Estimated minimum remaining charging time.
- Expected completion time.
- Confidence/quality of the estimate.
- Whether no additional wood is needed for the economic target because expected residual burn-down heat should complete it.

Example progress message:

> Fortsätt elda i minst cirka 35 minuter. 6,4 av 9,2 kWh har laddats. Beräknat mål nås cirka 20:25.

When the target is reached or expected residual heat is sufficient:

> Dagens planerade laddmål är uppnått. Ingen ytterligare ved behövs för energimålet. Följ alltid kaminens ordinarie eldning och säkerhetsinstruktioner.

The advisor must never instruct the user to extinguish a fire contrary to stove instructions. It only states whether additional fuel is economically required for the calculated target.

#### Notification behavior

- Recalculate the recommendation when new prices arrive, normally after 13:00.
- Send at most one initial recommendation per planning cycle unless a material change crosses a configurable threshold.
- Allow acknowledge, snooze, and dismiss behavior where supported by the configured Home Assistant notification target.
- Avoid repeated progress notifications. Prefer a continuously updated sensor/dashboard value and optionally update one replaceable mobile notification at configured intervals or milestones.
- Notify when firing should begin only if the recommendation is still feasible.
- Notify when the target is reached or when further charging would exceed the configured economic or safe target.
- Do not send a firing recommendation when confidence is insufficient.
- Retain all calculations locally in Home Assistant.

Additional entities should include:

| Entity | Purpose |
| --- | --- |
| `binary_sensor.thermal_storage_charge_recommended` | Whether a manual charge is currently recommended |
| `sensor.thermal_storage_recommended_charge_duration` | Recommended firing duration |
| `sensor.thermal_storage_recommended_start_earliest` | Earliest recommended start |
| `sensor.thermal_storage_recommended_start_latest` | Latest recommended start |
| `sensor.thermal_storage_charge_complete_by` | Required target completion time |
| `sensor.thermal_storage_charge_target_energy` | Additional target energy, kWh |
| `sensor.thermal_storage_charge_remaining_energy` | Remaining energy to target, kWh |
| `sensor.thermal_storage_charge_remaining_time` | Estimated minimum remaining time |
| `sensor.thermal_storage_charge_power` | Smoothed effective net charging power |
| `sensor.thermal_storage_charge_advice` | Concise human-readable advice |
| `binary_sensor.thermal_storage_stove_firing` | Detected active firing session |

---

## 5. Electricity-price forecast behavior

The available price forecast is normally published once per day at approximately 13:00 local time. It extends only through 23:59:59 the following day. Consequently, forecast coverage varies from approximately 34–35 hours after publication to approximately 11 hours immediately before the next publication.

Requirements:

- Never assume a fixed number of periods.
- Never assume a fixed interval duration.
- Use timezone-aware start and end timestamps.
- Handle daylight-saving changes without assuming 24 periods per day.
- Detect new price data from a changed final forecast timestamp or source update, not from the clock alone.
- Treat 13:00 only as an expected publication time.
- Run a full re-optimization when new prices arrive.
- Retain and continue using the last valid saved plan until replacement data is successfully parsed.
- Between approximately 12:00 and receipt of new prices, continue the previously calculated plan rather than treating the shortened horizon as evidence that all tank energy should be used.
- Do not dump or indefinitely reserve tank energy merely because the known forecast ends.
- If Home Assistant restarts, restore the last valid plan and validate that its timestamps are still applicable.
- When no usable current or saved plan exists, de-energize the offset output and use the normal local shunt behavior.

The price adapter shall normalize price units and allow configurable multiplicative and additive adjustments so that the optimizer can use the installation’s actual marginal electricity cost.

---

## 6. Recalculation triggers

The planner should recalculate when any of the following occurs:

- A new price forecast is detected.
- Tank energy changes more than a configurable threshold.
- A tank temperature crosses a configured limit.
- Stove charging starts or stops.
- A preferred firing window approaches.
- Effective charging power or remaining charge time changes materially during an active firing session.
- Outdoor-temperature forecast changes materially.
- A relevant configuration option changes.
- Home Assistant starts and valid inputs become available.
- A periodic planning interval expires, initially every 15 minutes.

The controller should evaluate the current plan and safety conditions more frequently, initially once per minute and on relevant state changes. Expensive calculations must not block the Home Assistant event loop.

---

## 7. Fail-safe and safety requirements

- Home Assistant is not a safety controller.
- Stove and tank overtemperature protection must remain independent of Home Assistant.
- The preferred physical relay design is de-energized for normal tank use so loss of Home Assistant or output power returns the shunt to local control.
- On integration load, unload, invalid data, internal exception, or missing valid plan, the component shall request output OFF/de-energized where Home Assistant is still able to issue the command.
- The integration shall not energize the reserve output until all required inputs have passed validation and the startup grace period has elapsed.
- A configurable high tank-temperature threshold must force tank use even in manual reserve mode.
- A configurable minimum dwell time, initially 30 minutes, must prevent rapid output changes except for thermal-protection transitions.
- State transitions and their reasons must be logged at an appropriate level.
- Invalid individual forecast periods should be rejected without crashing Home Assistant.
- Entity states `unknown`, `unavailable`, non-numeric values, missing attributes, stale values, and unit mismatches must be handled explicitly.
- Output service failures must set a fault state and must not be silently ignored.
- Charging recommendations must be capped by configured tank temperature, safe energy capacity, and residual-burn allowance.
- Notification advice must never supersede the stove manufacturer’s operating instructions or independent thermal safety systems.

---

## 8. Configuration model

### Required configuration entry data

- Tank top temperature entity.
- Tank middle temperature entity.
- Tank bottom temperature entity.
- Return temperature entity.
- Supply target entity.
- Outdoor temperature entity.
- Price forecast entity.
- Digital reserve-output entity.

### Options

- Total tank volume, default 500 L.
- Effective volume per temperature layer.
- Minimum useful temperature delta.
- Maximum calibrated usable energy.
- High-temperature forced-use threshold.
- High-temperature hysteresis.
- Output inversion.
- Startup grace period.
- Minimum dwell time.
- Planner interval.
- Heat-loss coefficient \(H\).
- Balance temperature.
- Fixed COP fallback.
- COP model parameters.
- Tank loss/retention model.
- Economic deadband.
- Price multiplier and additive marginal costs.
- Forecast uncertainty discount.
- Stove charging entity and interpretation, if configured.
- Preferred firing windows per weekday, default 15:00–23:00.
- Minimum and maximum preferred firing-session duration.
- Permission for exceptional recommendations outside preferred windows.
- Notification target, lead time, quiet hours, update interval, and minimum material-change threshold.
- Initial effective net stove charging power.
- Minimum estimated avoided electricity cost required before recommending a firing session.
- Optional wood cost, energy content, and estimated stove-to-tank efficiency.
- Maximum target temperature per tank layer and residual-burn energy allowance.
- Dry-run versus active-control permission.

Entity references that are necessary for operation belong in reconfiguration; tuning parameters belong in the options flow.

---

## 9. Suggested source structure

```text
custom_components/thermal_storage_optimizer/
├── __init__.py
├── manifest.json
├── const.py
├── config_flow.py
├── coordinator.py
├── data.py
├── energy.py
├── price.py
├── demand.py
├── cop.py
├── optimizer.py
├── controller.py
├── charging.py
├── firing_schedule.py
├── notifications.py
├── storage.py
├── sensor.py
├── binary_sensor.py
├── select.py
├── switch.py                 # only if an optimizer-enable entity is retained
├── diagnostics.py
├── services.yaml             # or current Home Assistant action description format
├── strings.json
└── translations/
    ├── en.json
    └── sv.json

tests/
├── conftest.py
├── test_config_flow.py
├── test_energy.py
├── test_price.py
├── test_demand.py
├── test_cop.py
├── test_optimizer.py
├── test_controller.py
├── test_charging.py
├── test_firing_schedule.py
├── test_notifications.py
├── test_restore.py
└── fixtures/
```

Use the current Home Assistant developer conventions discovered from the target development environment. Do not copy obsolete integration patterns blindly.

---

## 10. Development principles

- Build one milestone at a time.
- Keep calculation modules pure and independent from Home Assistant wherever practical.
- Use typed dataclasses or equivalent typed models for normalized inputs and plans.
- Use timezone-aware datetimes throughout.
- Separate recommendation from actuation.
- Keep active control disabled by default.
- Make every automatic decision explainable.
- Preserve backwards compatibility for config entries or add migrations.
- Add tests with each milestone, not afterwards.
- Do not introduce heavy numerical dependencies for the MVP.
- Avoid direct database queries for normal real-time operation.
- Never store large forecast arrays as frequently updated entity attributes.
- Do not silently guess units or malformed input schemas.
- Update project documentation and the milestone checklist after every milestone.

---

# 11. Implementation milestones

## Milestone 1 — Repository foundation and integration skeleton

### Goal

Create an installable Home Assistant custom integration with a clean architecture, UI setup flow, development tooling, and tests, but no optimization or physical control.

### Deliverables

- Integration manifest and package structure.
- Config flow that creates one integration instance.
- Initial reconfigure/options scaffolding.
- A Home Assistant device entry.
- Placeholder diagnostic status sensor.
- English and Swedish strings.
- Test setup and initial tests.
- README with installation and development instructions.
- Architecture decision record stating that recommendation and actuation remain separated.

### Acceptance criteria

- Home Assistant can load and unload the integration without errors.
- The integration can be added and removed through the UI.
- No YAML configuration is required.
- No physical output is controlled.
- Automated tests pass.
- Linting/type checks configured by the repository pass.

---

## Milestone 2 — Entity configuration, validation, and normalized input layer

**Status: Complete and verified (2026-09-07)**

### Goal

Allow the user to select the installation’s Home Assistant entities and reliably convert their states into validated, typed input data.

### Deliverables

- Entity selectors for all required inputs and reserve output.
- Optional selectors for indoor temperature, weather, COP, heat-pump measurements, and stove charging.
- Reconfiguration support for entity references.
- Options flow for non-entity tuning settings.
- Typed normalized snapshot model.
- Unit conversion and validation for temperatures and other implemented quantities.
- Stale/unavailable/unknown detection.
- Data-valid binary sensor and decision-status diagnostics.
- Tests for valid, invalid, unavailable, and malformed entities.

### Acceptance criteria

- [x] Entity references can be configured and changed through the UI.
- [x] A valid fixture produces a typed normalized snapshot.
- [x] Missing or malformed values produce an explicit invalid-data result, not an exception.
- [x] No reserve output is energized.
- [x] Tests cover startup before entities are ready and entity recovery after unavailability.

---

## Milestone 3 — Thermal energy, heat demand, and COP models

### Goal

Produce explainable estimates of usable tank energy and the building/heat-pump quantities needed by the optimizer.

### Deliverables

- Pure thermal energy model using the three tank layers.
- Total usable energy and high-grade energy.
- State-of-charge estimate and confidence/data-quality indicator.
- Basic charging/discharging trend detection.
- Basic building heat-demand model.
- Fixed-COP fallback and configurable COP model interface.
- Sensors for calculated quantities.
- Unit tests covering physical edge cases and representative examples.

### Acceptance criteria

- [x] For a 500 L equally divided tank, the model produces physically consistent energy values.
- [x] Energy is never negative.
- [x] Layer volume validation prevents invalid total configuration.
- [x] The reference temperature and minimum useful delta are applied explicitly.
- [x] COP cannot become zero or negative.
- [x] Model functions can be tested without starting Home Assistant.
- [x] Still no physical output actuation.

---

## Milestone 4 — Price adapter and dry-run rolling optimizer

**Status: Complete and verified (2026-09-07)**

### Goal

Normalize the installation’s price forecast and create a complete rolling use/reserve plan without controlling the shunt.

### Deliverables

- Price-provider abstraction.
- Adapter for the actual configured Home Assistant price entity format, isolated from core logic.
- Unit normalization and configurable variable-cost additions.
- Timezone-aware variable-length forecast intervals.
- Detection of new forecast publication.
- Forecast validity and coverage sensors.
- Pure optimizer producing interval allocations and decision explanations.
- Persistent last-valid plan.
- Dry-run recommendation entities.
- Tests for forecast lengths, missing tomorrow prices, delayed publication, restart, daylight-saving boundaries, and horizon-end behavior.

### Acceptance criteria

- [x] The implementation does not assume 24 hours, a fixed number of values, or hourly resolution.
- [x] New prices trigger full re-optimization.
- [x] Forecast coverage naturally varies from about 34–35 hours to about 11 hours.
- [x] The saved plan remains in use until valid replacement data arrives.
- [x] The optimizer does not consume all stored energy merely because the forecast ends.
- [x] The same pure optimizer input always produces the same plan.
- [x] The reserve output is never actuated.

---

## Milestone 5 — Supervisory controller and fail-safe shunt actuation

**Status: Complete and verified (2026-09-07)**

### Goal

Add explicit opt-in physical control of the digital −50 °C shunt-offset input, with strict state precedence and fail-safe behavior.

### Deliverables

- Controller state machine.
- `Auto`, `Use tank`, `Reserve tank`, and `Disabled` modes.
- Dry-run/active-control permission, defaulting to dry-run.
- Configurable output inversion.
- Thermal forced-use override.
- Startup grace period.
- Minimum dwell time and hysteresis.
- Safe unload/error behavior.
- Output service-error handling.
- State transition explanations and logs.
- Controller and end-to-end tests with a fake output entity.

### Acceptance criteria

- [x] Fresh installation cannot actuate the output until the user explicitly enables active control.
- [x] Output OFF/de-energized maps to default tank use for the intended installation.
- [x] High tank temperature forces tank use even when reserve is manually selected.
- [x] Invalid data and internal failures fall back to output OFF.
- [x] Dwell time prevents chatter but never delays forced thermal use.
- [x] Restart and unload behavior are tested.
- [x] No test can accidentally call a real entity.

---

## Milestone 6 — Stove charging advisor and live firing guidance

### Goal

Turn the optimized future energy requirement into practical, human-in-the-loop firing recommendations that match the household’s normal afternoon/evening pattern and provide live remaining-time guidance during charging.

### Deliverables

- Configurable preferred firing windows per weekday, default 15:00–23:00.
- Charging-target calculation limited by economic need and safe tank capacity.
- Feasible firing-duration and start-window planner.
- Detection of active firing/charging sessions.
- Smoothed effective net charging-power estimate.
- Continuously updated remaining energy, minimum remaining time, and completion estimate.
- Residual-burn allowance to avoid recommending unnecessary additional wood close to the target.
- Home Assistant notification support with throttling, acknowledgement/snooze where supported, and concise Swedish/English messages.
- Optional fuel-economics settings; gross avoided electricity cost clearly separated from net saving.
- Complete pure and Home Assistant integration tests.

### Acceptance criteria

- No recommendation is generated when current tank energy already covers the selected expensive periods.
- The default recommendation window remains within 15:00–23:00.
- Morning firing is not recommended unless the user explicitly permits exceptional out-of-window recommendations.
- The recommendation includes required duration, earliest/latest useful start, completion deadline, energy target, and estimated avoided electricity cost.
- Target energy never exceeds configured usable capacity or temperature-derived safe capacity.
- Active firing produces a stable, non-negative remaining-time estimate that updates as measured charging performance changes.
- Residual heat is considered before telling the user that more wood is required.
- Notifications are deduplicated and do not spam on every sensor update.
- Advice never instructs unsafe extinguishing and explicitly defers to stove operating and safety instructions.
- Failure of notification delivery does not affect shunt control or safety overrides.

---

## Milestone 7 — Diagnostics, usability, and field-validation release

**Status: Complete and verified (2026-09-08)**

### Goal

Make the integration understandable and safe to validate on the real heating system.

### Deliverables

- [x] Complete diagnostics output with sensitive identifiers redacted where appropriate.
- [x] Integration actions to recalculate, show/export a bounded plan, and reset learned state if present.
- [x] Clear dashboard entity set and example dashboard configuration.
- [x] Decision explanations and fault messages.
- [x] Field-validation checklist and staged commissioning guide.
- [x] Simulated multi-day test scenarios.
- [x] Documentation of backup, rollback, and disabling control.

### Acceptance criteria

- [x] A user can understand why the tank is being used or reserved.
- [x] Diagnostics show normalized inputs, model outputs, plan summary, controller state, and data validity without recorder-heavy entity attributes.
- [x] Commissioning starts in dry-run and compares recommendations against actual system behavior before active control.
- [x] Simulations cover low/flat/high/negative prices, cold and mild weather, active stove charging, delayed price data, sensor failures, and Home Assistant restart.
- [x] Documentation explains that the integration is not a safety controller.

---

## Milestone 8 — Adaptive energy model and measured-savings validation

### Goal

Improve tank-energy, heat-demand, and COP estimates from observed system behavior while retaining transparent fallbacks.

### Deliverables

- [x] Collection of bounded, relevant observation data inside Home Assistant.
- [x] Calibrated usable tank capacity/layer weighting.
- [x] Improved heat-demand estimate.
- [x] Optional measured COP calibration when suitable input measurements exist.
- [x] Learned effective stove-to-tank charging power, residual-burn energy, and typical firing start/duration patterns.
- [x] Confidence metrics and automatic fallback to deterministic defaults.
- [x] Estimated-versus-actual performance reporting.
- [x] Versioned persisted calibration state and reset capability.

### Acceptance criteria

- [x] Learning is optional and disabled or conservative by default.
- [x] Insufficient or poor-quality data cannot corrupt active control.
- [x] Every learned parameter has bounds, confidence, provenance, and a deterministic fallback.
- [x] Model changes are tested against fixed historical/synthetic datasets.
- [x] The user can inspect and reset learned values.
- [x] Claimed savings are labelled as estimated unless supported by adequate measurements.

---

## Milestone 9 — Packaging and maintainable release

**Status: Complete and verified (2026-09-08)**

### Goal

Prepare a stable, versioned release that can be installed manually and optionally distributed through HACS.

### Deliverables

- [x] Versioned release metadata.
- [x] Validated installation and upgrade instructions.
- [x] Config-entry migration policy.
- [x] Release notes and changelog.
- [x] HACS distribution decision documented; publishing metadata deferred until a
  real public repository identity, ownership, issue tracker, and Brands entry exist.
- [x] CI checks for tests and quality tools.
- [x] Compatibility statement for tested Home Assistant versions.

### Acceptance criteria

- [x] Clean installation, upgrade, reload, restart, and removal are tested.
- [x] Config entries survive upgrades or migrate explicitly.
- [x] The repository has reproducible quality checks.
- [x] Manual installation remains supported.
- [x] Active control remains opt-in after a new installation.

---

## 12. Field commissioning sequence

The implementation should ultimately be commissioned in this order:

1. Install the integration with active control disabled.
2. Verify all selected entity values and units.
3. Verify calculated tank energy manually at several temperature combinations.
4. Observe dry-run decisions for several complete price cycles.
5. Compare predicted tank depletion with actual sensor changes.
6. Verify charging recommendations without acting on them for several forecast cycles.
7. During supervised firing, compare predicted charge rate and remaining time with actual tank-temperature development.
8. Verify that the target is capped below configured maximum temperatures and accounts for residual burn-down heat.
9. Verify notification throttling, snooze, completion advice, and fallback when notification delivery fails.
10. Test the digital output manually while supervising the heating system.
11. Confirm that output OFF returns the shunt to normal local control.
12. Confirm high-temperature forced use.
13. Enable active control for a limited supervised period.
14. Review decisions, switching frequency, firing advice, comfort, heat-pump behavior, and calculated savings.
15. Tune model values before enabling long-term automatic operation.

---

## 13. Open installation details to collect before Milestone 4–5 commissioning

These do not block the initial integration architecture, but must be recorded before real control:

- Exact Home Assistant entity IDs.
- Example state and attributes from the electricity-price forecast entity before and after the daily publication.
- Price unit and whether taxes/fees are already included.
- Exact tank sensor positions and approximate volume represented by each.
- Normal radiator return-temperature range.
- Source and format of the supply-temperature target.
- Available weather forecast source.
- Available heat-pump electrical/thermal measurements.
- Digital output entity domain and confirmation of ON/OFF polarity.
- Verified tank maximum operating temperature and desired forced-use threshold.
- How active stove charging can be detected.
- Preferred firing windows per weekday and whether exceptional recommendations outside them are permitted.
- Notification target and desired reminder/snooze behavior.
- Typical firing duration and approximate effective heat transferred to the tank.
- Expected residual heat after the last wood is added.
- Maximum acceptable temperature for each measured tank layer and required safety margin.
- Whether wood cost and stove efficiency should be included or only avoided electricity cost shown.
- Initial heat-loss coefficient, balance temperature, COP assumptions, tank-loss assumption, and economic deadband.

---

## 14. Definition of project success

The project is successful when the integration can transparently show how much useful energy is believed to be in the tank, forecast when that energy has the greatest economic value, recommend a practical and safe-time-bounded manual firing session that fits the household’s normal pattern, guide the user with a credible remaining charging time, reserve or release stored heat through the existing binary shunt-offset input, recover safely from missing data and restarts, and demonstrate a credible reduction in heat-pump electricity cost without degrading comfort or bypassing independent heating-system safety functions.

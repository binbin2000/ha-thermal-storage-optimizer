# Multi-day simulated validation scenarios

Run these scenarios against a non-production Home Assistant instance or synthetic
fixtures. Each scenario spans at least 72 hours and includes a daily price
publication boundary. Capture the bounded plan action response, diagnostics, entity
history, output service calls, logs, and restart state. Never inject faults into a
live heating system unless the physical consequence is understood and supervised.

| Scenario | 72-hour stimulus | Required observations |
| --- | --- | --- |
| Low prices | Constant low positive prices; cold, warming, then mild outdoor conditions | Little/no allocation unless a difference clears deadband; heat demand falls as weather warms; no end-of-horizon dump |
| Flat prices | Constant representative price across all periods | No artificial arbitrage, chronological ties deterministic, energy retained beyond horizon |
| High-price spikes | Low baseline with morning/evening spikes on days 2–3 | Stored energy allocated first to highest adjusted avoided heat cost, bounded by demand and available energy; explanations identify use/reserve |
| Negative prices | Negative blocks followed by positive and high blocks | Negative periods receive no tank allocation while higher positive value exists; expected avoided cost is non-negative |
| Weather change | Cold → mild → cold temperatures with otherwise equal prices | Demand responds linearly to configured model; colder eligible intervals can accept more energy; COP source/confidence remain explicit |
| Tank stratification | Stratified, mixed, inverted, cold, and hot layer tuples | Energy remains non-negative; quality degrades for inversion; high-grade energy reflects supply target; hot layer caps charging/forces use |
| Stove charging and firing advice | Low initial tank, day-3 expensive demand, preferred 15:00–23:00 window, then positive energy samples during supervised firing | Feasible bounded start/duration/deadline, smooth non-negative remaining time, residual completion, no unsafe extinguishing instruction |
| Delayed/malformed publication | Keep day-1 valid plan while day-2 publication is late, partially malformed, then valid | Last unexpired valid plan continues, rejected count/reason visible, valid longer replacement reoptimizes |
| Missing sensors | Remove each required sensor in turn, then restore; separately remove optional sensors | Required failure produces explicit issue and immediate OFF fallback; optional failure degrades only related calculations; recovery is automatic |
| Notification failure | Fail initial/progress notification delivery, then recover service | Error visible and bounded; plan, controller, forced-use precedence, and output calls unchanged; deduplication resumes |
| Output failure | Fail ON, then fail OFF separately using a fake output entity | ON failure enters fault fallback and attempts OFF; failed OFF never claims de-energization and requires physical inspection |
| Home Assistant restart | Restart before valid data, during saved plan, during manual firing tracking, and while Reserve was last requested | Initial OFF request and fresh startup grace; valid plan/session continuity only; mode may restore but output state/dwell are not assumed |

Automated coverage lives in `tests/test_field_scenarios.py` for 72-hour
price/weather, tank/stove, malformed-publication, sensor/fault, and restart-state
logic. Home Assistant lifecycle coverage is in `test_planner_integration.py`,
`test_controller_integration.py`, `test_advisor_integration.py`, and
`test_diagnostics_actions.py`. The manual physical-output observations cannot be
proven by software tests and remain commissioning gates.

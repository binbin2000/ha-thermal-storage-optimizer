# Scope review implementation - 2026-09-08

The original review remains a historical record. This follow-up records the
software corrections and their verification; it is not physical commissioning.

| Finding | Implemented correction |
| --- | --- |
| 1 | Compare commands with observed output, bounded acknowledgement, latched disagreement fault, external ON/OFF regressions. |
| 2 | Keep valid prices independently; rebuild on input changes and configurable 1-60 minute planning interval; preserve longer horizons and restart continuation. |
| 3 | End-aligned partial release windows, boundary callbacks, minimum dwell eligibility and reserve-gap checks, observed energy budget stop; chronological binary simulation with rolling replanning and losses. |
| 4 | Exclude non-positive avoided cost, including after the reservation deadline. |
| 5 | Persist a 24-hour reservation deadline across publications; positive flat-price periods become eligible after it. |
| 6 | Divide delivered heat by interval-end retention when spending stored energy; compute avoided cost from delivered heat without double-discounting retention. |
| 7 | Use net storage gain consistently, solve the pre-firing discharge balance, account for manual/forced use, omit duplicate session building demand. |
| 8 | Per-feature evidence availability and age gates; clear invalid sample histories; preserve independent timestamps on restart and avoid refreshing unchanged evidence. |
| 9 | Format sources/tests, verify existing ZIP against every source byte, rebuild the distribution and test an extracted copy; qualify README milestone claims. |

The dispatch model assumes constant heat demand within each forecast interval.
Sensor latency, actuator travel time, and physical heat-flow uncertainty remain
commissioning concerns. Minimum dwell can be overridden by an exhausted Auto
energy budget or existing safety precedence. Manual and high-temperature use take
precedence over economic reservations.

The charging estimate assumes firing can begin at the modeled latest start;
preferred-window restrictions can make the resulting schedule infeasible. Live net
power and observed energy continue to update guidance while firing.

## Verification

- Ruff lint: passed.
- Ruff formatting: passed (73 files).
- Mypy: passed (26 integration source files).
- Rebuilt ZIP: all 31 packaged files compared byte-for-byte with sources.
- Full suite against an extracted copy of that exact ZIP: **160 passed in 17.95 s**.
  The test process asserted that the imported component came from the extraction,
  not the working source directory. Coverage includes setup, migration, reload,
  unload, frontend registration, controller and planning regressions.
- Runtime: repository Python 3.14.2 environment and Windows Home Assistant test
  wrapper with fake entities/services. Linux commissioning and remote CI/Hassfest
  were not run.

No production actuator was controlled. Measured cost/comfort success remains
unverified. The Windows test wrapper is not a live Home Assistant installation.

Archive: `dist/thermal_storage_optimizer-1.0.0.zip`

SHA-256: `19a791e1f89c1357df29db269985fd26dc1656199822d4ad8131998e827e64ac`


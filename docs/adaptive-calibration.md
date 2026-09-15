# Bounded adaptive calibration and performance validation

Adaptive calibration is local, transparent, optional, and disabled by default. It
subscribes only to the already configured Home Assistant entities and does not read
Recorder or use a network, cloud service, opaque model, or background database scan.
Accepted observations are at least five minutes apart (except session transitions),
the in-memory observation window is capped at 2,016 entries, and each persisted
feature is capped at 96 clean samples.

Every learned parameter reports its value, configured physical minimum/maximum,
confidence, sample count, provenance, last update, activation state, and fallback
reason on the **Adaptive calibration status** diagnostic entity and in integration
diagnostics. A value is used only when calibration is enabled, the fit is within its
bounds, and confidence reaches the configured threshold. Otherwise the original
configured deterministic value is selected on the same refresh. Controller safety
precedence and output transitions are unchanged.

## Measurement sufficiency

| Feature | Required observations | Sufficiency with configured entities |
| --- | --- | --- |
| Usable capacity / tank scale | Multiple large, same-direction tank changes after a confident demand fit, with produced-heat energy available to close the interval energy balance | Conditional; three tank sensors alone are insufficient |
| Heat demand coefficient and balance temperature | Produced-heat energy, tank energy, clean non-firing intervals, at least 12 samples, and at least 5 °C outdoor spread | Conditional; outdoor temperature alone is insufficient |
| COP | Paired monotonically increasing heat-pump electrical-energy and produced-heat-energy counters | Sufficient only when both optional energy meters are configured and valid; an instantaneous measured-COP entity still takes precedence |
| Stove net charging power and residual energy | At least three clearly detected sessions, tank-energy rise, and a post-session observation; five sessions for time preferences | Conditional; a pump, stove-temperature, or manual session signal is needed for reliable identification |
| Typical start and duration | Five detected local firing sessions | Sufficient as a soft preference only; configured windows always clip the result and the default window continues to prohibit morning recommendations |
| Observed heat-model validation | Produced-heat energy plus clean tank changes | Conditional |
| Measured monetary savings | A defensible counterfactual baseline in addition to energy and price measurements | Not supplied by the current entity set; savings therefore remain labelled **modeled avoided electricity cost**, never measured savings |

Counter resets, negative deltas, implausible jumps, short/low-quality intervals,
poor temperature diversity, outliers, and bound-hitting estimates are rejected or
left inactive with an explicit fallback reason. Persistence schema version 2 accepts
the bounded version-1 shape during migration and rejects unknown or malformed data.
The reset action does not touch the saved optimization plan, controller mode, safety
latch, actuator state, or active advisor-session continuity.

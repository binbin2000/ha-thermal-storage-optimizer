"""Bounded, transparent local calibration for the deterministic energy model."""

# ruff: noqa: D105, D107, EM101, PLR0913, PLR2004, TRY003

from __future__ import annotations

import math
import statistics
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Final

CALIBRATION_SCHEMA_VERSION: Final = 2
MAX_OBSERVATIONS: Final = 2016
MAX_CALIBRATION_SAMPLES: Final = 96
MIN_OBSERVATION_INTERVAL: Final = timedelta(minutes=5)
MIN_ACTIVE_CONFIDENCE: Final = 0.7
MIN_DEMAND_SAMPLES: Final = 12


@dataclass(frozen=True, slots=True)
class ParameterBounds:
    """Configured inclusive physical bounds for one learned scalar."""

    minimum: float
    maximum: float

    def __post_init__(self) -> None:
        if not all(math.isfinite(item) for item in (self.minimum, self.maximum)):
            raise ValueError("calibration bounds must be finite")
        if self.minimum > self.maximum:
            raise ValueError("calibration minimum must not exceed maximum")

    def clamp(self, value: float) -> float:
        """Clamp a finite estimate to the configured physical interval."""
        if not math.isfinite(value):
            raise ValueError("learned values must be finite")
        return min(max(value, self.minimum), self.maximum)


@dataclass(frozen=True, slots=True)
class LearnedParameter:
    """Inspectable learned value with enough metadata for safe selection."""

    value: float | None
    unit: str
    bounds: ParameterBounds
    confidence: float
    sample_count: int
    last_updated: datetime | None
    provenance: str
    fallback_reason: str | None

    def usable(self, minimum_confidence: float = MIN_ACTIVE_CONFIDENCE) -> bool:
        """Return whether this parameter may replace its configured fallback."""
        return (
            self.value is not None
            and self.bounds.minimum <= self.value <= self.bounds.maximum
            and self.sample_count > 0
            and self.confidence >= minimum_confidence
            and self.fallback_reason is None
        )

    def selected(self, fallback: float, minimum_confidence: float) -> float:
        """Select the learned value only after all conservative gates pass."""
        if not self.usable(minimum_confidence) or self.value is None:
            return fallback
        return self.value


@dataclass(frozen=True, slots=True)
class DemandSample:
    """Observed mean building heat power at one outdoor temperature."""

    outdoor_temperature_c: float
    heat_power_kw: float


@dataclass(frozen=True, slots=True)
class EnergyRatioSample:
    """Meter deltas from an identifiable heat-pump interval."""

    electrical_kwh: float
    produced_heat_kwh: float


@dataclass(frozen=True, slots=True)
class CapacityCycle:
    """An isolated cycle comparing external energy balance with tank estimate."""

    modeled_tank_change_kwh: float
    observed_net_tank_change_kwh: float


@dataclass(frozen=True, slots=True)
class FiringSessionSample:
    """A clearly detected stove session and its observed tank response."""

    start: datetime
    duration_hours: float
    net_tank_gain_kwh: float
    residual_gain_kwh: float


@dataclass(frozen=True, slots=True)
class Observation:
    """One bounded normalized observation, independent of HA state objects."""

    at: datetime
    tank_energy_kwh: float
    outdoor_temperature_c: float | None
    produced_heat_energy_kwh: float | None
    electrical_energy_kwh: float | None
    firing_active: bool
    predicted_heat_power_kw: float | None = None
    data_quality: float = 1.0


@dataclass(frozen=True, slots=True)
class PerformanceReport:
    """Bounded estimated-versus-observed aggregates with honest savings labels."""

    comparison_samples: int
    modeled_heat_kwh: float
    observed_heat_kwh: float
    mean_absolute_error_kwh: float | None
    modeled_savings: float | None
    measured_savings: float | None
    savings_label: str
    fallback_reason: str | None


@dataclass(frozen=True, slots=True)
class CalibrationConfig:
    """Fallbacks, physical bounds, and activation gate for local learning."""

    enabled: bool
    minimum_confidence: float
    capacity_fallback_kwh: float
    heat_loss_fallback_kw_per_k: float
    balance_fallback_c: float
    cop_fallback: float
    charging_power_fallback_kw: float
    residual_fallback_kwh: float
    capacity_bounds: ParameterBounds
    heat_loss_bounds: ParameterBounds
    balance_bounds: ParameterBounds
    cop_bounds: ParameterBounds
    charging_power_bounds: ParameterBounds
    residual_bounds: ParameterBounds


def calibrate_cop(
    samples: Iterable[EnergyRatioSample], bounds: ParameterBounds, *, now: datetime
) -> LearnedParameter:
    """Robustly calibrate COP only from positive paired meter deltas."""
    ratios = [
        item.produced_heat_kwh / item.electrical_kwh
        for item in samples
        if item.electrical_kwh > 0
        and item.produced_heat_kwh > 0
        and math.isfinite(item.electrical_kwh)
        and math.isfinite(item.produced_heat_kwh)
    ]
    return _robust_parameter(
        ratios,
        bounds,
        now=now,
        unit="COP",
        provenance="paired produced-heat and electrical-energy deltas",
        minimum_samples=6,
    )


def calibrate_capacity(
    cycles: Iterable[CapacityCycle],
    bounds: ParameterBounds,
    *,
    configured_capacity_kwh: float,
    now: datetime,
) -> LearnedParameter:
    """Scale configured capacity from complete, externally balanced tank cycles."""
    estimates = [
        configured_capacity_kwh
        * abs(item.observed_net_tank_change_kwh / item.modeled_tank_change_kwh)
        for item in cycles
        if abs(item.modeled_tank_change_kwh) >= 5
        and abs(item.observed_net_tank_change_kwh) >= 5
        and item.modeled_tank_change_kwh * item.observed_net_tank_change_kwh > 0
    ]
    return _robust_parameter(
        estimates,
        bounds,
        now=now,
        unit="kWh",
        provenance="identifiable metered charge/discharge cycles",
        minimum_samples=3,
    )


def calibrate_demand(
    samples: Iterable[DemandSample],
    heat_loss_bounds: ParameterBounds,
    balance_bounds: ParameterBounds,
    *,
    now: datetime,
) -> tuple[LearnedParameter, LearnedParameter]:
    """Fit Q=H(B-T) with bounded transparent least squares."""
    valid = [
        item
        for item in samples
        if math.isfinite(item.outdoor_temperature_c)
        and math.isfinite(item.heat_power_kw)
        and item.heat_power_kw >= 0
    ]
    reason = None
    if len(valid) < 12:
        reason = "insufficient clean heat-demand intervals (need 12)"
    elif (
        max(x.outdoor_temperature_c for x in valid)
        - min(x.outdoor_temperature_c for x in valid)
        < 5
    ):
        reason = "outdoor-temperature spread is too small"
    if reason is not None:
        return (
            _unavailable(
                heat_loss_bounds, "kW/K", "observed heat demand", len(valid), reason
            ),
            _unavailable(
                balance_bounds, "°C", "observed heat demand", len(valid), reason
            ),
        )
    mean_t = statistics.fmean(item.outdoor_temperature_c for item in valid)
    mean_q = statistics.fmean(item.heat_power_kw for item in valid)
    variance = sum((item.outdoor_temperature_c - mean_t) ** 2 for item in valid)
    slope = (
        sum(
            (item.outdoor_temperature_c - mean_t) * (item.heat_power_kw - mean_q)
            for item in valid
        )
        / variance
    )
    heat_loss = -slope
    if heat_loss <= 0:
        reason = "observations do not show increasing demand in colder weather"
        return (
            _unavailable(
                heat_loss_bounds, "kW/K", "observed heat demand", len(valid), reason
            ),
            _unavailable(
                balance_bounds, "°C", "observed heat demand", len(valid), reason
            ),
        )
    balance = (mean_q - slope * mean_t) / heat_loss
    predicted = [
        heat_loss * max(balance - item.outdoor_temperature_c, 0) for item in valid
    ]
    observed = [item.heat_power_kw for item in valid]
    error = statistics.fmean(
        abs(a - b) for a, b in zip(predicted, observed, strict=True)
    )
    scale = max(statistics.fmean(observed), 0.1)
    confidence = min(len(valid) / (MIN_DEMAND_SAMPLES * 2), 1.0) * max(
        1 - error / scale, 0
    )
    bounded_h = heat_loss_bounds.clamp(heat_loss)
    bounded_b = balance_bounds.clamp(balance)
    bound_reason = (
        "fit reached a configured physical bound"
        if bounded_h != heat_loss or bounded_b != balance
        else None
    )
    return (
        LearnedParameter(
            bounded_h,
            "kW/K",
            heat_loss_bounds,
            confidence,
            len(valid),
            now,
            "bounded linear regression of observed heat demand",
            bound_reason,
        ),
        LearnedParameter(
            bounded_b,
            "°C",
            balance_bounds,
            confidence,
            len(valid),
            now,
            "bounded linear regression of observed heat demand",
            bound_reason,
        ),
    )


def calibrate_firing_sessions(
    sessions: Iterable[FiringSessionSample],
    power_bounds: ParameterBounds,
    residual_bounds: ParameterBounds,
    *,
    now: datetime,
) -> tuple[LearnedParameter, LearnedParameter, LearnedParameter, LearnedParameter]:
    """Calibrate net power, residual energy, and soft local time preferences."""
    valid = [
        item
        for item in sessions
        if item.duration_hours >= 0.5 and item.net_tank_gain_kwh > 0
    ]
    power = _robust_parameter(
        (item.net_tank_gain_kwh / item.duration_hours for item in valid),
        power_bounds,
        now=now,
        unit="kW",
        provenance="clearly detected firing sessions",
        minimum_samples=3,
    )
    residual = _robust_parameter(
        (item.residual_gain_kwh for item in valid),
        residual_bounds,
        now=now,
        unit="kWh",
        provenance="post-firing tank-energy rise",
        minimum_samples=3,
    )
    time_bounds = ParameterBounds(0, 1439)
    duration_bounds = ParameterBounds(30, 720)
    start = _robust_parameter(
        (item.start.hour * 60 + item.start.minute for item in valid),
        time_bounds,
        now=now,
        unit="minute of day",
        provenance="local firing-session start times; soft preference only",
        minimum_samples=5,
    )
    duration = _robust_parameter(
        (item.duration_hours * 60 for item in valid),
        duration_bounds,
        now=now,
        unit="min",
        provenance="local firing-session durations; soft preference only",
        minimum_samples=5,
    )
    return power, residual, start, duration


class AdaptiveCalibration:
    """Own bounded observations, learned parameters, persistence, and reporting."""

    def __init__(self, config: CalibrationConfig) -> None:
        self.config = config
        self.observations: deque[Observation] = deque(maxlen=MAX_OBSERVATIONS)
        self.cop_samples: deque[EnergyRatioSample] = deque(
            maxlen=MAX_CALIBRATION_SAMPLES
        )
        self.demand_samples: deque[DemandSample] = deque(maxlen=MAX_CALIBRATION_SAMPLES)
        self.capacity_cycles: deque[CapacityCycle] = deque(
            maxlen=MAX_CALIBRATION_SAMPLES
        )
        self.sessions: deque[FiringSessionSample] = deque(
            maxlen=MAX_CALIBRATION_SAMPLES
        )
        self.parameters = self._fallback_parameters(
            "adaptive calibration is disabled"
            if not config.enabled
            else "insufficient observations"
        )
        self._evidence_revision = dict.fromkeys(
            ("cop", "demand", "capacity", "session"), 0
        )
        self._session_start: Observation | None = None
        self._pending_session: tuple[datetime, float, float] | None = None
        self._modeled_heat_kwh = 0.0
        self._observed_heat_kwh = 0.0
        self._absolute_error_kwh = 0.0
        self._comparison_samples = 0

    def value(self, name: str, fallback: float) -> float:
        """Return a safe active parameter or its deterministic fallback."""
        if not self.config.enabled:
            return fallback
        return self.parameters[name].selected(fallback, self.config.minimum_confidence)

    def check_health(
        self,
        *,
        now: datetime,
        tank_valid: bool,
        outdoor: float | None,
        heat_meter: float | None,
        electric_meter: float | None,
        firing_available: bool = True,
    ) -> None:
        """Invalidate only features whose supporting evidence is absent or stale."""
        if self.observations:
            previous = self.observations[-1]
            heat_delta = _counter_delta(previous.produced_heat_energy_kwh, heat_meter)
            electric_delta = _counter_delta(
                previous.electrical_energy_kwh, electric_meter
            )
            if heat_delta is None:
                heat_meter = None
            if electric_delta is None or (
                heat_delta is not None
                and electric_delta > 0
                and not self.config.cop_bounds.minimum
                <= heat_delta / electric_delta
                <= self.config.cop_bounds.maximum
            ):
                electric_meter = None
        groups = (
            (
                ("cop",),
                self.cop_samples,
                heat_meter is not None and electric_meter is not None,
                timedelta(days=1),
            ),
            (
                ("heat_loss_coefficient_kw_per_k", "balance_temperature_c"),
                self.demand_samples,
                tank_valid and outdoor is not None and heat_meter is not None,
                timedelta(days=1),
            ),
            (
                ("usable_capacity_kwh",),
                self.capacity_cycles,
                tank_valid and outdoor is not None and heat_meter is not None,
                timedelta(days=7),
            ),
            (
                (
                    "net_charging_power_kw",
                    "residual_burn_energy_kwh",
                    "typical_firing_start_minute",
                    "typical_firing_duration_min",
                ),
                self.sessions,
                tank_valid and firing_available,
                timedelta(days=30),
            ),
        )
        for names, samples, healthy, max_age in groups:
            stale = any(
                (updated := self.parameters[name].last_updated) is not None
                and now - updated > max_age
                for name in names
            )
            if not healthy or stale:
                samples.clear()
                for name in names:
                    self.parameters[name] = replace(
                        self.parameters[name],
                        fallback_reason="supporting observations unavailable or stale",
                        confidence=0,
                    )
        if not tank_valid or not firing_available:
            self._session_start = None
            self._pending_session = None

    def observe(self, item: Observation) -> bool:  # noqa: C901
        """Accept a normalized state-change observation and update bounded fits."""
        if self.observations and item.at <= self.observations[-1].at:
            return False
        self.check_health(
            now=item.at,
            tank_valid=_valid_observation(item)
            and item.data_quality >= 0.8
            and item.tank_energy_kwh <= self.config.capacity_bounds.maximum * 1.5,
            outdoor=item.outdoor_temperature_c,
            heat_meter=item.produced_heat_energy_kwh,
            electric_meter=item.electrical_energy_kwh,
        )
        if (
            not self.config.enabled
            or not _valid_observation(item)
            or item.tank_energy_kwh > self.config.capacity_bounds.maximum * 1.5
        ):
            return False
        previous = self.observations[-1] if self.observations else None
        if previous is not None and item.at <= previous.at:
            return False
        transition = (
            previous is not None and item.firing_active != previous.firing_active
        )
        if (
            previous is not None
            and not transition
            and item.at - previous.at < MIN_OBSERVATION_INTERVAL
        ):
            return False
        if previous is not None:
            heat_reset = (
                _counter_delta(
                    previous.produced_heat_energy_kwh, item.produced_heat_energy_kwh
                )
                is None
            )
            electric_reset = (
                _counter_delta(
                    previous.electrical_energy_kwh, item.electrical_energy_kwh
                )
                is None
            )
            if heat_reset or electric_reset:
                self.check_health(
                    now=item.at,
                    tank_valid=True,
                    outdoor=item.outdoor_temperature_c,
                    heat_meter=None if heat_reset else item.produced_heat_energy_kwh,
                    electric_meter=None
                    if electric_reset
                    else item.electrical_energy_kwh,
                )
        old_revisions = tuple(self._evidence_revision.values())
        old_parameters = self.parameters.copy()
        self.observations.append(item)
        if previous is not None:
            self._consume_interval(previous, item)
        self._consume_session(previous, item)
        self._recalibrate(item.at)
        groups = (
            ("cop",),
            ("heat_loss_coefficient_kw_per_k", "balance_temperature_c"),
            ("usable_capacity_kwh",),
            (
                "net_charging_power_kw",
                "residual_burn_energy_kwh",
                "typical_firing_start_minute",
                "typical_firing_duration_min",
            ),
        )
        for names, before, after in zip(
            groups,
            old_revisions,
            tuple(self._evidence_revision.values()),
            strict=True,
        ):
            if before == after:
                for name in names:
                    self.parameters[name] = old_parameters[name]
        return True

    def performance_report(self, modeled_savings: float | None) -> PerformanceReport:
        """Return honest aggregate validation; never relabel modeled savings."""
        mean_error = (
            self._absolute_error_kwh / self._comparison_samples
            if self._comparison_samples
            else None
        )
        reason = (
            None if self._comparison_samples else "paired heat observations unavailable"
        )
        return PerformanceReport(
            self._comparison_samples,
            self._modeled_heat_kwh,
            self._observed_heat_kwh,
            mean_error,
            modeled_savings,
            None,
            "modeled avoided electricity cost; not measured savings",
            reason,
        )

    def reset(self) -> None:
        """Clear only adaptive state; deterministic configuration is untouched."""
        self.observations.clear()
        self.cop_samples.clear()
        self.demand_samples.clear()
        self.capacity_cycles.clear()
        self.sessions.clear()
        self._session_start = None
        self._pending_session = None
        self._modeled_heat_kwh = 0
        self._observed_heat_kwh = 0
        self._absolute_error_kwh = 0
        self._comparison_samples = 0
        self.parameters = self._fallback_parameters("reset; insufficient observations")

    def serialize(self) -> dict[str, Any]:
        """Serialize only bounded calibration samples and aggregates."""
        update_times = [
            item.last_updated
            for item in self.parameters.values()
            if item.last_updated is not None
        ]
        last_updated = max(update_times) if update_times else None
        return {
            "schema_version": CALIBRATION_SCHEMA_VERSION,
            "feature_updated_at": {
                name: p.last_updated.isoformat() if p.last_updated else None
                for name, p in self.parameters.items()
            },
            "last_calibrated_at": (
                last_updated.isoformat() if last_updated is not None else None
            ),
            "cop_samples": [asdict(item) for item in self.cop_samples],
            "demand_samples": [asdict(item) for item in self.demand_samples],
            "capacity_cycles": [asdict(item) for item in self.capacity_cycles],
            "sessions": [
                {**asdict(item), "start": item.start.isoformat()}
                for item in self.sessions
            ],
            "performance": {
                "modeled_heat_kwh": self._modeled_heat_kwh,
                "observed_heat_kwh": self._observed_heat_kwh,
                "absolute_error_kwh": self._absolute_error_kwh,
                "comparison_samples": self._comparison_samples,
            },
        }

    def restore(self, payload: object, *, now: datetime) -> bool:
        """Restore schema v1/v2 safely, rejecting malformed or future state."""
        if not isinstance(payload, Mapping):
            return False
        version = payload.get("schema_version", 1)
        if version not in (1, CALIBRATION_SCHEMA_VERSION):
            return False
        try:
            self.cop_samples.extend(
                EnergyRatioSample(**x) for x in _dict_items(payload, "cop_samples")
            )
            self.demand_samples.extend(
                DemandSample(**x) for x in _dict_items(payload, "demand_samples")
            )
            self.capacity_cycles.extend(
                CapacityCycle(**x) for x in _dict_items(payload, "capacity_cycles")
            )
            self.sessions.extend(
                FiringSessionSample(
                    start=_aware(x["start"]),
                    duration_hours=float(x["duration_hours"]),
                    net_tank_gain_kwh=float(x["net_tank_gain_kwh"]),
                    residual_gain_kwh=float(x["residual_gain_kwh"]),
                )
                for x in _dict_items(payload, "sessions")
            )
            performance = payload.get("performance", {})
            if isinstance(performance, Mapping):
                self._modeled_heat_kwh = float(performance.get("modeled_heat_kwh", 0))
                self._observed_heat_kwh = float(performance.get("observed_heat_kwh", 0))
                self._absolute_error_kwh = float(
                    performance.get("absolute_error_kwh", 0)
                )
                self._comparison_samples = int(performance.get("comparison_samples", 0))
            calibrated_at = (
                _aware(payload["last_calibrated_at"])
                if payload.get("last_calibrated_at") is not None
                else now
            )
            if calibrated_at > now + timedelta(minutes=5):
                self.reset()
                return False
            self._recalibrate(calibrated_at)
            feature_times = payload.get("feature_updated_at", {})
            if isinstance(feature_times, Mapping):
                for name, value in feature_times.items():
                    if name in self.parameters and value is not None:
                        updated = _aware(value)
                        if updated > now + timedelta(minutes=5):
                            raise ValueError("future feature timestamp")  # noqa: TRY301
                        self.parameters[name] = replace(
                            self.parameters[name], last_updated=updated
                        )
            self.check_health(
                now=now, tank_valid=True, outdoor=0, heat_meter=0, electric_meter=0
            )
        except KeyError, TypeError, ValueError, OverflowError:
            self.reset()
            return False
        return True

    def diagnostics(self) -> dict[str, Any]:
        """Return bounded, entity-free calibration diagnostics."""
        return {
            "enabled": self.config.enabled,
            "observation_count": len(self.observations),
            "observation_limit": MAX_OBSERVATIONS,
            "parameters": {
                name: {
                    **asdict(item),
                    "bounds": asdict(item.bounds),
                    "last_updated": item.last_updated.isoformat()
                    if item.last_updated
                    else None,
                    "active": self.config.enabled
                    and item.usable(self.config.minimum_confidence),
                }
                for name, item in self.parameters.items()
            },
        }

    def _consume_interval(self, before: Observation, after: Observation) -> None:
        hours = (after.at - before.at).total_seconds() / 3600
        if (
            not 1 / 12 <= hours <= 2
            or min(before.data_quality, after.data_quality) < 0.8
        ):
            return
        tank_delta = after.tank_energy_kwh - before.tank_energy_kwh
        heat_delta = _counter_delta(
            before.produced_heat_energy_kwh, after.produced_heat_energy_kwh
        )
        electric_delta = _counter_delta(
            before.electrical_energy_kwh, after.electrical_energy_kwh
        )
        if (
            heat_delta is not None
            and electric_delta is not None
            and 0.05 <= electric_delta <= 20
        ):
            self.cop_samples.append(EnergyRatioSample(electric_delta, heat_delta))
            self._evidence_revision["cop"] += 1
        if (
            heat_delta is not None
            and not before.firing_active
            and not after.firing_active
        ):
            observed_demand = heat_delta - tank_delta
            if 0 <= observed_demand <= 30 and before.outdoor_temperature_c is not None:
                self._evidence_revision["demand"] += 1
                self.demand_samples.append(
                    DemandSample(before.outdoor_temperature_c, observed_demand / hours)
                )
                if before.predicted_heat_power_kw is not None:
                    modeled = max(before.predicted_heat_power_kw * hours, 0)
                    self._modeled_heat_kwh += modeled
                    self._observed_heat_kwh += observed_demand
                    self._absolute_error_kwh += abs(modeled - observed_demand)
                    self._comparison_samples += 1
            heat_loss = self.parameters["heat_loss_coefficient_kw_per_k"]
            balance = self.parameters["balance_temperature_c"]
            if (
                before.outdoor_temperature_c is not None
                and heat_loss.usable(self.config.minimum_confidence)
                and balance.usable(self.config.minimum_confidence)
                and heat_loss.value is not None
                and balance.value is not None
            ):
                expected_demand = (
                    heat_loss.value
                    * max(balance.value - before.outdoor_temperature_c, 0)
                    * hours
                )
                observed_net = heat_delta - expected_demand
                if (
                    abs(tank_delta) >= 5
                    and abs(observed_net) >= 5
                    and tank_delta * observed_net > 0
                ):
                    self.capacity_cycles.append(CapacityCycle(tank_delta, observed_net))
                    self._evidence_revision["capacity"] += 1

    def _consume_session(self, previous: Observation | None, item: Observation) -> None:
        if item.firing_active and (previous is None or not previous.firing_active):
            self._session_start = item
        if (
            previous is not None
            and previous.firing_active
            and not item.firing_active
            and self._session_start is not None
        ):
            duration = (item.at - self._session_start.at).total_seconds() / 3600
            gain = max(item.tank_energy_kwh - self._session_start.tank_energy_kwh, 0)
            self._pending_session = (item.at, item.tank_energy_kwh, duration)
            self._session_start = replace(self._session_start, tank_energy_kwh=gain)
        if (
            self._pending_session is None
            or item.firing_active
            or self._session_start is None
        ):
            return
        stopped, stop_energy, duration = self._pending_session
        if item.at - stopped < timedelta(minutes=30):
            return
        residual = max(item.tank_energy_kwh - stop_energy, 0)
        start = self._session_start
        self._evidence_revision["session"] += 1
        self.sessions.append(
            FiringSessionSample(start.at, duration, start.tank_energy_kwh, residual)
        )
        self._pending_session = None
        self._session_start = None

    def _recalibrate(self, now: datetime) -> None:
        capacity = calibrate_capacity(
            self.capacity_cycles,
            self.config.capacity_bounds,
            configured_capacity_kwh=self.config.capacity_fallback_kwh,
            now=now,
        )
        heat_loss, balance = calibrate_demand(
            self.demand_samples,
            self.config.heat_loss_bounds,
            self.config.balance_bounds,
            now=now,
        )
        cop = calibrate_cop(self.cop_samples, self.config.cop_bounds, now=now)
        power, residual, start, duration = calibrate_firing_sessions(
            self.sessions,
            self.config.charging_power_bounds,
            self.config.residual_bounds,
            now=now,
        )
        self.parameters = {
            "usable_capacity_kwh": capacity,
            "heat_loss_coefficient_kw_per_k": heat_loss,
            "balance_temperature_c": balance,
            "cop": cop,
            "net_charging_power_kw": power,
            "residual_burn_energy_kwh": residual,
            "typical_firing_start_minute": start,
            "typical_firing_duration_min": duration,
        }

    def _fallback_parameters(self, reason: str) -> dict[str, LearnedParameter]:
        specs = {
            "usable_capacity_kwh": ("kWh", self.config.capacity_bounds),
            "heat_loss_coefficient_kw_per_k": ("kW/K", self.config.heat_loss_bounds),
            "balance_temperature_c": ("°C", self.config.balance_bounds),
            "cop": ("COP", self.config.cop_bounds),
            "net_charging_power_kw": ("kW", self.config.charging_power_bounds),
            "residual_burn_energy_kwh": ("kWh", self.config.residual_bounds),
            "typical_firing_start_minute": ("minute of day", ParameterBounds(0, 1439)),
            "typical_firing_duration_min": ("min", ParameterBounds(30, 720)),
        }
        return {
            name: _unavailable(bounds, unit, "local bounded observations", 0, reason)
            for name, (unit, bounds) in specs.items()
        }


def _robust_parameter(
    values: Iterable[float],
    bounds: ParameterBounds,
    *,
    now: datetime,
    unit: str,
    provenance: str,
    minimum_samples: int,
) -> LearnedParameter:
    clean = [float(value) for value in values if math.isfinite(value)]
    if len(clean) < minimum_samples:
        return _unavailable(
            bounds,
            unit,
            provenance,
            len(clean),
            f"insufficient clean samples (need {minimum_samples})",
        )
    median = statistics.median(clean)
    deviations = [abs(value - median) for value in clean]
    mad = statistics.median(deviations)
    tolerance = 3 * mad if mad > 0 else 1e-9
    filtered = [value for value in clean if abs(value - median) <= tolerance]
    estimate = statistics.fmean(filtered)
    bounded = bounds.clamp(estimate)
    relative_spread = mad / max(abs(median), 0.1)
    confidence = min(len(filtered) / (minimum_samples * 2), 1.0) * max(
        1 - relative_spread * 3, 0
    )
    reason = (
        "estimate reached a configured physical bound" if bounded != estimate else None
    )
    return LearnedParameter(
        bounded, unit, bounds, confidence, len(filtered), now, provenance, reason
    )


def _unavailable(
    bounds: ParameterBounds, unit: str, provenance: str, count: int, reason: str
) -> LearnedParameter:
    return LearnedParameter(None, unit, bounds, 0, count, None, provenance, reason)


def _counter_delta(before: float | None, after: float | None) -> float | None:
    if (
        before is None
        or after is None
        or not all(math.isfinite(x) for x in (before, after))
    ):
        return None
    delta = after - before
    return delta if 0 <= delta <= 100 else None


def _valid_observation(item: Observation) -> bool:
    return (
        item.at.tzinfo is not None
        and item.at.utcoffset() is not None
        and math.isfinite(item.tank_energy_kwh)
        and item.tank_energy_kwh >= 0
        and 0 <= item.data_quality <= 1
    )


def _dict_items(payload: Mapping[str, object], key: str) -> list[dict[str, Any]]:
    value = payload.get(key, [])
    if not isinstance(value, list) or len(value) > MAX_CALIBRATION_SAMPLES:
        raise ValueError("invalid bounded calibration sample list")
    if not all(isinstance(item, dict) for item in value):
        raise ValueError("invalid calibration sample")
    return value


def _aware(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("calibration timestamp must be timezone-aware")
    return parsed

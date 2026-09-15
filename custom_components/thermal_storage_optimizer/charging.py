"""Pure charging-target and live stove-session calculations."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from itertools import pairwise
from typing import Final

from .energy import WATER_ENERGY_KWH_PER_LITRE_K

_EPSILON: Final = 1e-6
_HIGH_CONFIDENCE_SLOPE_COUNT: Final = 4


class EstimateConfidence(StrEnum):
    """Human-readable quality of a charging estimate."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True, slots=True)
class ChargingTargetInput:
    """All quantities used by the deterministic energy-target calculation."""

    current_tank_energy_kwh: float
    high_cost_heat_demand_kwh: float
    intervening_discharge_kwh: float
    firing_session_heat_use_kwh: float
    storage_losses_kwh: float
    usable_capacity_kwh: float
    layer_temperatures_c: tuple[float, ...]
    layer_volumes_l: tuple[float, ...]
    maximum_layer_temperatures_c: tuple[float, ...]
    forced_use_threshold_c: float
    forced_use_margin_c: float
    residual_burn_kwh: float
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class ChargingTarget:
    """A bounded economic energy target independent of Home Assistant."""

    additional_energy_kwh: float
    fuel_phase_energy_kwh: float
    economically_useful_energy_kwh: float
    safe_remaining_capacity_kwh: float
    residual_burn_kwh: float
    confidence: float
    feasible: bool
    reason: str


@dataclass(frozen=True, slots=True)
class EnergySample:
    """One timestamped usable tank-energy observation."""

    at: datetime
    energy_kwh: float


@dataclass(frozen=True, slots=True)
class LiveChargingEstimate:
    """Guarded progress estimate for an active manual firing session."""

    energy_added_kwh: float
    smoothed_net_power_kw: float | None
    remaining_energy_kwh: float
    minimum_remaining_time: timedelta | None
    expected_completion: datetime | None
    confidence: EstimateConfidence
    residual_heat_sufficient: bool
    reason: str


def calculate_charging_target(item: ChargingTargetInput) -> ChargingTarget:
    """Calculate useful additional tank energy, capped by every safe limit."""
    _validate_target(item)
    economic_total = (
        item.high_cost_heat_demand_kwh
        + item.intervening_discharge_kwh
        + item.firing_session_heat_use_kwh
        + item.storage_losses_kwh
    )
    physical_remaining = max(item.usable_capacity_kwh - item.current_tank_energy_kwh, 0)
    layers = tuple(
        (
            current,
            volume,
            min(maximum, item.forced_use_threshold_c - item.forced_use_margin_c),
        )
        for current, volume, maximum in zip(
            item.layer_temperatures_c,
            item.layer_volumes_l,
            item.maximum_layer_temperatures_c,
            strict=True,
        )
    )
    layer_remaining = (
        0.0
        if any(current >= limit for current, _volume, limit in layers)
        else sum(
            volume * WATER_ENERGY_KWH_PER_LITRE_K * max(limit - current, 0)
            for current, volume, limit in layers
        )
    )
    safe_remaining = max(min(physical_remaining, layer_remaining), 0)
    additional = max(
        min(economic_total - item.current_tank_energy_kwh, safe_remaining), 0
    )
    residual = min(item.residual_burn_kwh, additional)
    fuel_phase = max(additional - residual, 0)
    confidence = min(max(item.confidence, 0), 1)

    if item.high_cost_heat_demand_kwh <= _EPSILON:
        reason = "No useful high-cost heat demand is forecast"
    elif economic_total <= item.current_tank_energy_kwh + _EPSILON:
        reason = "Current tank energy already covers the economic target"
    elif safe_remaining <= _EPSILON:
        reason = "No safe tank capacity remains below configured temperature limits"
    elif additional + _EPSILON < economic_total - item.current_tank_energy_kwh:
        reason = "Charge target is capped by safe remaining tank capacity"
    elif fuel_phase <= _EPSILON:
        reason = "Expected residual heat is sufficient for the target"
    else:
        reason = "Additional stored heat is economically useful and safely feasible"
    return ChargingTarget(
        additional_energy_kwh=additional,
        fuel_phase_energy_kwh=fuel_phase,
        economically_useful_energy_kwh=max(economic_total, 0),
        safe_remaining_capacity_kwh=safe_remaining,
        residual_burn_kwh=residual,
        confidence=confidence,
        feasible=additional > _EPSILON and confidence > 0,
        reason=reason,
    )


def estimate_net_charging_power(  # noqa: PLR0913
    samples: tuple[EnergySample, ...],
    *,
    previous_smoothed_power_kw: float | None,
    initial_power_kw: float,
    smoothing_factor: float = 0.35,
    noise_deadband_kwh: float = 0.05,
    maximum_sample_gap: timedelta = timedelta(minutes=30),
) -> tuple[float | None, EstimateConfidence, str]:
    """Estimate a robust session-local net slope and reject unsafe time bases."""
    if not math.isfinite(initial_power_kw) or initial_power_kw <= 0:
        initial: float | None = None
    else:
        initial = initial_power_kw
    valid_slopes: list[float] = []
    ordered = sorted(samples, key=lambda sample: sample.at.timestamp())
    for before, after in pairwise(ordered):
        seconds = (after.at - before.at).total_seconds()
        change = after.energy_kwh - before.energy_kwh
        if seconds <= 0 or seconds > maximum_sample_gap.total_seconds():
            continue
        if not math.isfinite(change) or abs(change) <= noise_deadband_kwh:
            continue
        slope = change / seconds * 3600
        if slope > 0 and math.isfinite(slope):
            valid_slopes.append(slope)

    if not valid_slopes:
        fallback = previous_smoothed_power_kw or initial
        confidence = (
            EstimateConfidence.LOW
            if fallback is not None and fallback > 0
            else EstimateConfidence.INSUFFICIENT
        )
        return fallback, confidence, "No reliable positive tank-energy slope yet"

    measured = statistics.median(valid_slopes[-5:])
    previous = previous_smoothed_power_kw or initial or measured
    smoothed = smoothing_factor * measured + (1 - smoothing_factor) * previous
    confidence = (
        EstimateConfidence.HIGH
        if len(valid_slopes) >= _HIGH_CONFIDENCE_SLOPE_COUNT
        else EstimateConfidence.MEDIUM
    )
    return smoothed, confidence, "Positive tank-energy slope measured during session"


def calculate_live_charging_estimate(  # noqa: PLR0913
    *,
    now: datetime,
    session_start_energy_kwh: float,
    current_energy_kwh: float,
    target_additional_kwh: float,
    residual_burn_kwh: float,
    samples: tuple[EnergySample, ...],
    previous_smoothed_power_kw: float | None,
    initial_power_kw: float,
    data_stale: bool = False,
) -> LiveChargingEstimate:
    """Return stable non-negative progress and time estimates for live guidance."""
    values = (
        session_start_energy_kwh,
        current_energy_kwh,
        target_additional_kwh,
        residual_burn_kwh,
    )
    if not all(math.isfinite(value) and value >= 0 for value in values):
        msg = "live charging energy values must be finite and non-negative"
        raise ValueError(msg)
    added = max(current_energy_kwh - session_start_energy_kwh, 0)
    remaining = max(target_additional_kwh - added, 0)
    power, confidence, reason = estimate_net_charging_power(
        samples,
        previous_smoothed_power_kw=previous_smoothed_power_kw,
        initial_power_kw=initial_power_kw,
    )
    residual_sufficient = remaining <= residual_burn_kwh + _EPSILON
    fuel_remaining = max(remaining - residual_burn_kwh, 0)
    duration: timedelta | None = None
    completion: datetime | None = None
    if data_stale:
        confidence = EstimateConfidence.INSUFFICIENT
        reason = "Tank-energy data is stale; time estimate withheld"
    elif fuel_remaining <= _EPSILON:
        duration = timedelta(0)
        completion = now
        reason = "Target reached or expected residual heat can complete it"
    elif power is not None and math.isfinite(power) and power > _EPSILON:
        duration = timedelta(hours=fuel_remaining / power)
        completion = now + duration
    else:
        confidence = EstimateConfidence.INSUFFICIENT
        reason = "Positive charging power is unavailable; time estimate withheld"
    return LiveChargingEstimate(
        energy_added_kwh=added,
        smoothed_net_power_kw=power,
        remaining_energy_kwh=remaining,
        minimum_remaining_time=duration,
        expected_completion=completion,
        confidence=confidence,
        residual_heat_sufficient=residual_sufficient,
        reason=reason,
    )


def detect_active_firing(  # noqa: PLR0913
    *,
    pump_active: bool | None,
    stove_temperature_c: float | None,
    stove_temperature_threshold_c: float,
    net_energy_slope_kw: float | None,
    slope_threshold_kw: float,
    manual_active: bool,
) -> bool:
    """Combine independent configured indications of a manual stove session."""
    return bool(
        manual_active
        or pump_active is True
        or (
            stove_temperature_c is not None
            and math.isfinite(stove_temperature_c)
            and stove_temperature_c >= stove_temperature_threshold_c
        )
        or (
            net_energy_slope_kw is not None
            and math.isfinite(net_energy_slope_kw)
            and net_energy_slope_kw >= slope_threshold_kw
        )
    )


def _validate_target(item: ChargingTargetInput) -> None:
    values = (
        item.current_tank_energy_kwh,
        item.high_cost_heat_demand_kwh,
        item.intervening_discharge_kwh,
        item.firing_session_heat_use_kwh,
        item.storage_losses_kwh,
        item.usable_capacity_kwh,
        item.forced_use_threshold_c,
        item.forced_use_margin_c,
        item.residual_burn_kwh,
        item.confidence,
        *item.layer_temperatures_c,
        *item.layer_volumes_l,
        *item.maximum_layer_temperatures_c,
    )
    if not all(math.isfinite(value) for value in values):
        msg = "charging-target inputs must be finite"
        raise ValueError(msg)
    energy_values = (
        item.current_tank_energy_kwh,
        item.high_cost_heat_demand_kwh,
        item.intervening_discharge_kwh,
        item.firing_session_heat_use_kwh,
        item.storage_losses_kwh,
        item.residual_burn_kwh,
    )
    if any(value < 0 for value in energy_values) or item.usable_capacity_kwh <= 0:
        msg = "charging-target energy and capacity values must be non-negative"
        raise ValueError(msg)
    if item.forced_use_margin_c < 0:
        msg = "forced-use margin must be non-negative"
        raise ValueError(msg)
    if not (
        len(item.layer_temperatures_c)
        == len(item.layer_volumes_l)
        == len(item.maximum_layer_temperatures_c)
        > 0
    ):
        msg = "layer temperatures, volumes, and limits must have equal lengths"
        raise ValueError(msg)
    if any(volume <= 0 for volume in item.layer_volumes_l):
        msg = "layer volumes must be positive"
        raise ValueError(msg)

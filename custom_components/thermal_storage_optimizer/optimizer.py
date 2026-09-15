"""Explainable deterministic greedy thermal-energy allocation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from .forecast import EconomicForecastInterval

_ALLOCATION_EPSILON: Final = 1e-9
_REMAINING_EPSILON: Final = 1e-12


class Recommendation(StrEnum):
    """Dry-run recommendation for the currently active interval."""

    USE_TANK = "use_tank"
    RESERVE_TANK = "reserve_tank"
    WAITING = "waiting"


@dataclass(frozen=True, slots=True)
class PlannedInterval:
    """One explainable interval allocation."""

    forecast: EconomicForecastInterval
    allocated_energy_kwh: float
    expected_savings: float

    @property
    def release_start(self) -> datetime:
        """Start a bounded, end-aligned binary discharge window."""
        fraction = (
            min(self.allocated_energy_kwh / self.forecast.heat_demand_kwh, 1)
            if self.forecast.heat_demand_kwh > 0
            else 0
        )
        return self.forecast.end - self.forecast.duration * fraction


@dataclass(frozen=True, slots=True)
class OptimizationPlan:
    """Immutable optimizer output safe to persist."""

    publication_key: str
    optimized_at: datetime
    forecast_end: datetime
    available_energy_kwh: float
    retained_beyond_horizon_kwh: float
    expected_savings: float
    intervals: tuple[PlannedInterval, ...]
    reserve_until: datetime | None = None

    def recommendation_at(self, now: datetime) -> Recommendation:
        """Return the allocation decision for the current instant."""
        for period in self.intervals:
            if (
                period.forecast.start.timestamp()
                <= now.timestamp()
                < period.forecast.end.timestamp()
            ):
                if (
                    period.allocated_energy_kwh > _ALLOCATION_EPSILON
                    and now >= period.release_start
                ):
                    return Recommendation.USE_TANK
                return Recommendation.RESERVE_TANK
        return Recommendation.WAITING

    def reserve_floor_at(self, now: datetime) -> float:
        """Protect energy committed to later intervals and horizon continuation."""
        stored = self.retained_beyond_horizon_kwh + sum(
            p.allocated_energy_kwh / p.forecast.retention
            for p in self.intervals
            if p.forecast.start > now
        )
        first = self.intervals[0].forecast
        horizon = (first.end - self.optimized_at).total_seconds()
        elapsed = max((now - self.optimized_at).total_seconds(), 0)
        retention = first.retention ** (elapsed / horizon) if horizon > 0 else 1
        return stored * retention

    def next_release_at(self, now: datetime) -> datetime | None:
        """Return the next allocated interval start."""
        for period in self.intervals:
            if (
                period.forecast.end.timestamp() > now.timestamp()
                and period.allocated_energy_kwh > _ALLOCATION_EPSILON
            ):
                return period.release_start
        return None

    def decision_reason_at(self, now: datetime) -> str:
        """Explain the current dry-run decision with bounded economic detail."""
        for period in self.intervals:
            if (
                period.forecast.start.timestamp()
                <= now.timestamp()
                < period.forecast.end.timestamp()
            ):
                if (
                    period.allocated_energy_kwh > _ALLOCATION_EPSILON
                    and now >= period.release_start
                ):
                    value = period.forecast.adjusted_value_per_kwh
                    return (
                        f"Use tank: {period.allocated_energy_kwh:.2f} kWh allocated "
                        f"at adjusted value {value:.3f}"
                    )
                next_release = self.next_release_at(now)
                if next_release is not None:
                    release_time = next_release.isoformat()
                    return f"Reserve tank for higher-value interval at {release_time}"
                return "Reserve tank: no known interval clears the economic deadband"
        return "No priced current interval; preserve the saved allocation"


def optimize_plan(  # noqa: C901, PLR0913
    intervals: tuple[EconomicForecastInterval, ...],
    *,
    publication_key: str,
    optimized_at: datetime,
    available_energy_kwh: float,
    economic_deadband_per_kwh: float,
    reserve_until: datetime | None = None,
    minimum_dwell_seconds: float = 0,
    current_release_active: bool = False,
) -> OptimizationPlan:
    """Allocate energy to highest adjusted avoided-cost periods.

    The deadband creates a conservative horizon continuation value: intervals
    whose adjusted value is not materially above the cheapest known opportunity
    do not consume storage merely because the provider's forecast ends.
    """
    if optimized_at.tzinfo is None or optimized_at.utcoffset() is None:
        msg = "optimization timestamp must be timezone-aware"
        raise ValueError(msg)
    if not math.isfinite(available_energy_kwh) or available_energy_kwh < 0:
        msg = "available energy must be finite and non-negative"
        raise ValueError(msg)
    if not math.isfinite(economic_deadband_per_kwh) or economic_deadband_per_kwh < 0:
        msg = "economic deadband must be finite and non-negative"
        raise ValueError(msg)
    if not intervals:
        msg = "cannot optimize an empty forecast"
        raise ValueError(msg)

    reserve_until = reserve_until or optimized_at + timedelta(hours=24)
    baseline = min(period.adjusted_value_per_kwh for period in intervals)
    eligible = [
        (index, period)
        for index, period in enumerate(intervals)
        if period.adjusted_value_per_kwh > 0
        and (
            period.adjusted_value_per_kwh >= baseline + economic_deadband_per_kwh
            or period.start >= reserve_until
        )
    ]
    eligible.sort(key=lambda item: (-item[1].adjusted_value_per_kwh, item[1].start))
    remaining = available_energy_kwh
    allocations = [0.0] * len(intervals)
    for index, period in eligible:
        allocation = min(remaining * period.retention, period.heat_demand_kwh)
        release_seconds = (
            period.duration.total_seconds() * allocation / period.heat_demand_kwh
            if period.heat_demand_kwh > 0
            else 0
        )
        continuing = (
            current_release_active and period.start <= optimized_at < period.end
        )
        if release_seconds < minimum_dwell_seconds and not continuing:
            continue
        allocations[index] = allocation
        remaining -= allocation / period.retention
        if remaining <= _REMAINING_EPSILON:
            break
    # Separate non-contiguous releases by at least the actuator's reserve dwell.
    next_start: datetime | None = None
    for index in range(len(intervals) - 1, -1, -1):
        period = intervals[index]
        if allocations[index] <= _ALLOCATION_EPSILON:
            continue
        release = PlannedInterval(period, allocations[index], 0)
        if (
            next_start is not None
            and 0 < (next_start - period.end).total_seconds() < minimum_dwell_seconds
        ):
            remaining += allocations[index] / period.retention
            allocations[index] = 0
        else:
            next_start = release.release_start
    planned = tuple(
        PlannedInterval(
            period,
            allocations[index],
            allocations[index] * period.avoided_heat_cost_per_kwh * period.confidence,
        )
        for index, period in enumerate(intervals)
    )
    return OptimizationPlan(
        publication_key=publication_key,
        optimized_at=optimized_at,
        forecast_end=max(intervals, key=lambda period: period.end.timestamp()).end,
        available_energy_kwh=available_energy_kwh,
        retained_beyond_horizon_kwh=max(remaining, 0.0),
        expected_savings=sum(period.expected_savings for period in planned),
        intervals=planned,
        reserve_until=reserve_until,
    )

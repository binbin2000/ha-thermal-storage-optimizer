"""Explainable deterministic greedy thermal-energy allocation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from enum import StrEnum
from itertools import pairwise
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

    def decision_reason_at(
        self, now: datetime, *, local_timezone: tzinfo | None = None
    ) -> str:
        """Explain the current dry-run decision with bounded economic detail.

        Times are shown in ``local_timezone`` (the timezone of ``now`` when
        omitted) and rounded up to the whole minute, so the text is readable,
        never names a moment that has already passed, and does not change on
        every replan.
        """
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
                    release_time = _local_minute_text(next_release, now, local_timezone)
                    return f"Reserve tank for higher-value interval at {release_time}"
                return "Reserve tank: no known interval clears the economic deadband"
        return "No priced current interval; preserve the saved allocation"


def _local_minute_text(
    instant: datetime, now: datetime, local_timezone: tzinfo | None
) -> str:
    """Format a time in local time, rounded up to the minute.

    The date is included only when it differs from the local date of ``now``.
    """
    zone = local_timezone or now.tzinfo
    local = instant.astimezone(zone)
    if local.second or local.microsecond:
        local = local.replace(second=0, microsecond=0) + timedelta(minutes=1)
    if local.date() == now.astimezone(zone).date():
        return local.strftime("%H:%M")
    return local.strftime("%Y-%m-%d %H:%M")


def optimize_plan(  # noqa: PLR0913
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
    continuing_index = next(
        (
            index
            for index, period in enumerate(intervals)
            if current_release_active and period.start <= optimized_at < period.end
        ),
        None,
    )
    # Minimum dwell applies to contiguous release runs, not single price periods:
    # 15-minute market resolution must still allow a two-hour release. Periods
    # that cannot be realized are excluded and the allocation is repeated until
    # every remaining run is deliverable through the binary actuator.
    excluded: set[int] = set()
    eligible_indices = {index for index, _ in eligible}
    while True:
        allocations, remaining = _allocate(
            intervals, eligible, available_energy_kwh, excluded
        )
        _repair_chains(intervals, allocations, minimum_dwell_seconds, continuing_index)
        unrealizable = _unrealizable_periods(
            intervals,
            allocations,
            minimum_dwell_seconds,
            continuing_index,
            candidates=eligible_indices - excluded,
        )
        if not unrealizable:
            break
        excluded.update(unrealizable)
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


def _allocate(
    intervals: tuple[EconomicForecastInterval, ...],
    eligible: list[tuple[int, EconomicForecastInterval]],
    available_energy_kwh: float,
    excluded: set[int],
) -> tuple[list[float], float]:
    """Greedily fill the highest-value periods that remain allowed."""
    remaining = available_energy_kwh
    allocations = [0.0] * len(intervals)
    for index, period in eligible:
        if index in excluded:
            continue
        allocation = min(remaining * period.retention, period.heat_demand_kwh)
        if allocation <= _ALLOCATION_EPSILON:
            continue
        allocations[index] = allocation
        remaining -= allocation / period.retention
        if remaining <= _REMAINING_EPSILON:
            break
    return allocations, remaining


def _release_seconds(period: EconomicForecastInterval, allocation: float) -> float:
    return (
        period.duration.total_seconds() * min(allocation / period.heat_demand_kwh, 1)
        if period.heat_demand_kwh > 0
        else 0.0
    )


def _chains(
    intervals: tuple[EconomicForecastInterval, ...], allocations: list[float]
) -> list[list[int]]:
    """Group allocated periods that follow each other without a time gap."""
    chains: list[list[int]] = []
    for index, allocation in enumerate(allocations):
        if allocation <= _ALLOCATION_EPSILON:
            continue
        if (
            chains
            and intervals[index].start.timestamp()
            == intervals[chains[-1][-1]].end.timestamp()
        ):
            chains[-1].append(index)
        else:
            chains.append([index])
    return chains


def _runs(
    intervals: tuple[EconomicForecastInterval, ...],
    allocations: list[float],
    chain: list[int],
) -> list[list[int]]:
    """Split a chain into runs whose binary release windows touch.

    Partial releases are end-aligned, so only the first period of a run may be
    partially allocated; a later partial period starts a new run after a gap.
    """
    runs: list[list[int]] = [[chain[0]]]
    for index in chain[1:]:
        period = intervals[index]
        if allocations[index] >= period.heat_demand_kwh - _ALLOCATION_EPSILON:
            runs[-1].append(index)
        else:
            runs.append([index])
    return runs


def _run_seconds(
    intervals: tuple[EconomicForecastInterval, ...],
    allocations: list[float],
    run: list[int],
) -> float:
    return sum(_release_seconds(intervals[i], allocations[i]) for i in run)


def _gap_seconds(
    intervals: tuple[EconomicForecastInterval, ...],
    allocations: list[float],
    run: list[int],
    next_run: list[int],
) -> float:
    """Return the reserve time between one run's end and the next release."""
    next_release = PlannedInterval(
        intervals[next_run[0]], allocations[next_run[0]], 0
    ).release_start
    return (next_release - intervals[run[-1]].end).total_seconds()


def _gap_victim(  # noqa: PLR0913, PLR0917
    intervals: tuple[EconomicForecastInterval, ...],
    allocations: list[float],
    run: list[int],
    next_run: list[int],
    minimum_dwell_seconds: float,
    continuing_index: int | None,
) -> list[int] | None:
    """Return the run to give up when the reserve gap between two is too short."""
    gap = _gap_seconds(intervals, allocations, run, next_run)
    if not 0 < gap < minimum_dwell_seconds:
        return None
    if continuing_index in run:
        return next_run
    if continuing_index in next_run:
        return run
    return min(
        (run, next_run), key=lambda item: _run_seconds(intervals, allocations, item)
    )


def _violating_runs(
    intervals: tuple[EconomicForecastInterval, ...],
    allocations: list[float],
    runs: list[list[int]],
    minimum_dwell_seconds: float,
    continuing_index: int | None,
) -> list[list[int]]:
    """Return runs that are too short, or the smaller side of a too-short gap."""
    violating: list[list[int]] = [
        run
        for run in runs
        if _run_seconds(intervals, allocations, run) < minimum_dwell_seconds
        and continuing_index not in run
    ]
    for run, next_run in pairwise(runs):
        victim = _gap_victim(
            intervals,
            allocations,
            run,
            next_run,
            minimum_dwell_seconds,
            continuing_index,
        )
        if victim is not None and victim not in violating:
            violating.append(victim)
    return violating


def _repair_chains(
    intervals: tuple[EconomicForecastInterval, ...],
    allocations: list[float],
    minimum_dwell_seconds: float,
    continuing_index: int | None,
) -> None:
    """Re-lay a chain into one contiguous window when that beats dropping runs.

    The greedy fill leaves its partial period at the chain's lowest-value end,
    which can split the chain into a run and a short tail. Laying the chain's
    stored energy out from its last period backwards puts the partial release
    at the front, where it touches the following full periods. A chain holding
    the release already in progress is laid out forwards so it is never cut.
    The re-lay is applied only when it removes every violation in the chain and
    keeps at least the value that dropping the violating runs would keep.
    """
    for chain in _chains(intervals, allocations):
        runs = _runs(intervals, allocations, chain)
        violating = _violating_runs(
            intervals, allocations, runs, minimum_dwell_seconds, continuing_index
        )
        if not violating:
            continue
        relaid = list(allocations)
        stored = sum(relaid[i] / intervals[i].retention for i in chain)
        order = chain if continuing_index in chain else list(reversed(chain))
        for index in order:
            period = intervals[index]
            allocation = min(period.heat_demand_kwh, stored * period.retention)
            relaid[index] = allocation if allocation > _ALLOCATION_EPSILON else 0.0
            stored = max(stored - relaid[index] / period.retention, 0.0)
        relaid_chain = [i for i in chain if relaid[i] > _ALLOCATION_EPSILON]
        if not relaid_chain or _violating_runs(
            intervals,
            relaid,
            _runs(intervals, relaid, relaid_chain),
            minimum_dwell_seconds,
            continuing_index,
        ):
            continue
        dropped = {i for run in violating for i in run}
        kept_value = sum(
            allocations[i] * intervals[i].adjusted_value_per_kwh
            for i in chain
            if i not in dropped
        )
        relaid_value = sum(
            relaid[i] * intervals[i].adjusted_value_per_kwh for i in chain
        )
        if relaid_value >= kept_value - _ALLOCATION_EPSILON:
            for index in chain:
                allocations[index] = relaid[index]


def _unrealizable_periods(
    intervals: tuple[EconomicForecastInterval, ...],
    allocations: list[float],
    minimum_dwell_seconds: float,
    continuing_index: int | None,
    *,
    candidates: set[int],
) -> set[int]:
    """Return the next allocated periods whose release cannot honour the dwell.

    Only one run is dropped per call, because freeing its energy often lengthens
    another run. Runs whose whole block of consecutive eligible periods could
    never reach the dwell are dropped first, then the shortest release, so a
    lone high-priced quarter hour yields to a broad peak rather than starving it.
    """
    violating: list[list[int]] = []
    for chain in _chains(intervals, allocations):
        violating.extend(
            _violating_runs(
                intervals,
                allocations,
                _runs(intervals, allocations, chain),
                minimum_dwell_seconds,
                continuing_index,
            )
        )
    for chain, next_chain in pairwise(_chains(intervals, allocations)):
        victim = _gap_victim(
            intervals,
            allocations,
            _runs(intervals, allocations, chain)[-1],
            _runs(intervals, allocations, next_chain)[0],
            minimum_dwell_seconds,
            continuing_index,
        )
        if victim is not None and victim not in violating:
            violating.append(victim)
    if not violating:
        return set()

    def block_potential(run: list[int]) -> float:
        """Return the release time the run's eligible block could ever reach."""
        first, last = run[0], run[-1]
        while first - 1 in candidates and (
            intervals[first - 1].end.timestamp() == intervals[first].start.timestamp()
        ):
            first -= 1
        while last + 1 in candidates and (
            intervals[last + 1].start.timestamp() == intervals[last].end.timestamp()
        ):
            last += 1
        return sum(
            intervals[i].duration.total_seconds()
            for i in range(first, last + 1)
            if intervals[i].heat_demand_kwh > 0
        )

    chosen = min(
        violating,
        key=lambda run: (
            block_potential(run) >= minimum_dwell_seconds,
            _run_seconds(intervals, allocations, run),
            run[0],
        ),
    )
    return set(chosen)

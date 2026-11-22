"""Choosing when a manual firing session must be complete."""

from datetime import timedelta

from custom_components.thermal_storage_optimizer.advisor import _firing_deadline
from custom_components.thermal_storage_optimizer.optimizer import PlannedInterval

from .test_optimizer import NOW, economic


def _planned(start_hours: float, value: float, demand: float = 2.0) -> PlannedInterval:
    return PlannedInterval(economic(start_hours, 1, value, demand), 0, 0)


def _hourly(values: list[float], *, offset: float = -0.5) -> list[PlannedInterval]:
    return [_planned(offset + index, value) for index, value in enumerate(values)]


def test_deadline_precedes_later_peak_when_valuable_periods_are_ongoing() -> None:
    """An ongoing valuable period must not push the deadline past every peak."""
    # Moderate prices now and overnight, a morning bump, an evening peak.
    values = [1.5] * 7 + [1.2] * 9 + [1.8] * 3 + [1.4] * 6 + [2.1] * 5 + [1.3] * 2
    periods = _hourly(values)
    deadline, served = _firing_deadline(
        periods,
        NOW,
        capacity_kwh=10,
        minimum_lead=timedelta(minutes=30),
        horizon_end=periods[-1].forecast.end,
    )
    peak_start = next(
        p.forecast.start for p in periods if p.forecast.avoided_heat_cost_per_kwh == 2.1
    )
    assert deadline == peak_start
    assert all(p.forecast.start >= deadline for p in served)
    assert len(served) < len(periods)


def test_larger_tank_moves_deadline_before_secondary_peak() -> None:
    """Capacity for both peaks completes the session before the first one."""
    values = [1.5] * 7 + [1.2] * 9 + [1.8] * 3 + [1.4] * 6 + [2.1] * 5 + [1.3] * 2
    periods = _hourly(values)
    deadline, _ = _firing_deadline(
        periods,
        NOW,
        capacity_kwh=16,
        minimum_lead=timedelta(minutes=30),
        horizon_end=periods[-1].forecast.end,
    )
    morning_start = next(
        p.forecast.start for p in periods if p.forecast.avoided_heat_cost_per_kwh == 1.8
    )
    assert deadline == morning_start


def test_deadline_falls_back_without_reachable_periods() -> None:
    """Without a reachable valuable period the earliest valuable start is used."""
    periods = [_planned(-0.5, 2.0)]
    deadline, served = _firing_deadline(
        periods,
        NOW,
        capacity_kwh=10,
        minimum_lead=timedelta(hours=1),
        horizon_end=NOW + timedelta(days=1),
    )
    assert deadline == periods[0].forecast.start
    assert served == periods
    end = NOW + timedelta(days=1)
    assert _firing_deadline(
        [], NOW, capacity_kwh=10, minimum_lead=timedelta(0), horizon_end=end
    ) == (end, [])

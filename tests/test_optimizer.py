"""Pure tests for forecast enrichment and explainable greedy allocation."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.thermal_storage_optimizer.controller import (
    ControllerConfig,
    ControllerInput,
    ControllerStateMachine,
    UserMode,
)
from custom_components.thermal_storage_optimizer.cop import FixedCopModel
from custom_components.thermal_storage_optimizer.demand import HeatDemandConfig
from custom_components.thermal_storage_optimizer.forecast import (
    EconomicForecastInterval,
    ForecastModelConfig,
    build_economic_forecast,
)
from custom_components.thermal_storage_optimizer.optimizer import (
    Recommendation,
    optimize_plan,
)
from custom_components.thermal_storage_optimizer.price import (
    PriceNormalizationConfig,
    normalize_price_forecast,
)

NOW = datetime(2026, 9, 7, 11, tzinfo=UTC)
FIXED_COP = 3.0
EXPECTED_RETAINED_KWH = 8.0


def economic(
    start_hours: float, duration_hours: float, value: float, demand: float
) -> EconomicForecastInterval:
    """Build a compact optimizer input."""
    start = NOW + timedelta(hours=start_hours)
    duration = timedelta(hours=duration_hours)
    return EconomicForecastInterval(
        start=start,
        end=start + duration,
        duration=duration,
        electricity_cost_per_kwh=value * 3,
        outdoor_temperature_c=0,
        heat_demand_kwh=demand,
        cop=3,
        avoided_heat_cost_per_kwh=value,
        retention=1,
        confidence=1,
        adjusted_value_per_kwh=value,
    )


def test_forecast_uses_duration_demand_cop_retention_and_confidence() -> None:
    """Enrichment uses interval duration and all economic adjustments."""
    prices = normalize_price_forecast(
        [
            {
                "start": NOW.isoformat(),
                "end": (NOW + timedelta(minutes=30)).isoformat(),
                "price": 1.2,
            }
        ],
        unit="SEK/kWh",
        source_token="one",
        config=PriceNormalizationConfig(),
    )
    result = build_economic_forecast(
        prices,
        now=NOW,
        outdoor_temperature_c=7,
        supply_temperature_c=40,
        measured_cop=None,
        cop_model=FixedCopModel(FIXED_COP),
        demand_config=HeatDemandConfig(0.25, 17),
        model_config=ForecastModelConfig(0.99, 0.8),
    )
    assert result[0].heat_demand_kwh == pytest.approx(1.25)
    assert result[0].cop == FIXED_COP
    assert result[0].avoided_heat_cost_per_kwh == pytest.approx(0.4)
    assert result[0].adjusted_value_per_kwh == pytest.approx(0.32 * 0.99**0.5)


def test_greedy_allocation_is_deterministic_and_value_ranked() -> None:
    """Highest-value demand receives finite tank energy first with stable tie order."""
    intervals = (economic(0, 1, 0.3, 2), economic(1, 1, 1.2, 3), economic(2, 1, 0.8, 3))
    first = optimize_plan(
        intervals,
        publication_key="p",
        optimized_at=NOW,
        available_energy_kwh=4,
        economic_deadband_per_kwh=0.1,
    )
    second = optimize_plan(
        intervals,
        publication_key="p",
        optimized_at=NOW,
        available_energy_kwh=4,
        economic_deadband_per_kwh=0.1,
    )
    assert first == second
    assert [period.allocated_energy_kwh for period in first.intervals] == [0, 3, 1]
    assert first.recommendation_at(NOW) is Recommendation.RESERVE_TANK
    assert first.next_release_at(NOW) == NOW + timedelta(hours=1)
    assert "higher-value interval" in first.decision_reason_at(NOW)


def test_deadband_preserves_energy_at_short_horizon() -> None:
    """A flat/short forecast is not interpreted as an instruction to empty storage."""
    plan = optimize_plan(
        (economic(0, 1, 0.5, 10),),
        publication_key="short",
        optimized_at=NOW,
        available_energy_kwh=8,
        economic_deadband_per_kwh=0.05,
    )
    assert plan.intervals[0].allocated_energy_kwh == 0
    assert plan.retained_beyond_horizon_kwh == EXPECTED_RETAINED_KWH
    assert plan.recommendation_at(NOW) is Recommendation.RESERVE_TANK


def test_forecast_gap_returns_waiting_not_forced_release() -> None:
    """Missing current values do not turn a horizon gap into tank use."""
    plan = optimize_plan(
        (economic(2, 1, 1.0, 2), economic(4, 1, 0.2, 2)),
        publication_key="gap",
        optimized_at=NOW,
        available_energy_kwh=1,
        economic_deadband_per_kwh=0.05,
    )
    assert plan.recommendation_at(NOW) is Recommendation.WAITING
    assert plan.next_release_at(NOW) == NOW + timedelta(hours=2.5)


@pytest.mark.parametrize("values", [(-1, -0.2), (-0.01, 0, 0.01)])
def test_non_positive_avoided_cost_never_releases(values: tuple[float, ...]) -> None:
    """Even expired continuation never spends heat at non-positive value."""
    plan = optimize_plan(
        tuple(economic(i, 1, v, 5) for i, v in enumerate(values)),
        publication_key="negative",
        optimized_at=NOW,
        available_energy_kwh=10,
        economic_deadband_per_kwh=0.05,
        reserve_until=NOW,
    )
    assert plan.expected_savings >= 0
    assert all(
        p.allocated_energy_kwh == 0
        for p in plan.intervals
        if p.forecast.avoided_heat_cost_per_kwh <= 0
    )


def test_losses_limit_delivered_energy() -> None:
    """Ten stored kWh can deliver only five after fifty percent retention."""
    future = replace(economic(1, 1, 2, 10), retention=0.5, adjusted_value_per_kwh=1)
    plan = optimize_plan(
        (economic(0, 1, 0.1, 5), future),
        publication_key="loss",
        optimized_at=NOW,
        available_energy_kwh=10,
        economic_deadband_per_kwh=0.05,
    )
    assert plan.intervals[1].allocated_energy_kwh == 5
    assert (
        sum(p.allocated_energy_kwh / p.forecast.retention for p in plan.intervals) <= 10
    )
    assert plan.expected_savings == 10


def test_binary_closed_loop_preserves_later_allocation() -> None:
    """Chronological binary use delivers one early kWh and all three later kWh."""
    plan = optimize_plan(
        (economic(0, 1, 1, 5), economic(1, 1, 3, 3), economic(2, 1, 0.1, 5)),
        publication_key="dispatch",
        optimized_at=NOW,
        available_energy_kwh=4,
        economic_deadband_per_kwh=0.05,
        minimum_dwell_seconds=300,
    )
    assert [p.allocated_energy_kwh for p in plan.intervals] == [1, 3, 0]
    tank = 4.0
    delivered = [0.0, 0.0, 0.0]
    for minute in range(180):
        now = NOW + timedelta(minutes=minute)
        if plan.recommendation_at(now) is Recommendation.USE_TANK:
            index = minute // 60
            discharge = plan.intervals[index].forecast.heat_demand_kwh / 60
            tank -= discharge
            delivered[index] += discharge
        assert tank >= -1e-9
        if minute == 59:
            assert tank == pytest.approx(3)
    assert delivered == pytest.approx([1, 3, 0])
    assert tank == pytest.approx(0)


def test_dispatch_rejects_release_shorter_than_dwell() -> None:
    """A one-minute release cannot be realized with five-minute minimum dwell."""
    plan = optimize_plan(
        (economic(0, 1, 1, 6), economic(1, 1, 0.1, 1)),
        publication_key="dwell",
        optimized_at=NOW,
        available_energy_kwh=0.1,
        economic_deadband_per_kwh=0.05,
        minimum_dwell_seconds=300,
    )
    assert all(p.allocated_energy_kwh == 0 for p in plan.intervals)


def test_flat_publications_keep_original_reservation_deadline() -> None:
    """Repeated short publications eventually use heat at positive flat prices."""
    deadline = None
    energy = 4.0
    for hour in range(27):
        plan = optimize_plan(
            (economic(hour, 1, 0.5, 2),),
            publication_key=str(hour),
            optimized_at=NOW + timedelta(hours=hour),
            available_energy_kwh=energy,
            economic_deadband_per_kwh=0.05,
            reserve_until=deadline,
        )
        deadline = plan.reserve_until
        energy -= plan.intervals[0].allocated_energy_kwh
    assert deadline == NOW + timedelta(hours=24)
    assert energy == 0


def test_rolling_binary_controller_conserves_heat_with_losses() -> None:
    """Replan every minute while a binary controller discharges a lossy tank."""
    source = (economic(0, 1, 1, 5), economic(1, 1, 3, 3), economic(2, 1, 0.1, 5))
    tank = 4.0
    later_delivered = 0.0
    machine = ControllerStateMachine(
        ControllerConfig(
            active_control=True,
            startup_grace=timedelta(0),
            minimum_dwell=timedelta(minutes=5),
        ),
        started_at=NOW - timedelta(hours=1),
    )
    releasing = False
    plan = None
    for second in range(7200):
        now = NOW + timedelta(seconds=second)
        if second % 60 == 0:
            forecast = []
            for period in source:
                start = max(now, period.start)
                if start >= period.end:
                    continue
                retention = 0.99 ** ((period.end - now).total_seconds() / 3600)
                forecast.append(
                    replace(
                        period,
                        start=start,
                        duration=period.end - start,
                        heat_demand_kwh=period.heat_demand_kwh
                        * (period.end - start)
                        / period.duration,
                        retention=retention,
                        adjusted_value_per_kwh=period.avoided_heat_cost_per_kwh
                        * retention,
                    )
                )
            plan = optimize_plan(
                tuple(forecast),
                publication_key="rolling",
                optimized_at=now,
                available_energy_kwh=tank,
                economic_deadband_per_kwh=0.05,
                minimum_dwell_seconds=300,
                current_release_active=releasing,
            )
        assert plan is not None
        decision = machine.evaluate(
            ControllerInput(
                now=now,
                mode=UserMode.AUTO,
                required_inputs_valid=True,
                has_ever_had_valid_inputs=True,
                plan_valid=True,
                has_ever_had_valid_plan=True,
                recommendation=plan.recommendation_at(now),
                usable_energy_kwh=tank,
                tank_temperatures_c=(60, 50, 40),
                budget_exhausted=tank <= plan.reserve_floor_at(now) + 1e-6,
            )
        )
        releasing = not decision.reserve_requested
        discharge = source[second // 3600].heat_demand_kwh / 3600 if releasing else 0
        tank = tank * 0.99 ** (1 / 3600) - discharge
        assert tank >= -1e-6
        if second >= 3600:
            later_delivered += discharge
    assert later_delivered == pytest.approx(3, abs=0.02)

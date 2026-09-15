"""Multi-day synthetic field scenarios for Milestone 7 commissioning readiness."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.thermal_storage_optimizer.charging import (
    ChargingTargetInput,
    EnergySample,
    calculate_charging_target,
    calculate_live_charging_estimate,
)
from custom_components.thermal_storage_optimizer.controller import (
    ControllerConfig,
    ControllerInput,
    ControllerStateMachine,
    OperatingState,
    UserMode,
)
from custom_components.thermal_storage_optimizer.demand import (
    HeatDemandConfig,
    estimate_heat_demand_kwh,
)
from custom_components.thermal_storage_optimizer.energy import (
    TankTemperatures,
    ThermalEnergyConfig,
    estimate_thermal_state,
)
from custom_components.thermal_storage_optimizer.firing_schedule import (
    FiringScheduleInput,
    default_preferred_windows,
    schedule_firing,
)
from custom_components.thermal_storage_optimizer.forecast import (
    EconomicForecastInterval,
)
from custom_components.thermal_storage_optimizer.optimizer import (
    Recommendation,
    optimize_plan,
)
from custom_components.thermal_storage_optimizer.price import (
    PriceForecastError,
    PriceNormalizationConfig,
    normalize_price_forecast,
)

START = datetime(2026, 1, 12, tzinfo=UTC)


def _three_day_forecast(
    prices: tuple[float, ...], outdoors: tuple[float, ...]
) -> tuple[EconomicForecastInterval, ...]:
    """Build an explicit 72-hour price/weather scenario."""
    demand_config = HeatDemandConfig(0.3, 17)
    result: list[EconomicForecastInterval] = []
    for hour in range(72):
        price = prices[hour % len(prices)]
        outdoor = outdoors[hour % len(outdoors)]
        demand = estimate_heat_demand_kwh(outdoor, timedelta(hours=1), demand_config)
        cop = 3.0
        adjusted = price / cop * 0.85
        result.append(
            EconomicForecastInterval(
                start=START + timedelta(hours=hour),
                end=START + timedelta(hours=hour + 1),
                duration=timedelta(hours=1),
                electricity_cost_per_kwh=price,
                outdoor_temperature_c=outdoor,
                heat_demand_kwh=demand,
                cop=cop,
                avoided_heat_cost_per_kwh=price / cop,
                retention=1.0,
                confidence=0.85,
                adjusted_value_per_kwh=adjusted,
            )
        )
    return tuple(result)


@pytest.mark.parametrize(
    ("prices", "expect_release"),
    [
        ((0.15,), True),
        ((0.8,), True),
        ((0.2, 0.2, 3.5, 0.2), True),
        ((-0.5, -0.1, 2.8, 0.1), True),
    ],
    ids=("low", "flat", "high-spikes", "negative-and-positive"),
)
def test_three_day_price_and_weather_dispatch(
    prices: tuple[float, ...], *, expect_release: bool
) -> None:
    """Low/flat/high/negative prices stay deterministic across weather changes."""
    forecast = _three_day_forecast(prices, (-8.0, -2.0, 8.0, 14.0))
    plan = optimize_plan(
        forecast,
        publication_key="three-day-field-simulation",
        optimized_at=START,
        available_energy_kwh=18,
        economic_deadband_per_kwh=0.05,
    )
    allocated = [item for item in plan.intervals if item.allocated_energy_kwh > 0]
    assert bool(allocated) is expect_release
    assert all(item.forecast.electricity_cost_per_kwh >= 0 for item in allocated)
    assert all(item.expected_savings >= 0 for item in plan.intervals)
    cold = forecast[0].heat_demand_kwh
    mild = forecast[3].heat_demand_kwh
    assert cold > mild >= 0


def test_three_day_stratification_stove_target_and_firing_progress() -> None:
    """Tank layers and a supervised stove session remain bounded over three days."""
    config = ThermalEnergyConfig(500, (200, 175, 125), 3, 30)
    day_states = [
        estimate_thermal_state(
            TankTemperatures(*temperatures, 30, 45),
            config,
        )
        for temperatures in ((65, 50, 35), (55, 55, 45), (72, 63, 54))
    ]
    assert day_states[0].stratification_delta_c == 30
    assert day_states[1].usable_energy_kwh is not None
    assert day_states[2].usable_energy_kwh > day_states[1].usable_energy_kwh  # type: ignore[operator]

    target = calculate_charging_target(
        ChargingTargetInput(
            current_tank_energy_kwh=day_states[1].usable_energy_kwh or 0,
            high_cost_heat_demand_kwh=28,
            intervening_discharge_kwh=2,
            firing_session_heat_use_kwh=1,
            storage_losses_kwh=1,
            usable_capacity_kwh=30,
            layer_temperatures_c=(55, 55, 45),
            layer_volumes_l=(200, 175, 125),
            maximum_layer_temperatures_c=(80, 80, 75),
            forced_use_threshold_c=85,
            forced_use_margin_c=3,
            residual_burn_kwh=1,
            confidence=0.8,
        )
    )
    assert 0 < target.additional_energy_kwh <= target.safe_remaining_capacity_kwh
    deadline = START + timedelta(days=2, hours=7)
    schedule = schedule_firing(
        FiringScheduleInput(
            now=START + timedelta(days=1, hours=12),
            required_completion=deadline,
            target_additional_kwh=target.fuel_phase_energy_kwh,
            effective_net_power_kw=6,
            preferred_windows=default_preferred_windows(),
            minimum_duration=timedelta(minutes=15),
            maximum_duration=timedelta(hours=4),
            notification_lead_time=timedelta(hours=1),
        )
    )
    assert schedule.feasible
    assert schedule.latest_start is not None
    assert schedule.latest_start.hour >= 15

    session = START + timedelta(days=1, hours=17)
    samples = tuple(
        EnergySample(session + timedelta(minutes=15 * index), 12 + 1.5 * index)
        for index in range(5)
    )
    live = calculate_live_charging_estimate(
        now=samples[-1].at,
        session_start_energy_kwh=12,
        current_energy_kwh=18,
        target_additional_kwh=8,
        residual_burn_kwh=1,
        samples=samples,
        previous_smoothed_power_kw=None,
        initial_power_kw=6,
    )
    assert live.remaining_energy_kwh == 2
    assert live.minimum_remaining_time is not None
    assert live.minimum_remaining_time >= timedelta(0)


def test_three_day_fault_publication_and_restart_timeline() -> None:
    """Delayed/malformed prices and control faults remain explicit across restart."""
    valid_item = {
        "start": START.isoformat(),
        "end": (START + timedelta(days=3)).isoformat(),
        "price": 1.0,
    }
    valid = normalize_price_forecast(
        [valid_item],
        unit="SEK/kWh",
        source_token="day-one",
        config=PriceNormalizationConfig(),
    )
    assert valid.forecast_end == START + timedelta(days=3)
    with pytest.raises(PriceForecastError, match="no valid"):
        normalize_price_forecast(
            [1.0, {"start": "late"}],
            unit="SEK/kWh",
            source_token="delayed-malformed-day-two",
            config=PriceNormalizationConfig(),
        )

    config = ControllerConfig(
        active_control=True,
        startup_grace=timedelta(0),
        minimum_dwell=timedelta(0),
    )
    machine = ControllerStateMachine(config, started_at=START)
    common = {
        "mode": UserMode.AUTO,
        "has_ever_had_valid_inputs": True,
        "plan_valid": True,
        "has_ever_had_valid_plan": True,
        "recommendation": Recommendation.RESERVE_TANK,
        "usable_energy_kwh": 10.0,
        "tank_temperatures_c": (60.0, 50.0, 40.0),
    }
    normal = machine.evaluate(
        ControllerInput(now=START, required_inputs_valid=True, **common)
    )
    missing_sensor = machine.evaluate(
        ControllerInput(
            now=START + timedelta(days=1),
            required_inputs_valid=False,
            **common,
        )
    )
    output_failure = machine.evaluate(
        ControllerInput(
            now=START + timedelta(days=2),
            required_inputs_valid=True,
            service_fault="simulated notification-independent output failure",
            **common,
        )
    )
    restarted = ControllerStateMachine(
        ControllerConfig(active_control=True, startup_grace=timedelta(minutes=5)),
        started_at=START + timedelta(days=3),
    ).evaluate(
        ControllerInput(
            now=START + timedelta(days=3),
            required_inputs_valid=True,
            **common,
        )
    )
    assert normal.state is OperatingState.RESERVE_TANK
    assert missing_sensor.state is OperatingState.FAULT_FALLBACK
    assert not missing_sensor.output_on
    assert output_failure.state is OperatingState.FAULT_FALLBACK
    assert not output_failure.output_on
    assert restarted.state is OperatingState.WAITING_FOR_DATA
    assert not restarted.output_on

"""Pure Milestone 6 charging target and live-guidance tests."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.thermal_storage_optimizer.charging import (
    ChargingTargetInput,
    EnergySample,
    EstimateConfidence,
    calculate_charging_target,
    calculate_live_charging_estimate,
    detect_active_firing,
    estimate_net_charging_power,
)

NOW = datetime(2026, 9, 7, 18, tzinfo=UTC)


def _target(**changes: object) -> ChargingTargetInput:
    values: dict[str, object] = {
        "current_tank_energy_kwh": 4.0,
        "high_cost_heat_demand_kwh": 12.0,
        "intervening_discharge_kwh": 1.0,
        "firing_session_heat_use_kwh": 1.0,
        "storage_losses_kwh": 0.5,
        "usable_capacity_kwh": 30.0,
        "layer_temperatures_c": (50.0, 45.0, 40.0),
        "layer_volumes_l": (200.0, 200.0, 200.0),
        "maximum_layer_temperatures_c": (80.0, 80.0, 80.0),
        "forced_use_threshold_c": 85.0,
        "forced_use_margin_c": 3.0,
        "residual_burn_kwh": 1.0,
        "confidence": 0.8,
    }
    values.update(changes)
    return ChargingTargetInput(**values)  # type: ignore[arg-type]


def test_sufficient_initial_charge_and_no_useful_demand_return_zero() -> None:
    """Do not advise charging without an unmet economically useful load."""
    covered = calculate_charging_target(_target(current_tank_energy_kwh=20.0))
    no_demand = calculate_charging_target(_target(high_cost_heat_demand_kwh=0.0))
    assert covered.additional_energy_kwh == 0
    assert no_demand.additional_energy_kwh == 0
    assert "already covers" in covered.reason
    assert "No useful" in no_demand.reason


def test_empty_tank_target_includes_discharges_losses_and_session_use() -> None:
    """Every required energy component contributes to the pure target."""
    result = calculate_charging_target(_target(current_tank_energy_kwh=0.0))
    assert result.additional_energy_kwh == pytest.approx(14.5)
    assert result.fuel_phase_energy_kwh == pytest.approx(13.5)


def test_safe_capacity_and_maximum_layer_temperature_cap_target() -> None:
    """Capacity calibration and any reached layer limit independently stop charge."""
    capped = calculate_charging_target(
        _target(current_tank_energy_kwh=9.0, usable_capacity_kwh=10.0)
    )
    layer_hot = calculate_charging_target(
        _target(layer_temperatures_c=(80.0, 45.0, 40.0))
    )
    forced_margin_hot = calculate_charging_target(
        _target(
            layer_temperatures_c=(82.0, 45.0, 40.0),
            maximum_layer_temperatures_c=(100.0, 100.0, 100.0),
        )
    )
    assert capped.additional_energy_kwh == pytest.approx(1.0)
    assert "capped" in capped.reason
    assert layer_hot.additional_energy_kwh == 0
    assert forced_margin_hot.additional_energy_kwh == 0


def test_charging_detection_accepts_each_configured_signal() -> None:
    """Pump, temperature, slope, and manual integration action are independent."""
    base = {
        "pump_active": False,
        "stove_temperature_c": 30.0,
        "stove_temperature_threshold_c": 55.0,
        "net_energy_slope_kw": 0.0,
        "slope_threshold_kw": 1.0,
        "manual_active": False,
    }
    assert not detect_active_firing(**base)
    for change in (
        {"pump_active": True},
        {"stove_temperature_c": 60.0},
        {"net_energy_slope_kw": 2.0},
        {"manual_active": True},
    ):
        assert detect_active_firing(**(base | change))


def test_noisy_and_changing_slopes_produce_smoothed_non_negative_power() -> None:
    """Deadband noise is ignored and a changing rate updates through an EMA."""
    noisy = tuple(
        EnergySample(NOW + timedelta(minutes=5 * index), energy)
        for index, energy in enumerate((4.0, 4.01, 3.99, 4.02))
    )
    power, confidence, _reason = estimate_net_charging_power(
        noisy, previous_smoothed_power_kw=None, initial_power_kw=6.0
    )
    assert power == 6.0
    assert confidence is EstimateConfidence.LOW

    changing = (
        EnergySample(NOW, 4.0),
        EnergySample(NOW + timedelta(minutes=10), 5.0),
        EnergySample(NOW + timedelta(minutes=20), 7.0),
    )
    updated, confidence, _reason = estimate_net_charging_power(
        changing, previous_smoothed_power_kw=6.0, initial_power_kw=6.0
    )
    assert updated is not None
    assert 6.0 < updated < 12.0
    assert confidence is EstimateConfidence.MEDIUM


def test_simultaneous_discharge_and_zero_power_withhold_unsafe_time() -> None:
    """Falling tank energy never creates a negative or infinite remaining time."""
    samples = (
        EnergySample(NOW, 5.0),
        EnergySample(NOW + timedelta(minutes=10), 4.0),
    )
    estimate = calculate_live_charging_estimate(
        now=NOW + timedelta(minutes=10),
        session_start_energy_kwh=5.0,
        current_energy_kwh=4.0,
        target_additional_kwh=5.0,
        residual_burn_kwh=0.0,
        samples=samples,
        previous_smoothed_power_kw=None,
        initial_power_kw=0.0,
    )
    assert estimate.energy_added_kwh == 0
    assert estimate.remaining_energy_kwh == 5
    assert estimate.minimum_remaining_time is None
    assert estimate.expected_completion is None
    assert estimate.confidence is EstimateConfidence.INSUFFICIENT


def test_residual_heat_completes_target_without_more_fuel() -> None:
    """Residual burn-down allowance ends the fuel phase before total added is met."""
    estimate = calculate_live_charging_estimate(
        now=NOW,
        session_start_energy_kwh=4.0,
        current_energy_kwh=10.4,
        target_additional_kwh=9.2,
        residual_burn_kwh=3.0,
        samples=(),
        previous_smoothed_power_kw=6.0,
        initial_power_kw=6.0,
    )
    assert estimate.residual_heat_sufficient
    assert estimate.minimum_remaining_time == timedelta(0)
    assert estimate.remaining_energy_kwh == pytest.approx(2.8)


def test_sparse_or_stale_data_lowers_confidence() -> None:
    """Initial power guides provisionally, while stale data withholds time."""
    sparse = calculate_live_charging_estimate(
        now=NOW,
        session_start_energy_kwh=4.0,
        current_energy_kwh=4.0,
        target_additional_kwh=6.0,
        residual_burn_kwh=1.0,
        samples=(),
        previous_smoothed_power_kw=None,
        initial_power_kw=5.0,
    )
    stale = calculate_live_charging_estimate(
        now=NOW,
        session_start_energy_kwh=4.0,
        current_energy_kwh=4.0,
        target_additional_kwh=6.0,
        residual_burn_kwh=1.0,
        samples=(),
        previous_smoothed_power_kw=None,
        initial_power_kw=5.0,
        data_stale=True,
    )
    assert sparse.minimum_remaining_time == timedelta(hours=1)
    assert sparse.confidence is EstimateConfidence.LOW
    assert stale.minimum_remaining_time is None
    assert stale.confidence is EstimateConfidence.INSUFFICIENT

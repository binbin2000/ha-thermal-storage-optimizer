"""Unit tests for the pure three-layer accumulator model."""

import pytest

from custom_components.thermal_storage_optimizer.energy import (
    DataQuality,
    EnergyTrend,
    TankTemperatures,
    ThermalEnergyConfig,
    detect_energy_trend,
    estimate_thermal_state,
)


def config(**changes: object) -> ThermalEnergyConfig:
    """Return the representative 500-litre configuration."""
    values = {
        "total_volume_l": 500.0,
        "layer_volumes_l": (500.0 / 3.0,) * 3,
        "minimum_useful_delta_c": 3.0,
        "usable_capacity_kwh": 30.0,
        "trend_deadband_kwh": 0.1,
        **changes,
    }
    return ThermalEnergyConfig(**values)  # type: ignore[arg-type]


def test_exact_known_three_layer_example() -> None:
    """Test usable reference, high-grade target, SOC, and stratification."""
    result = estimate_thermal_state(
        TankTemperatures(60.0, 50.0, 40.0, 30.0, 45.0), config()
    )

    assert result.reference_temperature_c == 33.0
    assert result.usable_energy_kwh == pytest.approx(9.8855)
    assert result.high_grade_energy_kwh == pytest.approx(3.8766666667)
    assert result.state_of_charge_percent == pytest.approx(32.9516666667)
    assert result.stratification_delta_c == 20.0
    assert result.quality is DataQuality.GOOD
    assert result.confidence == 1.0
    assert result.trend is EnergyTrend.UNKNOWN


def test_temperatures_below_or_at_references_never_create_negative_energy() -> None:
    """Test clipping below the usable and high-grade boundary temperatures."""
    below = estimate_thermal_state(
        TankTemperatures(32.0, 20.0, -5.0, 30.0, 45.0), config()
    )
    boundary = estimate_thermal_state(
        TankTemperatures(45.0, 33.0, 33.0, 30.0, 45.0), config()
    )

    assert below.usable_energy_kwh == 0.0
    assert below.high_grade_energy_kwh == 0.0
    assert below.state_of_charge_percent == 0.0
    assert boundary.usable_energy_kwh == pytest.approx(2.326)
    assert boundary.high_grade_energy_kwh == 0.0


def test_soc_is_bounded_at_one_hundred_percent() -> None:
    """Test calibrated capacity cannot yield an out-of-range SOC sensor."""
    result = estimate_thermal_state(
        TankTemperatures(90.0, 90.0, 90.0, 20.0, 40.0),
        config(usable_capacity_kwh=1.0),
    )
    assert result.state_of_charge_percent == 100.0


def test_inverted_sensor_stratification_degrades_confidence() -> None:
    """Test physically inverted layers remain calculable but are clearly qualified."""
    result = estimate_thermal_state(
        TankTemperatures(40.0, 60.0, 50.0, 30.0, 45.0), config()
    )
    assert result.usable_energy_kwh is not None
    assert result.quality is DataQuality.DEGRADED
    assert result.confidence == 0.5
    assert result.stratification_delta_c == -10.0


def test_missing_values_return_conservative_unavailable_result() -> None:
    """Test incomplete normalized inputs are not extrapolated or guessed."""
    result = estimate_thermal_state(
        TankTemperatures(60.0, None, 40.0, 30.0, 45.0), config()
    )
    assert result.usable_energy_kwh is None
    assert result.high_grade_energy_kwh is None
    assert result.state_of_charge_percent is None
    assert result.quality is DataQuality.UNAVAILABLE
    assert result.confidence == 0.0
    assert result.missing_values == ("middle",)


@pytest.mark.parametrize(
    "changes",
    [
        {"total_volume_l": 0.0},
        {"layer_volumes_l": (166.0, 166.0, -1.0)},
        {"layer_volumes_l": (100.0, 100.0, 100.0)},
    ],
)
def test_invalid_layer_volumes_are_rejected(changes: dict[str, object]) -> None:
    """Test impossible volumes fail before any energy calculation."""
    with pytest.raises(ValueError, match="volume"):
        config(**changes)


def test_trend_detection_covers_charging_discharging_and_idle() -> None:
    """Test trend classification and exact deadband boundaries."""
    assert detect_energy_trend(10.2, 10.0, deadband_kwh=0.1) is EnergyTrend.CHARGING
    assert detect_energy_trend(9.8, 10.0, deadband_kwh=0.1) is EnergyTrend.DISCHARGING
    assert detect_energy_trend(10.1, 10.0, deadband_kwh=0.1) is EnergyTrend.IDLE
    assert detect_energy_trend(9.9, 10.0, deadband_kwh=0.1) is EnergyTrend.IDLE

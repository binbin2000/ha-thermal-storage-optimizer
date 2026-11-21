"""Unit tests for the replaceable COP interface and fixed fallback."""

from datetime import UTC, datetime

import pytest

from custom_components.thermal_storage_optimizer.adaptive import ParameterBounds
from custom_components.thermal_storage_optimizer.cop import (
    CopSource,
    FixedCopModel,
    LearnedCopModel,
    carnot_cop,
    carnot_efficiency,
    estimate_cop,
    system_cop,
)
from custom_components.thermal_storage_optimizer.curves import (
    MIN_BIN_SAMPLE_INTERVAL,
    OutdoorBinnedCurve,
)

NOW = datetime(2026, 11, 20, 12, tzinfo=UTC)


def test_fixed_cop_fallback_is_deterministic() -> None:
    """Test the fallback contract leaves room for temperature-aware models."""
    estimate = estimate_cop(
        FixedCopModel(3.2), outdoor_temperature_c=-5.0, supply_temperature_c=45.0
    )
    assert estimate.value == 3.2
    assert estimate.source is CopSource.FIXED_FALLBACK
    assert estimate.confidence == 0.6


def test_valid_measured_cop_is_preferred() -> None:
    """Test a normalized measurement supersedes the conservative fallback."""
    estimate = estimate_cop(
        FixedCopModel(3.2),
        outdoor_temperature_c=-5.0,
        supply_temperature_c=45.0,
        measured_cop=4.1,
    )
    assert estimate.value == 4.1
    assert estimate.source is CopSource.MEASURED


@pytest.mark.parametrize("invalid", [0.0, -1.0, float("inf"), float("nan")])
def test_invalid_fixed_cop_settings_are_rejected(invalid: float) -> None:
    """Test zero, negative, and non-finite fallback settings."""
    with pytest.raises(ValueError, match="fixed COP"):
        FixedCopModel(invalid)


@pytest.mark.parametrize("measured", [0.0, -2.0, float("nan")])
def test_invalid_measurement_uses_fixed_fallback(measured: float) -> None:
    """Test invalid optional measurements cannot poison the COP result."""
    estimate = estimate_cop(
        FixedCopModel(3.0),
        outdoor_temperature_c=0.0,
        supply_temperature_c=40.0,
        measured_cop=measured,
    )
    assert estimate.value == 3.0
    assert estimate.source is CopSource.FIXED_FALLBACK


def test_carnot_helpers_are_physical_and_guard_small_lifts() -> None:
    """Ideal COP falls with lift; efficiency is undefined without a real lift."""
    mild = carnot_cop(outdoor_temperature_c=7.0, supply_temperature_c=35.0)
    cold = carnot_cop(outdoor_temperature_c=-15.0, supply_temperature_c=50.0)
    assert mild > cold > 1
    assert carnot_efficiency(
        measured_cop=mild / 2, outdoor_temperature_c=7.0, supply_temperature_c=35.0
    ) == pytest.approx(0.5)
    assert (
        carnot_efficiency(
            measured_cop=3.0, outdoor_temperature_c=34.5, supply_temperature_c=35.0
        )
        is None
    )
    assert (
        carnot_efficiency(
            measured_cop=0.0, outdoor_temperature_c=0.0, supply_temperature_c=35.0
        )
        is None
    )
    with pytest.raises(ValueError, match="finite"):
        carnot_cop(outdoor_temperature_c=float("nan"), supply_temperature_c=35.0)


def test_learned_model_falls_back_without_carnot_efficiency() -> None:
    """Outside the learned range and without efficiency the fallback is explained."""
    curve = OutdoorBinnedCurve(
        name="cop_curve",
        unit="COP",
        bin_width_c=3.0,
        value_bounds=ParameterBounds(1, 7),
    )
    for index in range(8):
        for outdoor, value in ((1.0, 3.1), (7.0, 3.6)):
            curve.add_sample(NOW + index * MIN_BIN_SAMPLE_INTERVAL, outdoor, value)
    model = LearnedCopModel(
        curve,
        NOW + timedelta_hours(5),
        0.6,
        None,
        ParameterBounds(1, 7),
        FixedCopModel(2.5),
    )
    learned = model.explain(outdoor_temperature_c=1.0, supply_temperature_c=40)
    outside = model.explain(outdoor_temperature_c=-10.0, supply_temperature_c=40)
    assert learned.source is CopSource.LEARNED_CURVE
    assert learned.value == pytest.approx(3.1)
    assert outside.source is CopSource.FIXED_FALLBACK
    assert outside.value == 2.5
    assert (
        estimate_cop(model, outdoor_temperature_c=-10.0, supply_temperature_c=40).source
        is CopSource.FIXED_FALLBACK
    )
    assert (
        estimate_cop(
            model, outdoor_temperature_c=1.0, supply_temperature_c=40, measured_cop=3.9
        ).source
        is CopSource.MEASURED
    )


def timedelta_hours(hours: float):  # noqa: ANN201
    """Return a timedelta in hours without another import line."""
    from datetime import timedelta  # noqa: PLC0415

    return timedelta(hours=hours)


def test_system_cop_blends_heater_at_unity() -> None:
    """A resistive heater pulls the effective COP toward one by its heat share."""
    combined = system_cop(
        heat_pump_cop=3.0, heat_pump_power_kw=2.0, heater_power_kw=3.0
    )
    assert combined is not None
    assert combined.value == pytest.approx(9 / 5)
    assert combined.heater_heat_share == pytest.approx(3 / 9)
    alone = system_cop(heat_pump_cop=3.0, heat_pump_power_kw=2.0, heater_power_kw=0.0)
    assert alone is not None
    assert alone.value == 3.0
    assert alone.heater_heat_share == 0
    assert (
        system_cop(heat_pump_cop=3.0, heat_pump_power_kw=0.0, heater_power_kw=0.0)
        is None
    )
    assert (
        system_cop(heat_pump_cop=0.0, heat_pump_power_kw=1.0, heater_power_kw=1.0)
        is None
    )
    assert (
        system_cop(heat_pump_cop=3.0, heat_pump_power_kw=-1.0, heater_power_kw=1.0)
        is None
    )
    assert (
        system_cop(
            heat_pump_cop=float("nan"), heat_pump_power_kw=1.0, heater_power_kw=1.0
        )
        is None
    )

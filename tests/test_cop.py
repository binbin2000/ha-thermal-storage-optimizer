"""Unit tests for the replaceable COP interface and fixed fallback."""

import pytest

from custom_components.thermal_storage_optimizer.cop import (
    CopSource,
    FixedCopModel,
    estimate_cop,
)


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

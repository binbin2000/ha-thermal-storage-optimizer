"""Unit tests for the pure building heat-demand model."""

from datetime import timedelta

import pytest

from custom_components.thermal_storage_optimizer.demand import (
    HeatDemandConfig,
    estimate_heat_demand_kwh,
)


def test_exact_heat_demand_example_and_variable_interval() -> None:
    """Test coefficient, balance delta, outdoor temperature, and duration."""
    model = HeatDemandConfig(
        heat_loss_coefficient_kw_per_k=0.3, balance_temperature_c=17
    )
    assert estimate_heat_demand_kwh(2.0, timedelta(minutes=30), model) == 2.25


@pytest.mark.parametrize("outdoor", [17.0, 18.0, 40.0])
def test_temperature_at_or_above_balance_has_no_heat_demand(outdoor: float) -> None:
    """Test the model's temperature boundary is clipped to zero."""
    model = HeatDemandConfig(0.3, 17.0)
    assert estimate_heat_demand_kwh(outdoor, timedelta(hours=1), model) == 0.0


def test_zero_duration_and_invalid_settings() -> None:
    """Test interval and parameter edge cases."""
    model = HeatDemandConfig(0.3, 17.0)
    assert estimate_heat_demand_kwh(-10.0, timedelta(0), model) == 0.0
    with pytest.raises(ValueError, match="duration"):
        estimate_heat_demand_kwh(0.0, timedelta(seconds=-1), model)
    with pytest.raises(ValueError, match="heat-loss"):
        HeatDemandConfig(-0.1, 17.0)

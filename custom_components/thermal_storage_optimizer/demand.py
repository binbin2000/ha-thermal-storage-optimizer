"""Pure building heat-demand model."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True, slots=True)
class HeatDemandConfig:
    """Validated first-stage building heat-demand settings."""

    heat_loss_coefficient_kw_per_k: float
    balance_temperature_c: float

    def __post_init__(self) -> None:
        """Validate model parameters."""
        if (
            not math.isfinite(self.heat_loss_coefficient_kw_per_k)
            or self.heat_loss_coefficient_kw_per_k < 0
        ):
            msg = "heat-loss coefficient must be finite and non-negative"
            raise ValueError(msg)
        if not math.isfinite(self.balance_temperature_c):
            msg = "balance temperature must be finite"
            raise ValueError(msg)


def estimate_heat_demand_kwh(
    outdoor_temperature_c: float,
    interval: timedelta,
    config: HeatDemandConfig,
) -> float:
    """Return thermal demand for an interval using the transparent linear model."""
    if not math.isfinite(outdoor_temperature_c):
        msg = "outdoor temperature must be finite"
        raise ValueError(msg)
    duration_hours = interval.total_seconds() / 3600.0
    if not math.isfinite(duration_hours) or duration_hours < 0:
        msg = "interval duration must be finite and non-negative"
        raise ValueError(msg)
    temperature_difference = max(
        config.balance_temperature_c - outdoor_temperature_c, 0.0
    )
    return (
        config.heat_loss_coefficient_kw_per_k * temperature_difference * duration_hours
    )

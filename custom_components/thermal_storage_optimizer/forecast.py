"""Pure thermal/economic forecast construction."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .demand import HeatDemandConfig, estimate_heat_demand_kwh

if TYPE_CHECKING:
    from .cop import CopModel
    from .price import PriceForecast
    from .weather import OutdoorForecast


@dataclass(frozen=True, slots=True)
class ForecastModelConfig:
    """Validated loss and uncertainty assumptions."""

    hourly_retention: float = 0.995
    confidence: float = 0.85

    def __post_init__(self) -> None:
        """Validate bounded adjustment factors."""
        if (
            not math.isfinite(self.hourly_retention)
            or not 0 < self.hourly_retention <= 1
        ):
            msg = "hourly retention must be in (0, 1]"
            raise ValueError(msg)
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            msg = "forecast confidence must be in [0, 1]"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class EconomicForecastInterval:
    """One price period enriched with heat demand and avoided cost."""

    start: datetime
    end: datetime
    duration: timedelta
    electricity_cost_per_kwh: float
    outdoor_temperature_c: float
    heat_demand_kwh: float
    cop: float
    avoided_heat_cost_per_kwh: float
    retention: float
    confidence: float
    adjusted_value_per_kwh: float
    supply_temperature_c: float | None = None


def build_economic_forecast(  # noqa: PLR0913
    prices: PriceForecast,
    *,
    now: datetime,
    outdoor_temperature_c: float,
    supply_temperature_c: float,
    measured_cop: float | None,
    cop_model: CopModel,
    demand_config: HeatDemandConfig,
    model_config: ForecastModelConfig,
    outdoor_forecast: OutdoorForecast | None = None,
    supply_temperature_for: Callable[[float], float] | None = None,
) -> tuple[EconomicForecastInterval, ...]:
    """Enrich every non-expired price interval using deterministic models.

    When an hourly outdoor forecast is supplied, each interval uses its own
    forecast temperature corrected toward the current measurement; otherwise the
    measured outdoor temperature is repeated across the horizon. A learned
    heating curve likewise maps each interval's outdoor temperature to a supply
    target; otherwise the current supply target is repeated.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        msg = "planning time must be timezone-aware"
        raise ValueError(msg)
    result: list[EconomicForecastInterval] = []
    for price in prices.intervals:
        effective_start = (
            price.start if price.start.timestamp() >= now.timestamp() else now
        )
        duration_seconds = price.end.timestamp() - effective_start.timestamp()
        if duration_seconds <= 0:
            continue
        duration = timedelta(seconds=duration_seconds)
        outdoor = outdoor_temperature_c
        if outdoor_forecast is not None:
            outdoor = outdoor_forecast.interval_temperature(
                effective_start,
                price.end,
                measured_c=outdoor_temperature_c,
                measured_at=now,
            )
        supply = supply_temperature_c
        if supply_temperature_for is not None:
            supply = supply_temperature_for(outdoor)
            if not math.isfinite(supply):
                msg = "learned supply temperature must be finite"
                raise ValueError(msg)
        demand = estimate_heat_demand_kwh(outdoor, duration, demand_config)
        cop = measured_cop
        if cop is None or not math.isfinite(cop) or cop <= 0:
            cop = cop_model.estimate(
                outdoor_temperature_c=outdoor,
                supply_temperature_c=supply,
            )
        if not math.isfinite(cop) or cop <= 0:
            msg = "COP must be finite and positive"
            raise ValueError(msg)
        hours_ahead = max((price.end.timestamp() - now.timestamp()) / 3600.0, 0.0)
        retention = model_config.hourly_retention**hours_ahead
        avoided = price.marginal_cost_per_kwh / cop
        adjusted = avoided * retention * model_config.confidence
        result.append(
            EconomicForecastInterval(
                effective_start,
                price.end,
                duration,
                price.marginal_cost_per_kwh,
                outdoor,
                demand,
                cop,
                avoided,
                retention,
                model_config.confidence,
                adjusted,
                supply,
            )
        )
    return tuple(result)

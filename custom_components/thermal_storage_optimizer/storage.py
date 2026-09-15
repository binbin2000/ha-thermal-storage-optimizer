"""Bounded persistent representation of the last valid optimization plan."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .forecast import EconomicForecastInterval
from .optimizer import OptimizationPlan, PlannedInterval


def serialize_plan(plan: OptimizationPlan) -> dict[str, Any]:
    """Convert a plan to JSON-compatible primitives."""
    return {
        "publication_key": plan.publication_key,
        "reserve_until": plan.reserve_until.isoformat() if plan.reserve_until else None,
        "optimized_at": plan.optimized_at.isoformat(),
        "forecast_end": plan.forecast_end.isoformat(),
        "available_energy_kwh": plan.available_energy_kwh,
        "retained_beyond_horizon_kwh": plan.retained_beyond_horizon_kwh,
        "expected_savings": plan.expected_savings,
        "intervals": [
            {
                "start": item.forecast.start.isoformat(),
                "end": item.forecast.end.isoformat(),
                "electricity_cost_per_kwh": item.forecast.electricity_cost_per_kwh,
                "outdoor_temperature_c": item.forecast.outdoor_temperature_c,
                "heat_demand_kwh": item.forecast.heat_demand_kwh,
                "cop": item.forecast.cop,
                "avoided_heat_cost_per_kwh": item.forecast.avoided_heat_cost_per_kwh,
                "retention": item.forecast.retention,
                "confidence": item.forecast.confidence,
                "adjusted_value_per_kwh": item.forecast.adjusted_value_per_kwh,
                "allocated_energy_kwh": item.allocated_energy_kwh,
                "expected_savings": item.expected_savings,
            }
            for item in plan.intervals
        ],
    }


def deserialize_plan(  # noqa: PLR0911
    payload: object, *, now: datetime
) -> OptimizationPlan | None:
    """Restore a plan only while its aware timestamps remain applicable."""
    if not isinstance(payload, dict) or now.tzinfo is None or now.utcoffset() is None:
        return None
    try:
        optimized_at = _parse_aware(payload["optimized_at"])
        forecast_end = _parse_aware(payload["forecast_end"])
        if forecast_end.timestamp() <= now.timestamp():
            return None
        periods: list[PlannedInterval] = []
        raw_intervals = payload["intervals"]
        if not isinstance(raw_intervals, list):
            return None
        for raw in raw_intervals:
            if not isinstance(raw, dict):
                return None
            start = _parse_aware(raw["start"])
            end = _parse_aware(raw["end"])
            if end.timestamp() <= start.timestamp():
                return None
            forecast = EconomicForecastInterval(
                start=start,
                end=end,
                duration=timedelta(seconds=end.timestamp() - start.timestamp()),
                electricity_cost_per_kwh=float(raw["electricity_cost_per_kwh"]),
                outdoor_temperature_c=float(raw["outdoor_temperature_c"]),
                heat_demand_kwh=float(raw["heat_demand_kwh"]),
                cop=float(raw["cop"]),
                avoided_heat_cost_per_kwh=float(raw["avoided_heat_cost_per_kwh"]),
                retention=float(raw["retention"]),
                confidence=float(raw["confidence"]),
                adjusted_value_per_kwh=float(raw["adjusted_value_per_kwh"]),
            )
            periods.append(
                PlannedInterval(
                    forecast=forecast,
                    allocated_energy_kwh=float(raw["allocated_energy_kwh"]),
                    expected_savings=float(raw["expected_savings"]),
                )
            )
        if (
            not periods
            or max(periods, key=lambda item: item.forecast.end.timestamp()).forecast.end
            != forecast_end
        ):
            return None
        return OptimizationPlan(
            publication_key=str(payload["publication_key"]),
            optimized_at=optimized_at,
            forecast_end=forecast_end,
            available_energy_kwh=float(payload["available_energy_kwh"]),
            retained_beyond_horizon_kwh=float(payload["retained_beyond_horizon_kwh"]),
            expected_savings=float(payload["expected_savings"]),
            intervals=tuple(periods),
            reserve_until=_parse_aware(payload["reserve_until"])
            if payload.get("reserve_until")
            else optimized_at + timedelta(hours=24),
        )
    except KeyError, TypeError, ValueError, OverflowError:
        return None


def _parse_aware(value: object) -> datetime:
    """Parse and validate a stored ISO timestamp."""
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        message = "stored plan timestamp is not timezone-aware"
        raise ValueError(message)
    return parsed

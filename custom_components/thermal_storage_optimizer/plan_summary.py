"""Bounded, recorder-independent optimization-plan presentation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .coordinator import InputCoordinator


def build_plan_summary(
    coordinator: InputCoordinator, *, max_intervals: int
) -> dict[str, Any]:
    """Return current plan state and at most ``max_intervals`` future periods."""
    data = coordinator.data
    limit = max(max_intervals, 0)
    plan = data.plan
    response: dict[str, Any] = {
        "generated_at": data.captured_at.isoformat(),
        "plan_status": data.plan_status.value,
        "recommendation": (
            data.recommendation.value if data.recommendation is not None else None
        ),
        "decision_explanation": data.plan_reason,
        "data_valid": data.is_valid,
        "rejected_forecast_intervals": data.forecast_rejected_items,
        "currency_note": "Values use the configured price forecast currency.",
        "intervals": [],
        "returned_interval_count": 0,
        "omitted_interval_count": 0,
    }
    if plan is None:
        return response

    future = tuple(
        item
        for item in plan.intervals
        if item.forecast.end.timestamp() > data.captured_at.timestamp()
    )
    selected = future[:limit]
    response.update(
        {
            "optimized_at": plan.optimized_at.isoformat(),
            "forecast_end": plan.forecast_end.isoformat(),
            "available_energy_kwh": round(plan.available_energy_kwh, 3),
            "retained_beyond_horizon_kwh": round(plan.retained_beyond_horizon_kwh, 3),
            "expected_avoided_cost": round(plan.expected_savings, 3),
            "total_interval_count": len(plan.intervals),
            "future_interval_count": len(future),
            "returned_interval_count": len(selected),
            "omitted_interval_count": len(future) - len(selected),
            "intervals": [
                {
                    "start": item.forecast.start.isoformat(),
                    "end": item.forecast.end.isoformat(),
                    "recommendation": (
                        "use_tank" if item.allocated_energy_kwh > 0 else "reserve_tank"
                    ),
                    "allocated_energy_kwh": round(item.allocated_energy_kwh, 3),
                    "heat_demand_kwh": round(item.forecast.heat_demand_kwh, 3),
                    "electricity_cost_per_kwh": round(
                        item.forecast.electricity_cost_per_kwh, 4
                    ),
                    "cop": round(item.forecast.cop, 3),
                    "adjusted_heat_value_per_kwh": round(
                        item.forecast.adjusted_value_per_kwh, 4
                    ),
                    "expected_avoided_cost": round(item.expected_savings, 3),
                }
                for item in selected
            ],
        }
    )
    return response

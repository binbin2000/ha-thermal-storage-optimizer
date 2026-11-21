"""Today-and-tomorrow presentation data for the bundled day-chart card."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .price import PriceForecastError

if TYPE_CHECKING:
    from .advisor import AdvisorState
    from .coordinator import InputCoordinator

_ALLOCATION_EPSILON = 1e-9
# Unique-ID suffix and entity domain for every history series the card reads.
_HISTORY_ENTITIES = {
    "operating_state": "sensor",
    "release_recommended": "binary_sensor",
    "stove_firing": "binary_sensor",
}


def day_chart_window(now: datetime) -> tuple[datetime, datetime]:
    """Return local midnight today and local midnight two days later."""
    start = dt_util.start_of_local_day(dt_util.as_local(now))
    # Resolve the end from the calendar date so DST days keep their true length.
    end = dt_util.start_of_local_day(start.date() + timedelta(days=2))
    return start, end


def build_day_chart(coordinator: InputCoordinator, *, now: datetime) -> dict[str, Any]:
    """Return prices, the tank plan, and the firing advice for two local days.

    Past outcomes are deliberately absent: the card reads them from recorder
    history for the entity IDs listed under ``entities``.
    """
    start, end = day_chart_window(now)
    data = coordinator.data
    response: dict[str, Any] = {
        "generated_at": now.isoformat(),
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "day_boundary": dt_util.start_of_local_day(
            start.date() + timedelta(days=1)
        ).isoformat(),
        "plan_status": data.plan_status.value if data is not None else None,
        "prices": _prices(coordinator, start, end),
        "price_error": None,
        "planned": [],
        "firing": _firing(coordinator.advisor.state, start, end),
        "entities": _entities(coordinator),
    }
    if not response["prices"]:
        response["price_error"] = _price_error(coordinator)
    plan = data.plan if data is not None else None
    if plan is not None:
        response["planned"] = [
            {
                "start": item.forecast.start.isoformat(),
                "end": item.forecast.end.isoformat(),
                "release_start": item.release_start.isoformat(),
                "recommendation": (
                    "use_tank"
                    if item.allocated_energy_kwh > _ALLOCATION_EPSILON
                    else "reserve_tank"
                ),
                "allocated_energy_kwh": round(item.allocated_energy_kwh, 3),
                "heat_demand_kwh": round(item.forecast.heat_demand_kwh, 3),
            }
            for item in plan.intervals
            if _overlaps(item.forecast.start, item.forecast.end, start, end)
        ]
    return response


def _prices(
    coordinator: InputCoordinator, start: datetime, end: datetime
) -> list[dict[str, Any]]:
    try:
        forecast = coordinator.price_forecast()
    except PriceForecastError:
        return []
    return [
        {
            "start": item.start.isoformat(),
            "end": item.end.isoformat(),
            "price": round(item.marginal_cost_per_kwh, 4),
        }
        for item in forecast.intervals
        if _overlaps(item.start, item.end, start, end)
    ]


def _price_error(coordinator: InputCoordinator) -> str | None:
    try:
        coordinator.price_forecast()
    except PriceForecastError as err:
        return str(err)
    return None


def _firing(
    state: AdvisorState, start: datetime, end: datetime
) -> dict[str, Any] | None:
    schedule = state.schedule
    if schedule is None:
        return None
    window_start = schedule.earliest_useful_start
    latest_start = schedule.latest_start
    duration = schedule.recommended_duration
    visible = (
        state.charge_recommended
        and window_start is not None
        and latest_start is not None
        and duration is not None
        and _overlaps(window_start, schedule.required_completion, start, end)
    )
    return {
        "recommended": visible,
        "feasible": schedule.feasible,
        "active": state.firing_active,
        "earliest_start": _iso(window_start),
        "latest_start": _iso(latest_start),
        "duration_minutes": (
            round(duration.total_seconds() / 60) if duration is not None else None
        ),
        "complete_by": schedule.required_completion.isoformat(),
        "target_kwh": round(schedule.target_additional_kwh, 3),
        "reason": schedule.reason,
    }


def _entities(coordinator: InputCoordinator) -> dict[str, str | None]:
    entry = coordinator.config_entry
    if entry is None:
        return dict.fromkeys(_HISTORY_ENTITIES)
    registry = er.async_get(coordinator.hass)
    return {
        key: registry.async_get_entity_id(domain, DOMAIN, f"{entry.entry_id}_{key}")
        for key, domain in _HISTORY_ENTITIES.items()
    }


def _overlaps(
    start: datetime, end: datetime, window_start: datetime, window_end: datetime
) -> bool:
    return (
        end.timestamp() > window_start.timestamp()
        and start.timestamp() < window_end.timestamp()
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None

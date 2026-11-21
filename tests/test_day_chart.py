"""Day-chart response tests for the bundled today-and-tomorrow card."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermal_storage_optimizer.const import (
    DOMAIN,
    INTEGRATION_NAME,
    SERVICE_GET_DAY_CHART,
    UNIQUE_ID,
)
from custom_components.thermal_storage_optimizer.day_chart import (
    build_day_chart,
    day_chart_window,
)

from .helpers import REQUIRED_CONFIG, set_valid_required_states


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    """Load a dry-run instance with fake output services."""
    set_valid_required_states(hass)
    output = AsyncMock()
    hass.services.async_register("switch", "turn_on", output)
    hass.services.async_register("switch", "turn_off", output)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=INTEGRATION_NAME,
        unique_id=UNIQUE_ID,
        data=REQUIRED_CONFIG,
        version=5,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _set_prices(hass: HomeAssistant, start: datetime, count: int) -> None:
    hass.states.async_set(
        "sensor.price_forecast",
        "published",
        {
            "unit_of_measurement": "SEK/kWh",
            "publication_id": f"day-chart-{start.isoformat()}-{count}",
            "prices": [
                {
                    "start": (start + timedelta(hours=index)).isoformat(),
                    "end": (start + timedelta(hours=index + 1)).isoformat(),
                    "price": 0.5 + (index % 5) * 0.3,
                }
                for index in range(count)
            ],
        },
    )


async def test_window_spans_two_local_days(hass: HomeAssistant) -> None:
    """The window runs from local midnight today to midnight after tomorrow."""
    await hass.config.async_set_time_zone("Europe/Stockholm")
    now = datetime(2026, 11, 21, 14, 30, tzinfo=dt_util.UTC)

    start, end = day_chart_window(now)

    assert start.isoformat() == "2026-11-21T00:00:00+01:00"
    assert end.isoformat() == "2026-11-23T00:00:00+01:00"


async def test_window_keeps_true_length_across_dst(hass: HomeAssistant) -> None:
    """A daylight-saving change makes the two-day window 47 hours long."""
    await hass.config.async_set_time_zone("Europe/Stockholm")
    now = datetime(2026, 3, 28, 12, 0, tzinfo=dt_util.UTC)

    start, end = day_chart_window(now)

    assert end.timestamp() - start.timestamp() == 47 * 3600
    assert end.isoformat() == "2026-03-30T00:00:00+02:00"


async def test_action_returns_past_prices_plan_and_entities(
    hass: HomeAssistant,
) -> None:
    """Prices cover already-past hours while the plan only covers the future."""
    entry = await _setup(hass)
    now = dt_util.utcnow()
    window_start, window_end = day_chart_window(now)
    _set_prices(hass, window_start - timedelta(hours=3), 80)
    await hass.async_block_till_done()

    response = await hass.services.async_call(
        DOMAIN, SERVICE_GET_DAY_CHART, blocking=True, return_response=True
    )

    assert response is not None
    assert response["window_start"] == window_start.isoformat()
    assert response["window_end"] == window_end.isoformat()
    prices = response["prices"]
    assert response["price_error"] is None
    # Every hour of both local days is present; out-of-window items are dropped.
    assert len(prices) == round(
        (window_end.timestamp() - window_start.timestamp()) / 3600
    )
    assert datetime.fromisoformat(prices[0]["start"]) == window_start
    assert datetime.fromisoformat(prices[-1]["end"]) == window_end
    # Window item 3 is source item 6 because three earlier hours were dropped.
    assert prices[3]["price"] == pytest.approx(0.5 + (6 % 5) * 0.3)
    boundary = datetime.fromisoformat(response["day_boundary"])
    assert window_start < boundary < window_end
    assert dt_util.as_local(boundary).hour == 0

    planned = response["planned"]
    assert planned
    for item in planned:
        start = datetime.fromisoformat(item["start"])
        end = datetime.fromisoformat(item["end"])
        release = datetime.fromisoformat(item["release_start"])
        assert end > now - timedelta(minutes=1)
        assert start < window_end
        assert start <= release <= end
        assert (item["recommendation"] == "use_tank") == (
            item["allocated_energy_kwh"] > 0
        )
        if item["recommendation"] == "reserve_tank":
            assert release == end

    entities = response["entities"]
    assert set(entities) == {"operating_state", "release_recommended", "stove_firing"}
    for entity_id in entities.values():
        assert entity_id is not None
        assert hass.states.get(entity_id) is not None
    assert entities["operating_state"].startswith("sensor.")
    assert entities["stove_firing"].startswith("binary_sensor.")
    assert response["plan_status"] == entry.runtime_data.data.plan_status.value


async def test_firing_advice_matches_advisor_state(hass: HomeAssistant) -> None:
    """The firing block mirrors the advisor schedule and its recommendation."""
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    now = dt_util.utcnow()

    response = build_day_chart(coordinator, now=now)

    state = coordinator.advisor.state
    firing = response["firing"]
    if state.schedule is None:
        assert firing is None
        return
    assert firing["feasible"] is state.schedule.feasible
    assert firing["active"] is state.firing_active
    assert firing["complete_by"] == state.schedule.required_completion.isoformat()
    assert firing["target_kwh"] == round(state.schedule.target_additional_kwh, 3)
    if firing["recommended"]:
        assert state.charge_recommended
        assert firing["earliest_start"] is not None
        assert firing["latest_start"] is not None
        assert firing["duration_minutes"] > 0


async def test_missing_price_forecast_is_reported_not_raised(
    hass: HomeAssistant,
) -> None:
    """An unusable price source yields an empty series and a bounded reason."""
    entry = await _setup(hass)
    hass.states.async_remove("sensor.price_forecast")
    await hass.async_block_till_done()

    response = build_day_chart(entry.runtime_data, now=dt_util.utcnow())

    assert response["prices"] == []
    assert response["price_error"] == "price forecast entity is missing"
    assert isinstance(response["planned"], list)

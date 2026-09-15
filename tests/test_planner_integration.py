"""Home Assistant tests for publication rollover and dry-run persistence."""

from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermal_storage_optimizer.const import (
    DOMAIN,
    INTEGRATION_NAME,
    UNIQUE_ID,
)
from custom_components.thermal_storage_optimizer.data import PlanStatus

from .helpers import REQUIRED_CONFIG, set_valid_required_states

DIAGNOSTIC_PREVIEW_LIMIT = 3


def _entity_id(hass: HomeAssistant, platform: str, unique_id: str) -> str:
    """Resolve a planner entity by unique ID."""
    result = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert result is not None
    return result


def _state(hass: HomeAssistant, entity_id: str):  # noqa: ANN202
    """Return an asserted-present state."""
    result = hass.states.get(entity_id)
    assert result is not None
    return result


async def _setup(hass: HomeAssistant, output_service: AsyncMock) -> MockConfigEntry:
    """Set up a representative timestamped forecast fixture."""
    set_valid_required_states(hass)
    hass.services.async_register("switch", "turn_on", output_service)
    hass.services.async_register("switch", "turn_off", output_service)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=INTEGRATION_NAME,
        unique_id=UNIQUE_ID,
        data=REQUIRED_CONFIG,
        version=3,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_entities_are_bounded_and_dry_run_only_requests_safe_off(
    hass: HomeAssistant,
) -> None:
    """Expose complete dry-run summaries without recorder-heavy attributes."""
    output_service = AsyncMock()
    entry = await _setup(hass, output_service)
    data = entry.runtime_data.data
    assert data.plan is not None
    assert data.plan_status is PlanStatus.FULL_FORECAST

    plan_status_id = _entity_id(hass, "sensor", f"{entry.entry_id}_plan_status")
    release_id = _entity_id(
        hass, "binary_sensor", f"{entry.entry_id}_release_recommended"
    )
    forecast_end_id = _entity_id(hass, "sensor", f"{entry.entry_id}_forecast_end")
    coverage_id = _entity_id(hass, "sensor", f"{entry.entry_id}_forecast_coverage")
    assert _state(hass, forecast_end_id).state != "unknown"
    assert float(_state(hass, coverage_id).state) > 0
    assert (
        len(_state(hass, plan_status_id).attributes["preview"])
        <= DIAGNOSTIC_PREVIEW_LIMIT
    )
    assert _state(hass, release_id).state in {"on", STATE_OFF}
    assert output_service.await_count == 1
    assert output_service.await_args.args[0].service == "turn_off"


async def test_new_source_or_final_timestamp_reoptimizes_without_clock_trigger(
    hass: HomeAssistant,
) -> None:
    """An entity publication update, not an exact 13:00 timer, replaces the plan."""
    output_service = AsyncMock()
    entry = await _setup(hass, output_service)
    old_plan = entry.runtime_data.data.plan
    assert old_plan is not None
    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    prices = [
        {
            "start": (start + timedelta(hours=index)).isoformat(),
            "end": (start + timedelta(hours=index + 1)).isoformat(),
            "price": 2.0 if index == 0 else 0.2,
        }
        for index in range(8)
    ]
    hass.states.async_set(
        "sensor.price_forecast",
        "published",
        {
            "unit_of_measurement": "SEK/kWh",
            "publication_id": "delayed-13-47-publication",
            "prices": prices,
        },
    )
    await hass.async_block_till_done()
    new_plan = entry.runtime_data.data.plan
    assert new_plan is not None
    assert new_plan.publication_key != old_plan.publication_key
    assert new_plan.forecast_end.timestamp() > old_plan.forecast_end.timestamp()
    assert output_service.await_count == 1


async def test_malformed_delayed_update_and_restart_continue_saved_plan(
    hass: HomeAssistant,
) -> None:
    """Keep a valid plan through malformed publication and Home Assistant reload."""
    output_service = AsyncMock()
    entry = await _setup(hass, output_service)
    original = entry.runtime_data.data.plan
    assert original is not None
    hass.states.async_set(
        "sensor.price_forecast",
        "malformed-delayed",
        {"unit_of_measurement": "SEK/kWh", "prices": [1.0, 2.0]},
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.data.plan == original
    assert entry.runtime_data.data.plan_status is PlanStatus.SAVED_PLAN

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.data.plan.publication_key == original.publication_key
    assert entry.runtime_data.data.plan.reserve_until == original.reserve_until
    assert entry.runtime_data.data.plan_status is PlanStatus.SAVED_PLAN
    assert "Continuing last valid plan" in entry.runtime_data.data.plan_reason
    assert output_service.await_count == 3
    assert all(
        call.args[0].service == "turn_off" for call in output_service.await_args_list
    )


async def test_missing_tomorrow_values_preserve_energy_at_horizon(
    hass: HomeAssistant,
) -> None:
    """A one-period replacement remains valid but does not dump tank energy."""
    output_service = AsyncMock()
    entry = await _setup(hass, output_service)
    original = entry.runtime_data.data.plan
    assert original is not None
    start = dt_util.utcnow()
    hass.states.async_set(
        "sensor.price_forecast",
        "published-short",
        {
            "unit_of_measurement": "SEK/kWh",
            "publication_id": "missing-tomorrow",
            "prices": [
                {
                    "start": start.isoformat(),
                    "end": (start + timedelta(hours=1)).isoformat(),
                    "price": 1.0,
                }
            ],
        },
    )
    await hass.async_block_till_done()
    plan = entry.runtime_data.data.plan
    assert plan == original
    assert entry.runtime_data.data.plan_status is PlanStatus.SAVED_PLAN
    assert "shorter horizon" in entry.runtime_data.data.plan_reason
    assert output_service.await_count == 1


async def test_energy_and_weather_replan_with_saved_prices(hass: HomeAssistant) -> None:
    """A charge and changed weather update allocations even during provider failure."""
    entry = await _setup(hass, AsyncMock())
    old = entry.runtime_data.data.plan
    hass.states.async_set("sensor.price_forecast", "unavailable")
    hass.states.async_set("sensor.tank_top", "75", {"unit_of_measurement": "°C"})
    hass.states.async_set(
        "sensor.outdoor_temperature", "-15", {"unit_of_measurement": "°C"}
    )
    await hass.async_block_till_done()
    new = entry.runtime_data.data.plan
    assert new is not None
    assert old is not None
    assert new.publication_key == old.publication_key
    assert new.available_energy_kwh != old.available_energy_kwh
    assert new.intervals[0].forecast.outdoor_temperature_c == -15
    assert new.reserve_until == old.reserve_until


async def test_periodic_planning_refreshes_unchanged_inputs(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The timer rebuilds demand with unchanged publication and inputs."""
    entry = await _setup(hass, AsyncMock())
    coordinator = entry.runtime_data
    original = coordinator.data.plan
    assert original is not None
    freezer.tick(timedelta(minutes=16))
    coordinator._async_validity_refresh(coordinator.data.captured_at)  # noqa: SLF001
    await hass.async_block_till_done()
    new = coordinator.data.plan
    assert new is not None
    assert new.optimized_at > original.optimized_at
    assert new.publication_key == original.publication_key
    assert new.reserve_until == original.reserve_until

"""Home Assistant tests for publication rollover and dry-run persistence."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_OFF
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermal_storage_optimizer.const import (
    CONF_HEAT_PUMP_ELECTRICAL_POWER,
    CONF_MEASURED_COP,
    CONF_SUPPLEMENTARY_HEATER_POWER,
    CONF_TEMPERATURE_CURVES,
    CONF_WEATHER,
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


def _publish_prices(hass: HomeAssistant) -> None:
    """Publish a six-hour price fixture starting at the current hour."""
    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    hass.states.async_set(
        "sensor.price_forecast",
        "published",
        {
            "unit_of_measurement": "SEK/kWh",
            "publication_id": f"rolling-{start.isoformat()}",
            "prices": [
                {
                    "start": (start + timedelta(hours=index)).isoformat(),
                    "end": (start + timedelta(hours=index + 1)).isoformat(),
                    "price": price,
                }
                for index, price in enumerate((0.5, 0.4, 1.4, 0.7, 1.8, 0.6))
            ],
        },
    )


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
    assert coordinator.data.plan_reason.startswith("Rolling allocation optimized; ")
    # A refresh that reuses the plan must not leave a dangling separator.
    coordinator._async_validity_refresh(coordinator.data.captured_at)  # noqa: SLF001
    await hass.async_block_till_done()
    assert coordinator.data.plan is new
    assert not coordinator.data.plan_reason.startswith(";")
    assert "+00:00" not in coordinator.data.plan_reason
    assert new.optimized_at > original.optimized_at
    assert new.publication_key == original.publication_key
    assert new.reserve_until == original.reserve_until


async def test_hourly_weather_forecast_drives_interval_demand(
    hass: HomeAssistant,
) -> None:
    """Each interval uses its own bias-corrected forecast temperature."""
    set_valid_required_states(hass)
    hass.states.async_set("weather.home", "cloudy", {"temperature_unit": "°C"})
    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)

    async def get_forecasts(_call: ServiceCall) -> dict[str, object]:
        return {
            "weather.home": {
                "forecast": [
                    {
                        "datetime": (start + timedelta(hours=index)).isoformat(),
                        "temperature": 6 - 3 * index,
                    }
                    for index in range(12)
                ]
            }
        }

    action = AsyncMock(side_effect=get_forecasts)
    hass.services.async_register(
        "weather", "get_forecasts", action, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=INTEGRATION_NAME,
        unique_id=UNIQUE_ID,
        data={**REQUIRED_CONFIG, CONF_WEATHER: "weather.home"},
        version=3,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert action.await_count == 1
    assert action.await_args.args[0].data["type"] == "hourly"
    plan = entry.runtime_data.data.plan
    assert plan is not None
    temperatures = [item.forecast.outdoor_temperature_c for item in plan.intervals]
    assert temperatures == sorted(temperatures, reverse=True)
    assert temperatures[0] > temperatures[-1] + 5
    assert temperatures[-1] < 0
    # The measured 5 °C corrects the near-term forecast; the far horizon follows it.
    assert abs(temperatures[0] - 5) < 1.5
    assert entry.runtime_data.adapter.outdoor_forecast_error is None

    hass.states.async_set("weather.home", "rainy", {"temperature_unit": "°C"})
    await hass.async_block_till_done()
    assert action.await_count == 2


async def test_weather_forecast_failure_falls_back_to_measured_outdoor(
    hass: HomeAssistant,
) -> None:
    """An unavailable or malformed forecast never blocks planning."""
    set_valid_required_states(hass)
    hass.states.async_set("weather.home", "cloudy", {"temperature_unit": "°C"})
    hass.services.async_register(
        "weather",
        "get_forecasts",
        AsyncMock(return_value={"weather.home": {"forecast": []}}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=INTEGRATION_NAME,
        unique_id=UNIQUE_ID,
        data={**REQUIRED_CONFIG, CONF_WEATHER: "weather.home"},
        version=3,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    plan = entry.runtime_data.data.plan
    assert plan is not None
    assert {item.forecast.outdoor_temperature_c for item in plan.intervals} == {5}
    assert entry.runtime_data.data.plan_status is PlanStatus.FULL_FORECAST
    assert "too few" in str(entry.runtime_data.adapter.outdoor_forecast_error)


async def test_learned_heating_curve_sets_interval_supply_targets(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Enabled curve learning fills bins and the forecast uses them per interval."""
    set_valid_required_states(hass)
    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=INTEGRATION_NAME,
        unique_id=UNIQUE_ID,
        data=REQUIRED_CONFIG,
        options={CONF_TEMPERATURE_CURVES: True},
        version=3,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    curve_id = _entity_id(hass, "sensor", f"{entry.entry_id}_temperature_curves")
    assert _state(hass, curve_id).state == "learning"
    assert all(
        item.forecast.supply_temperature_c == 45
        for item in coordinator.data.plan.intervals
    )

    # Alternate between a mild and a cold bin with a 1.2 K/K reference curve.
    # Republish prices each step so the fixture horizon never expires.
    for index in range(16):
        outdoor = 4.0 if index % 2 else -5.0
        freezer.tick(timedelta(minutes=31))
        _publish_prices(hass)
        for entity_id, value in (
            ("sensor.tank_top", "60"),
            ("sensor.tank_middle", "50"),
            ("sensor.tank_bottom", "40"),
            ("sensor.return_temperature", "30"),
        ):
            hass.states.async_set(
                entity_id, value, {"unit_of_measurement": "°C"}, force_update=True
            )
        hass.states.async_set(
            "sensor.supply_target",
            str(20 + 1.2 * (17 - outdoor)),
            {"unit_of_measurement": "°C"},
        )
        hass.states.async_set(
            "sensor.outdoor_temperature", str(outdoor), {"unit_of_measurement": "°C"}
        )
        await hass.async_block_till_done()
    assert _state(hass, curve_id).state == "active"
    bins = _state(hass, curve_id).attributes["heating_curve"]["bins"]
    assert len(bins) == 2
    plan = coordinator.data.plan
    assert plan is not None
    # The last measured outdoor temperature is 4 °C, so every interval uses the
    # learned mild-bin supply target instead of the raw current setpoint.
    assert {
        round(item.forecast.supply_temperature_c or 0, 1) for item in plan.intervals
    } == {round(20 + 1.2 * (17 - 4.0), 1)}

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert _state(hass, curve_id).state == "active"

    response = await hass.services.async_call(
        DOMAIN, "reset_learned_state", blocking=True, return_response=True
    )
    assert "heating_curve" in response["reset_items"]
    assert _state(hass, curve_id).state == "learning"


async def test_learned_cop_curve_drives_per_interval_cop_and_current_source(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A measured COP sensor teaches per-bin COP used per interval and as fallback."""
    set_valid_required_states(hass)
    hass.states.async_set("sensor.measured_cop", "3.4")
    hass.states.async_set("weather.home", "cloudy", {"temperature_unit": "°C"})
    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)

    async def get_forecasts(_call: ServiceCall) -> dict[str, object]:
        now = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        return {
            "weather.home": {
                "forecast": [
                    {
                        "datetime": (now + timedelta(hours=index)).isoformat(),
                        "temperature": 5 - 2 * index,
                    }
                    for index in range(12)
                ]
            }
        }

    hass.services.async_register(
        "weather",
        "get_forecasts",
        AsyncMock(side_effect=get_forecasts),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=INTEGRATION_NAME,
        unique_id=UNIQUE_ID,
        data={
            **REQUIRED_CONFIG,
            CONF_MEASURED_COP: "sensor.measured_cop",
            CONF_WEATHER: "weather.home",
        },
        options={CONF_TEMPERATURE_CURVES: True},
        version=3,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    source_id = _entity_id(hass, "sensor", f"{entry.entry_id}_cop_source")
    assert _state(hass, source_id).state == "measured"
    assert {item.forecast.cop for item in coordinator.data.plan.intervals} == {3.4}
    del start

    # End on the mild bin so the measured 5 °C matches the forecast start and
    # no bias correction distorts the per-interval temperatures.
    for index in range(19):
        outdoor, cop = ((5.0, 3.4), (-1.0, 2.9), (-7.0, 2.3))[index % 3]
        freezer.tick(timedelta(minutes=31))
        _publish_prices(hass)
        for entity_id, value in (
            ("sensor.tank_top", "60"),
            ("sensor.tank_middle", "50"),
            ("sensor.tank_bottom", "40"),
            ("sensor.return_temperature", "30"),
            ("sensor.supply_target", "45"),
        ):
            hass.states.async_set(
                entity_id, value, {"unit_of_measurement": "°C"}, force_update=True
            )
        hass.states.async_set("sensor.measured_cop", str(cop))
        hass.states.async_set(
            "sensor.outdoor_temperature", str(outdoor), {"unit_of_measurement": "°C"}
        )
        await hass.async_block_till_done()
    assert coordinator.curves.cop_curve_usable(coordinator.data.captured_at)
    # A weather-entity update refreshes the hourly forecast from the current hour.
    hass.states.async_set("weather.home", "rainy", {"temperature_unit": "°C"})
    await hass.async_block_till_done()
    plan = coordinator.data.plan
    assert plan is not None
    temperatures = [item.forecast.outdoor_temperature_c for item in plan.intervals]
    assert temperatures[0] > temperatures[-1]
    cops = [item.forecast.cop for item in plan.intervals]
    # The forecast cools over the horizon, so the per-interval COP must fall.
    assert cops == sorted(cops, reverse=True)
    assert cops[0] > cops[-1]
    assert _state(hass, source_id).state == "measured"

    hass.states.async_set("sensor.measured_cop", "unavailable")
    await hass.async_block_till_done()
    assert _state(hass, source_id).state == "learned_curve"
    assert coordinator.data.cop is not None
    assert coordinator.data.cop.value == pytest.approx(3.4, abs=0.05)


async def test_supplementary_heater_lowers_effective_cop(hass: HomeAssistant) -> None:
    """Separate heater and heat-pump power meters yield a system COP and share."""
    set_valid_required_states(hass)
    hass.states.async_set("sensor.measured_cop", "3.0")
    hass.states.async_set("sensor.hp_power", "2000", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.heater_power", "3", {"unit_of_measurement": "kW"})
    hass.services.async_register("switch", "turn_on", AsyncMock())
    hass.services.async_register("switch", "turn_off", AsyncMock())
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=INTEGRATION_NAME,
        unique_id=UNIQUE_ID,
        data={
            **REQUIRED_CONFIG,
            CONF_MEASURED_COP: "sensor.measured_cop",
            CONF_HEAT_PUMP_ELECTRICAL_POWER: "sensor.hp_power",
            CONF_SUPPLEMENTARY_HEATER_POWER: "sensor.heater_power",
        },
        version=3,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    data = entry.runtime_data.data
    assert data.cop is not None
    assert data.cop.value == pytest.approx(9 / 5)
    assert data.cop.source.value == "measured"
    assert data.supplementary_heat_share == pytest.approx(1 / 3)
    assert all(item.forecast.cop == pytest.approx(1.8) for item in data.plan.intervals)
    share_id = _entity_id(hass, "sensor", f"{entry.entry_id}_supplementary_heat_share")
    assert float(_state(hass, share_id).state) == pytest.approx(100 / 3, abs=0.01)

    hass.states.async_set("sensor.heater_power", "0", {"unit_of_measurement": "kW"})
    await hass.async_block_till_done()
    data = entry.runtime_data.data
    assert data.cop is not None
    assert data.cop.value == 3.0
    assert data.supplementary_heat_share == 0

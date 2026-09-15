"""Tests for the Home Assistant boundary adapter."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermal_storage_optimizer.adapter import (
    HomeAssistantInputAdapter,
)
from custom_components.thermal_storage_optimizer.const import (
    CONF_HEAT_PUMP_ELECTRICAL_POWER,
    CONF_PRICE_FORECAST,
    CONF_SENSOR_STALE_AFTER,
    CONF_TANK_TOP,
)
from custom_components.thermal_storage_optimizer.inputs import InputProblem
from custom_components.thermal_storage_optimizer.price import PriceNormalizationConfig

from .helpers import REQUIRED_CONFIG, set_valid_required_states


def test_adapter_reads_only_configured_entities(hass: HomeAssistant) -> None:
    """Test subscriptions are bounded to entity references in entry data."""
    configured = {
        **REQUIRED_CONFIG,
        CONF_HEAT_PUMP_ELECTRICAL_POWER: "sensor.heat_pump_power",
    }

    adapter = HomeAssistantInputAdapter(hass, configured, {})

    assert set(adapter.entity_ids) == set(configured.values())


def test_adapter_normalizes_ha_states_and_optional_quantities(
    hass: HomeAssistant,
) -> None:
    """Test raw HA state objects are isolated behind canonical typed values."""
    set_valid_required_states(hass)
    hass.states.async_set("sensor.tank_top", "140", {"unit_of_measurement": "°F"})
    hass.states.async_set(
        "sensor.heat_pump_power", "2500", {"unit_of_measurement": "W"}
    )
    configured = {
        **REQUIRED_CONFIG,
        CONF_HEAT_PUMP_ELECTRICAL_POWER: "sensor.heat_pump_power",
    }

    snapshot = HomeAssistantInputAdapter(hass, configured, {}).snapshot()

    assert snapshot.is_valid
    assert snapshot.values[CONF_TANK_TOP].value == pytest.approx(60.0)
    assert snapshot.values[CONF_TANK_TOP].unit == "°C"
    assert snapshot.values[CONF_HEAT_PUMP_ELECTRICAL_POWER].value == pytest.approx(2.5)
    assert snapshot.values[CONF_HEAT_PUMP_ELECTRICAL_POWER].unit == "kW"


def test_adapter_reports_missing_unit_and_stale_state(hass: HomeAssistant) -> None:
    """Test HA metadata and timestamps produce explicit diagnostic problems."""
    set_valid_required_states(hass)
    hass.states.async_set("sensor.tank_top", "60", force_update=True)

    missing_unit = HomeAssistantInputAdapter(hass, REQUIRED_CONFIG, {}).snapshot()

    assert not missing_unit.is_valid
    assert (
        next(
            issue for issue in missing_unit.issues if issue.key == CONF_TANK_TOP
        ).problem
        is InputProblem.INCOMPATIBLE_UNIT
    )

    old_timestamp = (dt_util.utcnow() - timedelta(minutes=2)).timestamp()
    hass.states.async_set(
        "sensor.tank_top",
        "60",
        {"unit_of_measurement": "°C"},
        force_update=True,
        timestamp=old_timestamp,
    )
    stale = HomeAssistantInputAdapter(
        hass,
        REQUIRED_CONFIG,
        {CONF_SENSOR_STALE_AFTER: 60},
    ).snapshot()

    assert not stale.is_valid
    assert (
        next(issue for issue in stale.issues if issue.key == CONF_TANK_TOP).problem
        is InputProblem.STALE
    )


async def test_official_nordpool_sensor_uses_timestamped_response_action(
    hass: HomeAssistant,
) -> None:
    """Fetch today and tomorrow from the core Nord Pool action contract."""
    nordpool_entry = MockConfigEntry(
        domain="nordpool",
        title="Nord Pool",
        data={"areas": ["SE3"], "currency": "SEK"},
        version=1,
    )
    nordpool_entry.add_to_hass(hass)
    registry_entry = er.async_get(hass).async_get_or_create(
        "sensor",
        "nordpool",
        "SE3-current_price",
        suggested_object_id="nord_pool_se3_current_price",
        config_entry=nordpool_entry,
    )
    hass.states.async_set(
        registry_entry.entity_id,
        "0.5",
        {"unit_of_measurement": "SEK/kWh"},
    )

    async def get_prices(call: ServiceCall) -> dict[str, object]:
        requested = call.data["date"]
        start = dt_util.start_of_local_day().replace(
            year=requested.year,
            month=requested.month,
            day=requested.day,
        )
        return {
            "SE3": [
                {
                    "start": start.isoformat(),
                    "end": (start + timedelta(minutes=15)).isoformat(),
                    "price": 500.0,
                }
            ]
        }

    action = AsyncMock(side_effect=get_prices)
    hass.services.async_register(
        "nordpool",
        "get_prices_for_date",
        action,
        supports_response=SupportsResponse.ONLY,
    )
    configured = {**REQUIRED_CONFIG, CONF_PRICE_FORECAST: registry_entry.entity_id}
    adapter = HomeAssistantInputAdapter(hass, configured, {})
    config = PriceNormalizationConfig()
    await adapter.async_prepare_price_forecast(config)
    result = adapter.price_forecast(config)

    assert action.await_count == 2
    assert len(result.intervals) == 2
    assert result.intervals[0].marginal_cost_per_kwh == pytest.approx(0.5)
    assert result.intervals[0].duration == timedelta(minutes=15)
    assert result.source_token.startswith(f"nordpool:{nordpool_entry.entry_id}:SE3:")


def test_timestamped_raw_today_and_tomorrow_attributes_are_supported(
    hass: HomeAssistant,
) -> None:
    """Accept the established custom Nord Pool raw timestamp/value schema."""
    set_valid_required_states(hass)
    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    hass.states.async_set(
        "sensor.price_forecast",
        "0.5",
        {
            "unit_of_measurement": "SEK/kWh",
            "raw_today": [
                {
                    "start": start.isoformat(),
                    "end": (start + timedelta(hours=1)).isoformat(),
                    "value": 0.5,
                }
            ],
            "raw_tomorrow": [
                {
                    "start": (start + timedelta(hours=1)).isoformat(),
                    "end": (start + timedelta(hours=2)).isoformat(),
                    "value": 0.8,
                }
            ],
        },
    )
    result = HomeAssistantInputAdapter(hass, REQUIRED_CONFIG, {}).price_forecast(
        PriceNormalizationConfig()
    )
    assert [item.marginal_cost_per_kwh for item in result.intervals] == [0.5, 0.8]

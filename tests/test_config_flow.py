"""Tests for the Thermal Storage Optimizer config flow."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermal_storage_optimizer.const import (
    CONF_ACTIVE_CONTROL,
    CONF_ACTUAL_SUPPLY_TEMPERATURE,
    CONF_ADDITIVE_VARIABLE_COST,
    CONF_BALANCE_TEMPERATURE,
    CONF_BOTTOM_LAYER_VOLUME,
    CONF_ECONOMIC_DEADBAND,
    CONF_FIXED_COP,
    CONF_FORECAST_CONFIDENCE,
    CONF_FORECAST_STALE_AFTER,
    CONF_HEAT_LOSS_COEFFICIENT,
    CONF_HIGH_TEMPERATURE_HYSTERESIS,
    CONF_HIGH_TEMPERATURE_THRESHOLD,
    CONF_HOURLY_RETENTION,
    CONF_MIDDLE_LAYER_VOLUME,
    CONF_MINIMUM_DWELL_TIME,
    CONF_MINIMUM_USEFUL_DELTA,
    CONF_OUTPUT_INVERTED,
    CONF_PRICE_MULTIPLIER,
    CONF_SENSOR_STALE_AFTER,
    CONF_STARTUP_GRACE_PERIOD,
    CONF_TOP_LAYER_VOLUME,
    CONF_TOTAL_TANK_VOLUME,
    CONF_TREND_DEADBAND,
    CONF_USABLE_CAPACITY,
    DOMAIN,
    INTEGRATION_NAME,
    UNIQUE_ID,
)

from .helpers import OPTIONAL_CONFIG, REQUIRED_CONFIG


async def test_user_flow_stores_required_and_optional_entities(
    hass: HomeAssistant,
) -> None:
    """Test entity selectors, setup, and duplicate prevention."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    configured = {**REQUIRED_CONFIG, **OPTIONAL_CONFIG}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=configured
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == INTEGRATION_NAME
    assert result["data"] == configured
    assert result["result"].unique_id == UNIQUE_ID

    duplicate = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert duplicate["type"] is FlowResultType.ABORT
    assert duplicate["reason"] == "single_instance_allowed"


async def test_reconfigure_changes_only_entry_data(hass: HomeAssistant) -> None:
    """Test entity references are replaced while options are preserved."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=INTEGRATION_NAME,
        unique_id=UNIQUE_ID,
        data=REQUIRED_CONFIG,
        options={CONF_SENSOR_STALE_AFTER: 1800},
        version=2,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    changed = {
        **REQUIRED_CONFIG,
        CONF_ACTUAL_SUPPLY_TEMPERATURE: "sensor.actual_supply",
    }
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=changed
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert dict(entry.data) == changed
    assert dict(entry.options) == {
        CONF_ACTIVE_CONTROL: False,
        CONF_SENSOR_STALE_AFTER: 1800,
    }


async def test_options_flow_stores_only_tuning_values(hass: HomeAssistant) -> None:
    """Test freshness tuning is stored in options, separate from entity IDs."""
    entry = MockConfigEntry(domain=DOMAIN, title=INTEGRATION_NAME, data=REQUIRED_CONFIG)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    options = {
        CONF_SENSOR_STALE_AFTER: 7200,
        CONF_FORECAST_STALE_AFTER: 86400,
        CONF_TOTAL_TANK_VOLUME: 600,
        CONF_TOP_LAYER_VOLUME: 200,
        CONF_MIDDLE_LAYER_VOLUME: 200,
        CONF_BOTTOM_LAYER_VOLUME: 200,
        CONF_MINIMUM_USEFUL_DELTA: 4,
        CONF_USABLE_CAPACITY: 35,
        CONF_TREND_DEADBAND: 0.2,
        CONF_HEAT_LOSS_COEFFICIENT: 0.25,
        CONF_BALANCE_TEMPERATURE: 16,
        CONF_FIXED_COP: 3.5,
        CONF_PRICE_MULTIPLIER: 1.25,
        CONF_ADDITIVE_VARIABLE_COST: 0.4,
        CONF_HOURLY_RETENTION: 0.99,
        CONF_FORECAST_CONFIDENCE: 0.8,
        CONF_ECONOMIC_DEADBAND: 0.1,
        CONF_ACTIVE_CONTROL: False,
        CONF_OUTPUT_INVERTED: False,
        CONF_HIGH_TEMPERATURE_THRESHOLD: 82,
        CONF_HIGH_TEMPERATURE_HYSTERESIS: 4,
        CONF_STARTUP_GRACE_PERIOD: 300,
        CONF_MINIMUM_DWELL_TIME: 1800,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=options
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert {key: result["data"][key] for key in options} == options
    assert result["data"]["adaptive_calibration_enabled"] is False
    assert dict(entry.data) == REQUIRED_CONFIG
    await hass.async_block_till_done()
    if entry.state is config_entries.ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(entry.entry_id)


async def test_options_flow_rejects_inconsistent_layer_volumes(
    hass: HomeAssistant,
) -> None:
    """Test the UI cannot persist a physically inconsistent tank model."""
    entry = MockConfigEntry(domain=DOMAIN, title=INTEGRATION_NAME, data=REQUIRED_CONFIG)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_SENSOR_STALE_AFTER: 7200,
            CONF_FORECAST_STALE_AFTER: 86400,
            CONF_TOTAL_TANK_VOLUME: 500,
            CONF_TOP_LAYER_VOLUME: 100,
            CONF_MIDDLE_LAYER_VOLUME: 100,
            CONF_BOTTOM_LAYER_VOLUME: 100,
            CONF_MINIMUM_USEFUL_DELTA: 3,
            CONF_USABLE_CAPACITY: 30,
            CONF_TREND_DEADBAND: 0.1,
            CONF_HEAT_LOSS_COEFFICIENT: 0.3,
            CONF_BALANCE_TEMPERATURE: 17,
            CONF_FIXED_COP: 3,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_layer_volumes"}


async def test_options_flow_rejects_hysteresis_at_or_above_high_limit(
    hass: HomeAssistant,
) -> None:
    """Keep the thermal forced-use release boundary physically meaningful."""
    entry = MockConfigEntry(domain=DOMAIN, title=INTEGRATION_NAME, data=REQUIRED_CONFIG)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_HIGH_TEMPERATURE_THRESHOLD: 20,
            CONF_HIGH_TEMPERATURE_HYSTERESIS: 20,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_high_temperature_hysteresis"}

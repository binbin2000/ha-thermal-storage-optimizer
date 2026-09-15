"""Test data helpers for Thermal Storage Optimizer."""

from datetime import timedelta

from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.thermal_storage_optimizer.const import (
    CONF_ACTUAL_SUPPLY_TEMPERATURE,
    CONF_FLOW_RATE,
    CONF_HEAT_PUMP_ELECTRICAL_ENERGY,
    CONF_HEAT_PUMP_ELECTRICAL_POWER,
    CONF_HEAT_PUMP_PRODUCED_HEAT,
    CONF_INDOOR_TEMPERATURE,
    CONF_MEASURED_COP,
    CONF_NOTIFICATION_TARGET,
    CONF_OUTDOOR_TEMPERATURE,
    CONF_PRICE_FORECAST,
    CONF_RESERVE_OUTPUT,
    CONF_RETURN_TEMPERATURE,
    CONF_STOVE_CHARGING_PUMP,
    CONF_STOVE_FLOW_TEMPERATURE,
    CONF_SUPPLY_TARGET,
    CONF_TANK_BOTTOM,
    CONF_TANK_MIDDLE,
    CONF_TANK_TOP,
    CONF_WEATHER,
)

REQUIRED_CONFIG: dict[str, str] = {
    CONF_TANK_TOP: "sensor.tank_top",
    CONF_TANK_MIDDLE: "sensor.tank_middle",
    CONF_TANK_BOTTOM: "sensor.tank_bottom",
    CONF_RETURN_TEMPERATURE: "sensor.return_temperature",
    CONF_SUPPLY_TARGET: "sensor.supply_target",
    CONF_OUTDOOR_TEMPERATURE: "sensor.outdoor_temperature",
    CONF_PRICE_FORECAST: "sensor.price_forecast",
    CONF_RESERVE_OUTPUT: "switch.reserve_output",
}

OPTIONAL_CONFIG: dict[str, str] = {
    CONF_ACTUAL_SUPPLY_TEMPERATURE: "sensor.actual_supply_temperature",
    CONF_INDOOR_TEMPERATURE: "sensor.indoor_temperature",
    CONF_WEATHER: "weather.home",
    CONF_HEAT_PUMP_ELECTRICAL_POWER: "sensor.heat_pump_electrical_power",
    CONF_HEAT_PUMP_ELECTRICAL_ENERGY: "sensor.heat_pump_electrical_energy",
    CONF_HEAT_PUMP_PRODUCED_HEAT: "sensor.heat_pump_produced_heat",
    CONF_MEASURED_COP: "sensor.measured_cop",
    CONF_STOVE_CHARGING_PUMP: "binary_sensor.stove_charging_pump",
    CONF_STOVE_FLOW_TEMPERATURE: "sensor.stove_flow_temperature",
    CONF_FLOW_RATE: "sensor.tank_flow_rate",
    CONF_NOTIFICATION_TARGET: "notify.mobile_app",
}


def set_valid_required_states(hass: HomeAssistant) -> None:
    """Create a complete valid state fixture."""
    temperatures = {
        "sensor.tank_top": "60",
        "sensor.tank_middle": "50",
        "sensor.tank_bottom": "40",
        "sensor.return_temperature": "30",
        "sensor.supply_target": "45",
        "sensor.outdoor_temperature": "5",
    }
    for entity_id, value in temperatures.items():
        hass.states.async_set(
            entity_id,
            value,
            {"unit_of_measurement": UnitOfTemperature.CELSIUS},
        )
    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    prices = [
        {
            "start": (start + timedelta(hours=index)).isoformat(),
            "end": (start + timedelta(hours=index + 1)).isoformat(),
            "price": price,
        }
        for index, price in enumerate((0.5, 0.4, 1.4, 0.7, 1.8, 0.6))
    ]
    hass.states.async_set(
        "sensor.price_forecast",
        "published",
        {
            "unit_of_measurement": "SEK/kWh",
            "publication_id": "representative-fixture",
            "prices": prices,
        },
    )
    hass.states.async_set("switch.reserve_output", "off")

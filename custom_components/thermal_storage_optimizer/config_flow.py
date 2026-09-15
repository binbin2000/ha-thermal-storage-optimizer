"""Config and options flows for Thermal Storage Optimizer."""

from __future__ import annotations

from typing import Any, override

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import UnitOfTime
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_ACTIVE_CONTROL,
    CONF_ACTUAL_SUPPLY_TEMPERATURE,
    CONF_ADAPTIVE_CALIBRATION,
    CONF_ADDITIVE_VARIABLE_COST,
    CONF_ADVISOR_LANGUAGE,
    CONF_ALLOW_EXCEPTIONAL_FIRING,
    CONF_BALANCE_MAX,
    CONF_BALANCE_MIN,
    CONF_BALANCE_TEMPERATURE,
    CONF_BOTTOM_LAYER_VOLUME,
    CONF_CALIBRATION_MIN_CONFIDENCE,
    CONF_CAPACITY_MAX,
    CONF_CAPACITY_MIN,
    CONF_CHARGING_POWER_MAX,
    CONF_CHARGING_POWER_MIN,
    CONF_CHARGING_SLOPE_THRESHOLD,
    CONF_COP_MAX,
    CONF_COP_MIN,
    CONF_ECONOMIC_DEADBAND,
    CONF_FIXED_COP,
    CONF_FLOW_RATE,
    CONF_FORCED_USE_MARGIN,
    CONF_FORECAST_CONFIDENCE,
    CONF_FORECAST_STALE_AFTER,
    CONF_HEAT_LOSS_COEFFICIENT,
    CONF_HEAT_LOSS_MAX,
    CONF_HEAT_LOSS_MIN,
    CONF_HEAT_PUMP_ELECTRICAL_ENERGY,
    CONF_HEAT_PUMP_ELECTRICAL_POWER,
    CONF_HEAT_PUMP_PRODUCED_HEAT,
    CONF_HIGH_TEMPERATURE_HYSTERESIS,
    CONF_HIGH_TEMPERATURE_THRESHOLD,
    CONF_HOURLY_RETENTION,
    CONF_INDOOR_TEMPERATURE,
    CONF_INITIAL_CHARGING_POWER,
    CONF_MAXIMUM_BOTTOM_TEMPERATURE,
    CONF_MAXIMUM_FIRING_DURATION,
    CONF_MAXIMUM_MIDDLE_TEMPERATURE,
    CONF_MAXIMUM_TOP_TEMPERATURE,
    CONF_MEASURED_COP,
    CONF_MIDDLE_LAYER_VOLUME,
    CONF_MINIMUM_AVOIDED_COST,
    CONF_MINIMUM_DWELL_TIME,
    CONF_MINIMUM_FIRING_DURATION,
    CONF_MINIMUM_USEFUL_DELTA,
    CONF_NOTIFICATION_LEAD_TIME,
    CONF_NOTIFICATION_MATERIAL_CHANGE,
    CONF_NOTIFICATION_TARGET,
    CONF_NOTIFICATION_UPDATE_INTERVAL,
    CONF_OUTDOOR_TEMPERATURE,
    CONF_OUTPUT_INVERTED,
    CONF_PREFERRED_FIRING_WINDOWS,
    CONF_PRICE_FORECAST,
    CONF_PRICE_MULTIPLIER,
    CONF_QUIET_HOURS_END,
    CONF_QUIET_HOURS_START,
    CONF_REPLAN_INTERVAL,
    CONF_RESERVE_OUTPUT,
    CONF_RESIDUAL_BURN_ENERGY,
    CONF_RESIDUAL_MAX,
    CONF_RESIDUAL_MIN,
    CONF_RETURN_TEMPERATURE,
    CONF_SENSOR_STALE_AFTER,
    CONF_SNOOZE_DURATION,
    CONF_STARTUP_GRACE_PERIOD,
    CONF_STOVE_CHARGING_PUMP,
    CONF_STOVE_EFFICIENCY,
    CONF_STOVE_FLOW_TEMPERATURE,
    CONF_STOVE_TEMPERATURE_THRESHOLD,
    CONF_SUPPLY_TARGET,
    CONF_TANK_BOTTOM,
    CONF_TANK_MIDDLE,
    CONF_TANK_TOP,
    CONF_TOP_LAYER_VOLUME,
    CONF_TOTAL_TANK_VOLUME,
    CONF_TREND_DEADBAND,
    CONF_USABLE_CAPACITY,
    CONF_WEATHER,
    CONF_WOOD_COST,
    CONF_WOOD_ENERGY_CONTENT,
    CONFIG_ENTRY_MINOR_VERSION,
    CONFIG_ENTRY_VERSION,
    DEFAULT_ACTIVE_CONTROL,
    DEFAULT_ADAPTIVE_CALIBRATION,
    DEFAULT_ADDITIVE_VARIABLE_COST,
    DEFAULT_BALANCE_MAX,
    DEFAULT_BALANCE_MIN,
    DEFAULT_BALANCE_TEMPERATURE,
    DEFAULT_CALIBRATION_MIN_CONFIDENCE,
    DEFAULT_CAPACITY_MAX,
    DEFAULT_CAPACITY_MIN,
    DEFAULT_CHARGING_POWER_MAX,
    DEFAULT_CHARGING_POWER_MIN,
    DEFAULT_COP_MAX,
    DEFAULT_COP_MIN,
    DEFAULT_ECONOMIC_DEADBAND,
    DEFAULT_FIXED_COP,
    DEFAULT_FORECAST_CONFIDENCE,
    DEFAULT_FORECAST_STALE_AFTER,
    DEFAULT_HEAT_LOSS_COEFFICIENT,
    DEFAULT_HEAT_LOSS_MAX,
    DEFAULT_HEAT_LOSS_MIN,
    DEFAULT_HIGH_TEMPERATURE_HYSTERESIS,
    DEFAULT_HIGH_TEMPERATURE_THRESHOLD,
    DEFAULT_HOURLY_RETENTION,
    DEFAULT_LAYER_VOLUME,
    DEFAULT_MINIMUM_DWELL_TIME,
    DEFAULT_MINIMUM_USEFUL_DELTA,
    DEFAULT_OUTPUT_INVERTED,
    DEFAULT_PREFERRED_FIRING_WINDOWS,
    DEFAULT_PRICE_MULTIPLIER,
    DEFAULT_REPLAN_INTERVAL,
    DEFAULT_RESIDUAL_MAX,
    DEFAULT_RESIDUAL_MIN,
    DEFAULT_SENSOR_STALE_AFTER,
    DEFAULT_STARTUP_GRACE_PERIOD,
    DEFAULT_TOTAL_TANK_VOLUME,
    DEFAULT_TREND_DEADBAND,
    DEFAULT_USABLE_CAPACITY,
    DOMAIN,
    INTEGRATION_NAME,
    UNIQUE_ID,
)


def _entity_selector(
    *, domain: str | list[str], device_class: SensorDeviceClass | None = None
) -> selector.EntitySelector:
    config = selector.EntitySelectorConfig(domain=domain)
    if device_class is not None:
        config["device_class"] = device_class
    return selector.EntitySelector(config)


TEMPERATURE_SELECTOR = _entity_selector(
    domain="sensor", device_class=SensorDeviceClass.TEMPERATURE
)
ENTITY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TANK_TOP): TEMPERATURE_SELECTOR,
        vol.Required(CONF_TANK_MIDDLE): TEMPERATURE_SELECTOR,
        vol.Required(CONF_TANK_BOTTOM): TEMPERATURE_SELECTOR,
        vol.Required(CONF_RETURN_TEMPERATURE): TEMPERATURE_SELECTOR,
        vol.Required(CONF_SUPPLY_TARGET): TEMPERATURE_SELECTOR,
        vol.Required(CONF_OUTDOOR_TEMPERATURE): TEMPERATURE_SELECTOR,
        vol.Required(CONF_PRICE_FORECAST): _entity_selector(domain="sensor"),
        vol.Required(CONF_RESERVE_OUTPUT): _entity_selector(
            domain=["switch", "input_boolean"]
        ),
        vol.Optional(CONF_ACTUAL_SUPPLY_TEMPERATURE): TEMPERATURE_SELECTOR,
        vol.Optional(CONF_INDOOR_TEMPERATURE): TEMPERATURE_SELECTOR,
        vol.Optional(CONF_WEATHER): _entity_selector(domain="weather"),
        vol.Optional(CONF_HEAT_PUMP_ELECTRICAL_POWER): _entity_selector(
            domain="sensor", device_class=SensorDeviceClass.POWER
        ),
        vol.Optional(CONF_HEAT_PUMP_ELECTRICAL_ENERGY): _entity_selector(
            domain="sensor", device_class=SensorDeviceClass.ENERGY
        ),
        vol.Optional(CONF_HEAT_PUMP_PRODUCED_HEAT): _entity_selector(
            domain="sensor", device_class=SensorDeviceClass.ENERGY
        ),
        vol.Optional(CONF_MEASURED_COP): _entity_selector(domain="sensor"),
        vol.Optional(CONF_STOVE_CHARGING_PUMP): _entity_selector(
            domain=["binary_sensor", "switch", "input_boolean"]
        ),
        vol.Optional(CONF_STOVE_FLOW_TEMPERATURE): TEMPERATURE_SELECTOR,
        vol.Optional(CONF_FLOW_RATE): _entity_selector(
            domain="sensor", device_class=SensorDeviceClass.VOLUME_FLOW_RATE
        ),
        vol.Optional(CONF_NOTIFICATION_TARGET): _entity_selector(domain="notify"),
    }
)


def _number_selector(
    minimum: float, maximum: float, step: float, unit: str | None = None
) -> selector.NumberSelector:
    """Build a box-style numeric option selector."""
    config = selector.NumberSelectorConfig(
        min=minimum,
        max=maximum,
        step=step,
        mode=selector.NumberSelectorMode.BOX,
    )
    if unit is not None:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


def _validate_options(options: dict[str, Any]) -> dict[str, Any]:
    """Validate physical model and controller relationships."""
    total = float(options.get(CONF_TOTAL_TANK_VOLUME, DEFAULT_TOTAL_TANK_VOLUME))
    layers = sum(
        float(options.get(key, DEFAULT_LAYER_VOLUME))
        for key in (
            CONF_TOP_LAYER_VOLUME,
            CONF_MIDDLE_LAYER_VOLUME,
            CONF_BOTTOM_LAYER_VOLUME,
        )
    )
    volume_tolerance_l = 0.01
    if abs(total - layers) > volume_tolerance_l:
        message = "layer volumes must sum to total tank volume"
        raise vol.Invalid(message)
    if float(
        options.get(
            CONF_HIGH_TEMPERATURE_HYSTERESIS, DEFAULT_HIGH_TEMPERATURE_HYSTERESIS
        )
    ) >= float(
        options.get(CONF_HIGH_TEMPERATURE_THRESHOLD, DEFAULT_HIGH_TEMPERATURE_THRESHOLD)
    ):
        message = "high-temperature hysteresis must be below the threshold"
        raise vol.Invalid(message)
    minimum = float(options.get(CONF_MINIMUM_FIRING_DURATION, 30))
    maximum = float(options.get(CONF_MAXIMUM_FIRING_DURATION, 240))
    if minimum > maximum:
        message = "minimum firing duration must not exceed maximum"
        raise vol.Invalid(message)
    for minimum_key, maximum_key, default_minimum, default_maximum in (
        (
            CONF_CAPACITY_MIN,
            CONF_CAPACITY_MAX,
            DEFAULT_CAPACITY_MIN,
            DEFAULT_CAPACITY_MAX,
        ),
        (
            CONF_HEAT_LOSS_MIN,
            CONF_HEAT_LOSS_MAX,
            DEFAULT_HEAT_LOSS_MIN,
            DEFAULT_HEAT_LOSS_MAX,
        ),
        (CONF_BALANCE_MIN, CONF_BALANCE_MAX, DEFAULT_BALANCE_MIN, DEFAULT_BALANCE_MAX),
        (CONF_COP_MIN, CONF_COP_MAX, DEFAULT_COP_MIN, DEFAULT_COP_MAX),
        (
            CONF_CHARGING_POWER_MIN,
            CONF_CHARGING_POWER_MAX,
            DEFAULT_CHARGING_POWER_MIN,
            DEFAULT_CHARGING_POWER_MAX,
        ),
        (
            CONF_RESIDUAL_MIN,
            CONF_RESIDUAL_MAX,
            DEFAULT_RESIDUAL_MIN,
            DEFAULT_RESIDUAL_MAX,
        ),
    ):
        if float(options.get(minimum_key, default_minimum)) > float(
            options.get(maximum_key, default_maximum)
        ):
            message = "calibration minimum must not exceed maximum"
            raise vol.Invalid(message)
    from .firing_schedule import parse_preferred_windows  # noqa: PLC0415

    try:
        parse_preferred_windows(
            options.get(CONF_PREFERRED_FIRING_WINDOWS, DEFAULT_PREFERRED_FIRING_WINDOWS)
        )
    except ValueError as err:
        raise vol.Invalid(str(err)) from err
    return options


OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(
            CONF_ADAPTIVE_CALIBRATION, default=DEFAULT_ADAPTIVE_CALIBRATION
        ): selector.BooleanSelector(),
        vol.Required(
            CONF_CALIBRATION_MIN_CONFIDENCE,
            default=DEFAULT_CALIBRATION_MIN_CONFIDENCE,
        ): _number_selector(0.5, 1, 0.01),
        vol.Required(CONF_CAPACITY_MIN, default=DEFAULT_CAPACITY_MIN): _number_selector(
            1, 500, 0.1, "kWh"
        ),
        vol.Required(CONF_CAPACITY_MAX, default=DEFAULT_CAPACITY_MAX): _number_selector(
            1, 500, 0.1, "kWh"
        ),
        vol.Required(
            CONF_HEAT_LOSS_MIN, default=DEFAULT_HEAT_LOSS_MIN
        ): _number_selector(0, 10, 0.01, "kW/K"),
        vol.Required(
            CONF_HEAT_LOSS_MAX, default=DEFAULT_HEAT_LOSS_MAX
        ): _number_selector(0, 10, 0.01, "kW/K"),
        vol.Required(CONF_BALANCE_MIN, default=DEFAULT_BALANCE_MIN): _number_selector(
            -20, 35, 0.1, "°C"
        ),
        vol.Required(CONF_BALANCE_MAX, default=DEFAULT_BALANCE_MAX): _number_selector(
            -20, 35, 0.1, "°C"
        ),
        vol.Required(CONF_COP_MIN, default=DEFAULT_COP_MIN): _number_selector(
            0.1, 15, 0.1
        ),
        vol.Required(CONF_COP_MAX, default=DEFAULT_COP_MAX): _number_selector(
            0.1, 15, 0.1
        ),
        vol.Required(
            CONF_CHARGING_POWER_MIN, default=DEFAULT_CHARGING_POWER_MIN
        ): _number_selector(0.1, 100, 0.1, "kW"),
        vol.Required(
            CONF_CHARGING_POWER_MAX, default=DEFAULT_CHARGING_POWER_MAX
        ): _number_selector(0.1, 100, 0.1, "kW"),
        vol.Required(CONF_RESIDUAL_MIN, default=DEFAULT_RESIDUAL_MIN): _number_selector(
            0, 50, 0.1, "kWh"
        ),
        vol.Required(CONF_RESIDUAL_MAX, default=DEFAULT_RESIDUAL_MAX): _number_selector(
            0, 50, 0.1, "kWh"
        ),
        vol.Required(
            CONF_SENSOR_STALE_AFTER, default=DEFAULT_SENSOR_STALE_AFTER
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=60,
                max=86400,
                step=60,
                mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement=UnitOfTime.SECONDS,
            )
        ),
        vol.Required(
            CONF_FORECAST_STALE_AFTER, default=DEFAULT_FORECAST_STALE_AFTER
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=3600,
                max=259200,
                step=3600,
                mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement=UnitOfTime.SECONDS,
            )
        ),
        vol.Required(
            CONF_TOTAL_TANK_VOLUME, default=DEFAULT_TOTAL_TANK_VOLUME
        ): _number_selector(1, 10000, 0.1, "L"),
        vol.Required(
            CONF_TOP_LAYER_VOLUME, default=DEFAULT_LAYER_VOLUME
        ): _number_selector(0.1, 10000, 0.1, "L"),
        vol.Required(
            CONF_MIDDLE_LAYER_VOLUME, default=DEFAULT_LAYER_VOLUME
        ): _number_selector(0.1, 10000, 0.1, "L"),
        vol.Required(
            CONF_BOTTOM_LAYER_VOLUME, default=DEFAULT_LAYER_VOLUME
        ): _number_selector(0.1, 10000, 0.1, "L"),
        vol.Required(
            CONF_MINIMUM_USEFUL_DELTA, default=DEFAULT_MINIMUM_USEFUL_DELTA
        ): _number_selector(0, 30, 0.1, "°C"),
        vol.Required(
            CONF_USABLE_CAPACITY, default=DEFAULT_USABLE_CAPACITY
        ): _number_selector(0.1, 500, 0.1, "kWh"),
        vol.Required(
            CONF_TREND_DEADBAND, default=DEFAULT_TREND_DEADBAND
        ): _number_selector(0, 20, 0.01, "kWh"),
        vol.Required(
            CONF_HEAT_LOSS_COEFFICIENT,
            default=DEFAULT_HEAT_LOSS_COEFFICIENT,
        ): _number_selector(0, 10, 0.01, "kW/K"),
        vol.Required(
            CONF_BALANCE_TEMPERATURE, default=DEFAULT_BALANCE_TEMPERATURE
        ): _number_selector(-20, 35, 0.1, "°C"),
        vol.Required(CONF_FIXED_COP, default=DEFAULT_FIXED_COP): _number_selector(
            0.1, 15, 0.1
        ),
        vol.Required(
            CONF_PRICE_MULTIPLIER, default=DEFAULT_PRICE_MULTIPLIER
        ): _number_selector(0, 100, 0.001),
        vol.Required(
            CONF_ADDITIVE_VARIABLE_COST,
            default=DEFAULT_ADDITIVE_VARIABLE_COST,
        ): _number_selector(-100, 100, 0.001, "currency/kWh"),
        vol.Required(
            CONF_HOURLY_RETENTION, default=DEFAULT_HOURLY_RETENTION
        ): _number_selector(0.9, 1, 0.001),
        vol.Required(
            CONF_FORECAST_CONFIDENCE, default=DEFAULT_FORECAST_CONFIDENCE
        ): _number_selector(0, 1, 0.01),
        vol.Required(
            CONF_ECONOMIC_DEADBAND, default=DEFAULT_ECONOMIC_DEADBAND
        ): _number_selector(0, 100, 0.001, "currency/kWh heat"),
        vol.Required(
            CONF_REPLAN_INTERVAL, default=DEFAULT_REPLAN_INTERVAL
        ): _number_selector(1, 60, 1, "min"),
        vol.Required(
            CONF_ACTIVE_CONTROL, default=DEFAULT_ACTIVE_CONTROL
        ): selector.BooleanSelector(),
        vol.Required(
            CONF_OUTPUT_INVERTED, default=DEFAULT_OUTPUT_INVERTED
        ): selector.BooleanSelector(),
        vol.Required(
            CONF_HIGH_TEMPERATURE_THRESHOLD,
            default=DEFAULT_HIGH_TEMPERATURE_THRESHOLD,
        ): _number_selector(20, 120, 0.5, "°C"),
        vol.Required(
            CONF_HIGH_TEMPERATURE_HYSTERESIS,
            default=DEFAULT_HIGH_TEMPERATURE_HYSTERESIS,
        ): _number_selector(0.5, 30, 0.5, "°C"),
        vol.Required(
            CONF_STARTUP_GRACE_PERIOD, default=DEFAULT_STARTUP_GRACE_PERIOD
        ): _number_selector(0, 3600, 1, "s"),
        vol.Required(
            CONF_MINIMUM_DWELL_TIME, default=DEFAULT_MINIMUM_DWELL_TIME
        ): _number_selector(0, 14400, 1, "s"),
        vol.Optional(CONF_PREFERRED_FIRING_WINDOWS): selector.ObjectSelector(),
        vol.Optional(CONF_MINIMUM_FIRING_DURATION): _number_selector(1, 720, 1, "min"),
        vol.Optional(CONF_MAXIMUM_FIRING_DURATION): _number_selector(1, 720, 1, "min"),
        vol.Optional(CONF_NOTIFICATION_LEAD_TIME): _number_selector(0, 1440, 1, "min"),
        vol.Optional(CONF_QUIET_HOURS_START): selector.TimeSelector(),
        vol.Optional(CONF_QUIET_HOURS_END): selector.TimeSelector(),
        vol.Optional(CONF_ALLOW_EXCEPTIONAL_FIRING): selector.BooleanSelector(),
        vol.Optional(CONF_INITIAL_CHARGING_POWER): _number_selector(0, 100, 0.1, "kW"),
        vol.Optional(CONF_STOVE_TEMPERATURE_THRESHOLD): _number_selector(
            0, 150, 0.5, "°C"
        ),
        vol.Optional(CONF_CHARGING_SLOPE_THRESHOLD): _number_selector(
            0, 100, 0.1, "kW"
        ),
        vol.Optional(CONF_MAXIMUM_TOP_TEMPERATURE): _number_selector(
            20, 120, 0.5, "°C"
        ),
        vol.Optional(CONF_MAXIMUM_MIDDLE_TEMPERATURE): _number_selector(
            20, 120, 0.5, "°C"
        ),
        vol.Optional(CONF_MAXIMUM_BOTTOM_TEMPERATURE): _number_selector(
            20, 120, 0.5, "°C"
        ),
        vol.Optional(CONF_FORCED_USE_MARGIN): _number_selector(0, 30, 0.5, "°C"),
        vol.Optional(CONF_RESIDUAL_BURN_ENERGY): _number_selector(0, 50, 0.1, "kWh"),
        vol.Optional(CONF_MINIMUM_AVOIDED_COST): _number_selector(
            0, 1000, 0.1, "currency"
        ),
        vol.Optional(CONF_NOTIFICATION_UPDATE_INTERVAL): _number_selector(
            1, 1440, 1, "min"
        ),
        vol.Optional(CONF_NOTIFICATION_MATERIAL_CHANGE): _number_selector(
            0, 100, 0.1, "kWh"
        ),
        vol.Optional(CONF_SNOOZE_DURATION): _number_selector(1, 1440, 1, "min"),
        vol.Optional(CONF_ADVISOR_LANGUAGE): selector.SelectSelector(
            selector.SelectSelectorConfig(options=["auto", "en", "sv"])
        ),
        vol.Optional(CONF_WOOD_COST): _number_selector(0, 1000, 0.01, "currency/kg"),
        vol.Optional(CONF_WOOD_ENERGY_CONTENT): _number_selector(
            0.1, 20, 0.1, "kWh/kg"
        ),
        vol.Optional(CONF_STOVE_EFFICIENCY): _number_selector(0.01, 1, 0.01),
    }
)


class ThermalStorageOptimizerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle configuration for Thermal Storage Optimizer."""

    VERSION = CONFIG_ENTRY_VERSION
    MINOR_VERSION = CONFIG_ENTRY_MINOR_VERSION

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the single supported integration instance."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=ENTITY_SCHEMA)

        await self.async_set_unique_id(UNIQUE_ID)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=INTEGRATION_NAME, data=user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change entity references and reload the entry."""
        entry = self._get_reconfigure_entry()
        if user_input is None:
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=self.add_suggested_values_to_schema(
                    ENTITY_SCHEMA, dict(entry.data)
                ),
            )

        return self.async_update_reload_and_abort(entry, data=user_input)

    @staticmethod
    @callback
    @override
    def async_get_options_flow(
        _config_entry: config_entries.ConfigEntry,
    ) -> ThermalStorageOptimizerOptionsFlow:
        """Return the options flow handler."""
        return ThermalStorageOptimizerOptionsFlow()


class ThermalStorageOptimizerOptionsFlow(OptionsFlowWithReload):
    """Configure non-entity input-layer tuning values."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure model and staleness settings and reload the entry."""
        if user_input is None:
            return self.async_show_form(
                step_id="init",
                data_schema=self.add_suggested_values_to_schema(
                    OPTIONS_SCHEMA, dict(self.config_entry.options)
                ),
            )

        try:
            _validate_options(user_input)
        except vol.Invalid as err:
            if "hysteresis" in str(err):
                error = "invalid_high_temperature_hysteresis"
            elif "firing" in str(err):
                error = "invalid_firing_options"
            elif "calibration" in str(err):
                error = "invalid_calibration_bounds"
            else:
                error = "invalid_layer_volumes"
            return self.async_show_form(
                step_id="init",
                data_schema=self.add_suggested_values_to_schema(
                    OPTIONS_SCHEMA, user_input
                ),
                errors={"base": error},
            )
        return self.async_create_entry(title="", data=user_input)

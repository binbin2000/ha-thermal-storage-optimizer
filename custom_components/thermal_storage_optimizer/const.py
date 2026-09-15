"""Constants for Thermal Storage Optimizer."""

from typing import Final

from homeassistant.const import UnitOfTime

DOMAIN: Final = "thermal_storage_optimizer"
INTEGRATION_NAME: Final = "Thermal Storage Optimizer"
DEVICE_MODEL: Final = "Supervisory optimizer"
VERSION: Final = "1.0.0"
CONFIG_ENTRY_VERSION: Final = 6
CONFIG_ENTRY_MINOR_VERSION: Final = 1
UNIQUE_ID: Final = DOMAIN

CONF_TANK_TOP: Final = "tank_top_entity"
CONF_TANK_MIDDLE: Final = "tank_middle_entity"
CONF_TANK_BOTTOM: Final = "tank_bottom_entity"
CONF_RETURN_TEMPERATURE: Final = "return_temperature_entity"
CONF_SUPPLY_TARGET: Final = "supply_target_entity"
CONF_OUTDOOR_TEMPERATURE: Final = "outdoor_temperature_entity"
CONF_PRICE_FORECAST: Final = "price_forecast_entity"
CONF_RESERVE_OUTPUT: Final = "reserve_output_entity"

CONF_ACTUAL_SUPPLY_TEMPERATURE: Final = "actual_supply_temperature_entity"
CONF_INDOOR_TEMPERATURE: Final = "indoor_temperature_entity"
CONF_WEATHER: Final = "weather_entity"
CONF_HEAT_PUMP_ELECTRICAL_POWER: Final = "heat_pump_electrical_power_entity"
CONF_HEAT_PUMP_ELECTRICAL_ENERGY: Final = "heat_pump_electrical_energy_entity"
CONF_HEAT_PUMP_PRODUCED_HEAT: Final = "heat_pump_produced_heat_entity"
CONF_MEASURED_COP: Final = "measured_cop_entity"
CONF_STOVE_CHARGING_PUMP: Final = "stove_charging_pump_entity"
CONF_STOVE_FLOW_TEMPERATURE: Final = "stove_flow_temperature_entity"
CONF_FLOW_RATE: Final = "flow_rate_entity"
CONF_NOTIFICATION_TARGET: Final = "notification_target_entity"

CONF_SENSOR_STALE_AFTER: Final = "sensor_stale_after"
CONF_FORECAST_STALE_AFTER: Final = "forecast_stale_after"
CONF_TOTAL_TANK_VOLUME: Final = "total_tank_volume_l"
CONF_TOP_LAYER_VOLUME: Final = "top_layer_volume_l"
CONF_MIDDLE_LAYER_VOLUME: Final = "middle_layer_volume_l"
CONF_BOTTOM_LAYER_VOLUME: Final = "bottom_layer_volume_l"
CONF_MINIMUM_USEFUL_DELTA: Final = "minimum_useful_delta_c"
CONF_USABLE_CAPACITY: Final = "usable_capacity_kwh"
CONF_TREND_DEADBAND: Final = "trend_deadband_kwh"
CONF_HEAT_LOSS_COEFFICIENT: Final = "heat_loss_coefficient_kw_per_k"
CONF_BALANCE_TEMPERATURE: Final = "balance_temperature_c"
CONF_FIXED_COP: Final = "fixed_cop"
CONF_PRICE_MULTIPLIER: Final = "price_multiplier"
CONF_ADDITIVE_VARIABLE_COST: Final = "additive_variable_cost_per_kwh"
CONF_HOURLY_RETENTION: Final = "hourly_retention"
CONF_FORECAST_CONFIDENCE: Final = "forecast_confidence"
CONF_ECONOMIC_DEADBAND: Final = "economic_deadband_per_kwh"
CONF_ACTIVE_CONTROL: Final = "active_control"
CONF_OUTPUT_INVERTED: Final = "output_inverted"
CONF_HIGH_TEMPERATURE_THRESHOLD: Final = "high_temperature_threshold_c"
CONF_HIGH_TEMPERATURE_HYSTERESIS: Final = "high_temperature_hysteresis_c"
CONF_STARTUP_GRACE_PERIOD: Final = "startup_grace_period_s"
CONF_MINIMUM_DWELL_TIME: Final = "minimum_dwell_time_s"
CONF_PREFERRED_FIRING_WINDOWS: Final = "preferred_firing_windows"
CONF_MINIMUM_FIRING_DURATION: Final = "minimum_firing_duration_min"
CONF_MAXIMUM_FIRING_DURATION: Final = "maximum_firing_duration_min"
CONF_NOTIFICATION_LEAD_TIME: Final = "notification_lead_time_min"
CONF_QUIET_HOURS_START: Final = "quiet_hours_start"
CONF_QUIET_HOURS_END: Final = "quiet_hours_end"
CONF_ALLOW_EXCEPTIONAL_FIRING: Final = "allow_exceptional_out_of_window"
CONF_INITIAL_CHARGING_POWER: Final = "initial_net_charging_power_kw"
CONF_STOVE_TEMPERATURE_THRESHOLD: Final = "stove_temperature_threshold_c"
CONF_CHARGING_SLOPE_THRESHOLD: Final = "charging_slope_threshold_kw"
CONF_MAXIMUM_TOP_TEMPERATURE: Final = "maximum_top_temperature_c"
CONF_MAXIMUM_MIDDLE_TEMPERATURE: Final = "maximum_middle_temperature_c"
CONF_MAXIMUM_BOTTOM_TEMPERATURE: Final = "maximum_bottom_temperature_c"
CONF_FORCED_USE_MARGIN: Final = "forced_use_margin_c"
CONF_RESIDUAL_BURN_ENERGY: Final = "residual_burn_energy_kwh"
CONF_MINIMUM_AVOIDED_COST: Final = "minimum_avoided_electricity_cost"
CONF_NOTIFICATION_UPDATE_INTERVAL: Final = "notification_update_interval_min"
CONF_NOTIFICATION_MATERIAL_CHANGE: Final = "notification_material_change_kwh"
CONF_SNOOZE_DURATION: Final = "notification_snooze_duration_min"
CONF_ADVISOR_LANGUAGE: Final = "advisor_language"
CONF_WOOD_COST: Final = "wood_cost_per_kg"
CONF_WOOD_ENERGY_CONTENT: Final = "wood_energy_content_kwh_per_kg"
CONF_STOVE_EFFICIENCY: Final = "stove_to_tank_efficiency"
CONF_ADAPTIVE_CALIBRATION: Final = "adaptive_calibration_enabled"
CONF_CALIBRATION_MIN_CONFIDENCE: Final = "calibration_min_confidence"
CONF_CAPACITY_MIN: Final = "capacity_calibration_min_kwh"
CONF_CAPACITY_MAX: Final = "capacity_calibration_max_kwh"
CONF_HEAT_LOSS_MIN: Final = "heat_loss_calibration_min_kw_per_k"
CONF_HEAT_LOSS_MAX: Final = "heat_loss_calibration_max_kw_per_k"
CONF_BALANCE_MIN: Final = "balance_calibration_min_c"
CONF_BALANCE_MAX: Final = "balance_calibration_max_c"
CONF_COP_MIN: Final = "cop_calibration_min"
CONF_COP_MAX: Final = "cop_calibration_max"
CONF_CHARGING_POWER_MIN: Final = "charging_power_calibration_min_kw"
CONF_CHARGING_POWER_MAX: Final = "charging_power_calibration_max_kw"
CONF_RESIDUAL_MIN: Final = "residual_calibration_min_kwh"
CONF_RESIDUAL_MAX: Final = "residual_calibration_max_kwh"
DEFAULT_SENSOR_STALE_AFTER: Final = 3600
DEFAULT_FORECAST_STALE_AFTER: Final = 36 * 3600
DEFAULT_TOTAL_TANK_VOLUME: Final = 500.0
DEFAULT_LAYER_VOLUME: Final = DEFAULT_TOTAL_TANK_VOLUME / 3.0
DEFAULT_MINIMUM_USEFUL_DELTA: Final = 3.0
DEFAULT_USABLE_CAPACITY: Final = 30.0
DEFAULT_TREND_DEADBAND: Final = 0.1
DEFAULT_HEAT_LOSS_COEFFICIENT: Final = 0.3
DEFAULT_BALANCE_TEMPERATURE: Final = 17.0
DEFAULT_FIXED_COP: Final = 3.0
DEFAULT_PRICE_MULTIPLIER: Final = 1.0
DEFAULT_ADDITIVE_VARIABLE_COST: Final = 0.0
DEFAULT_HOURLY_RETENTION: Final = 0.995
DEFAULT_FORECAST_CONFIDENCE: Final = 0.85
DEFAULT_ECONOMIC_DEADBAND: Final = 0.05
DEFAULT_ACTIVE_CONTROL: Final = False
DEFAULT_OUTPUT_INVERTED: Final = False
DEFAULT_HIGH_TEMPERATURE_THRESHOLD: Final = 85.0
DEFAULT_HIGH_TEMPERATURE_HYSTERESIS: Final = 5.0
DEFAULT_STARTUP_GRACE_PERIOD: Final = 300
DEFAULT_MINIMUM_DWELL_TIME: Final = 1800
DEFAULT_PREFERRED_FIRING_WINDOWS: Final = dict.fromkeys(
    (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ),
    "15:00-23:00",
)
DEFAULT_MINIMUM_FIRING_DURATION: Final = 30
DEFAULT_MAXIMUM_FIRING_DURATION: Final = 240
DEFAULT_NOTIFICATION_LEAD_TIME: Final = 60
DEFAULT_QUIET_HOURS_START: Final = "23:00"
DEFAULT_QUIET_HOURS_END: Final = "07:00"
DEFAULT_ALLOW_EXCEPTIONAL_FIRING: Final = False
DEFAULT_INITIAL_CHARGING_POWER: Final = 6.0
DEFAULT_STOVE_TEMPERATURE_THRESHOLD: Final = 55.0
DEFAULT_CHARGING_SLOPE_THRESHOLD: Final = 1.0
DEFAULT_MAXIMUM_LAYER_TEMPERATURE: Final = 80.0
DEFAULT_FORCED_USE_MARGIN: Final = 3.0
DEFAULT_RESIDUAL_BURN_ENERGY: Final = 1.0
DEFAULT_MINIMUM_AVOIDED_COST: Final = 0.0
DEFAULT_NOTIFICATION_UPDATE_INTERVAL: Final = 15
DEFAULT_NOTIFICATION_MATERIAL_CHANGE: Final = 1.0
DEFAULT_SNOOZE_DURATION: Final = 60
DEFAULT_ADVISOR_LANGUAGE: Final = "en"
DEFAULT_ADAPTIVE_CALIBRATION: Final = False
DEFAULT_CALIBRATION_MIN_CONFIDENCE: Final = 0.7
DEFAULT_CAPACITY_MIN: Final = 10.0
DEFAULT_CAPACITY_MAX: Final = 80.0
DEFAULT_HEAT_LOSS_MIN: Final = 0.05
DEFAULT_HEAT_LOSS_MAX: Final = 2.0
DEFAULT_BALANCE_MIN: Final = 10.0
DEFAULT_BALANCE_MAX: Final = 24.0
DEFAULT_COP_MIN: Final = 1.0
DEFAULT_COP_MAX: Final = 7.0
DEFAULT_CHARGING_POWER_MIN: Final = 1.0
DEFAULT_CHARGING_POWER_MAX: Final = 30.0
DEFAULT_RESIDUAL_MIN: Final = 0.0
DEFAULT_RESIDUAL_MAX: Final = 10.0

SERVICE_START_FIRING: Final = "start_firing"
SERVICE_STOP_FIRING: Final = "stop_firing"
SERVICE_ACKNOWLEDGE: Final = "acknowledge_recommendation"
SERVICE_SNOOZE: Final = "snooze_recommendation"
SERVICE_DISMISS: Final = "dismiss_recommendation"
SERVICE_RECALCULATE: Final = "recalculate"
SERVICE_GET_PLAN_SUMMARY: Final = "get_plan_summary"
SERVICE_RESET_LEARNED_STATE: Final = "reset_learned_state"
DEFAULT_PLAN_SUMMARY_INTERVALS: Final = 12
MAX_PLAN_SUMMARY_INTERVALS: Final = 48
STALE_TIME_UNIT: Final = UnitOfTime.SECONDS

REQUIRED_ENTITY_KEYS: Final = (
    CONF_TANK_TOP,
    CONF_TANK_MIDDLE,
    CONF_TANK_BOTTOM,
    CONF_RETURN_TEMPERATURE,
    CONF_SUPPLY_TARGET,
    CONF_OUTDOOR_TEMPERATURE,
    CONF_PRICE_FORECAST,
    CONF_RESERVE_OUTPUT,
)

OPTIONAL_ENTITY_KEYS: Final = (
    CONF_ACTUAL_SUPPLY_TEMPERATURE,
    CONF_INDOOR_TEMPERATURE,
    CONF_WEATHER,
    CONF_HEAT_PUMP_ELECTRICAL_POWER,
    CONF_HEAT_PUMP_ELECTRICAL_ENERGY,
    CONF_HEAT_PUMP_PRODUCED_HEAT,
    CONF_MEASURED_COP,
    CONF_STOVE_CHARGING_PUMP,
    CONF_STOVE_FLOW_TEMPERATURE,
    CONF_FLOW_RATE,
    CONF_NOTIFICATION_TARGET,
)

CONF_REPLAN_INTERVAL: Final = "replan_interval_minutes"
DEFAULT_REPLAN_INTERVAL: Final = 15

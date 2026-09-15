"""Event-driven input coordination for Thermal Storage Optimizer."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .adaptive import (
    AdaptiveCalibration,
    CalibrationConfig,
    Observation,
    ParameterBounds,
)
from .advisor import ChargingAdvisor
from .const import (
    CONF_ADAPTIVE_CALIBRATION,
    CONF_ADDITIVE_VARIABLE_COST,
    CONF_BALANCE_MAX,
    CONF_BALANCE_MIN,
    CONF_BALANCE_TEMPERATURE,
    CONF_BOTTOM_LAYER_VOLUME,
    CONF_CALIBRATION_MIN_CONFIDENCE,
    CONF_CAPACITY_MAX,
    CONF_CAPACITY_MIN,
    CONF_CHARGING_POWER_MAX,
    CONF_CHARGING_POWER_MIN,
    CONF_COP_MAX,
    CONF_COP_MIN,
    CONF_ECONOMIC_DEADBAND,
    CONF_FIXED_COP,
    CONF_FORECAST_CONFIDENCE,
    CONF_HEAT_LOSS_COEFFICIENT,
    CONF_HEAT_LOSS_MAX,
    CONF_HEAT_LOSS_MIN,
    CONF_HEAT_PUMP_ELECTRICAL_ENERGY,
    CONF_HEAT_PUMP_PRODUCED_HEAT,
    CONF_HOURLY_RETENTION,
    CONF_INITIAL_CHARGING_POWER,
    CONF_MEASURED_COP,
    CONF_MIDDLE_LAYER_VOLUME,
    CONF_MINIMUM_USEFUL_DELTA,
    CONF_OUTDOOR_TEMPERATURE,
    CONF_PRICE_MULTIPLIER,
    CONF_REPLAN_INTERVAL,
    CONF_RESIDUAL_BURN_ENERGY,
    CONF_RESIDUAL_MAX,
    CONF_RESIDUAL_MIN,
    CONF_RETURN_TEMPERATURE,
    CONF_STOVE_CHARGING_PUMP,
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
    DEFAULT_HEAT_LOSS_COEFFICIENT,
    DEFAULT_HEAT_LOSS_MAX,
    DEFAULT_HEAT_LOSS_MIN,
    DEFAULT_HOURLY_RETENTION,
    DEFAULT_INITIAL_CHARGING_POWER,
    DEFAULT_LAYER_VOLUME,
    DEFAULT_MINIMUM_USEFUL_DELTA,
    DEFAULT_PRICE_MULTIPLIER,
    DEFAULT_REPLAN_INTERVAL,
    DEFAULT_RESIDUAL_BURN_ENERGY,
    DEFAULT_RESIDUAL_MAX,
    DEFAULT_RESIDUAL_MIN,
    DEFAULT_STOVE_TEMPERATURE_THRESHOLD,
    DEFAULT_TOTAL_TANK_VOLUME,
    DEFAULT_TREND_DEADBAND,
    DEFAULT_USABLE_CAPACITY,
    DOMAIN,
)
from .controller import SupervisoryController
from .cop import CopEstimate, CopSource, FixedCopModel, estimate_cop
from .data import PlanStatus, RuntimeSnapshot
from .demand import HeatDemandConfig, estimate_heat_demand_kwh
from .energy import TankTemperatures, ThermalEnergyConfig, estimate_thermal_state
from .forecast import ForecastModelConfig, build_economic_forecast
from .optimizer import OptimizationPlan, Recommendation, optimize_plan
from .price import (
    PriceForecast,
    PriceForecastError,
    PriceInterval,
    PriceNormalizationConfig,
)
from .storage import deserialize_plan, serialize_plan

if TYPE_CHECKING:
    from .adapter import HomeAssistantInputAdapter
    from .inputs import NormalizedInputSnapshot

_LOGGER = logging.getLogger(__name__)
_VALIDITY_REFRESH_INTERVAL = timedelta(minutes=1)
_STORAGE_VERSION = 1
_MAX_EXPLANATION_LENGTH: Final = 320


class InputCoordinator(DataUpdateCoordinator[RuntimeSnapshot]):
    """Refresh a normalized snapshot when any configured source changes."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        adapter: HomeAssistantInputAdapter,
    ) -> None:
        """Initialize an event-only coordinator."""
        super().__init__(hass, logger=_LOGGER, config_entry=entry, name=DOMAIN)
        self._entry = entry
        self._adapter = adapter
        options = dict(entry.options)
        self._energy_config = ThermalEnergyConfig(
            total_volume_l=_option(
                options, CONF_TOTAL_TANK_VOLUME, DEFAULT_TOTAL_TANK_VOLUME
            ),
            layer_volumes_l=(
                _option(options, CONF_TOP_LAYER_VOLUME, DEFAULT_LAYER_VOLUME),
                _option(options, CONF_MIDDLE_LAYER_VOLUME, DEFAULT_LAYER_VOLUME),
                _option(options, CONF_BOTTOM_LAYER_VOLUME, DEFAULT_LAYER_VOLUME),
            ),
            minimum_useful_delta_c=_option(
                options, CONF_MINIMUM_USEFUL_DELTA, DEFAULT_MINIMUM_USEFUL_DELTA
            ),
            usable_capacity_kwh=_option(
                options, CONF_USABLE_CAPACITY, DEFAULT_USABLE_CAPACITY
            ),
            trend_deadband_kwh=_option(
                options, CONF_TREND_DEADBAND, DEFAULT_TREND_DEADBAND
            ),
        )
        self._demand_config = HeatDemandConfig(
            heat_loss_coefficient_kw_per_k=_option(
                options, CONF_HEAT_LOSS_COEFFICIENT, DEFAULT_HEAT_LOSS_COEFFICIENT
            ),
            balance_temperature_c=_option(
                options, CONF_BALANCE_TEMPERATURE, DEFAULT_BALANCE_TEMPERATURE
            ),
        )
        self._cop_model = FixedCopModel(
            _option(options, CONF_FIXED_COP, DEFAULT_FIXED_COP)
        )
        self._price_config = PriceNormalizationConfig(
            multiplier=_option(
                options, CONF_PRICE_MULTIPLIER, DEFAULT_PRICE_MULTIPLIER
            ),
            additive_cost_per_kwh=_option(
                options,
                CONF_ADDITIVE_VARIABLE_COST,
                DEFAULT_ADDITIVE_VARIABLE_COST,
            ),
        )
        self._hourly_retention = _option(
            options, CONF_HOURLY_RETENTION, DEFAULT_HOURLY_RETENTION
        )
        self._forecast_confidence = _option(
            options, CONF_FORECAST_CONFIDENCE, DEFAULT_FORECAST_CONFIDENCE
        )
        self._economic_deadband = _option(
            options, CONF_ECONOMIC_DEADBAND, DEFAULT_ECONOMIC_DEADBAND
        )
        self._store = Store[dict[str, object]](
            hass, _STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.plan"
        )
        self._calibration_store = Store[dict[str, object]](
            hass, 1, f"{DOMAIN}.{entry.entry_id}.calibration"
        )
        self.calibration = AdaptiveCalibration(
            CalibrationConfig(
                enabled=options.get(
                    CONF_ADAPTIVE_CALIBRATION, DEFAULT_ADAPTIVE_CALIBRATION
                )
                is True,
                minimum_confidence=_option(
                    options,
                    CONF_CALIBRATION_MIN_CONFIDENCE,
                    DEFAULT_CALIBRATION_MIN_CONFIDENCE,
                ),
                capacity_fallback_kwh=self._energy_config.usable_capacity_kwh,
                heat_loss_fallback_kw_per_k=self._demand_config.heat_loss_coefficient_kw_per_k,
                balance_fallback_c=self._demand_config.balance_temperature_c,
                cop_fallback=self._cop_model.cop,
                charging_power_fallback_kw=_option(
                    options, CONF_INITIAL_CHARGING_POWER, DEFAULT_INITIAL_CHARGING_POWER
                ),
                residual_fallback_kwh=_option(
                    options, CONF_RESIDUAL_BURN_ENERGY, DEFAULT_RESIDUAL_BURN_ENERGY
                ),
                capacity_bounds=ParameterBounds(
                    _option(options, CONF_CAPACITY_MIN, DEFAULT_CAPACITY_MIN),
                    _option(options, CONF_CAPACITY_MAX, DEFAULT_CAPACITY_MAX),
                ),
                heat_loss_bounds=ParameterBounds(
                    _option(options, CONF_HEAT_LOSS_MIN, DEFAULT_HEAT_LOSS_MIN),
                    _option(options, CONF_HEAT_LOSS_MAX, DEFAULT_HEAT_LOSS_MAX),
                ),
                balance_bounds=ParameterBounds(
                    _option(options, CONF_BALANCE_MIN, DEFAULT_BALANCE_MIN),
                    _option(options, CONF_BALANCE_MAX, DEFAULT_BALANCE_MAX),
                ),
                cop_bounds=ParameterBounds(
                    _option(options, CONF_COP_MIN, DEFAULT_COP_MIN),
                    _option(options, CONF_COP_MAX, DEFAULT_COP_MAX),
                ),
                charging_power_bounds=ParameterBounds(
                    _option(
                        options, CONF_CHARGING_POWER_MIN, DEFAULT_CHARGING_POWER_MIN
                    ),
                    _option(
                        options, CONF_CHARGING_POWER_MAX, DEFAULT_CHARGING_POWER_MAX
                    ),
                ),
                residual_bounds=ParameterBounds(
                    _option(options, CONF_RESIDUAL_MIN, DEFAULT_RESIDUAL_MIN),
                    _option(options, CONF_RESIDUAL_MAX, DEFAULT_RESIDUAL_MAX),
                ),
            )
        )
        self._prices: PriceForecast | None = None
        self._planning_inputs: tuple[object, ...] | None = None
        self._reserve_until: datetime | None = None
        self._dispatch_timer: Callable[[], None] | None = None
        self._replan_interval = timedelta(
            minutes=_option(options, CONF_REPLAN_INTERVAL, DEFAULT_REPLAN_INTERVAL)
        )
        self._plan: OptimizationPlan | None = None
        self._plan_loaded_from_storage = False
        self.has_received_valid_data = False
        self._price_refresh_lock = asyncio.Lock()
        self._force_recalculation = False
        self.controller = SupervisoryController(hass, entry, self)
        self.advisor = ChargingAdvisor(hass, entry, self)

    async def async_start(self) -> None:
        """Create the initial snapshot, then subscribe for recovery updates."""
        await self._adapter.async_prepare_price_forecast(self._price_config)
        stored = await self._store.async_load()
        calibration = await self._calibration_store.async_load()
        self.calibration.restore(calibration, now=self._adapter.snapshot().captured_at)
        self._plan = deserialize_plan(stored, now=self._adapter.snapshot().captured_at)
        self._plan_loaded_from_storage = self._plan is not None
        if self._plan is not None:
            self._reserve_until = self._plan.reserve_until
            self._prices = PriceForecast(
                tuple(
                    PriceInterval(
                        p.forecast.start,
                        p.forecast.end,
                        p.forecast.duration,
                        p.forecast.electricity_cost_per_kwh,
                    )
                    for p in self._plan.intervals
                ),
                "restored",
                self._plan.publication_key,
                self._plan.forecast_end,
            )
        self._entry.async_on_unload(self._cancel_dispatch_timer)
        self._refresh_snapshot()
        unsubscribe = async_track_state_change_event(
            self.hass, self._adapter.entity_ids, self._async_state_changed
        )
        self._entry.async_on_unload(unsubscribe)
        self._entry.async_on_unload(
            async_track_time_interval(
                self.hass,
                self._async_validity_refresh,
                _VALIDITY_REFRESH_INTERVAL,
                cancel_on_shutdown=True,
            )
        )

    async def async_recalculate(self) -> None:
        """Refresh provider data and rebuild the plan from the current snapshot."""
        async with self._price_refresh_lock:
            await self._adapter.async_prepare_price_forecast(self._price_config)
            self._force_recalculation = True
            try:
                self._refresh_snapshot()
            finally:
                self._force_recalculation = False

    @callback
    def _async_state_changed(self, event: Event[EventStateChangedData]) -> None:
        """Publish a new snapshot after a relevant state change."""
        if (
            event.data["entity_id"] == self._adapter.price_entity_id
            and self._adapter.uses_official_nordpool
        ):
            self.hass.async_create_task(
                self._async_refresh_official_price(),
                f"refresh {DOMAIN} Nord Pool forecast",
            )
            return
        self._refresh_or_fallback()

    async def _async_refresh_official_price(self) -> None:
        """Serialize official Nord Pool response-action refreshes."""
        async with self._price_refresh_lock:
            await self._adapter.async_prepare_price_forecast(self._price_config)
            self._refresh_or_fallback()

    @callback
    def _async_validity_refresh(self, _now: datetime) -> None:
        """Re-evaluate timestamp freshness even when source values are unchanged."""
        self._refresh_or_fallback()

    @callback
    def _refresh_or_fallback(self) -> None:
        """Turn a recoverable runtime exception into an explicit safe fault."""
        try:
            self._refresh_snapshot()
        except Exception as err:
            _LOGGER.exception("Runtime refresh failed; requesting safe fallback")
            self.hass.async_create_task(
                self.controller.async_handle_fault(f"runtime refresh failed: {err}"),
                f"fallback {DOMAIN} controller",
            )

    @callback
    def _refresh_snapshot(self) -> None:
        """Publish the latest normalized snapshot."""
        inputs = self._adapter.snapshot()
        self.calibration.check_health(
            now=inputs.captured_at,
            tank_valid=inputs.is_valid,
            outdoor=_numeric_value(inputs, CONF_OUTDOOR_TEMPERATURE),
            heat_meter=_numeric_value(inputs, CONF_HEAT_PUMP_PRODUCED_HEAT),
            electric_meter=_numeric_value(inputs, CONF_HEAT_PUMP_ELECTRICAL_ENERGY),
            firing_available=_bool_value(inputs, CONF_STOVE_CHARGING_PUMP) is not None
            or _numeric_value(inputs, CONF_STOVE_FLOW_TEMPERATURE) is not None,
        )
        previous_energy = (
            self.data.thermal.usable_energy_kwh if self.data is not None else None
        )
        effective_energy_config = ThermalEnergyConfig(
            total_volume_l=self._energy_config.total_volume_l,
            layer_volumes_l=self._energy_config.layer_volumes_l,
            minimum_useful_delta_c=self._energy_config.minimum_useful_delta_c,
            usable_capacity_kwh=self.calibration.value(
                "usable_capacity_kwh", self._energy_config.usable_capacity_kwh
            ),
            trend_deadband_kwh=self._energy_config.trend_deadband_kwh,
        )
        effective_demand_config = HeatDemandConfig(
            heat_loss_coefficient_kw_per_k=self.calibration.value(
                "heat_loss_coefficient_kw_per_k",
                self._demand_config.heat_loss_coefficient_kw_per_k,
            ),
            balance_temperature_c=self.calibration.value(
                "balance_temperature_c", self._demand_config.balance_temperature_c
            ),
        )
        effective_cop_model = FixedCopModel(
            self.calibration.value("cop", self._cop_model.cop)
        )
        thermal = estimate_thermal_state(
            TankTemperatures(
                top_c=_numeric_value(inputs, CONF_TANK_TOP),
                middle_c=_numeric_value(inputs, CONF_TANK_MIDDLE),
                bottom_c=_numeric_value(inputs, CONF_TANK_BOTTOM),
                return_c=_numeric_value(inputs, CONF_RETURN_TEMPERATURE),
                supply_target_c=_numeric_value(inputs, CONF_SUPPLY_TARGET),
            ),
            effective_energy_config,
            previous_usable_energy_kwh=previous_energy,
        )
        outdoor = _numeric_value(inputs, CONF_OUTDOOR_TEMPERATURE)
        supply_target = _numeric_value(inputs, CONF_SUPPLY_TARGET)
        hourly_demand = None
        cop = None
        if outdoor is not None:
            hourly_demand = estimate_heat_demand_kwh(
                outdoor, timedelta(hours=1), effective_demand_config
            )
        if outdoor is not None and supply_target is not None:
            cop = estimate_cop(
                effective_cop_model,
                outdoor_temperature_c=outdoor,
                supply_temperature_c=supply_target,
                measured_cop=_numeric_value(inputs, CONF_MEASURED_COP),
            )
            calibrated_cop = self.calibration.parameters["cop"]
            if _numeric_value(
                inputs, CONF_MEASURED_COP
            ) is None and calibrated_cop.usable(
                self.calibration.config.minimum_confidence
            ):
                cop = CopEstimate(
                    cop.value, CopSource.CALIBRATED, calibrated_cop.confidence
                )
        plan, plan_status, reason, recommendation, rejected = self._update_plan(
            inputs.captured_at,
            thermal.usable_energy_kwh,
            thermal.confidence,
            outdoor,
            supply_target,
            _numeric_value(inputs, CONF_MEASURED_COP),
            cop.confidence if cop is not None else 0.0,
            demand_config=effective_demand_config,
            cop_model=effective_cop_model,
        )
        snapshot = RuntimeSnapshot(
            inputs,
            thermal,
            hourly_demand,
            cop,
            plan,
            plan_status,
            _bounded_explanation(reason),
            recommendation,
            rejected,
        )
        self.has_received_valid_data = self.has_received_valid_data or inputs.is_valid
        self.async_set_updated_data(snapshot)
        self._cancel_dispatch_timer()
        if plan is not None:
            transitions = [
                instant
                for p in plan.intervals
                for instant in (p.release_start, p.forecast.end)
                if instant > inputs.captured_at
            ]
            if transitions:
                self._dispatch_timer = async_track_point_in_utc_time(
                    self.hass, self._async_validity_refresh, min(transitions)
                )
        if thermal.usable_energy_kwh is not None:
            firing = _bool_value(inputs, CONF_STOVE_CHARGING_PUMP) is True or (
                _numeric_value(inputs, CONF_STOVE_FLOW_TEMPERATURE) or -math.inf
            ) >= _option(
                dict(self._entry.options),
                CONF_STOVE_TEMPERATURE_THRESHOLD,
                DEFAULT_STOVE_TEMPERATURE_THRESHOLD,
            )
            accepted = self.calibration.observe(
                Observation(
                    at=inputs.captured_at,
                    tank_energy_kwh=thermal.usable_energy_kwh,
                    outdoor_temperature_c=outdoor,
                    produced_heat_energy_kwh=_numeric_value(
                        inputs, CONF_HEAT_PUMP_PRODUCED_HEAT
                    ),
                    electrical_energy_kwh=_numeric_value(
                        inputs, CONF_HEAT_PUMP_ELECTRICAL_ENERGY
                    ),
                    firing_active=firing,
                    predicted_heat_power_kw=hourly_demand,
                    data_quality=thermal.confidence,
                )
            )
            if accepted:
                self.hass.async_create_task(
                    self._calibration_store.async_save(self.calibration.serialize()),
                    f"save {DOMAIN} calibration",
                )

    def _cancel_dispatch_timer(self) -> None:
        """Replace or remove the timer for the next binary dispatch boundary."""
        if self._dispatch_timer is not None:
            self._dispatch_timer()
            self._dispatch_timer = None

    async def async_reset_calibration(self) -> None:
        """Reset adaptive values without touching plans, modes, or safety state."""
        self.calibration.reset()
        await self._calibration_store.async_save(self.calibration.serialize())
        self._refresh_snapshot()

    def _update_plan(  # noqa: C901, PLR0911, PLR0913, PLR0917
        self,
        now: datetime,
        available_energy_kwh: float | None,
        thermal_confidence: float,
        outdoor_temperature_c: float | None,
        supply_temperature_c: float | None,
        measured_cop: float | None,
        cop_confidence: float,
        *,
        demand_config: HeatDemandConfig,
        cop_model: FixedCopModel,
    ) -> tuple[
        OptimizationPlan | None,
        PlanStatus,
        str,
        Recommendation,
        int,
    ]:
        """Create a new-publication plan or continue the last valid one."""
        if (
            self._plan is not None
            and self._plan.forecast_end.timestamp() <= now.timestamp()
        ):
            self._plan = None
            self._plan_loaded_from_storage = False
        rejected = 0
        continuation = ""
        prices: PriceForecast | None
        try:
            prices = self._adapter.price_forecast(self._price_config)
            rejected = prices.rejected_items
            if (
                self._prices is not None
                and prices.forecast_end < self._prices.forecast_end
            ):
                continuation = (
                    "Continuing last valid plan prices; shorter horizon rejected"
                )
            else:
                self._prices = prices
        except PriceForecastError as err:
            continuation = (
                f"Continuing last valid plan prices; new forecast invalid: {err}"
            )
        prices = self._prices
        if prices is None:
            return (
                None,
                PlanStatus.INVALID,
                continuation,
                Recommendation.WAITING,
                rejected,
            )
        planning_inputs = (
            available_energy_kwh,
            outdoor_temperature_c,
            supply_temperature_c,
            measured_cop,
            thermal_confidence,
            cop_confidence,
            demand_config,
            cop_model,
        )
        if (
            not self._force_recalculation
            and self._plan is not None
            and self._plan.publication_key == prices.publication_key
            and self._planning_inputs == planning_inputs
            and now - self._plan.optimized_at < self._replan_interval
        ):
            return (
                self._plan,
                PlanStatus.SAVED_PLAN if continuation else PlanStatus.FULL_FORECAST,
                f"{continuation}; {self._plan.decision_reason_at(now)}",
                self._plan.recommendation_at(now),
                rejected,
            )
        if (
            available_energy_kwh is None
            or outdoor_temperature_c is None
            or supply_temperature_c is None
        ):
            if self._plan is not None:
                return (
                    self._plan,
                    PlanStatus.SAVED_PLAN,
                    (
                        "Model inputs unavailable; continuing last valid plan; "
                        f"{self._plan.decision_reason_at(now)}"
                    ),
                    self._plan.recommendation_at(now),
                    rejected,
                )
            return (
                None,
                PlanStatus.WAITING,
                "Waiting for thermal and weather model inputs",
                Recommendation.WAITING,
                rejected,
            )
        confidence = self._forecast_confidence * thermal_confidence * cop_confidence
        model_config = ForecastModelConfig(self._hourly_retention, confidence)
        forecast = build_economic_forecast(
            prices,
            now=now,
            outdoor_temperature_c=float(outdoor_temperature_c),
            supply_temperature_c=float(supply_temperature_c),
            measured_cop=measured_cop,
            cop_model=cop_model,
            demand_config=demand_config,
            model_config=model_config,
        )
        if not forecast:
            if self._plan is not None:
                return (
                    self._plan,
                    PlanStatus.SAVED_PLAN,
                    "Continuing last valid plan; replacement has no future intervals",
                    self._plan.recommendation_at(now),
                    rejected,
                )
            return (
                None,
                PlanStatus.INVALID,
                "Price forecast has no future intervals",
                Recommendation.WAITING,
                rejected,
            )
        self._plan = optimize_plan(
            forecast,
            publication_key=prices.publication_key,
            optimized_at=now,
            available_energy_kwh=float(available_energy_kwh),
            economic_deadband_per_kwh=self._economic_deadband,
            reserve_until=self._reserve_until if available_energy_kwh > 0 else None,
            minimum_dwell_seconds=self.controller.config.minimum_dwell.total_seconds(),
            current_release_active=self.controller.decision.state.value == "USE_TANK",
        )
        self._plan_loaded_from_storage = False
        self._reserve_until = self._plan.reserve_until
        self._planning_inputs = planning_inputs
        self.hass.async_create_task(
            self._store.async_save(serialize_plan(self._plan)),
            f"save {DOMAIN} optimization plan",
        )
        reason = (
            f"{continuation or 'Rolling allocation optimized'}; "
            f"{self._plan.decision_reason_at(now)}"
        )
        if rejected:
            reason += f"; ignored {rejected} malformed interval(s)"
        return (
            self._plan,
            PlanStatus.SAVED_PLAN if continuation else PlanStatus.FULL_FORECAST,
            reason,
            self._plan.recommendation_at(now),
            rejected,
        )


def _option(options: dict[str, object], key: str, default: float) -> float:
    """Read one numeric option whose UI schema has already validated it."""
    return float(str(options.get(key, default)))


def _numeric_value(snapshot: NormalizedInputSnapshot, key: str) -> float | None:
    """Read a normalized numeric value without leaking HA state objects."""
    normalized = snapshot.values.get(key)
    if normalized is None or isinstance(normalized.value, (str, bool)):
        return None
    return normalized.value


def _bool_value(snapshot: NormalizedInputSnapshot, key: str) -> bool | None:
    """Read a normalized boolean value."""
    normalized = snapshot.values.get(key)
    return (
        normalized.value
        if normalized is not None and isinstance(normalized.value, bool)
        else None
    )


def _bounded_explanation(reason: str) -> str:
    """Keep entity-state explanations concise and single-line."""
    normalized = " ".join(reason.split())
    return (
        normalized
        if len(normalized) <= _MAX_EXPLANATION_LENGTH
        else f"{normalized[: _MAX_EXPLANATION_LENGTH - 3]}..."
    )

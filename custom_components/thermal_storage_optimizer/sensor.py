"""Sensor platform for Thermal Storage Optimizer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .controller import OperatingState, SupervisoryController
from .coordinator import InputCoordinator
from .data import IntegrationStatus, PlanStatus, RuntimeSnapshot
from .energy import DataQuality, EnergyTrend
from .price import forecast_coverage_hours

if TYPE_CHECKING:
    from .advisor import AdvisorState

type SensorValue = StateType | date | datetime | Decimal


@dataclass(frozen=True, kw_only=True)
class CalculatedSensorDescription(SensorEntityDescription):
    """Describe a calculated value read from a runtime snapshot."""

    value_fn: Callable[[RuntimeSnapshot], SensorValue]


CALCULATED_SENSORS: tuple[CalculatedSensorDescription, ...] = (
    CalculatedSensorDescription(
        key="energy",
        translation_key="energy",
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: data.thermal.usable_energy_kwh,
    ),
    CalculatedSensorDescription(
        key="high_grade_energy",
        translation_key="high_grade_energy",
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: data.thermal.high_grade_energy_kwh,
    ),
    CalculatedSensorDescription(
        key="soc",
        translation_key="soc",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.thermal.state_of_charge_percent,
    ),
    CalculatedSensorDescription(
        key="reference_temperature",
        translation_key="reference_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value_fn=lambda data: data.thermal.reference_temperature_c,
    ),
    CalculatedSensorDescription(
        key="stratification",
        translation_key="stratification",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value_fn=lambda data: data.thermal.stratification_delta_c,
    ),
    CalculatedSensorDescription(
        key="confidence",
        translation_key="confidence",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=lambda data: data.thermal.confidence * 100.0,
    ),
    CalculatedSensorDescription(
        key="data_quality",
        translation_key="data_quality",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
        options=[item.value for item in DataQuality],
        value_fn=lambda data: data.thermal.quality,
    ),
    CalculatedSensorDescription(
        key="trend",
        translation_key="trend",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
        options=[item.value for item in EnergyTrend],
        value_fn=lambda data: data.thermal.trend,
    ),
    CalculatedSensorDescription(
        key="hourly_heat_demand",
        translation_key="hourly_heat_demand",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=2,
        value_fn=lambda data: data.hourly_heat_demand_kwh,
    ),
    CalculatedSensorDescription(
        key="estimated_cop",
        translation_key="estimated_cop",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=2,
        value_fn=lambda data: data.cop.value if data.cop is not None else None,
    ),
    CalculatedSensorDescription(
        key="cop_source",
        translation_key="cop_source",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
        options=["measured", "calibrated", "fixed_fallback"],
        value_fn=lambda data: data.cop.source if data.cop is not None else None,
    ),
    CalculatedSensorDescription(
        key="forecast_end",
        translation_key="forecast_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.plan.forecast_end if data.plan is not None else None,
    ),
    CalculatedSensorDescription(
        key="forecast_coverage",
        translation_key="forecast_coverage",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value_fn=lambda data: (
            forecast_coverage_hours(
                forecast_end=data.plan.forecast_end,
                now=data.captured_at,
            )
            if data.plan is not None
            else None
        ),
    ),
    CalculatedSensorDescription(
        key="last_optimization",
        translation_key="last_optimization",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.plan.optimized_at if data.plan is not None else None,
    ),
    CalculatedSensorDescription(
        key="next_release",
        translation_key="next_release",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: (
            data.plan.next_release_at(data.captured_at)
            if data.plan is not None
            else None
        ),
    ),
    CalculatedSensorDescription(
        key="expected_savings",
        translation_key="expected_savings",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: (
            data.plan.expected_savings if data.plan is not None else None
        ),
    ),
    CalculatedSensorDescription(
        key="decision_reason",
        translation_key="decision_reason",
        value_fn=lambda data: data.plan_reason,
    ),
)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: ConfigEntry[InputCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Thermal Storage Optimizer sensors."""
    async_add_entities(
        [
            ThermalStorageOptimizerStatusSensor(entry),
            ThermalStorageOptimizerPlanStatusSensor(entry),
            ThermalStorageOptimizerOperatingStateSensor(entry),
            ThermalStorageOptimizerControllerReasonSensor(entry),
            ThermalStorageOptimizerCalibrationStatusSensor(entry),
            *(
                ThermalStorageOptimizerAdvisorSensor(entry, description)
                for description in ADVISOR_SENSORS
            ),
            *(
                ThermalStorageOptimizerCalculatedSensor(entry, description)
                for description in CALCULATED_SENSORS
            ),
        ]
    )


class ThermalStorageOptimizerCalibrationStatusSensor(
    CoordinatorEntity[InputCoordinator], SensorEntity
):
    """Expose bounded adaptive state without recording raw observations."""

    _attr_has_entity_name = True
    _attr_name = "Adaptive calibration status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry[InputCoordinator]) -> None:
        """Initialize the calibration status entity."""
        super().__init__(entry.runtime_data)
        self._attr_unique_id = f"{entry.entry_id}_adaptive_calibration_status"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def native_value(self) -> str:
        """Return the conservative adaptive activation state."""
        calibration = self.coordinator.calibration
        if not calibration.config.enabled:
            return "disabled"
        if any(
            item.usable(calibration.config.minimum_confidence)
            for item in calibration.parameters.values()
        ):
            return "active"
        return "learning"

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return learned metadata and bounded aggregate performance only."""
        calibration = self.coordinator.calibration
        report = calibration.performance_report(
            self.coordinator.data.plan.expected_savings
            if self.coordinator.data.plan is not None
            else None
        )
        return {
            "parameters": calibration.diagnostics()["parameters"],
            "performance": {
                "comparison_samples": report.comparison_samples,
                "modeled_heat_kwh": round(report.modeled_heat_kwh, 3),
                "observed_heat_kwh": round(report.observed_heat_kwh, 3),
                "mean_absolute_error_kwh": report.mean_absolute_error_kwh,
                "modeled_savings": report.modeled_savings,
                "measured_savings": report.measured_savings,
                "savings_label": report.savings_label,
                "fallback_reason": report.fallback_reason,
            },
        }


class ThermalStorageOptimizerStatusSensor(
    CoordinatorEntity[InputCoordinator], SensorEntity
):
    """Report the input layer's concise decision status."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_translation_key = "status"

    def __init__(self, entry: ConfigEntry[InputCoordinator]) -> None:
        """Initialize the diagnostic status sensor."""
        super().__init__(entry.runtime_data)
        self._attr_options = [status.value for status in IntegrationStatus]
        self._attr_unique_id = f"{entry.entry_id}_status"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
        )

    @property
    def native_value(self) -> IntegrationStatus:
        """Return ready, waiting, or invalid based on the current snapshot."""
        required_issues = self.coordinator.data.required_issues
        if not required_issues:
            return IntegrationStatus.READY
        startup_problems = {"missing", "unknown", "unavailable"}
        if not self.coordinator.has_received_valid_data and all(
            issue.problem.value in startup_problems for issue in required_issues
        ):
            return IntegrationStatus.WAITING_FOR_DATA
        return IntegrationStatus.INVALID_DATA

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose bounded issue details useful during commissioning."""
        issues = self.coordinator.data.issues
        return {
            "issue_count": len(issues),
            "required_issue_count": len(self.coordinator.data.required_issues),
            "issues": [f"{issue.key}:{issue.problem.value}" for issue in issues],
        }


class ThermalStorageOptimizerCalculatedSensor(
    CoordinatorEntity[InputCoordinator], SensorEntity
):
    """Expose one pure calculated model result."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry[InputCoordinator],
        description: CalculatedSensorDescription,
    ) -> None:
        """Initialize a calculated sensor from its immutable description."""
        super().__init__(entry.runtime_data)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def native_value(self) -> SensorValue:
        """Return the latest deterministic calculated value."""
        description = cast("CalculatedSensorDescription", self.entity_description)
        return description.value_fn(self.coordinator.data)


@dataclass(frozen=True, kw_only=True)
class AdvisorSensorDescription(SensorEntityDescription):
    """Describe one value owned only by the non-actuating advisor."""

    value_fn: Callable[[AdvisorState], SensorValue]


def _duration_minutes(value: object) -> float | None:
    """Convert an optional timedelta to recorder-friendly minutes."""
    from datetime import timedelta  # noqa: PLC0415

    return value.total_seconds() / 60 if isinstance(value, timedelta) else None


ADVISOR_SENSORS: tuple[AdvisorSensorDescription, ...] = (
    AdvisorSensorDescription(
        key="recommended_charge_duration",
        translation_key="recommended_charge_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda state: _duration_minutes(
            state.schedule.recommended_duration if state.schedule is not None else None
        ),
    ),
    AdvisorSensorDescription(
        key="recommended_start_earliest",
        translation_key="recommended_start_earliest",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda state: (
            state.schedule.earliest_useful_start if state.schedule is not None else None
        ),
    ),
    AdvisorSensorDescription(
        key="recommended_start_latest",
        translation_key="recommended_start_latest",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda state: (
            state.schedule.latest_start if state.schedule is not None else None
        ),
    ),
    AdvisorSensorDescription(
        key="charge_complete_by",
        translation_key="charge_complete_by",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda state: (
            state.schedule.required_completion if state.schedule is not None else None
        ),
    ),
    AdvisorSensorDescription(
        key="charge_target_energy",
        translation_key="charge_target_energy",
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda state: (
            state.target.additional_energy_kwh if state.target is not None else None
        ),
    ),
    AdvisorSensorDescription(
        key="charge_remaining_energy",
        translation_key="charge_remaining_energy",
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda state: (
            state.live.remaining_energy_kwh
            if state.live is not None
            else (
                state.target.additional_energy_kwh if state.target is not None else None
            )
        ),
    ),
    AdvisorSensorDescription(
        key="charge_remaining_time",
        translation_key="charge_remaining_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda state: _duration_minutes(
            state.live.minimum_remaining_time if state.live is not None else None
        ),
    ),
    AdvisorSensorDescription(
        key="charge_power",
        translation_key="charge_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=1,
        value_fn=lambda state: (
            state.live.smoothed_net_power_kw if state.live is not None else None
        ),
    ),
    AdvisorSensorDescription(
        key="charge_advice",
        translation_key="charge_advice",
        value_fn=lambda state: state.advice,
    ),
    AdvisorSensorDescription(
        key="estimated_avoided_electricity_cost",
        translation_key="estimated_avoided_electricity_cost",
        suggested_display_precision=2,
        value_fn=lambda state: state.estimated_avoided_electricity_cost,
    ),
    AdvisorSensorDescription(
        key="estimated_net_saving",
        translation_key="estimated_net_saving",
        suggested_display_precision=2,
        value_fn=lambda state: state.estimated_net_saving,
    ),
)


class ThermalStorageOptimizerAdvisorSensor(SensorEntity):
    """Expose state from the advisor without coupling it to the controller."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry[InputCoordinator],
        description: AdvisorSensorDescription,
    ) -> None:
        """Initialize an advisor-backed entity."""
        self._advisor = entry.runtime_data.advisor
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self.internal_integration_suggested_object_id = (
            f"thermal_storage_{description.key}"
        )
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def native_value(self) -> SensorValue:
        """Return one bounded live advisor value."""
        description = cast("AdvisorSensorDescription", self.entity_description)
        return description.value_fn(self._advisor.state)

    @property
    def extra_state_attributes(self) -> dict[str, object] | None:
        """Expose notification errors only on the human-readable advice sensor."""
        if self.entity_description.key != "charge_advice":
            return None
        state = self._advisor.state
        return {
            "confidence": (
                state.live.confidence.value
                if state.live is not None
                else state.target.confidence
                if state.target is not None
                else 0
            ),
            "reason": (
                state.live.reason
                if state.live is not None
                else state.schedule.reason
                if state.schedule is not None
                else state.advice
            ),
            "notification_error": state.notification_error,
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe after the entity is attached to Home Assistant."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._advisor.async_add_listener(self.async_write_ha_state)
        )


class ThermalStorageOptimizerPlanStatusSensor(
    CoordinatorEntity[InputCoordinator], SensorEntity
):
    """Expose plan continuity plus a bounded diagnostics preview."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_translation_key = "plan_status"

    def __init__(self, entry: ConfigEntry[InputCoordinator]) -> None:
        """Initialize the plan status entity."""
        super().__init__(entry.runtime_data)
        self._attr_options = [status.value for status in PlanStatus]
        self._attr_unique_id = f"{entry.entry_id}_plan_status"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def native_value(self) -> PlanStatus:
        """Return the rolling plan's current source status."""
        return self.coordinator.data.plan_status

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return only three interval summaries, never the full plan."""
        data = self.coordinator.data
        plan = data.plan
        if plan is None:
            return {"rejected_items": data.forecast_rejected_items, "preview": []}
        active = [
            item
            for item in plan.intervals
            if item.forecast.end.timestamp() > data.captured_at.timestamp()
        ]
        preview = [
            {
                "start": item.forecast.start.isoformat(),
                "end": item.forecast.end.isoformat(),
                "allocation_kwh": round(item.allocated_energy_kwh, 3),
                "value_per_kwh": round(item.forecast.adjusted_value_per_kwh, 4),
            }
            for item in active[:3]
        ]
        return {
            "interval_count": len(plan.intervals),
            "rejected_items": data.forecast_rejected_items,
            "retained_beyond_horizon_kwh": round(plan.retained_beyond_horizon_kwh, 3),
            "preview": preview,
        }


class _ControllerSensor(SensorEntity):
    """Base sensor updated by controller-only transitions."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry[InputCoordinator], key: str) -> None:
        self._controller: SupervisoryController = entry.runtime_data.controller
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    async def async_added_to_hass(self) -> None:
        """Subscribe after the entity is attached to Home Assistant."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._controller.async_add_listener(self.async_write_ha_state)
        )


class ThermalStorageOptimizerOperatingStateSensor(_ControllerSensor):
    """Expose the final state after all precedence and dwell rules."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_translation_key = "operating_state"

    def __init__(self, entry: ConfigEntry[InputCoordinator]) -> None:
        """Initialize the operating-state sensor."""
        super().__init__(entry, "operating_state")
        self._attr_options = [state.value for state in OperatingState]

    @property
    def native_value(self) -> str:
        """Return the exact specification state token."""
        return self._controller.decision.state.value


class ThermalStorageOptimizerControllerReasonSensor(_ControllerSensor):
    """Expose a concise final controller decision explanation."""

    _attr_translation_key = "controller_reason"

    def __init__(self, entry: ConfigEntry[InputCoordinator]) -> None:
        """Initialize the controller-reason sensor."""
        super().__init__(entry, "controller_reason")

    @property
    def native_value(self) -> str:
        """Return the current transition reason."""
        return self._controller.decision.reason

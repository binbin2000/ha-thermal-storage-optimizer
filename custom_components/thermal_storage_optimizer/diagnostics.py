"""Redacted Home Assistant diagnostics for field commissioning."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import OPTIONAL_ENTITY_KEYS, REQUIRED_ENTITY_KEYS, VERSION
from .plan_summary import build_plan_summary

if TYPE_CHECKING:
    from . import ThermalStorageOptimizerConfigEntry

_TO_REDACT = {*REQUIRED_ENTITY_KEYS, *OPTIONAL_ENTITY_KEYS}
_DIAGNOSTIC_PLAN_INTERVALS = 12


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant, entry: ThermalStorageOptimizerConfigEntry
) -> dict[str, Any]:
    """Return bounded diagnostics without entity IDs or raw provider payloads."""
    coordinator = entry.runtime_data
    data = coordinator.data
    issues = {issue.key: issue for issue in data.issues}
    normalized_inputs: dict[str, Any] = {}
    for key in (*REQUIRED_ENTITY_KEYS, *OPTIONAL_ENTITY_KEYS):
        if key not in entry.data:
            continue
        value = data.values.get(key)
        issue = issues.get(key)
        normalized_inputs[key] = {
            "required": key in REQUIRED_ENTITY_KEYS,
            "valid": value is not None,
            "value": value.value if value is not None else None,
            "unit": value.unit if value is not None else None,
            "updated_at": value.updated_at.isoformat() if value is not None else None,
            "problem": issue.problem.value if issue is not None else None,
        }

    thermal = data.thermal
    cop = data.cop
    advisor = coordinator.advisor.state
    controller = coordinator.controller
    performance = coordinator.calibration.performance_report(
        data.plan.expected_savings if data.plan is not None else None
    )
    return {
        "integration_version": VERSION,
        "config_entry_version": entry.version,
        "config_entry_data": async_redact_data(dict(entry.data), _TO_REDACT),
        "options": dict(entry.options),
        "data_validity": {
            "valid": data.is_valid,
            "issue_count": len(data.issues),
            "required_issue_count": len(data.required_issues),
            "issues": [
                {
                    "input": issue.key,
                    "problem": issue.problem.value,
                    "required": issue.required,
                }
                for issue in data.issues
            ],
        },
        "normalized_inputs": normalized_inputs,
        "model_outputs": {
            "usable_energy_kwh": thermal.usable_energy_kwh,
            "high_grade_energy_kwh": thermal.high_grade_energy_kwh,
            "state_of_charge_percent": thermal.state_of_charge_percent,
            "reference_temperature_c": thermal.reference_temperature_c,
            "stratification_delta_c": thermal.stratification_delta_c,
            "energy_trend": thermal.trend.value,
            "energy_quality": thermal.quality.value,
            "energy_confidence": thermal.confidence,
            "missing_thermal_values": list(thermal.missing_values),
            "hourly_heat_demand_kwh": data.hourly_heat_demand_kwh,
            "cop": cop.value if cop is not None else None,
            "cop_source": cop.source.value if cop is not None else None,
            "cop_confidence": cop.confidence if cop is not None else None,
        },
        "adaptive_calibration": coordinator.calibration.diagnostics(),
        "performance_validation": {
            "comparison_samples": performance.comparison_samples,
            "modeled_heat_kwh": performance.modeled_heat_kwh,
            "observed_heat_kwh": performance.observed_heat_kwh,
            "mean_absolute_error_kwh": performance.mean_absolute_error_kwh,
            "modeled_savings": performance.modeled_savings,
            "measured_savings": performance.measured_savings,
            "savings_label": performance.savings_label,
            "fallback_reason": performance.fallback_reason,
        },
        "plan_summary": build_plan_summary(
            coordinator, max_intervals=_DIAGNOSTIC_PLAN_INTERVALS
        ),
        "controller": {
            "mode": controller.mode.value,
            "operating_state": controller.decision.state.value,
            "decision_explanation": controller.decision.reason,
            "reserve_requested": controller.decision.reserve_requested,
            "active_control_enabled": controller.config.active_control,
            "commanded_output_on": controller.output_active,
        },
        "charging_advisor": {
            "charge_recommended": advisor.charge_recommended,
            "firing_active": advisor.firing_active,
            "advice": advisor.advice,
            "target_energy_kwh": (
                advisor.target.additional_energy_kwh
                if advisor.target is not None
                else None
            ),
            "remaining_energy_kwh": (
                advisor.live.remaining_energy_kwh if advisor.live is not None else None
            ),
            "notification_failed": advisor.notification_error is not None,
        },
        "redaction": {
            "entity_identifiers_redacted": True,
            "raw_price_payload_included": False,
            "notification_error_detail_included": False,
        },
    }

"""Home Assistant actions for commissioning and bounded plan inspection."""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.core import ServiceCall, ServiceResponse, SupportsResponse

from .const import (
    DEFAULT_PLAN_SUMMARY_INTERVALS,
    DOMAIN,
    MAX_PLAN_SUMMARY_INTERVALS,
    SERVICE_GET_PLAN_SUMMARY,
    SERVICE_RECALCULATE,
    SERVICE_RESET_LEARNED_STATE,
)
from .plan_summary import build_plan_summary

if TYPE_CHECKING:
    from . import ThermalStorageOptimizerConfigEntry


async def async_setup_actions(entry: ThermalStorageOptimizerConfigEntry) -> None:
    """Register the single-instance integration actions."""
    hass = entry.runtime_data.hass

    async def handle_recalculate(_call: ServiceCall) -> None:
        await entry.runtime_data.async_recalculate()

    async def handle_get_plan_summary(call: ServiceCall) -> ServiceResponse:
        return build_plan_summary(
            entry.runtime_data,
            max_intervals=int(call.data["max_intervals"]),
        )

    async def handle_reset_learned_state(_call: ServiceCall) -> ServiceResponse:
        await entry.runtime_data.async_reset_calibration()
        return {
            "reset": True,
            "reset_items": list(entry.runtime_data.calibration.parameters),
            "message": (
                "Adaptive calibration reset; deterministic configuration retained."
            ),
        }

    hass.services.async_register(DOMAIN, SERVICE_RECALCULATE, handle_recalculate)
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_PLAN_SUMMARY,
        handle_get_plan_summary,
        schema=vol.Schema(
            {
                vol.Optional(
                    "max_intervals", default=DEFAULT_PLAN_SUMMARY_INTERVALS
                ): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=MAX_PLAN_SUMMARY_INTERVALS)
                )
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_LEARNED_STATE,
        handle_reset_learned_state,
        supports_response=SupportsResponse.ONLY,
    )


def async_unload_actions(entry: ThermalStorageOptimizerConfigEntry) -> None:
    """Remove actions owned by the unloaded single config entry."""
    for action in (
        SERVICE_RECALCULATE,
        SERVICE_GET_PLAN_SUMMARY,
        SERVICE_RESET_LEARNED_STATE,
    ):
        if entry.runtime_data.hass.services.has_service(DOMAIN, action):
            entry.runtime_data.hass.services.async_remove(DOMAIN, action)

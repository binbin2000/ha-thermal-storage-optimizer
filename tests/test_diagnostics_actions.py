"""Milestone 7 diagnostics, action, and entity-contract tests."""

from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermal_storage_optimizer.const import (
    DOMAIN,
    INTEGRATION_NAME,
    SERVICE_GET_PLAN_SUMMARY,
    SERVICE_RECALCULATE,
    SERVICE_RESET_LEARNED_STATE,
    UNIQUE_ID,
)
from custom_components.thermal_storage_optimizer.controller import UserMode
from custom_components.thermal_storage_optimizer.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .helpers import REQUIRED_CONFIG, set_valid_required_states


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    """Load a dry-run instance with fake output services."""
    set_valid_required_states(hass)
    output = AsyncMock()
    hass.services.async_register("switch", "turn_on", output)
    hass.services.async_register("switch", "turn_off", output)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=INTEGRATION_NAME,
        unique_id=UNIQUE_ID,
        data=REQUIRED_CONFIG,
        version=5,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_diagnostics_are_complete_bounded_and_redacted(
    hass: HomeAssistant,
) -> None:
    """Diagnostics expose commissioning evidence without source identifiers."""
    entry = await _setup(hass)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    rendered = repr(diagnostics)

    assert diagnostics["data_validity"]["valid"] is True
    assert diagnostics["model_outputs"]["usable_energy_kwh"] is not None
    assert diagnostics["controller"]["operating_state"]
    assert diagnostics["plan_summary"]["returned_interval_count"] <= 12
    assert diagnostics["redaction"]["raw_price_payload_included"] is False
    assert "sensor.tank_top" not in rendered
    assert "switch.reserve_output" not in rendered
    assert diagnostics["config_entry_data"]["tank_top_entity"] == "**REDACTED**"

    registry = er.async_get(hass)
    energy_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_energy"
    )
    operating_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_operating_state"
    )
    assert energy_id is not None
    assert operating_id is not None
    energy = hass.states.get(energy_id)
    operating = registry.async_get(operating_id)
    assert energy is not None
    assert operating is not None
    assert energy.attributes["device_class"] == "energy_storage"
    assert energy.attributes["state_class"] == "measurement"
    assert operating.entity_category is None


async def test_recalculate_and_bounded_plan_response(hass: HomeAssistant) -> None:
    """Actions force same-publication optimization and bound exported intervals."""
    entry = await _setup(hass)
    before = entry.runtime_data.data.plan
    assert before is not None

    await hass.services.async_call(DOMAIN, SERVICE_RECALCULATE, blocking=True)
    after = entry.runtime_data.data.plan
    assert after is not None
    assert after is not before
    assert after.publication_key == before.publication_key

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_PLAN_SUMMARY,
        {"max_intervals": 2},
        blocking=True,
        return_response=True,
    )
    assert response is not None
    assert response["returned_interval_count"] <= 2
    assert len(response["intervals"]) == response["returned_interval_count"]
    assert response["future_interval_count"] == (
        response["returned_interval_count"] + response["omitted_interval_count"]
    )


async def test_reset_action_never_clears_critical_continuity_state(
    hass: HomeAssistant,
) -> None:
    """Calibration reset preserves the plan and user mode."""
    entry = await _setup(hass)
    await entry.runtime_data.controller.async_set_mode(UserMode.USE_TANK)
    plan = entry.runtime_data.data.plan

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_RESET_LEARNED_STATE,
        blocking=True,
        return_response=True,
    )
    assert response["reset"] is True
    assert "cop" in response["reset_items"]
    assert "deterministic configuration retained" in response["message"]
    assert entry.runtime_data.data.plan is plan
    assert entry.runtime_data.controller.mode is UserMode.USE_TANK

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not hass.services.has_service(DOMAIN, SERVICE_RECALCULATE)
    assert not hass.services.has_service(DOMAIN, SERVICE_GET_PLAN_SUMMARY)

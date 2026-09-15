"""Fake-entity integration tests for safe actuation and lifecycle failures."""

from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermal_storage_optimizer.const import (
    CONF_ACTIVE_CONTROL,
    CONF_MINIMUM_DWELL_TIME,
    CONF_STARTUP_GRACE_PERIOD,
    DOMAIN,
    INTEGRATION_NAME,
    UNIQUE_ID,
)
from custom_components.thermal_storage_optimizer.controller import (
    OperatingState,
    UserMode,
)

from .helpers import REQUIRED_CONFIG, set_valid_required_states


def _options(*, active: bool = True, grace: int = 0) -> dict[str, object]:
    """Return fast deterministic controller settings for integration tests."""
    return {
        CONF_ACTIVE_CONTROL: active,
        CONF_STARTUP_GRACE_PERIOD: grace,
        CONF_MINIMUM_DWELL_TIME: 0,
    }


async def _setup(
    hass: HomeAssistant,
    *,
    active: bool = True,
    grace: int = 0,
    turn_on: AsyncMock | None = None,
    turn_off: AsyncMock | None = None,
) -> tuple[MockConfigEntry, AsyncMock, AsyncMock]:
    """Load against fake switch services and valid fake sensor entities."""
    set_valid_required_states(hass)

    async def on_handler(_call: ServiceCall) -> None:
        hass.states.async_set("switch.reserve_output", STATE_ON)

    async def off_handler(_call: ServiceCall) -> None:
        hass.states.async_set("switch.reserve_output", STATE_OFF)

    on_mock = turn_on or AsyncMock(side_effect=on_handler)
    off_mock = turn_off or AsyncMock(side_effect=off_handler)
    hass.services.async_register("switch", "turn_on", on_mock)
    hass.services.async_register("switch", "turn_off", off_mock)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=INTEGRATION_NAME,
        unique_id=UNIQUE_ID,
        data=REQUIRED_CONFIG,
        options=_options(active=active, grace=grace),
        version=4,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, on_mock, off_mock


async def test_active_manual_reserve_then_invalid_input_falls_back_off(
    hass: HomeAssistant,
) -> None:
    """Actuate a fake output, then immediately de-energize on invalid data."""
    entry, on_mock, off_mock = await _setup(hass)
    controller = entry.runtime_data.controller
    await controller.async_set_mode(UserMode.RESERVE_TANK)
    assert controller.decision.state is OperatingState.RESERVE_TANK
    assert controller.output_active
    assert on_mock.await_count == 1

    hass.states.async_set("sensor.tank_middle", "unavailable")
    await hass.async_block_till_done()
    assert controller.decision.state is OperatingState.FAULT_FALLBACK
    assert not controller.output_active
    assert off_mock.await_count >= 2


async def test_high_temperature_forces_off_and_hysteresis_holds(
    hass: HomeAssistant,
) -> None:
    """Manual reserve cannot bypass the fake tank high-temperature override."""
    entry, _on_mock, _off_mock = await _setup(hass)
    controller = entry.runtime_data.controller
    await controller.async_set_mode(UserMode.RESERVE_TANK)
    hass.states.async_set("sensor.tank_top", "86", {"unit_of_measurement": "°C"})
    await hass.async_block_till_done()
    assert controller.decision.state is OperatingState.FORCED_USE
    assert not controller.output_active

    hass.states.async_set("sensor.tank_top", "81", {"unit_of_measurement": "°C"})
    await hass.async_block_till_done()
    assert controller.decision.state is OperatingState.FORCED_USE
    hass.states.async_set("sensor.tank_top", "80", {"unit_of_measurement": "°C"})
    await hass.async_block_till_done()
    assert controller.decision.state is OperatingState.RESERVE_TANK


async def test_service_failure_sets_fault_and_requests_off(hass: HomeAssistant) -> None:
    """Never hide a failed ON call; issue an immediate fake OFF fallback."""
    failed_on = AsyncMock(side_effect=HomeAssistantError("relay unavailable"))
    entry, _on_mock, off_mock = await _setup(hass, turn_on=failed_on)
    controller = entry.runtime_data.controller
    await controller.async_set_mode(UserMode.RESERVE_TANK)
    assert controller.decision.state is OperatingState.FAULT_FALLBACK
    assert "service fault" in controller.decision.reason.lower()
    assert not controller.output_active
    assert off_mock.await_count >= 2


async def test_recoverable_controller_exception_exposes_fault_and_turns_off(
    hass: HomeAssistant,
) -> None:
    """Convert a caught runtime failure into a visible fail-safe state."""
    entry, _on_mock, off_mock = await _setup(hass)
    controller = entry.runtime_data.controller
    await controller.async_set_mode(UserMode.RESERVE_TANK)
    assert controller.output_active
    await controller.async_handle_fault("synthetic recoverable failure")
    assert controller.decision.state is OperatingState.FAULT_FALLBACK
    assert "synthetic recoverable failure" in controller.decision.reason
    assert not controller.output_active
    assert off_mock.await_count >= 2


async def test_failed_off_call_keeps_fault_and_does_not_claim_deenergized(
    hass: HomeAssistant,
) -> None:
    """Expose that the last successful command remains ON when OFF fails."""
    entry, _on_mock, off_mock = await _setup(hass)
    controller = entry.runtime_data.controller
    await controller.async_set_mode(UserMode.RESERVE_TANK)
    assert controller.output_active
    off_mock.side_effect = HomeAssistantError("relay stuck")

    hass.states.async_set("sensor.tank_middle", "unavailable")
    await hass.async_block_till_done()
    assert controller.decision.state is OperatingState.FAULT_FALLBACK
    assert "relay stuck" in controller.decision.reason
    assert controller.output_active


async def test_restart_restores_mode_but_reapplies_grace_and_unload_off(
    hass: HomeAssistant,
) -> None:
    """Persist mode without carrying actuation through restart or unload."""
    entry, _on_mock, off_mock = await _setup(hass, grace=300)
    controller = entry.runtime_data.controller
    await controller.async_set_mode(UserMode.RESERVE_TANK)
    assert controller.mode is UserMode.RESERVE_TANK
    assert controller.decision.state is OperatingState.WAITING_FOR_DATA
    assert not controller.output_active

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert off_mock.await_count >= 2
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    restored = entry.runtime_data.controller
    assert restored.mode is UserMode.RESERVE_TANK
    assert restored.decision.state is OperatingState.WAITING_FOR_DATA
    assert not restored.output_active


async def test_fresh_auto_install_remains_dry_run(hass: HomeAssistant) -> None:
    """Auto mode alone never produces a fake ON call on a fresh installation."""
    entry, on_mock, off_mock = await _setup(hass, active=False, grace=0)
    controller = entry.runtime_data.controller
    assert controller.mode is UserMode.AUTO
    assert not controller.config.active_control
    assert not controller.output_active
    on_mock.assert_not_awaited()
    assert off_mock.await_count == 1


async def test_external_output_changes_are_corrected(hass: HomeAssistant) -> None:
    """External ON during use and OFF during reserve are both corrected."""
    entry, on_mock, off_mock = await _setup(hass)
    controller = entry.runtime_data.controller
    await controller.async_set_mode(UserMode.USE_TANK)
    count = off_mock.await_count
    hass.states.async_set("switch.reserve_output", STATE_ON)
    await hass.async_block_till_done()
    assert off_mock.await_count > count
    assert controller.output_active is False
    await controller.async_set_mode(UserMode.RESERVE_TANK)
    count = on_mock.await_count
    hass.states.async_set("switch.reserve_output", STATE_OFF)
    await hass.async_block_till_done()
    assert on_mock.await_count > count
    assert controller.output_active is True


async def test_unacknowledged_output_becomes_persistent_fault(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """An accepted service call is not confirmation, and retries are bounded."""
    ignored = AsyncMock()
    entry, on_mock, _ = await _setup(hass, turn_on=ignored)
    controller = entry.runtime_data.controller
    await controller.async_set_mode(UserMode.RESERVE_TANK)
    assert controller.output_active is False
    await controller.async_evaluate()
    assert on_mock.await_count == 1
    freezer.tick(timedelta(seconds=31))
    entry.runtime_data._refresh_snapshot()  # noqa: SLF001
    await hass.async_block_till_done()
    assert controller.decision.state is OperatingState.FAULT_FALLBACK
    assert "acknowledgement" in controller.decision.reason
    await controller.async_evaluate()
    assert controller.decision.state is OperatingState.FAULT_FALLBACK

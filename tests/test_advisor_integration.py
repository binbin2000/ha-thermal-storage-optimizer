"""Home Assistant tests for Milestone 6 recovery and notification isolation."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermal_storage_optimizer.const import (
    CONF_ADVISOR_LANGUAGE,
    CONF_ALLOW_EXCEPTIONAL_FIRING,
    CONF_MINIMUM_FIRING_DURATION,
    CONF_NOTIFICATION_LEAD_TIME,
    CONF_NOTIFICATION_TARGET,
    DOMAIN,
    INTEGRATION_NAME,
    SERVICE_SNOOZE,
    SERVICE_START_FIRING,
    SERVICE_STOP_FIRING,
    UNIQUE_ID,
)
from custom_components.thermal_storage_optimizer.controller import (
    OperatingState,
    UserMode,
)
from custom_components.thermal_storage_optimizer.optimizer import optimize_plan

from .helpers import REQUIRED_CONFIG
from .test_optimizer import economic


def _set_advisor_inputs(hass: HomeAssistant, publication: str = "cycle-a") -> None:
    """Create a low tank and an evening price spike in a normal firing window."""
    temperatures = {
        "sensor.tank_top": "36",
        "sensor.tank_middle": "34",
        "sensor.tank_bottom": "32",
        "sensor.return_temperature": "30",
        "sensor.supply_target": "45",
        "sensor.outdoor_temperature": "5",
    }
    for entity_id, value in temperatures.items():
        hass.states.async_set(entity_id, value, {"unit_of_measurement": "°C"})
    start = datetime(2026, 9, 7, 16, tzinfo=UTC)
    prices = [
        {
            "start": (start + timedelta(hours=index)).isoformat(),
            "end": (start + timedelta(hours=index + 1)).isoformat(),
            "price": 3.0 if index == 4 else 0.2,
        }
        for index in range(10)
    ]
    hass.states.async_set(
        "sensor.price_forecast",
        "published",
        {
            "unit_of_measurement": "SEK/kWh",
            "publication_id": publication,
            "prices": prices,
        },
    )
    hass.states.async_set("switch.reserve_output", "off")


async def _setup(
    hass: HomeAssistant,
    notify: AsyncMock,
    output: AsyncMock,
) -> MockConfigEntry:
    """Load an advisor configured to notify well before its preferred window."""
    hass.services.async_register("notify", "test", notify)
    hass.services.async_register("switch", "turn_on", output)
    hass.services.async_register("switch", "turn_off", output)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=INTEGRATION_NAME,
        unique_id=UNIQUE_ID,
        data={**REQUIRED_CONFIG, CONF_NOTIFICATION_TARGET: "notify.test"},
        options={
            CONF_NOTIFICATION_LEAD_TIME: 600,
            CONF_MINIMUM_FIRING_DURATION: 1,
            CONF_ADVISOR_LANGUAGE: "sv",
            CONF_ALLOW_EXCEPTIONAL_FIRING: True,
        },
        version=5,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_initial_notification_deduplicates_and_survives_restart(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """One publication sends one initial recommendation, including after restart."""
    freezer.move_to(datetime(2026, 9, 7, 16, tzinfo=UTC))
    _set_advisor_inputs(hass)
    notify = AsyncMock()
    output = AsyncMock()
    entry = await _setup(hass, notify, output)
    assert entry.runtime_data.advisor.state.schedule is not None
    assert entry.runtime_data.advisor.state.schedule.feasible
    assert entry.runtime_data.advisor.state.charge_recommended
    assert notify.await_count == 1
    message = notify.await_args.args[0].data["message"]
    assert "Beräknad undvikbar elkostnad" in message

    hass.states.async_set("sensor.tank_bottom", "32", {"unit_of_measurement": "°C"})
    await hass.async_block_till_done()
    assert notify.await_count == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert notify.await_count == 1


async def test_snooze_suppresses_new_planning_cycle(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A bounded snooze blocks a delayed replacement publication notification."""
    freezer.move_to(datetime(2026, 9, 7, 16, tzinfo=UTC))
    _set_advisor_inputs(hass)
    notify = AsyncMock()
    entry = await _setup(hass, notify, AsyncMock())
    assert notify.await_count == 1
    await hass.services.async_call(
        DOMAIN, SERVICE_SNOOZE, {"minutes": 120}, blocking=True
    )
    _set_advisor_inputs(hass, publication="delayed-cycle-b")
    await hass.async_block_till_done()
    assert entry.runtime_data.data.plan is not None
    assert entry.runtime_data.data.plan.publication_key != ""
    assert notify.await_count == 1


async def test_manual_session_action_restores_bounded_active_state(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The manual integration action and restart recovery never control the stove."""
    freezer.move_to(datetime(2026, 9, 7, 16, tzinfo=UTC))
    _set_advisor_inputs(hass)
    output = AsyncMock()
    entry = await _setup(hass, AsyncMock(), output)
    await hass.services.async_call(DOMAIN, SERVICE_START_FIRING, blocking=True)
    assert entry.runtime_data.advisor.state.firing_active

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.advisor.state.firing_active
    await hass.services.async_call(DOMAIN, SERVICE_STOP_FIRING, blocking=True)
    assert not entry.runtime_data.advisor.state.firing_active
    assert all(call.args[0].service == "turn_off" for call in output.await_args_list)


async def test_notification_failure_is_visible_but_cannot_affect_controller(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Delivery errors remain in advisor diagnostics and never alter shunt safety."""
    freezer.move_to(datetime(2026, 9, 7, 16, tzinfo=UTC))
    _set_advisor_inputs(hass)
    notify = AsyncMock(side_effect=HomeAssistantError("phone offline"))
    output = AsyncMock()
    entry = await _setup(hass, notify, output)
    assert entry.runtime_data.advisor.state.notification_error == "phone offline"
    assert not entry.runtime_data.controller.output_active
    assert all(call.args[0].service == "turn_off" for call in output.await_args_list)
    advice_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_charge_advice"
    )
    assert advice_id == "sensor.thermal_storage_charge_advice"
    advice = hass.states.get(advice_id)
    assert advice is not None
    assert advice.attributes["notification_error"] == "phone offline"


async def test_net_charge_target_does_not_add_building_load_twice(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """An unchanged dispatch forecast yields the same net target at any live load."""
    freezer.move_to(datetime(2026, 9, 7, 16, tzinfo=UTC))
    _set_advisor_inputs(hass)
    entry = await _setup(hass, AsyncMock(), AsyncMock())
    advisor = entry.runtime_data.advisor
    data = entry.runtime_data.data
    now = data.captured_at
    quiet = advisor._build_plan(replace(data, hourly_heat_demand_kwh=0), now)[0]  # noqa: SLF001
    busy = advisor._build_plan(replace(data, hourly_heat_demand_kwh=20), now)[0]  # noqa: SLF001
    assert quiet is not None
    assert busy == quiet


async def test_manual_and_forced_use_increase_precharge_target(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Heat used before charging starts is replenished in manual and forced use."""
    freezer.move_to(datetime(2026, 9, 7, 11, tzinfo=UTC))
    _set_advisor_inputs(hass)
    entry = await _setup(hass, AsyncMock(), AsyncMock())
    coordinator = entry.runtime_data
    plan = optimize_plan(
        (economic(0, 4, 0.1, 4), economic(4, 1, 2, 10)),
        optimized_at=coordinator.data.captured_at,
        publication_key="charge",
        available_energy_kwh=2,
        economic_deadband_per_kwh=0.05,
    )
    data = replace(
        coordinator.data,
        plan=plan,
        thermal=replace(coordinator.data.thermal, usable_energy_kwh=2),
    )
    auto = coordinator.advisor._build_plan(data, data.captured_at)[0]  # noqa: SLF001
    coordinator.controller.mode = UserMode.USE_TANK
    manual = coordinator.advisor._build_plan(data, data.captured_at)[0]  # noqa: SLF001
    coordinator.controller.mode = UserMode.AUTO
    coordinator.controller.decision = replace(
        coordinator.controller.decision, state=OperatingState.FORCED_USE
    )
    forced = coordinator.advisor._build_plan(data, data.captured_at)[0]  # noqa: SLF001
    assert auto is not None
    assert manual is not None
    assert manual.additional_energy_kwh > auto.additional_energy_kwh
    assert forced == manual

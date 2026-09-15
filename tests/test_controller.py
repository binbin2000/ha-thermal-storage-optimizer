"""Pure tests for supervisory state precedence and anti-chatter behavior."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from custom_components.thermal_storage_optimizer.controller import (
    ControllerConfig,
    ControllerInput,
    ControllerStateMachine,
    OperatingState,
    UserMode,
)
from custom_components.thermal_storage_optimizer.optimizer import Recommendation

NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)


def _input(**changes: object) -> ControllerInput:
    """Return a valid automatic use request with selected overrides."""
    base = ControllerInput(
        now=NOW,
        mode=UserMode.AUTO,
        required_inputs_valid=True,
        has_ever_had_valid_inputs=True,
        plan_valid=True,
        has_ever_had_valid_plan=True,
        recommendation=Recommendation.USE_TANK,
        usable_energy_kwh=10,
        tank_temperatures_c=(60, 50, 40),
    )
    return replace(base, **changes)


def _machine(**changes: object) -> ControllerStateMachine:
    """Return an active controller with no grace or dwell by default."""
    config = ControllerConfig(
        active_control=True,
        startup_grace=timedelta(0),
        minimum_dwell=timedelta(0),
    )
    return ControllerStateMachine(replace(config, **changes), started_at=NOW)


def test_all_final_modes_and_automatic_states_are_deterministic() -> None:
    """Map every normal manual/automatic branch to its specified state."""
    machine = _machine()
    assert machine.evaluate(_input()).state is OperatingState.USE_TANK
    assert (
        machine.evaluate(_input(mode=UserMode.USE_TANK)).state
        is OperatingState.USE_TANK
    )
    assert (
        machine.evaluate(_input(mode=UserMode.RESERVE_TANK)).state
        is OperatingState.RESERVE_TANK
    )
    assert (
        machine.evaluate(_input(mode=UserMode.DISABLED)).state
        is OperatingState.DISABLED
    )
    assert (
        machine.evaluate(_input(usable_energy_kwh=0)).state
        is OperatingState.COLD_OR_EMPTY
    )
    assert (
        machine.evaluate(_input(recommendation=Recommendation.RESERVE_TANK)).state
        is OperatingState.RESERVE_TANK
    )


def test_precedence_forced_use_invalid_disabled_manual_and_auto() -> None:
    """Higher safety states override every lower user/planner request."""
    machine = _machine()
    forced = machine.evaluate(
        _input(
            mode=UserMode.DISABLED,
            required_inputs_valid=False,
            tank_temperatures_c=(86,),
            service_fault="failed",
        )
    )
    assert forced.state is OperatingState.FORCED_USE
    assert not forced.reserve_requested

    invalid = _machine().evaluate(
        _input(mode=UserMode.DISABLED, required_inputs_valid=False)
    )
    assert invalid.state is OperatingState.FAULT_FALLBACK
    assert not invalid.output_on

    no_plan = _machine().evaluate(_input(mode=UserMode.RESERVE_TANK, plan_valid=False))
    assert no_plan.state is OperatingState.FAULT_FALLBACK
    assert not no_plan.output_on
    disabled_without_plan = _machine().evaluate(
        _input(mode=UserMode.DISABLED, plan_valid=False)
    )
    assert disabled_without_plan.state is OperatingState.FAULT_FALLBACK


def test_startup_and_initial_missing_data_wait_deenergized() -> None:
    """Never energize before valid data and startup grace have both cleared."""
    machine = ControllerStateMachine(
        ControllerConfig(active_control=True, startup_grace=timedelta(minutes=5)),
        started_at=NOW,
    )
    missing = machine.evaluate(
        _input(
            required_inputs_valid=False,
            has_ever_had_valid_inputs=False,
            plan_valid=False,
            has_ever_had_valid_plan=False,
        )
    )
    assert missing.state is OperatingState.WAITING_FOR_DATA
    assert not missing.output_on
    grace = machine.evaluate(
        _input(
            now=NOW + timedelta(minutes=4),
            recommendation=Recommendation.RESERVE_TANK,
        )
    )
    assert grace.state is OperatingState.WAITING_FOR_DATA
    assert not grace.output_on


def test_dwell_prevents_chatter_but_forced_use_is_immediate() -> None:
    """Hold ordinary changes and bypass the hold for high temperature."""
    machine = _machine(minimum_dwell=timedelta(minutes=30))
    reserve = machine.evaluate(
        _input(
            now=NOW + timedelta(minutes=31),
            recommendation=Recommendation.RESERVE_TANK,
        )
    )
    assert reserve.state is OperatingState.RESERVE_TANK
    held = machine.evaluate(_input(now=NOW + timedelta(minutes=32)))
    assert held.state is OperatingState.RESERVE_TANK
    assert "Minimum dwell" in held.reason
    forced = machine.evaluate(
        _input(now=NOW + timedelta(minutes=33), tank_temperatures_c=(85,))
    )
    assert forced.state is OperatingState.FORCED_USE
    assert not forced.output_on


def test_forced_use_hysteresis_cannot_be_bypassed_by_manual_reserve() -> None:
    """Keep forced use latched until the configured release boundary."""
    machine = _machine(
        high_temperature_c=85,
        high_temperature_hysteresis_c=5,
    )
    request = _input(mode=UserMode.RESERVE_TANK)
    assert (
        machine.evaluate(replace(request, tank_temperatures_c=(85,))).state
        is OperatingState.FORCED_USE
    )
    assert (
        machine.evaluate(replace(request, tank_temperatures_c=(81,))).state
        is OperatingState.FORCED_USE
    )
    released = machine.evaluate(replace(request, tank_temperatures_c=(80,)))
    assert released.state is OperatingState.RESERVE_TANK


def test_dry_run_permission_and_output_inversion_are_independent() -> None:
    """Auto/mode decisions cannot grant permission and polarity is configurable."""
    dry = ControllerStateMachine(
        ControllerConfig(
            active_control=False,
            startup_grace=timedelta(0),
            minimum_dwell=timedelta(0),
        ),
        started_at=NOW,
    ).evaluate(_input(mode=UserMode.RESERVE_TANK))
    assert dry.state is OperatingState.RESERVE_TANK
    assert not dry.output_on
    assert "dry-run" in dry.reason

    inverted = _machine(output_inverted=True)
    assert not inverted.evaluate(_input(mode=UserMode.RESERVE_TANK)).output_on
    assert inverted.evaluate(_input(mode=UserMode.USE_TANK)).output_on

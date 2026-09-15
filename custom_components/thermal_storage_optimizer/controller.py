"""Pure supervisory state machine and fail-safe Home Assistant actuation."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF, SERVICE_TURN_ON
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

from .const import (
    CONF_ACTIVE_CONTROL,
    CONF_HIGH_TEMPERATURE_HYSTERESIS,
    CONF_HIGH_TEMPERATURE_THRESHOLD,
    CONF_MINIMUM_DWELL_TIME,
    CONF_OUTPUT_INVERTED,
    CONF_RESERVE_OUTPUT,
    CONF_STARTUP_GRACE_PERIOD,
    CONF_TANK_BOTTOM,
    CONF_TANK_MIDDLE,
    CONF_TANK_TOP,
    DEFAULT_ACTIVE_CONTROL,
    DEFAULT_HIGH_TEMPERATURE_HYSTERESIS,
    DEFAULT_HIGH_TEMPERATURE_THRESHOLD,
    DEFAULT_MINIMUM_DWELL_TIME,
    DEFAULT_OUTPUT_INVERTED,
    DEFAULT_STARTUP_GRACE_PERIOD,
    DOMAIN,
)
from .data import PlanStatus
from .optimizer import Recommendation

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .coordinator import InputCoordinator
    from .data import RuntimeSnapshot

_LOGGER = logging.getLogger(__name__)
_STORE_VERSION = 1
_EMPTY_ENERGY_EPSILON_KWH = 1e-6
_MAX_FAULT_DETAIL_LENGTH: Final = 200


class UserMode(StrEnum):
    """User-selectable supervisory modes."""

    AUTO = "auto"
    USE_TANK = "use_tank"
    RESERVE_TANK = "reserve_tank"
    DISABLED = "disabled"


class OperatingState(StrEnum):
    """Final operating states from the system specification."""

    USE_TANK = "USE_TANK"
    RESERVE_TANK = "RESERVE_TANK"
    FORCED_USE = "FORCED_USE"
    COLD_OR_EMPTY = "COLD_OR_EMPTY"
    WAITING_FOR_DATA = "WAITING_FOR_DATA"
    FAULT_FALLBACK = "FAULT_FALLBACK"
    DISABLED = "DISABLED"


@dataclass(frozen=True, slots=True)
class ControllerConfig:
    """Controller tuning and independent actuation permission."""

    active_control: bool = DEFAULT_ACTIVE_CONTROL
    output_inverted: bool = DEFAULT_OUTPUT_INVERTED
    high_temperature_c: float = DEFAULT_HIGH_TEMPERATURE_THRESHOLD
    high_temperature_hysteresis_c: float = DEFAULT_HIGH_TEMPERATURE_HYSTERESIS
    startup_grace: timedelta = timedelta(seconds=DEFAULT_STARTUP_GRACE_PERIOD)
    minimum_dwell: timedelta = timedelta(seconds=DEFAULT_MINIMUM_DWELL_TIME)


@dataclass(frozen=True, slots=True)
class ControllerInput:
    """Pure timestamped state-machine input."""

    now: datetime
    mode: UserMode
    required_inputs_valid: bool
    has_ever_had_valid_inputs: bool
    plan_valid: bool
    has_ever_had_valid_plan: bool
    recommendation: Recommendation
    usable_energy_kwh: float | None
    tank_temperatures_c: tuple[float, ...]
    service_fault: str | None = None
    budget_exhausted: bool = False


@dataclass(frozen=True, slots=True)
class ControllerDecision:
    """One explainable final state and requested physical command."""

    state: OperatingState
    reason: str
    reserve_requested: bool
    output_on: bool
    active_control: bool


class ControllerStateMachine:
    """Implement precedence, high-limit hysteresis, and minimum dwell."""

    def __init__(self, config: ControllerConfig, *, started_at: datetime) -> None:
        """Initialize with a new grace period and normal tank-use request."""
        self.config = config
        self.started_at = started_at
        self._forced_use_latched = False
        self._last_flow_request = False
        self._last_flow_change = started_at

    def evaluate(  # noqa: C901, PLR0911, PLR0912
        self, item: ControllerInput
    ) -> ControllerDecision:
        """Apply the specified precedence, with dwell evaluated last."""
        self._update_forced_use_latch(item.tank_temperatures_c)
        if self._forced_use_latched:
            return self._decision(
                OperatingState.FORCED_USE,
                "High tank temperature forces immediate tank use",
                reserve=False,
                fallback=False,
                now=item.now,
            )
        if item.service_fault is not None:
            return self._decision(
                OperatingState.FAULT_FALLBACK,
                f"Output service fault; de-energized fallback: {item.service_fault}",
                reserve=False,
                fallback=True,
                now=item.now,
            )
        if not item.required_inputs_valid:
            state = (
                OperatingState.FAULT_FALLBACK
                if item.has_ever_had_valid_inputs
                else OperatingState.WAITING_FOR_DATA
            )
            return self._decision(
                state,
                "Required input is invalid; output de-energized",
                reserve=False,
                fallback=True,
                now=item.now,
            )
        if not item.plan_valid:
            state = (
                OperatingState.FAULT_FALLBACK
                if item.has_ever_had_valid_plan
                else OperatingState.WAITING_FOR_DATA
            )
            return self._decision(
                state,
                "No valid current or saved plan; output de-energized",
                reserve=False,
                fallback=True,
                now=item.now,
            )
        if item.mode is UserMode.DISABLED:
            return self._decision(
                OperatingState.DISABLED,
                "Controller disabled; output de-energized",
                reserve=False,
                fallback=True,
                now=item.now,
            )
        if item.now < self.started_at + self.config.startup_grace:
            return self._decision(
                OperatingState.WAITING_FOR_DATA,
                "Valid inputs received; startup grace period is still active",
                reserve=False,
                fallback=True,
                now=item.now,
            )

        if item.mode is UserMode.USE_TANK:
            requested_state = OperatingState.USE_TANK
            reason = "Manual Use tank mode requests normal shunt operation"
            reserve = False
        elif item.mode is UserMode.RESERVE_TANK:
            requested_state = OperatingState.RESERVE_TANK
            reason = "Manual Reserve tank mode requests the configured offset"
            reserve = True
        elif (
            item.usable_energy_kwh is None
            or item.usable_energy_kwh <= _EMPTY_ENERGY_EPSILON_KWH
        ):
            requested_state = OperatingState.COLD_OR_EMPTY
            reason = "Tank has no estimated usable energy"
            reserve = False
        elif (
            item.budget_exhausted or item.recommendation is Recommendation.RESERVE_TANK
        ):
            requested_state = OperatingState.RESERVE_TANK
            reason = "Auto follows the current plan: reserve tank"
            reserve = True
        elif item.recommendation is Recommendation.USE_TANK:
            requested_state = OperatingState.USE_TANK
            reason = "Auto follows the current plan: use tank"
            reserve = False
        else:
            return self._decision(
                OperatingState.FAULT_FALLBACK,
                "Current plan has no actionable recommendation; output de-energized",
                reserve=False,
                fallback=True,
                now=item.now,
            )

        elapsed = item.now - self._last_flow_change
        if (
            reserve != self._last_flow_request
            and elapsed < self.config.minimum_dwell
            and not (item.mode is UserMode.AUTO and item.budget_exhausted)
        ):
            remaining = self.config.minimum_dwell - elapsed
            held_state = (
                OperatingState.RESERVE_TANK
                if self._last_flow_request
                else OperatingState.USE_TANK
            )
            return self._decision(
                held_state,
                f"Minimum dwell holds the previous command for {remaining}",
                reserve=self._last_flow_request,
                fallback=False,
                now=item.now,
            )
        return self._decision(
            requested_state,
            reason,
            reserve=reserve,
            fallback=False,
            now=item.now,
        )

    def _update_forced_use_latch(self, temperatures: tuple[float, ...]) -> None:
        """Latch at the high limit and release at limit minus hysteresis."""
        if any(value >= self.config.high_temperature_c for value in temperatures):
            self._forced_use_latched = True
            return
        release_at = (
            self.config.high_temperature_c - self.config.high_temperature_hysteresis_c
        )
        if (
            self._forced_use_latched
            and temperatures
            and max(temperatures) <= release_at
        ):
            self._forced_use_latched = False

    def _decision(
        self,
        state: OperatingState,
        reason: str,
        *,
        reserve: bool,
        fallback: bool,
        now: datetime,
    ) -> ControllerDecision:
        """Map logical use/reserve to permission and configured polarity."""
        if reserve != self._last_flow_request:
            self._last_flow_request = reserve
            self._last_flow_change = now
        output_on = False
        if self.config.active_control and not fallback:
            output_on = reserve != self.config.output_inverted
        if not self.config.active_control:
            reason = f"{reason}; dry-run only, output remains de-energized"
        return ControllerDecision(
            state,
            reason,
            reserve,
            output_on,
            self.config.active_control,
        )


class SupervisoryController:
    """Connect the pure state machine to one HA digital output entity."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry[InputCoordinator],
        coordinator: InputCoordinator,
    ) -> None:
        """Build a controller from config options, defaulting to dry-run."""
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        options = dict(entry.options)
        self.config = ControllerConfig(
            active_control=(
                options.get(CONF_ACTIVE_CONTROL, DEFAULT_ACTIVE_CONTROL) is True
            ),
            output_inverted=(
                options.get(CONF_OUTPUT_INVERTED, DEFAULT_OUTPUT_INVERTED) is True
            ),
            high_temperature_c=float(
                str(
                    options.get(
                        CONF_HIGH_TEMPERATURE_THRESHOLD,
                        DEFAULT_HIGH_TEMPERATURE_THRESHOLD,
                    )
                )
            ),
            high_temperature_hysteresis_c=float(
                str(
                    options.get(
                        CONF_HIGH_TEMPERATURE_HYSTERESIS,
                        DEFAULT_HIGH_TEMPERATURE_HYSTERESIS,
                    )
                )
            ),
            startup_grace=timedelta(
                seconds=float(
                    str(
                        options.get(
                            CONF_STARTUP_GRACE_PERIOD,
                            DEFAULT_STARTUP_GRACE_PERIOD,
                        )
                    )
                )
            ),
            minimum_dwell=timedelta(
                seconds=float(
                    str(
                        options.get(
                            CONF_MINIMUM_DWELL_TIME,
                            DEFAULT_MINIMUM_DWELL_TIME,
                        )
                    )
                )
            ),
        )
        self.mode = UserMode.AUTO
        self.decision = ControllerDecision(
            state=OperatingState.WAITING_FOR_DATA,
            reason="Controller is starting; output de-energized",
            reserve_requested=False,
            output_on=False,
            active_control=self.config.active_control,
        )
        self.output_active: bool | None = None
        self._pending_output: tuple[bool, datetime] | None = None
        self._machine: ControllerStateMachine | None = None
        self._service_fault: str | None = None
        self._acknowledgement_fault = False
        self._has_valid_plan = False
        self._listeners: set[Callable[[], None]] = set()
        self._lock = asyncio.Lock()
        self._store = Store[dict[str, str]](
            hass, _STORE_VERSION, f"{DOMAIN}.{entry.entry_id}.controller"
        )
        self._remove_coordinator_listener: Callable[[], None] | None = None

    async def async_start(self) -> None:
        """De-energize first, restore mode, and subscribe to updates."""
        try:
            await self._async_call_output(turn_on=False, force=True)
        except HomeAssistantError as err:
            self._service_fault = _bounded_detail(str(err))
        stored = await self._store.async_load()
        if stored is not None:
            try:
                self.mode = UserMode(stored.get("mode", UserMode.AUTO))
            except ValueError:
                self.mode = UserMode.AUTO
        self._machine = ControllerStateMachine(self.config, started_at=self._now())
        self._remove_coordinator_listener = self.coordinator.async_add_listener(
            self._schedule_evaluate
        )
        self.entry.async_on_unload(self._remove_listener)

    async def async_evaluate(self) -> None:
        """Evaluate and apply one serialized control decision."""
        async with self._lock:
            try:
                data = self.coordinator.data
                if data is None or self._machine is None:
                    return
                plan_valid = data.plan is not None and data.plan_status in {
                    PlanStatus.FULL_FORECAST,
                    PlanStatus.SAVED_PLAN,
                }
                self._has_valid_plan = self._has_valid_plan or plan_valid
                item = ControllerInput(
                    now=data.captured_at,
                    mode=self.mode,
                    required_inputs_valid=data.is_valid,
                    has_ever_had_valid_inputs=self.coordinator.has_received_valid_data,
                    plan_valid=plan_valid,
                    has_ever_had_valid_plan=self._has_valid_plan,
                    recommendation=data.recommendation or Recommendation.WAITING,
                    usable_energy_kwh=data.thermal.usable_energy_kwh,
                    tank_temperatures_c=_tank_temperatures(data),
                    service_fault=self._service_fault,
                    budget_exhausted=(
                        data.plan is not None
                        and data.thermal.usable_energy_kwh is not None
                        and data.thermal.usable_energy_kwh
                        <= data.plan.reserve_floor_at(data.captured_at)
                        + _EMPTY_ENERGY_EPSILON_KWH
                    ),
                )
                await self._apply_decision(self._machine.evaluate(item))
            except (HomeAssistantError, TypeError, ValueError) as err:
                await self.async_handle_fault(f"controller exception: {err}")

    async def async_set_mode(self, mode: UserMode) -> None:
        """Persist a user mode and evaluate it immediately."""
        self.mode = mode
        self._acknowledgement_fault = False
        self._service_fault = None
        await self._store.async_save({"mode": mode.value})
        await self.async_evaluate()

    async def async_handle_fault(self, reason: str) -> None:
        """Expose a recoverable fault and make a best-effort OFF request."""
        reason = _bounded_detail(reason)
        self._service_fault = reason
        try:
            await self._async_call_output(turn_on=False, force=True)
        except HomeAssistantError as err:
            reason = _bounded_detail(f"{reason}; OFF request also failed: {err}")
        self._set_decision(
            ControllerDecision(
                state=OperatingState.FAULT_FALLBACK,
                reason=f"Fault fallback; OFF requested: {reason}",
                reserve_requested=False,
                output_on=False,
                active_control=self.config.active_control,
            )
        )

    async def async_shutdown(self) -> None:
        """Stop evaluation and request absolute de-energized fallback."""
        self._remove_listener()
        try:
            await self._async_call_output(turn_on=False, force=True)
        except HomeAssistantError:
            _LOGGER.exception("Unload OFF request failed")

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Subscribe an entity to controller-only changes."""
        self._listeners.add(listener)

        def remove() -> None:
            self._listeners.discard(listener)

        return remove

    async def _apply_decision(self, decision: ControllerDecision) -> None:
        """Apply a command and convert service errors to fault fallback."""
        safety_state = decision.state in {
            OperatingState.FORCED_USE,
            OperatingState.WAITING_FOR_DATA,
            OperatingState.FAULT_FALLBACK,
            OperatingState.DISABLED,
        }
        force_safe_transition = (
            safety_state
            and not decision.output_on
            and decision.state is not self.decision.state
        )
        self._observe_output()
        if self._pending_output is not None:
            requested, sent_at = self._pending_output
            if self.output_active == requested:
                self._pending_output = None
            elif requested == decision.output_on and not force_safe_transition:
                if self._now() - sent_at < timedelta(seconds=30):
                    self._set_decision(decision)
                    return
                self._acknowledgement_fault = True
                await self.async_handle_fault(
                    "output acknowledgement timed out; observed state disagrees"
                )
                return
        if decision.output_on != self.output_active or force_safe_transition:
            try:
                await self._async_call_output(
                    turn_on=decision.output_on,
                    force=True,
                )
            except HomeAssistantError as err:
                self._service_fault = _bounded_detail(str(err))
                with suppress(HomeAssistantError):
                    await self._async_call_output(turn_on=False, force=True)
                self._set_decision(
                    ControllerDecision(
                        state=OperatingState.FAULT_FALLBACK,
                        reason=f"Output service fault; OFF fallback requested: {err}",
                        reserve_requested=False,
                        output_on=False,
                        active_control=self.config.active_control,
                    )
                )
                return
        if not self._acknowledgement_fault:
            self._service_fault = None
        self._set_decision(decision)

    async def _async_call_output(self, *, turn_on: bool, force: bool = False) -> None:
        """Use the entity domain's async turn-on/turn-off service API."""
        self._observe_output()
        if not force and turn_on == self.output_active:
            return
        try:
            entity_id = str(self.entry.data[CONF_RESERVE_OUTPUT])
            domain = entity_id.partition(".")[0]
            service = SERVICE_TURN_ON if turn_on else SERVICE_TURN_OFF
            await self.hass.services.async_call(
                domain,
                service,
                {ATTR_ENTITY_ID: entity_id},
                blocking=True,
            )
        except Exception as err:
            message = f"digital output service request failed: {err}"
            raise HomeAssistantError(message) from err
        self._observe_output()
        self._pending_output = (
            (turn_on, self._now()) if self.output_active != turn_on else None
        )

    def _observe_output(self) -> None:
        """Expose confirmation from the entity, never infer it from a service call."""
        state = self.hass.states.get(str(self.entry.data.get(CONF_RESERVE_OUTPUT, "")))
        previous = self.output_active
        self.output_active = (
            state.state == "on"
            if state is not None and state.state in {"on", "off"}
            else None
        )
        if previous != self.output_active:
            for listener in tuple(self._listeners):
                listener()

    def _schedule_evaluate(self) -> None:
        """Schedule service I/O outside the state-change callback."""
        self.hass.async_create_task(
            self.async_evaluate(), f"evaluate {DOMAIN} controller"
        )

    def _set_decision(self, decision: ControllerDecision) -> None:
        """Log transitions and notify presentation entities."""
        if decision != self.decision:
            _LOGGER.info(
                "Controller transition %s -> %s: %s",
                self.decision.state,
                decision.state,
                decision.reason,
            )
            self.decision = decision
            for listener in tuple(self._listeners):
                listener()

    def _remove_listener(self) -> None:
        """Remove the coordinator subscription exactly once."""
        if self._remove_coordinator_listener is not None:
            self._remove_coordinator_listener()
            self._remove_coordinator_listener = None

    def _now(self) -> datetime:
        """Use snapshot time when available so tests share the controller clock."""
        if self.coordinator.data is not None:
            return self.coordinator.data.captured_at
        from homeassistant.util import dt as dt_util  # noqa: PLC0415

        return dt_util.utcnow()


def _tank_temperatures(data: RuntimeSnapshot) -> tuple[float, ...]:
    """Return each individually valid tank reading for thermal protection."""
    values: list[float] = []
    for key in (CONF_TANK_TOP, CONF_TANK_MIDDLE, CONF_TANK_BOTTOM):
        normalized = data.values.get(key)
        if normalized is not None and isinstance(normalized.value, (int, float)):
            values.append(float(normalized.value))
    return tuple(values)


def _bounded_detail(detail: str) -> str:
    """Normalize service/runtime fault details for logs and entity states."""
    normalized = " ".join(detail.split())
    return (
        normalized
        if len(normalized) <= _MAX_FAULT_DETAIL_LENGTH
        else f"{normalized[: _MAX_FAULT_DETAIL_LENGTH - 3]}..."
    )

"""Home Assistant runtime for human-in-the-loop stove charging advice."""

from __future__ import annotations

import asyncio
import logging
import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Any, Final

import voluptuous as vol
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .charging import (
    ChargingTarget,
    ChargingTargetInput,
    EnergySample,
    EstimateConfidence,
    LiveChargingEstimate,
    calculate_charging_target,
    calculate_live_charging_estimate,
    detect_active_firing,
    estimate_net_charging_power,
)
from .const import (
    CONF_ADVISOR_LANGUAGE,
    CONF_ALLOW_EXCEPTIONAL_FIRING,
    CONF_BOTTOM_LAYER_VOLUME,
    CONF_CHARGING_SLOPE_THRESHOLD,
    CONF_FORCED_USE_MARGIN,
    CONF_HIGH_TEMPERATURE_THRESHOLD,
    CONF_INITIAL_CHARGING_POWER,
    CONF_MAXIMUM_BOTTOM_TEMPERATURE,
    CONF_MAXIMUM_FIRING_DURATION,
    CONF_MAXIMUM_MIDDLE_TEMPERATURE,
    CONF_MAXIMUM_TOP_TEMPERATURE,
    CONF_MIDDLE_LAYER_VOLUME,
    CONF_MINIMUM_AVOIDED_COST,
    CONF_MINIMUM_FIRING_DURATION,
    CONF_NOTIFICATION_LEAD_TIME,
    CONF_NOTIFICATION_MATERIAL_CHANGE,
    CONF_NOTIFICATION_TARGET,
    CONF_NOTIFICATION_UPDATE_INTERVAL,
    CONF_PREFERRED_FIRING_WINDOWS,
    CONF_QUIET_HOURS_END,
    CONF_QUIET_HOURS_START,
    CONF_RESIDUAL_BURN_ENERGY,
    CONF_SNOOZE_DURATION,
    CONF_STOVE_CHARGING_PUMP,
    CONF_STOVE_EFFICIENCY,
    CONF_STOVE_FLOW_TEMPERATURE,
    CONF_STOVE_TEMPERATURE_THRESHOLD,
    CONF_TANK_BOTTOM,
    CONF_TANK_MIDDLE,
    CONF_TANK_TOP,
    CONF_TOP_LAYER_VOLUME,
    CONF_USABLE_CAPACITY,
    CONF_WOOD_COST,
    CONF_WOOD_ENERGY_CONTENT,
    DEFAULT_ADVISOR_LANGUAGE,
    DEFAULT_ALLOW_EXCEPTIONAL_FIRING,
    DEFAULT_CHARGING_SLOPE_THRESHOLD,
    DEFAULT_FORCED_USE_MARGIN,
    DEFAULT_HIGH_TEMPERATURE_THRESHOLD,
    DEFAULT_INITIAL_CHARGING_POWER,
    DEFAULT_LAYER_VOLUME,
    DEFAULT_MAXIMUM_FIRING_DURATION,
    DEFAULT_MAXIMUM_LAYER_TEMPERATURE,
    DEFAULT_MINIMUM_AVOIDED_COST,
    DEFAULT_MINIMUM_FIRING_DURATION,
    DEFAULT_NOTIFICATION_LEAD_TIME,
    DEFAULT_NOTIFICATION_MATERIAL_CHANGE,
    DEFAULT_NOTIFICATION_UPDATE_INTERVAL,
    DEFAULT_PREFERRED_FIRING_WINDOWS,
    DEFAULT_QUIET_HOURS_END,
    DEFAULT_QUIET_HOURS_START,
    DEFAULT_RESIDUAL_BURN_ENERGY,
    DEFAULT_SNOOZE_DURATION,
    DEFAULT_STOVE_TEMPERATURE_THRESHOLD,
    DEFAULT_USABLE_CAPACITY,
    DOMAIN,
    SERVICE_ACKNOWLEDGE,
    SERVICE_DISMISS,
    SERVICE_SNOOZE,
    SERVICE_START_FIRING,
    SERVICE_STOP_FIRING,
)
from .firing_schedule import (
    FiringSchedule,
    FiringScheduleInput,
    is_in_quiet_hours,
    parse_preferred_windows,
    schedule_firing,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .coordinator import InputCoordinator
    from .data import RuntimeSnapshot
    from .optimizer import PlannedInterval

_LOGGER = logging.getLogger(__name__)
_STORE_VERSION: Final = 1
_MAX_ENERGY_SAMPLES: Final = 12
_ACTION_EVENT: Final = "mobile_app_notification_action"
_MINIMUM_ADVICE_CONFIDENCE: Final = 0.25
_MINIMUM_SLOPE_SAMPLE_COUNT: Final = 2
_TANK_LAYER_COUNT: Final = 3


@dataclass(frozen=True, slots=True)
class AdvisorState:
    """Bounded presentation state published by the advisor runtime."""

    target: ChargingTarget | None
    schedule: FiringSchedule | None
    firing_active: bool
    live: LiveChargingEstimate | None
    advice: str
    estimated_avoided_electricity_cost: float | None
    estimated_net_saving: float | None
    cycle_key: str | None
    notification_error: str | None = None

    @property
    def charge_recommended(self) -> bool:
        """Return whether a feasible, confident manual charge remains useful."""
        if self.target is None or self.schedule is None:
            return False
        residual_done = self.live is not None and self.live.residual_heat_sufficient
        return (
            self.target.additional_energy_kwh > 0
            and self.schedule.feasible
            and self.target.confidence >= _MINIMUM_ADVICE_CONFIDENCE
            and not residual_done
        )


class ChargingAdvisor:
    """Observe the coordinator and issue non-actuating firing guidance."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry[InputCoordinator],
        coordinator: InputCoordinator,
    ) -> None:
        """Initialize isolated advisor runtime and bounded recovery state."""
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.state = AdvisorState(
            target=None,
            schedule=None,
            firing_active=False,
            live=None,
            advice="Waiting for a valid economic plan",
            estimated_avoided_electricity_cost=None,
            estimated_net_saving=None,
            cycle_key=None,
        )
        self._listeners: set[Callable[[], None]] = set()
        self._remove_coordinator_listener: Callable[[], None] | None = None
        self._remove_action_listener: Callable[[], None] | None = None
        self._lock = asyncio.Lock()
        self._samples: deque[EnergySample] = deque(maxlen=_MAX_ENERGY_SAMPLES)
        self._manual_active = False
        self._session_start: datetime | None = None
        self._session_start_energy_kwh: float | None = None
        self._session_target_kwh: float | None = None
        self._smoothed_power_kw: float | None = None
        self._sent_cycle: str | None = None
        self._sent_target_kwh: float | None = None
        self._last_progress_notification: datetime | None = None
        self._completion_notified = False
        self._snoozed_until: datetime | None = None
        self._dismissed_cycle: str | None = None
        self._notification_error: str | None = None
        self._store = Store[dict[str, object]](
            hass, _STORE_VERSION, f"{DOMAIN}.{entry.entry_id}.advisor"
        )

    async def async_start(self) -> None:
        """Restore bounded state, register manual actions, and begin observing."""
        self._restore(await self._store.async_load())
        self._remove_coordinator_listener = self.coordinator.async_add_listener(
            self._schedule_update
        )
        self._remove_action_listener = self.hass.bus.async_listen(
            _ACTION_EVENT, self._async_mobile_action
        )
        self.entry.async_on_unload(self._remove_listeners)
        self._register_services()
        await self.async_update()

    async def async_shutdown(self) -> None:
        """Persist only restart-critical bounded state and detach services."""
        self._remove_listeners()
        for service in (
            SERVICE_START_FIRING,
            SERVICE_STOP_FIRING,
            SERVICE_ACKNOWLEDGE,
            SERVICE_SNOOZE,
            SERVICE_DISMISS,
        ):
            if self.hass.services.has_service(DOMAIN, service):
                self.hass.services.async_remove(DOMAIN, service)
        await self._save()

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Subscribe presentation entities to advisor-only changes."""
        self._listeners.add(listener)

        def remove() -> None:
            self._listeners.discard(listener)

        return remove

    async def async_update(self) -> None:
        """Recalculate target, schedule, session progress, and notifications."""
        async with self._lock:
            data = self.coordinator.data
            if data is None:
                return
            previous_firing = self.state.firing_active
            now = dt_util.as_local(data.captured_at)
            current_energy = data.thermal.usable_energy_kwh
            if current_energy is not None:
                self._record_energy(now, current_energy)
            target, schedule, avoided_cost = self._build_plan(data, now)
            preliminary_power, preliminary_confidence, _ = estimate_net_charging_power(
                tuple(self._samples),
                previous_smoothed_power_kw=self._smoothed_power_kw,
                initial_power_kw=self.coordinator.calibration.value(
                    "net_charging_power_kw",
                    self._option(
                        CONF_INITIAL_CHARGING_POWER, DEFAULT_INITIAL_CHARGING_POWER
                    ),
                ),
            )
            firing = detect_active_firing(
                pump_active=self._bool_value(data, CONF_STOVE_CHARGING_PUMP),
                stove_temperature_c=self._number_value(
                    data, CONF_STOVE_FLOW_TEMPERATURE
                ),
                stove_temperature_threshold_c=self._option(
                    CONF_STOVE_TEMPERATURE_THRESHOLD,
                    DEFAULT_STOVE_TEMPERATURE_THRESHOLD,
                ),
                net_energy_slope_kw=(
                    preliminary_power
                    if len(self._samples) >= _MINIMUM_SLOPE_SAMPLE_COUNT
                    and preliminary_confidence
                    in {EstimateConfidence.MEDIUM, EstimateConfidence.HIGH}
                    and now - self._samples[-1].at <= timedelta(minutes=30)
                    else None
                ),
                slope_threshold_kw=self._option(
                    CONF_CHARGING_SLOPE_THRESHOLD,
                    DEFAULT_CHARGING_SLOPE_THRESHOLD,
                ),
                manual_active=self._manual_active,
            )
            live = self._update_session(
                now,
                current_energy,
                target,
                firing=firing,
                data=data,
            )
            cycle = data.plan.publication_key if data.plan is not None else None
            net_saving = self._net_saving(avoided_cost, target)
            advice = self._format_advice(now, target, schedule, live, avoided_cost)
            new_state = AdvisorState(
                target,
                schedule,
                firing,
                live,
                advice,
                avoided_cost,
                net_saving,
                cycle,
                self._notification_error,
            )
            changed = new_state != self.state
            self.state = new_state
            if changed:
                for listener in tuple(self._listeners):
                    listener()
            await self._maybe_notify(now)
            if self.state.notification_error != self._notification_error:
                self.state = replace(
                    self.state, notification_error=self._notification_error
                )
                for listener in tuple(self._listeners):
                    listener()
            if firing != previous_firing:
                await self._save()

    def _build_plan(
        self, data: RuntimeSnapshot, now: datetime
    ) -> tuple[ChargingTarget | None, FiringSchedule | None, float | None]:
        plan = data.plan
        current = data.thermal.usable_energy_kwh
        if plan is None or current is None or not plan.intervals:
            return None, None, None
        future = [
            period
            for period in plan.intervals
            if period.forecast.end.timestamp() > data.captured_at.timestamp()
        ]
        if not future:
            return None, None, None
        baseline = min(period.forecast.adjusted_value_per_kwh for period in future)
        deadband = self._option("economic_deadband_per_kwh", 0.05)
        valuable = [
            period
            for period in future
            if period.forecast.adjusted_value_per_kwh > 0
            and period.forecast.adjusted_value_per_kwh >= baseline + deadband
        ]
        high_demand = sum(period.forecast.heat_demand_kwh for period in valuable)
        if valuable:
            completion = dt_util.as_local(
                min(valuable, key=lambda period: period.forecast.start).forecast.start
            )
        else:
            completion = dt_util.as_local(plan.forecast_end)
        storage_losses = sum(
            period.forecast.heat_demand_kwh
            * max(1 / max(period.forecast.retention, 1e-6) - 1, 0)
            for period in valuable
        )
        # Charging power is NET storage gain, so concurrent building demand is
        # already reflected in that power and must not be added again.
        initial_power = self.coordinator.calibration.value(
            "net_charging_power_kw",
            self._option(CONF_INITIAL_CHARGING_POWER, DEFAULT_INITIAL_CHARGING_POWER),
        )
        manual_use = self.coordinator.controller.mode.value == "use_tank"
        forced_use = self.coordinator.controller.decision.state.value == "FORCED_USE"
        residual = self.coordinator.calibration.value(
            "residual_burn_energy_kwh",
            self._option(CONF_RESIDUAL_BURN_ENERGY, DEFAULT_RESIDUAL_BURN_ENERGY),
        )
        # Solve the pre-firing discharge/net storage balance. Discharge while
        # firing is already included in net charging power.
        low, high = 0.0, max(high_demand + storage_losses, 0)
        for _ in range(40):
            additional = (low + high) / 2
            firing_start = max(
                now,
                completion
                - timedelta(hours=max(additional - residual, 0) / initial_power),
            )
            intervening = _dispatch_discharge(
                future, now, firing_start, use_all=manual_use or forced_use
            )
            needed = max(
                high_demand + storage_losses - max(current - intervening, 0), 0
            )
            if additional < needed:
                low = additional
            else:
                high = additional
        firing_start = max(
            now, completion - timedelta(hours=max(high - residual, 0) / initial_power)
        )
        intervening = _dispatch_discharge(
            future, now, firing_start, use_all=manual_use or forced_use
        )
        temperatures = tuple(
            value
            for value in (
                self._number_value(data, CONF_TANK_TOP),
                self._number_value(data, CONF_TANK_MIDDLE),
                self._number_value(data, CONF_TANK_BOTTOM),
            )
            if value is not None
        )
        if len(temperatures) != _TANK_LAYER_COUNT:
            return None, None, None
        target = calculate_charging_target(
            ChargingTargetInput(
                current_tank_energy_kwh=current,
                high_cost_heat_demand_kwh=high_demand,
                intervening_discharge_kwh=min(intervening, current),
                firing_session_heat_use_kwh=0,
                storage_losses_kwh=storage_losses,
                usable_capacity_kwh=self.coordinator.calibration.value(
                    "usable_capacity_kwh",
                    self._option(CONF_USABLE_CAPACITY, DEFAULT_USABLE_CAPACITY),
                ),
                layer_temperatures_c=temperatures,
                layer_volumes_l=(
                    self._option(CONF_TOP_LAYER_VOLUME, DEFAULT_LAYER_VOLUME),
                    self._option(CONF_MIDDLE_LAYER_VOLUME, DEFAULT_LAYER_VOLUME),
                    self._option(CONF_BOTTOM_LAYER_VOLUME, DEFAULT_LAYER_VOLUME),
                ),
                maximum_layer_temperatures_c=(
                    self._option(
                        CONF_MAXIMUM_TOP_TEMPERATURE,
                        DEFAULT_MAXIMUM_LAYER_TEMPERATURE,
                    ),
                    self._option(
                        CONF_MAXIMUM_MIDDLE_TEMPERATURE,
                        DEFAULT_MAXIMUM_LAYER_TEMPERATURE,
                    ),
                    self._option(
                        CONF_MAXIMUM_BOTTOM_TEMPERATURE,
                        DEFAULT_MAXIMUM_LAYER_TEMPERATURE,
                    ),
                ),
                forced_use_threshold_c=self._option(
                    CONF_HIGH_TEMPERATURE_THRESHOLD,
                    DEFAULT_HIGH_TEMPERATURE_THRESHOLD,
                ),
                forced_use_margin_c=self._option(
                    CONF_FORCED_USE_MARGIN, DEFAULT_FORCED_USE_MARGIN
                ),
                residual_burn_kwh=self.coordinator.calibration.value(
                    "residual_burn_energy_kwh",
                    self._option(
                        CONF_RESIDUAL_BURN_ENERGY, DEFAULT_RESIDUAL_BURN_ENERGY
                    ),
                ),
                confidence=data.thermal.confidence
                * min((period.forecast.confidence for period in valuable), default=0),
            )
        )
        avoided_cost = sum(
            period.forecast.adjusted_value_per_kwh * period.forecast.heat_demand_kwh
            for period in valuable
        )
        avoided_cost = min(
            avoided_cost,
            target.additional_energy_kwh
            * max(
                (period.forecast.adjusted_value_per_kwh for period in valuable),
                default=0,
            ),
        )
        if avoided_cost < self._option(
            CONF_MINIMUM_AVOIDED_COST, DEFAULT_MINIMUM_AVOIDED_COST
        ):
            target = ChargingTarget(
                additional_energy_kwh=0,
                fuel_phase_energy_kwh=0,
                economically_useful_energy_kwh=target.economically_useful_energy_kwh,
                safe_remaining_capacity_kwh=target.safe_remaining_capacity_kwh,
                residual_burn_kwh=0,
                confidence=target.confidence,
                feasible=False,
                reason=(
                    "Estimated avoided electricity cost is below the configured minimum"
                ),
            )
        if completion <= now:
            completion = max(
                (dt_util.as_local(p.forecast.end) for p in valuable), default=now
            )
        if completion <= now:
            return target, None, avoided_cost
        schedule = schedule_firing(
            FiringScheduleInput(
                now=now,
                required_completion=completion,
                target_additional_kwh=target.fuel_phase_energy_kwh,
                effective_net_power_kw=initial_power,
                preferred_windows=parse_preferred_windows(
                    self.entry.options.get(
                        CONF_PREFERRED_FIRING_WINDOWS,
                        DEFAULT_PREFERRED_FIRING_WINDOWS,
                    )
                ),
                minimum_duration=timedelta(
                    minutes=self._option(
                        CONF_MINIMUM_FIRING_DURATION,
                        DEFAULT_MINIMUM_FIRING_DURATION,
                    )
                ),
                maximum_duration=timedelta(
                    minutes=self._option(
                        CONF_MAXIMUM_FIRING_DURATION,
                        DEFAULT_MAXIMUM_FIRING_DURATION,
                    )
                ),
                notification_lead_time=timedelta(
                    minutes=self._option(
                        CONF_NOTIFICATION_LEAD_TIME,
                        DEFAULT_NOTIFICATION_LEAD_TIME,
                    )
                ),
                allow_exceptional_out_of_window=self._bool_option(
                    CONF_ALLOW_EXCEPTIONAL_FIRING,
                    DEFAULT_ALLOW_EXCEPTIONAL_FIRING,
                ),
                confidence=target.confidence,
                typical_start_minute=(
                    self.coordinator.calibration.parameters[
                        "typical_firing_start_minute"
                    ].value
                    if self.coordinator.calibration.parameters[
                        "typical_firing_start_minute"
                    ].usable(self.coordinator.calibration.config.minimum_confidence)
                    else None
                ),
                typical_duration=(
                    timedelta(
                        minutes=self.coordinator.calibration.parameters[
                            "typical_firing_duration_min"
                        ].value
                        or 0
                    )
                    if self.coordinator.calibration.parameters[
                        "typical_firing_duration_min"
                    ].usable(self.coordinator.calibration.config.minimum_confidence)
                    else None
                ),
            )
        )
        return target, schedule, avoided_cost

    def _update_session(
        self,
        now: datetime,
        current_energy: float | None,
        target: ChargingTarget | None,
        *,
        firing: bool,
        data: RuntimeSnapshot,
    ) -> LiveChargingEstimate | None:
        if not firing or current_energy is None:
            if self.state.firing_active:
                self._manual_active = False
                self._session_start = None
                self._session_start_energy_kwh = None
                self._session_target_kwh = None
                self._smoothed_power_kw = None
                self._completion_notified = False
            return None
        if self._session_start_energy_kwh is None:
            self._session_start = now
            self._session_start_energy_kwh = current_energy
            self._session_target_kwh = (
                target.additional_energy_kwh if target is not None else 0
            )
            self._completion_notified = False
        already_added = max(current_energy - self._session_start_energy_kwh, 0)
        if target is not None:
            self._session_target_kwh = max(
                already_added + target.additional_energy_kwh,
                already_added,
            )
        energy_times = [
            normalized.updated_at
            for key in (CONF_TANK_TOP, CONF_TANK_MIDDLE, CONF_TANK_BOTTOM)
            if (normalized := data.values.get(key)) is not None
        ]
        stale = not energy_times or data.captured_at - max(energy_times) > timedelta(
            minutes=30
        )
        live = calculate_live_charging_estimate(
            now=now,
            session_start_energy_kwh=self._session_start_energy_kwh,
            current_energy_kwh=current_energy,
            target_additional_kwh=self._session_target_kwh or 0,
            residual_burn_kwh=(
                target.residual_burn_kwh
                if target is not None
                else self.coordinator.calibration.value(
                    "residual_burn_energy_kwh",
                    self._option(
                        CONF_RESIDUAL_BURN_ENERGY, DEFAULT_RESIDUAL_BURN_ENERGY
                    ),
                )
            ),
            samples=tuple(
                sample
                for sample in self._samples
                if self._session_start is None or sample.at >= self._session_start
            ),
            previous_smoothed_power_kw=self._smoothed_power_kw,
            initial_power_kw=self.coordinator.calibration.value(
                "net_charging_power_kw",
                self._option(
                    CONF_INITIAL_CHARGING_POWER, DEFAULT_INITIAL_CHARGING_POWER
                ),
            ),
            data_stale=stale,
        )
        self._smoothed_power_kw = live.smoothed_net_power_kw
        return live

    async def _maybe_notify(self, now: datetime) -> None:  # noqa: PLR0911
        target_entity = self.entry.data.get(CONF_NOTIFICATION_TARGET)
        if not target_entity or self._notifications_suppressed(now):
            return
        state = self.state
        cycle = state.cycle_key
        if state.firing_active and state.live is not None:
            if state.live.residual_heat_sufficient and not self._completion_notified:
                self._completion_notified = True
                await self._send_notification(state.advice, replace=True)
                await self._save()
                return
            interval = timedelta(
                minutes=self._option(
                    CONF_NOTIFICATION_UPDATE_INTERVAL,
                    DEFAULT_NOTIFICATION_UPDATE_INTERVAL,
                )
            )
            if (
                self._last_progress_notification is None
                or now - self._last_progress_notification >= interval
            ):
                self._last_progress_notification = now
                await self._send_notification(state.advice, replace=True)
                await self._save()
            return
        schedule = state.schedule
        if not state.charge_recommended or schedule is None or cycle is None:
            return
        if schedule.earliest_useful_start is None:
            return
        lead = timedelta(
            minutes=self._option(
                CONF_NOTIFICATION_LEAD_TIME, DEFAULT_NOTIFICATION_LEAD_TIME
            )
        )
        if now < schedule.earliest_useful_start - lead:
            return
        material = self._option(
            CONF_NOTIFICATION_MATERIAL_CHANGE,
            DEFAULT_NOTIFICATION_MATERIAL_CHANGE,
        )
        changed = (
            self._sent_cycle == cycle
            and self._sent_target_kwh is not None
            and state.target is not None
            and abs(state.target.additional_energy_kwh - self._sent_target_kwh)
            >= material
        )
        if self._sent_cycle == cycle and not changed:
            return
        self._sent_cycle = cycle
        self._sent_target_kwh = (
            state.target.additional_energy_kwh if state.target is not None else None
        )
        await self._send_notification(state.advice, replace=False)
        await self._save()

    async def _send_notification(self, message: str, *, replace: bool) -> bool:
        target = str(self.entry.data[CONF_NOTIFICATION_TARGET])
        title = (
            "Rekommenderad vedeldning"
            if self._language() == "sv"
            else "Recommended stove charging"
        )
        tag = f"{DOMAIN}_{self.entry.entry_id}_{'progress' if replace else 'plan'}"
        payload: dict[str, Any] = {"title": title, "message": message}
        if self._supports_actions(target):
            payload["data"] = {
                "tag": tag,
                "actions": [
                    {"action": self._action("ack"), "title": "OK"},
                    {"action": self._action("snooze"), "title": "Snooze"},
                    {"action": self._action("dismiss"), "title": "Dismiss"},
                ],
            }
        elif replace:
            payload["data"] = {"tag": tag}
        try:
            state_exists = self.hass.states.get(target) is not None
            if state_exists and self.hass.services.has_service(
                "notify", "send_message"
            ):
                await self.hass.services.async_call(
                    "notify",
                    "send_message",
                    payload,
                    target={"entity_id": target},
                    blocking=True,
                )
            else:
                domain, separator, service = target.partition(".")
                if not separator or domain != "notify":
                    msg = "notification target must be a notify entity or service"
                    raise ValueError(msg)  # noqa: TRY301
                await self.hass.services.async_call(
                    domain, service, payload, blocking=True
                )
        except Exception as err:  # noqa: BLE001 - HA services may raise any error.
            self._notification_error = str(err)[:200]
            _LOGGER.warning("Charging-advisor notification failed: %s", err)
            return False
        self._notification_error = None
        return True

    def _notifications_suppressed(self, now: datetime) -> bool:
        if self._snoozed_until is not None and now < self._snoozed_until:
            return True
        if self._dismissed_cycle == self.state.cycle_key:
            return True
        return is_in_quiet_hours(
            now,
            time.fromisoformat(
                str(
                    self.entry.options.get(
                        CONF_QUIET_HOURS_START, DEFAULT_QUIET_HOURS_START
                    )
                )
            ),
            time.fromisoformat(
                str(
                    self.entry.options.get(
                        CONF_QUIET_HOURS_END, DEFAULT_QUIET_HOURS_END
                    )
                )
            ),
        )

    def _format_advice(  # noqa: PLR0911
        self,
        now: datetime,
        target: ChargingTarget | None,
        schedule: FiringSchedule | None,
        live: LiveChargingEstimate | None,
        avoided_cost: float | None,
    ) -> str:
        language = self._language()
        if live is not None:
            total = self._session_target_kwh or 0
            if live.residual_heat_sufficient:
                if language == "sv":
                    return (
                        "Dagens planerade laddmål är uppnått. Ingen ytterligare ved "
                        "behövs för energimålet. Följ alltid kaminens ordinarie "
                        "eldning och säkerhetsinstruktioner."
                    )
                return (
                    "Today's planned charging target has been reached. No more wood "
                    "is needed for the energy target. Always follow the stove's "
                    "normal firing and safety instructions."
                )
            minutes = _minutes(live.minimum_remaining_time)
            completion = _clock(live.expected_completion)
            if language == "sv":
                return (
                    f"Fortsätt elda i minst cirka {minutes} minuter. "
                    f"{live.energy_added_kwh:.1f} av {total:.1f} kWh har laddats. "
                    f"Beräknat mål nås cirka {completion}."
                )
            return (
                f"Continue firing for at least about {minutes} minutes. "
                f"{live.energy_added_kwh:.1f} of {total:.1f} kWh has been charged. "
                f"The target is expected around {completion}."
            )
        if target is None or schedule is None or not schedule.feasible:
            return target.reason if target is not None else "No feasible charge plan"
        duration = _duration_text(schedule.recommended_duration, language)
        earliest = _clock(schedule.earliest_useful_start)
        latest = _clock(schedule.latest_start)
        complete = _clock(schedule.required_completion)
        day = (
            "i dag"
            if schedule.required_completion.date() == now.date()
            else "före behovet"
        )
        cost = round(avoided_cost or 0)
        if language == "sv":
            return (
                f"Elda cirka {duration} {day}. Börja mellan {earliest} och {latest} "
                f"och var klar senast {complete}. Målet är att lagra ytterligare "
                f"{target.additional_energy_kwh:.1f} kWh inför de dyra timmarna. "
                f"Beräknad undvikbar elkostnad: {cost} kr."
            )
        return (
            f"Fire for about {duration}. Start between {earliest} and {latest} and "
            f"finish by {complete}. The target is to store another "
            f"{target.additional_energy_kwh:.1f} kWh for the expensive hours. "
            f"Estimated avoided electricity cost: {cost}."
        )

    def _net_saving(
        self, avoided_cost: float | None, target: ChargingTarget | None
    ) -> float | None:
        values = (
            self.entry.options.get(CONF_WOOD_COST),
            self.entry.options.get(CONF_WOOD_ENERGY_CONTENT),
            self.entry.options.get(CONF_STOVE_EFFICIENCY),
        )
        if (
            avoided_cost is None
            or target is None
            or any(value is None for value in values)
        ):
            return None
        cost, content, efficiency = (float(str(value)) for value in values)
        if cost < 0 or content <= 0 or not 0 < efficiency <= 1:
            return None
        wood_kg = target.additional_energy_kwh / (content * efficiency)
        return avoided_cost - wood_kg * cost

    def _record_energy(self, now: datetime, energy: float) -> None:
        if not self._samples or not math.isclose(
            self._samples[-1].energy_kwh, energy, abs_tol=1e-6
        ):
            self._samples.append(EnergySample(now, energy))

    def _register_services(self) -> None:
        async def handle(call: ServiceCall) -> None:
            now = dt_util.as_local(dt_util.utcnow())
            if call.service == SERVICE_START_FIRING:
                self._manual_active = True
            elif call.service == SERVICE_STOP_FIRING:
                self._manual_active = False
            elif call.service == SERVICE_ACKNOWLEDGE:
                self._sent_cycle = self.state.cycle_key
            elif call.service == SERVICE_SNOOZE:
                minutes = float(
                    call.data.get(
                        "minutes",
                        self._option(CONF_SNOOZE_DURATION, DEFAULT_SNOOZE_DURATION),
                    )
                )
                self._snoozed_until = now + timedelta(minutes=max(minutes, 0))
            elif call.service == SERVICE_DISMISS:
                self._dismissed_cycle = self.state.cycle_key
            await self._save()
            await self.async_update()

        for service in (
            SERVICE_START_FIRING,
            SERVICE_STOP_FIRING,
            SERVICE_ACKNOWLEDGE,
            SERVICE_DISMISS,
        ):
            self.hass.services.async_register(DOMAIN, service, handle)
        self.hass.services.async_register(
            DOMAIN,
            SERVICE_SNOOZE,
            handle,
            schema=vol.Schema({vol.Optional("minutes"): vol.Coerce(float)}),
        )

    @callback
    def _async_mobile_action(self, event: Event) -> None:
        action = str(event.data.get("action", ""))
        if not action.startswith(f"{DOMAIN}_{self.entry.entry_id}_"):
            return
        service = {
            "ack": SERVICE_ACKNOWLEDGE,
            "snooze": SERVICE_SNOOZE,
            "dismiss": SERVICE_DISMISS,
        }.get(action.rsplit("_", maxsplit=1)[-1])
        if service is not None:
            self.hass.async_create_task(
                self.hass.services.async_call(DOMAIN, service, blocking=True),
                f"handle {DOMAIN} notification action",
            )

    def _action(self, suffix: str) -> str:
        return f"{DOMAIN}_{self.entry.entry_id}_{suffix}"

    def _supports_actions(self, target: str) -> bool:
        return target.startswith("notify.mobile_app_")

    async def _save(self) -> None:
        await self._store.async_save(
            {
                "manual_active": self._manual_active,
                "session_start": _iso(self._session_start),
                "session_start_energy_kwh": self._session_start_energy_kwh,
                "session_target_kwh": self._session_target_kwh,
                "smoothed_power_kw": self._smoothed_power_kw,
                "sent_cycle": self._sent_cycle,
                "sent_target_kwh": self._sent_target_kwh,
                "last_progress_notification": _iso(self._last_progress_notification),
                "completion_notified": self._completion_notified,
                "snoozed_until": _iso(self._snoozed_until),
                "dismissed_cycle": self._dismissed_cycle,
            }
        )

    def _restore(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        try:
            self._manual_active = payload.get("manual_active") is True
            self._session_start = _parse_datetime(payload.get("session_start"))
            self._session_start_energy_kwh = _optional_float(
                payload.get("session_start_energy_kwh")
            )
            self._session_target_kwh = _optional_float(
                payload.get("session_target_kwh")
            )
            self._smoothed_power_kw = _optional_float(payload.get("smoothed_power_kw"))
            self._sent_cycle = _optional_string(payload.get("sent_cycle"))
            self._sent_target_kwh = _optional_float(payload.get("sent_target_kwh"))
            self._last_progress_notification = _parse_datetime(
                payload.get("last_progress_notification")
            )
            self._completion_notified = payload.get("completion_notified") is True
            self._snoozed_until = _parse_datetime(payload.get("snoozed_until"))
            self._dismissed_cycle = _optional_string(payload.get("dismissed_cycle"))
        except TypeError, ValueError, OverflowError:
            _LOGGER.warning("Ignoring invalid bounded charging-advisor restore state")

    def _schedule_update(self) -> None:
        self.hass.async_create_task(
            self.async_update(), f"update {DOMAIN} charging advisor"
        )

    def _remove_listeners(self) -> None:
        if self._remove_coordinator_listener is not None:
            self._remove_coordinator_listener()
            self._remove_coordinator_listener = None
        if self._remove_action_listener is not None:
            self._remove_action_listener()
            self._remove_action_listener = None

    def _option(self, key: str, default: float) -> float:
        return float(str(self.entry.options.get(key, default)))

    def _bool_option(self, key: str, default: bool) -> bool:  # noqa: FBT001
        return self.entry.options.get(key, default) is True

    def _language(self) -> str:
        configured = str(
            self.entry.options.get(CONF_ADVISOR_LANGUAGE, DEFAULT_ADVISOR_LANGUAGE)
        ).lower()
        if configured == "auto":
            configured = str(self.hass.config.language).lower()
        return "sv" if configured.startswith("sv") else "en"

    @staticmethod
    def _number_value(data: RuntimeSnapshot, key: str) -> float | None:
        normalized = data.values.get(key)
        if normalized is None or not isinstance(normalized.value, int | float):
            return None
        return float(normalized.value)

    @staticmethod
    def _bool_value(data: RuntimeSnapshot, key: str) -> bool | None:
        normalized = data.values.get(key)
        return (
            normalized.value
            if normalized is not None and isinstance(normalized.value, bool)
            else None
        )


def _dispatch_discharge(
    periods: list[PlannedInterval],
    now: datetime,
    until: datetime,
    *,
    use_all: bool,
) -> float:
    """Estimate discharge only before net charging begins."""
    total = 0.0
    for period in periods:
        start = max(now, period.forecast.start if use_all else period.release_start)
        end = min(until, period.forecast.end)
        if end > start:
            total += (
                period.forecast.heat_demand_kwh
                * (end - start)
                / period.forecast.duration
            )
    return total


def _minutes(duration: timedelta | None) -> int:
    return max(round(duration.total_seconds() / 60), 0) if duration is not None else 0


def _clock(value: datetime | None) -> str:
    return value.strftime("%H:%M") if value is not None else "—"


def _duration_text(duration: timedelta | None, language: str) -> str:
    total = _minutes(duration)
    hours, minutes = divmod(total, 60)
    if language == "sv":
        return f"{hours} tim {minutes} min" if hours else f"{minutes} min"
    return f"{hours} h {minutes} min" if hours else f"{minutes} min"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        msg = "persisted timestamp must be timezone-aware"
        raise ValueError(msg)
    return parsed


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    parsed = float(str(value))
    return parsed if math.isfinite(parsed) else None


def _optional_string(value: object) -> str | None:
    return str(value)[:200] if value is not None else None

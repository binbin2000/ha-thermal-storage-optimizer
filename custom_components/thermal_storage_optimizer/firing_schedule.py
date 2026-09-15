"""Pure preferred-window scheduling for manual stove charging."""

# ruff: noqa: EM101, PLR2004, TRY003

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Final

_WEEKDAYS: Final = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


@dataclass(frozen=True, slots=True)
class FiringWindow:
    """A local wall-clock interval, optionally crossing midnight."""

    start: time
    end: time


@dataclass(frozen=True, slots=True)
class FiringScheduleInput:
    """Inputs to one deterministic schedule calculation."""

    now: datetime
    required_completion: datetime
    target_additional_kwh: float
    effective_net_power_kw: float
    preferred_windows: dict[int, tuple[FiringWindow, ...]]
    minimum_duration: timedelta
    maximum_duration: timedelta
    notification_lead_time: timedelta
    allow_exceptional_out_of_window: bool = False
    confidence: float = 1.0
    typical_start_minute: float | None = None
    typical_duration: timedelta | None = None


@dataclass(frozen=True, slots=True)
class FiringSchedule:
    """Actionable duration and start range for a human operator."""

    recommended_duration: timedelta | None
    earliest_useful_start: datetime | None
    latest_start: datetime | None
    required_completion: datetime
    target_additional_kwh: float
    feasible: bool
    confidence: float
    reason: str


def default_preferred_windows() -> dict[int, tuple[FiringWindow, ...]]:
    """Return a fresh seven-day 15:00-23:00 preferred pattern."""
    return {day: (FiringWindow(time(15), time(23)),) for day in range(7)}


def parse_preferred_windows(value: object) -> dict[int, tuple[FiringWindow, ...]]:
    """Parse weekday mappings such as ``monday: 15:00-23:00``."""
    if value is None:
        return default_preferred_windows()
    if not isinstance(value, dict):
        msg = "preferred firing windows must be a weekday mapping"
        raise TypeError(msg)
    result: dict[int, tuple[FiringWindow, ...]] = {}
    for index, name in enumerate(_WEEKDAYS):
        raw = value.get(name, value.get(str(index), "15:00-23:00"))
        parts = raw if isinstance(raw, list | tuple) else str(raw).split(",")
        windows: list[FiringWindow] = []
        for part in parts:
            text = str(part).strip()
            if not text:
                continue
            start_text, separator, end_text = text.partition("-")
            if not separator:
                msg = f"invalid firing window: {text}"
                raise ValueError(msg)
            windows.append(
                FiringWindow(
                    time.fromisoformat(start_text), time.fromisoformat(end_text)
                )
            )
        result[index] = tuple(windows)
    return result


def schedule_firing(item: FiringScheduleInput) -> FiringSchedule:  # noqa: C901
    """Place charging as late as practical inside a preferred user window."""
    _validate(item)
    if item.target_additional_kwh <= 0:
        return _empty(item, "No additional tank energy is required")
    if item.effective_net_power_kw <= 0:
        return _empty(item, "Effective charging power is not positive")
    raw_duration = timedelta(
        hours=item.target_additional_kwh / item.effective_net_power_kw
    )
    if raw_duration < item.minimum_duration:
        return FiringSchedule(
            recommended_duration=raw_duration,
            earliest_useful_start=None,
            latest_start=None,
            required_completion=item.required_completion,
            target_additional_kwh=item.target_additional_kwh,
            feasible=False,
            confidence=item.confidence,
            reason="Required session is shorter than the configured worthwhile minimum",
        )
    duration = min(raw_duration, item.maximum_duration)
    duration_feasible = raw_duration <= item.maximum_duration
    candidates = _candidate_windows(item)
    chosen: tuple[datetime, datetime] | None = None
    for start, end in candidates:
        completion = min(end, item.required_completion)
        latest = completion - duration
        if latest >= max(start, item.now):
            chosen = start, completion
    exceptional = False
    if chosen is None and item.allow_exceptional_out_of_window:
        latest = item.required_completion - duration
        if latest >= item.now:
            chosen = item.now, item.required_completion
            exceptional = True
    if chosen is None:
        reason = (
            "No preferred firing window can complete the target before it is needed"
        )
        if not duration_feasible:
            reason += "; the full target also exceeds maximum session duration"
        return FiringSchedule(
            recommended_duration=duration,
            earliest_useful_start=None,
            latest_start=None,
            required_completion=item.required_completion,
            target_additional_kwh=item.target_additional_kwh,
            feasible=False,
            confidence=item.confidence,
            reason=reason,
        )
    window_start, completion = chosen
    latest_start = completion - duration
    # A bounded range preserves flexibility but biases toward late charging/lower loss.
    flexibility = min(item.maximum_duration, max(duration, item.notification_lead_time))
    earliest = max(window_start, item.now, latest_start - flexibility)
    learned_preference_used = False
    if item.typical_start_minute is not None:
        preferred = datetime.combine(
            latest_start.date(),
            time(
                int(item.typical_start_minute) // 60,
                int(item.typical_start_minute) % 60,
            ),
            tzinfo=latest_start.tzinfo,
        )
        if max(window_start, item.now) <= preferred <= latest_start:
            margin = timedelta(minutes=30)
            earliest = max(window_start, item.now, preferred - margin)
            latest_start = min(latest_start, preferred + margin)
            learned_preference_used = True
    feasible = duration_feasible and earliest <= latest_start
    reason = (
        "Exceptional out-of-window recommendation explicitly permitted"
        if exceptional
        else (
            "Scheduled within configured window near the learned soft start preference"
            if learned_preference_used
            else "Scheduled late in the preferred window to reduce storage losses"
        )
    )
    if not duration_feasible:
        reason += "; maximum session duration cannot reach the full target"
    return FiringSchedule(
        duration,
        earliest,
        latest_start,
        completion,
        item.target_additional_kwh,
        feasible,
        item.confidence,
        reason,
    )


def is_in_quiet_hours(now: datetime, quiet_start: time, quiet_end: time) -> bool:
    """Return whether a local time lies in a possibly overnight quiet interval."""
    current = now.timetz().replace(tzinfo=None)
    if quiet_start == quiet_end:
        return False
    if quiet_start < quiet_end:
        return quiet_start <= current < quiet_end
    return current >= quiet_start or current < quiet_end


def _candidate_windows(item: FiringScheduleInput) -> list[tuple[datetime, datetime]]:
    tzinfo = item.now.tzinfo
    if tzinfo is None:
        msg = "schedule timestamp must be timezone-aware"
        raise ValueError(msg)
    first = item.now.date() - timedelta(days=1)
    last = item.required_completion.date()
    count = (last - first).days + 1
    result: list[tuple[datetime, datetime]] = []
    for offset in range(count):
        day: date = first + timedelta(days=offset)
        for window in item.preferred_windows.get(day.weekday(), ()):
            start = datetime.combine(day, window.start, tzinfo=tzinfo)
            end_day = day + timedelta(days=1) if window.end <= window.start else day
            end = datetime.combine(end_day, window.end, tzinfo=tzinfo)
            if end > item.now and start < item.required_completion:
                result.append((start, end))
    result.sort()
    return result


def _empty(item: FiringScheduleInput, reason: str) -> FiringSchedule:
    return FiringSchedule(
        recommended_duration=None,
        earliest_useful_start=None,
        latest_start=None,
        required_completion=item.required_completion,
        target_additional_kwh=item.target_additional_kwh,
        feasible=False,
        confidence=item.confidence,
        reason=reason,
    )


def _validate(item: FiringScheduleInput) -> None:
    if item.now.tzinfo is None or item.required_completion.tzinfo is None:
        msg = "schedule timestamps must be timezone-aware"
        raise ValueError(msg)
    if item.required_completion <= item.now:
        msg = "required completion must be in the future"
        raise ValueError(msg)
    if not all(
        math.isfinite(value)
        for value in (
            item.target_additional_kwh,
            item.effective_net_power_kw,
            item.confidence,
        )
    ):
        msg = "schedule quantities must be finite"
        raise ValueError(msg)
    if item.target_additional_kwh < 0:
        msg = "target energy cannot be negative"
        raise ValueError(msg)
    if item.minimum_duration < timedelta(0) or item.maximum_duration <= timedelta(0):
        msg = "session durations must be positive"
        raise ValueError(msg)
    if item.minimum_duration > item.maximum_duration:
        msg = "minimum session duration cannot exceed maximum"
        raise ValueError(msg)
    if item.typical_start_minute is not None and not (
        math.isfinite(item.typical_start_minute)
        and 0 <= item.typical_start_minute < 1440
    ):
        raise ValueError("typical start minute must be within one day")

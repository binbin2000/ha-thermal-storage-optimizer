"""Pure tests for preferred-window manual firing scheduling."""

from datetime import UTC, datetime, time, timedelta

from custom_components.thermal_storage_optimizer.firing_schedule import (
    FiringScheduleInput,
    FiringWindow,
    default_preferred_windows,
    schedule_firing,
)


def _input(**changes: object) -> FiringScheduleInput:
    now = datetime(2026, 9, 7, 10, tzinfo=UTC)  # Monday
    values: dict[str, object] = {
        "now": now,
        "required_completion": now.replace(hour=22),
        "target_additional_kwh": 9.0,
        "effective_net_power_kw": 6.0,
        "preferred_windows": default_preferred_windows(),
        "minimum_duration": timedelta(minutes=30),
        "maximum_duration": timedelta(hours=4),
        "notification_lead_time": timedelta(hours=1),
        "allow_exceptional_out_of_window": False,
        "confidence": 0.8,
    }
    values.update(changes)
    return FiringScheduleInput(**values)  # type: ignore[arg-type]


def test_preferred_window_schedule_is_late_and_fully_bounded() -> None:
    """A normal recommendation stays within 15:00-23:00 and near demand."""
    result = schedule_firing(_input())
    assert result.feasible
    assert result.recommended_duration == timedelta(hours=1, minutes=30)
    assert result.earliest_useful_start is not None
    assert result.latest_start is not None
    assert result.earliest_useful_start.time() >= time(15)
    assert (
        result.latest_start + result.recommended_duration <= result.required_completion
    )


def test_morning_recommendation_is_forbidden_by_default() -> None:
    """A morning deadline cannot pull the default schedule outside its window."""
    result = schedule_firing(
        _input(required_completion=datetime(2026, 9, 8, 7, tzinfo=UTC))
    )
    assert result.feasible
    assert result.latest_start is not None
    assert result.latest_start.date() == datetime(2026, 9, 7, tzinfo=UTC).date()
    assert result.latest_start.time() >= time(15)


def test_exceptional_morning_recommendation_requires_explicit_permission() -> None:
    """When no prior normal window remains, only explicit permission allows morning."""
    now = datetime(2026, 9, 8, 5, tzinfo=UTC)
    deadline = now.replace(hour=7)
    forbidden = schedule_firing(_input(now=now, required_completion=deadline))
    allowed = schedule_firing(
        _input(
            now=now,
            required_completion=deadline,
            allow_exceptional_out_of_window=True,
        )
    )
    assert not forbidden.feasible
    assert allowed.feasible
    assert allowed.earliest_useful_start == now
    assert "explicitly permitted" in allowed.reason


def test_infeasible_duration_reports_maximum_session_limit() -> None:
    """The returned partial duration never disguises an unreachable full target."""
    result = schedule_firing(_input(target_additional_kwh=40.0))
    assert result.recommended_duration == timedelta(hours=4)
    assert not result.feasible
    assert "maximum session duration" in result.reason


def test_zero_power_and_below_minimum_sessions_are_not_recommended() -> None:
    """Zero/negative estimates and trivial fuel phases cannot generate advice."""
    no_power = schedule_firing(_input(effective_net_power_kw=0.0))
    trivial = schedule_firing(_input(target_additional_kwh=1.0))
    assert not no_power.feasible
    assert no_power.recommended_duration is None
    assert not trivial.feasible


def test_custom_weekday_window_is_honored() -> None:
    """Weekday-specific configured patterns replace the default on that day."""
    windows = default_preferred_windows()
    windows[0] = (FiringWindow(time(17), time(20)),)
    result = schedule_firing(
        _input(
            preferred_windows=windows,
            required_completion=datetime(2026, 9, 7, 20, tzinfo=UTC),
        )
    )
    assert result.feasible
    assert result.earliest_useful_start is not None
    assert result.earliest_useful_start.time() >= time(17)


def test_learned_start_is_soft_and_never_bypasses_configured_window() -> None:
    """A learned morning pattern cannot override the default morning prohibition."""
    morning = schedule_firing(_input(typical_start_minute=6 * 60))
    evening = schedule_firing(_input(typical_start_minute=18 * 60))
    assert morning.earliest_useful_start is not None
    assert morning.earliest_useful_start.time() >= time(15)
    assert evening.earliest_useful_start is not None
    assert evening.latest_start is not None
    assert evening.earliest_useful_start.time() >= time(17, 30)
    assert evening.latest_start.time() <= time(18, 30)

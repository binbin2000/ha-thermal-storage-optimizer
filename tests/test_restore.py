"""Pure last-valid-plan persistence validation tests."""

from datetime import UTC, datetime, timedelta

from custom_components.thermal_storage_optimizer.forecast import (
    EconomicForecastInterval,
)
from custom_components.thermal_storage_optimizer.optimizer import optimize_plan
from custom_components.thermal_storage_optimizer.storage import (
    deserialize_plan,
    serialize_plan,
)


def _plan(now: datetime):  # noqa: ANN202
    interval = EconomicForecastInterval(
        now,
        now + timedelta(hours=2),
        timedelta(hours=2),
        3,
        0,
        2,
        3,
        1,
        1,
        1,
        1,
    )
    return optimize_plan(
        (interval,),
        publication_key="restore",
        optimized_at=now,
        available_energy_kwh=1,
        economic_deadband_per_kwh=0,
    )


def test_plan_round_trip_while_timestamps_apply() -> None:
    """Restore the same immutable plan while forecast coverage remains."""
    now = datetime(2026, 9, 7, 11, tzinfo=UTC)
    plan = _plan(now)
    assert (
        deserialize_plan(serialize_plan(plan), now=now + timedelta(minutes=1)) == plan
    )


def test_expired_or_naive_saved_plan_is_rejected() -> None:
    """Never continue stale coverage or timestamps without timezone context."""
    now = datetime(2026, 9, 7, 11, tzinfo=UTC)
    payload = serialize_plan(_plan(now))
    assert deserialize_plan(payload, now=now + timedelta(hours=3)) is None
    payload["forecast_end"] = "2026-09-08T00:00:00"
    assert deserialize_plan(payload, now=now) is None

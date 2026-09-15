"""Unit tests for the pure normalized input layer."""

from datetime import UTC, datetime, timedelta, tzinfo

import pytest

from custom_components.thermal_storage_optimizer.inputs import (
    InputKind,
    InputProblem,
    RawInput,
    normalize_inputs,
)

NOW = datetime(2026, 9, 6, 12, tzinfo=UTC)


def raw(
    *,
    state: str | None = "68",
    unit: str | None = "°F",
    updated_at: datetime | None = NOW,
    kind: InputKind = InputKind.TEMPERATURE,
) -> RawInput:
    """Build one required raw input."""
    return RawInput(
        key="test",
        entity_id="sensor.test",
        kind=kind,
        required=True,
        state=state,
        unit=unit,
        updated_at=updated_at,
        stale_after=timedelta(hours=1),
    )


def test_valid_fixture_produces_typed_normalized_snapshot() -> None:
    """Test canonical unit conversion and immutable typed output."""
    snapshot = normalize_inputs(
        (
            raw(),
            RawInput(
                key="power",
                entity_id="sensor.power",
                kind=InputKind.POWER,
                required=False,
                state="2500",
                unit="W",
                updated_at=NOW,
                stale_after=timedelta(hours=1),
            ),
        ),
        NOW,
    )

    assert snapshot.is_valid
    assert snapshot.issues == ()
    assert snapshot.values["test"].value == pytest.approx(20.0)
    assert snapshot.values["test"].unit == "°C"
    assert snapshot.values["power"].value == pytest.approx(2.5)
    with pytest.raises(TypeError):
        snapshot.values["new"] = snapshot.values["test"]  # type: ignore[index]


@pytest.mark.parametrize(
    ("reading", "problem"),
    [
        (raw(state=None), InputProblem.MISSING),
        (raw(state="unknown"), InputProblem.UNKNOWN),
        (raw(state="unavailable"), InputProblem.UNAVAILABLE),
        (raw(state="warm"), InputProblem.NON_NUMERIC),
        (raw(unit="kWh"), InputProblem.INCOMPATIBLE_UNIT),
        (raw(updated_at=None), InputProblem.INVALID_TIMESTAMP),
        (
            raw(updated_at=NOW - timedelta(hours=2)),
            InputProblem.STALE,
        ),
    ],
)
def test_invalid_values_are_explicit(reading: RawInput, problem: InputProblem) -> None:
    """Test malformed inputs become issues rather than exceptions."""
    snapshot = normalize_inputs((reading,), NOW)

    assert not snapshot.is_valid
    assert snapshot.issues[0].problem is problem
    assert "test" not in snapshot.values


def test_naive_capture_timestamp_is_rejected() -> None:
    """Test callers cannot silently introduce ambiguous timestamps."""
    with pytest.raises(ValueError, match="timezone-aware"):
        normalize_inputs((raw(),), NOW.replace(tzinfo=None))


class UndefinedOffsetTimezone(tzinfo):
    """Timezone marker that deliberately has no usable UTC offset."""

    def utcoffset(self, _value: datetime | None) -> None:
        """Return an undefined offset."""

    def dst(self, _value: datetime | None) -> None:
        """Return an undefined daylight-saving offset."""


def test_timestamp_with_undefined_offset_is_explicitly_rejected() -> None:
    """Test malformed timezone metadata cannot escape as a comparison error."""
    malformed = NOW.replace(tzinfo=UndefinedOffsetTimezone())

    snapshot = normalize_inputs((raw(updated_at=malformed),), NOW)

    assert not snapshot.is_valid
    assert snapshot.issues[0].problem is InputProblem.INVALID_TIMESTAMP


@pytest.mark.parametrize(
    ("kind", "state", "unit", "expected_value", "expected_unit"),
    [
        (InputKind.TEMPERATURE, "293.15", "K", 20.0, "°C"),
        (InputKind.POWER, "1.5", "MW", 1500.0, "kW"),
        (InputKind.ENERGY, "2500", "Wh", 2.5, "kWh"),
        (InputKind.FLOW_RATE, "1", "m³/h", 1000.0 / 60.0, "L/min"),
        (InputKind.COP, "3.2", None, 3.2, None),
    ],
)
def test_supported_input_kinds_use_canonical_values(
    kind: InputKind,
    state: str,
    unit: str | None,
    expected_value: float,
    expected_unit: str | None,
) -> None:
    """Test every implemented quantity has a typed canonical representation."""
    snapshot = normalize_inputs(
        (raw(kind=kind, state=state, unit=unit),),
        NOW,
    )

    assert snapshot.is_valid
    assert snapshot.values["test"].value == pytest.approx(expected_value)
    assert snapshot.values["test"].unit == expected_unit


def test_digital_input_is_normalized_to_boolean() -> None:
    """Test Home Assistant digital state becomes a typed boolean."""
    snapshot = normalize_inputs(
        (raw(kind=InputKind.DIGITAL, state="on", unit=None),), NOW
    )

    assert snapshot.is_valid
    assert snapshot.values["test"].value is True
    assert snapshot.values["test"].unit is None


def test_invalid_optional_input_is_reported_without_invalidating_snapshot() -> None:
    """Test optional input defects remain visible but do not block required data."""
    optional = RawInput(
        key="optional_power",
        entity_id="sensor.optional_power",
        kind=InputKind.POWER,
        required=False,
        state="broken",
        unit="W",
        updated_at=NOW,
        stale_after=timedelta(hours=1),
    )

    snapshot = normalize_inputs((raw(), optional), NOW)

    assert snapshot.is_valid
    assert snapshot.issues[0].problem is InputProblem.NON_NUMERIC
    assert snapshot.required_issues == ()


@pytest.mark.parametrize("state", ["open", "1", ""])
def test_invalid_digital_states_are_explicit(state: str) -> None:
    """Test a digital source accepts only Home Assistant on/off states."""
    snapshot = normalize_inputs(
        (raw(kind=InputKind.DIGITAL, state=state, unit=None),), NOW
    )

    assert not snapshot.is_valid
    assert snapshot.issues[0].problem is InputProblem.INVALID_STATE

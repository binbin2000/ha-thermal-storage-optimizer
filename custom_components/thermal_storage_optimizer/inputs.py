"""Pure, typed normalization models for installation inputs."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class InputKind(StrEnum):
    """Supported normalized input quantities."""

    TEMPERATURE = "temperature"
    POWER = "power"
    ENERGY = "energy"
    COP = "cop"
    FLOW_RATE = "flow_rate"
    AVAILABILITY = "availability"
    DIGITAL = "digital"


class InputProblem(StrEnum):
    """Explicit reasons why a source could not be normalized."""

    MISSING = "missing"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    NON_NUMERIC = "non_numeric"
    INCOMPATIBLE_UNIT = "incompatible_unit"
    INVALID_TIMESTAMP = "invalid_timestamp"
    INVALID_STATE = "invalid_state"


@dataclass(frozen=True, slots=True)
class RawInput:
    """Source-neutral representation of one raw Home Assistant reading."""

    key: str
    entity_id: str
    kind: InputKind
    required: bool
    state: str | float | None
    unit: str | None
    updated_at: datetime | None
    stale_after: timedelta | None


@dataclass(frozen=True, slots=True)
class NormalizedValue:
    """One validated value in canonical units."""

    entity_id: str
    value: float | str | bool
    unit: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class InputIssue:
    """A normalization failure that can be safely presented in diagnostics."""

    key: str
    entity_id: str
    problem: InputProblem
    required: bool


@dataclass(frozen=True, slots=True)
class NormalizedInputSnapshot:
    """Immutable normalized inputs consumed by later pure domain layers."""

    captured_at: datetime
    values: Mapping[str, NormalizedValue]
    issues: tuple[InputIssue, ...]

    @property
    def is_valid(self) -> bool:
        """Return whether every required input was normalized."""
        return not any(issue.required for issue in self.issues)

    @property
    def required_issues(self) -> tuple[InputIssue, ...]:
        """Return issues affecting required inputs."""
        return tuple(issue for issue in self.issues if issue.required)


_TEMPERATURE_FACTORS: Final = {
    "°c": lambda value: value,
    "c": lambda value: value,
    "°f": lambda value: (value - 32.0) * 5.0 / 9.0,
    "f": lambda value: (value - 32.0) * 5.0 / 9.0,
    "k": lambda value: value - 273.15,
}
_POWER_FACTORS: Final = {"w": 0.001, "kw": 1.0, "mw": 1000.0}
_ENERGY_FACTORS: Final = {"wh": 0.001, "kwh": 1.0, "mwh": 1000.0}
_FLOW_FACTORS: Final = {
    "l/min": 1.0,
    "l/s": 60.0,
    "m³/h": 1000.0 / 60.0,
    "m3/h": 1000.0 / 60.0,
}
_CANONICAL_UNITS: Final = {
    InputKind.TEMPERATURE: "°C",
    InputKind.POWER: "kW",
    InputKind.ENERGY: "kWh",
    InputKind.COP: None,
    InputKind.FLOW_RATE: "L/min",
}


def normalize_inputs(
    raw_inputs: tuple[RawInput, ...], captured_at: datetime
) -> NormalizedInputSnapshot:
    """Normalize raw readings without importing Home Assistant."""
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        message = "captured_at must be timezone-aware"
        raise ValueError(message)

    values: dict[str, NormalizedValue] = {}
    issues: list[InputIssue] = []
    for raw in raw_inputs:
        result = _normalize_one(raw, captured_at)
        if isinstance(result, InputIssue):
            issues.append(result)
        else:
            values[raw.key] = result
    return NormalizedInputSnapshot(
        captured_at=captured_at,
        values=MappingProxyType(values),
        issues=tuple(issues),
    )


def _normalize_one(
    raw: RawInput, captured_at: datetime
) -> NormalizedValue | InputIssue:
    problem = _common_problem(raw, captured_at)
    if problem is not None:
        return _issue(raw, problem)
    if raw.state is None or raw.updated_at is None:
        return _issue(raw, InputProblem.INVALID_TIMESTAMP)
    state = str(raw.state).strip()

    if raw.kind is InputKind.AVAILABILITY:
        return NormalizedValue(raw.entity_id, state, None, raw.updated_at)
    if raw.kind is InputKind.DIGITAL:
        if state.lower() not in {"on", "off"}:
            return _issue(raw, InputProblem.INVALID_STATE)
        return NormalizedValue(
            raw.entity_id, state.lower() == "on", None, raw.updated_at
        )

    return _normalize_numeric(raw, state, raw.updated_at)


def _common_problem(raw: RawInput, captured_at: datetime) -> InputProblem | None:
    """Validate state availability, timestamp shape, and freshness."""
    problem: InputProblem | None = None
    if raw.state is None:
        problem = InputProblem.MISSING
    elif str(raw.state).strip().lower() == "unknown":
        problem = InputProblem.UNKNOWN
    elif str(raw.state).strip().lower() == "unavailable":
        problem = InputProblem.UNAVAILABLE
    elif (
        raw.updated_at is None
        or raw.updated_at.tzinfo is None
        or raw.updated_at.utcoffset() is None
        or raw.updated_at > captured_at + timedelta(seconds=1)
    ):
        problem = InputProblem.INVALID_TIMESTAMP
    elif raw.stale_after is not None and captured_at - raw.updated_at > raw.stale_after:
        problem = InputProblem.STALE
    return problem


def _normalize_numeric(
    raw: RawInput, state: str, updated_at: datetime
) -> NormalizedValue | InputIssue:
    """Parse and convert a finite numeric quantity."""
    try:
        numeric = float(state)
    except ValueError:
        return _issue(raw, InputProblem.NON_NUMERIC)
    if not math.isfinite(numeric):
        return _issue(raw, InputProblem.NON_NUMERIC)

    normalized = _convert_value(raw.kind, numeric, raw.unit)
    if normalized is None:
        return _issue(raw, InputProblem.INCOMPATIBLE_UNIT)
    return NormalizedValue(
        raw.entity_id,
        normalized,
        _CANONICAL_UNITS[raw.kind],
        updated_at,
    )


def _issue(raw: RawInput, problem: InputProblem) -> InputIssue:
    """Build one consistently shaped diagnostic issue."""
    return InputIssue(raw.key, raw.entity_id, problem, raw.required)


def _convert_value(kind: InputKind, value: float, unit: str | None) -> float | None:
    normalized_unit = unit.strip().lower() if unit is not None else None
    if kind is InputKind.COP:
        return value if normalized_unit in {None, "", "cop"} and value > 0 else None
    if kind is InputKind.TEMPERATURE:
        converter = _TEMPERATURE_FACTORS.get(normalized_unit or "")
        return converter(value) if converter is not None else None
    if kind is InputKind.POWER:
        factor = _POWER_FACTORS.get(normalized_unit or "")
    elif kind is InputKind.ENERGY:
        factor = _ENERGY_FACTORS.get(normalized_unit or "")
    elif kind is InputKind.FLOW_RATE:
        factor = _FLOW_FACTORS.get(normalized_unit or "")
    else:
        return None
    return value * factor if factor is not None else None

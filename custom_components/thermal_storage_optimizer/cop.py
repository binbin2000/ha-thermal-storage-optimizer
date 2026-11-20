"""Replaceable coefficient-of-performance models with a fixed fallback."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Protocol

if TYPE_CHECKING:
    from datetime import datetime

    from .adaptive import ParameterBounds
    from .curves import OutdoorBinnedCurve

KELVIN_OFFSET: Final = 273.15
FIXED_FALLBACK_CONFIDENCE: Final = 0.6
_CARNOT_CONFIDENCE_FACTOR: Final = 0.5
_MINIMUM_LIFT_K: Final = 1.0


class CopSource(StrEnum):
    """Origin of a selected COP value."""

    MEASURED = "measured"
    LEARNED_CURVE = "learned_curve"
    CARNOT_EXTRAPOLATION = "carnot_extrapolation"
    CALIBRATED = "calibrated"
    FIXED_FALLBACK = "fixed_fallback"


@dataclass(frozen=True, slots=True)
class CopEstimate:
    """Selected COP plus source and conservative confidence."""

    value: float
    source: CopSource
    confidence: float


class CopModel(Protocol):
    """Interface for fixed or temperature-dependent COP models."""

    def estimate(
        self, *, outdoor_temperature_c: float, supply_temperature_c: float
    ) -> float:
        """Estimate COP for operating temperatures."""
        ...

    def explain(
        self, *, outdoor_temperature_c: float, supply_temperature_c: float
    ) -> CopEstimate:
        """Estimate COP together with its source and confidence."""
        ...


@dataclass(frozen=True, slots=True)
class FixedCopModel:
    """Validated deterministic COP model independent of temperatures."""

    cop: float

    def __post_init__(self) -> None:
        """Reject physically invalid fallback values."""
        if not math.isfinite(self.cop) or self.cop <= 0:
            msg = "fixed COP must be finite and positive"
            raise ValueError(msg)

    def estimate(
        self, *, outdoor_temperature_c: float, supply_temperature_c: float
    ) -> float:
        """Return the configured COP after validating interface inputs."""
        _validate_temperatures(outdoor_temperature_c, supply_temperature_c)
        return self.cop

    def explain(
        self, *, outdoor_temperature_c: float, supply_temperature_c: float
    ) -> CopEstimate:
        """Return the fixed fallback with its conservative confidence."""
        return CopEstimate(
            self.estimate(
                outdoor_temperature_c=outdoor_temperature_c,
                supply_temperature_c=supply_temperature_c,
            ),
            CopSource.FIXED_FALLBACK,
            FIXED_FALLBACK_CONFIDENCE,
        )


@dataclass(frozen=True, slots=True)
class LearnedCopModel:
    """COP from learned outdoor-temperature bins, Carnot extrapolation, or fallback.

    Inside the learned range a bin median or interpolation between bins is used.
    Outside it, the learned Carnot efficiency scales the ideal COP for the
    interval's outdoor and supply temperatures, so colder weather lowers COP even
    where no sample exists yet. Without a learned efficiency the fallback applies.
    """

    curve: OutdoorBinnedCurve
    now: datetime
    minimum_confidence: float
    carnot_efficiency: float | None
    bounds: ParameterBounds
    fallback: CopModel

    def estimate(
        self, *, outdoor_temperature_c: float, supply_temperature_c: float
    ) -> float:
        """Return the explained estimate's value."""
        return self.explain(
            outdoor_temperature_c=outdoor_temperature_c,
            supply_temperature_c=supply_temperature_c,
        ).value

    def explain(
        self, *, outdoor_temperature_c: float, supply_temperature_c: float
    ) -> CopEstimate:
        """Select learned bins, Carnot extrapolation, or the fallback in order."""
        _validate_temperatures(outdoor_temperature_c, supply_temperature_c)
        learned = self.curve.estimate(
            outdoor_temperature_c, self.now, self.minimum_confidence
        )
        if learned is not None and learned.source != "nearest":
            return CopEstimate(
                self.bounds.clamp(learned.value),
                CopSource.LEARNED_CURVE,
                learned.confidence,
            )
        if self.carnot_efficiency is not None:
            ideal = carnot_cop(
                outdoor_temperature_c=outdoor_temperature_c,
                supply_temperature_c=supply_temperature_c,
            )
            confidence = (
                learned.confidence if learned is not None else self.minimum_confidence
            ) * _CARNOT_CONFIDENCE_FACTOR
            return CopEstimate(
                self.bounds.clamp(self.carnot_efficiency * ideal),
                CopSource.CARNOT_EXTRAPOLATION,
                confidence,
            )
        return self.fallback.explain(
            outdoor_temperature_c=outdoor_temperature_c,
            supply_temperature_c=supply_temperature_c,
        )


def carnot_cop(*, outdoor_temperature_c: float, supply_temperature_c: float) -> float:
    """Return the ideal heating COP for a sink at supply and a source at outdoor."""
    _validate_temperatures(outdoor_temperature_c, supply_temperature_c)
    lift = max(supply_temperature_c - outdoor_temperature_c, _MINIMUM_LIFT_K)
    return (supply_temperature_c + KELVIN_OFFSET) / lift


def carnot_efficiency(
    *, measured_cop: float, outdoor_temperature_c: float, supply_temperature_c: float
) -> float | None:
    """Return the measured fraction of ideal COP, or None when not identifiable."""
    if not math.isfinite(measured_cop) or measured_cop <= 0:
        return None
    if supply_temperature_c - outdoor_temperature_c < _MINIMUM_LIFT_K:
        return None
    return measured_cop / carnot_cop(
        outdoor_temperature_c=outdoor_temperature_c,
        supply_temperature_c=supply_temperature_c,
    )


def estimate_cop(
    model: CopModel,
    *,
    outdoor_temperature_c: float,
    supply_temperature_c: float,
    measured_cop: float | None = None,
) -> CopEstimate:
    """Prefer a valid measurement and otherwise use the model's explained value."""
    if measured_cop is not None and math.isfinite(measured_cop) and measured_cop > 0:
        return CopEstimate(measured_cop, CopSource.MEASURED, 1.0)
    estimate = model.explain(
        outdoor_temperature_c=outdoor_temperature_c,
        supply_temperature_c=supply_temperature_c,
    )
    if not math.isfinite(estimate.value) or estimate.value <= 0:
        msg = "COP model must return a finite positive value"
        raise ValueError(msg)
    return estimate


def _validate_temperatures(
    outdoor_temperature_c: float, supply_temperature_c: float
) -> None:
    if not all(
        math.isfinite(value) for value in (outdoor_temperature_c, supply_temperature_c)
    ):
        msg = "COP model temperatures must be finite"
        raise ValueError(msg)

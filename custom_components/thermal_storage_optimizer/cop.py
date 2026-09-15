"""Replaceable coefficient-of-performance models with a fixed fallback."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class CopSource(StrEnum):
    """Origin of a selected COP value."""

    MEASURED = "measured"
    CALIBRATED = "calibrated"
    FIXED_FALLBACK = "fixed_fallback"


class CopModel(Protocol):
    """Interface for fixed or future temperature-dependent COP models."""

    def estimate(
        self, *, outdoor_temperature_c: float, supply_temperature_c: float
    ) -> float:
        """Estimate COP for operating temperatures."""
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
        if not all(
            math.isfinite(value)
            for value in (outdoor_temperature_c, supply_temperature_c)
        ):
            msg = "COP model temperatures must be finite"
            raise ValueError(msg)
        return self.cop


@dataclass(frozen=True, slots=True)
class CopEstimate:
    """Selected COP plus source and conservative confidence."""

    value: float
    source: CopSource
    confidence: float


def estimate_cop(
    model: CopModel,
    *,
    outdoor_temperature_c: float,
    supply_temperature_c: float,
    measured_cop: float | None = None,
) -> CopEstimate:
    """Prefer a valid measurement and otherwise use the configured model fallback."""
    if measured_cop is not None and math.isfinite(measured_cop) and measured_cop > 0:
        return CopEstimate(measured_cop, CopSource.MEASURED, 1.0)
    fallback = model.estimate(
        outdoor_temperature_c=outdoor_temperature_c,
        supply_temperature_c=supply_temperature_c,
    )
    if not math.isfinite(fallback) or fallback <= 0:
        msg = "COP model must return a finite positive value"
        raise ValueError(msg)
    return CopEstimate(fallback, CopSource.FIXED_FALLBACK, 0.6)

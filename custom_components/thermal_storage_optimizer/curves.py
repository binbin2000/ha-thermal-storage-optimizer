"""Bounded curves binned by outdoor temperature and learned from live inputs.

The same binning model serves the heating curve (heat-pump supply target versus
outdoor temperature) and, later, temperature-dependent COP. Samples are kept per
outdoor-temperature bin with a robust median, bounded counts, and age limits so a
changed installation setting is forgotten within the configured sample age.
"""

# ruff: noqa: EM101, PLR0913, TRY003

from __future__ import annotations

import math
import statistics
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from .adaptive import ParameterBounds

CURVE_SCHEMA_VERSION: Final = 1
MAX_SAMPLES_PER_BIN: Final = 48
MAX_BINS: Final = 30
MAX_SAMPLE_AGE: Final = timedelta(days=30)
MIN_BIN_SAMPLE_INTERVAL: Final = timedelta(minutes=30)
MIN_BIN_SAMPLES: Final = 6
MIN_POPULATED_BINS: Final = 2
DEFAULT_BIN_WIDTH_C: Final = 3.0
_EXTRAPOLATION_CONFIDENCE_FACTOR: Final = 0.8
_OUTDOOR_LIMITS_C: Final = (-60.0, 60.0)


@dataclass(frozen=True, slots=True)
class CurveSample:
    """One timestamped measurement at a known outdoor temperature."""

    at: datetime
    outdoor_c: float
    value: float


@dataclass(frozen=True, slots=True)
class BinSummary:
    """Robust statistics of one outdoor-temperature bin."""

    center_c: float
    median: float
    sample_count: int
    confidence: float


@dataclass(frozen=True, slots=True)
class CurveEstimate:
    """One explainable curve lookup."""

    value: float
    confidence: float
    source: str
    sample_count: int


class OutdoorBinnedCurve:
    """Bounded per-bin samples with robust median lookup and interpolation."""

    def __init__(
        self,
        *,
        name: str,
        unit: str,
        bin_width_c: float,
        value_bounds: ParameterBounds,
        max_age: timedelta = MAX_SAMPLE_AGE,
        min_bin_samples: int = MIN_BIN_SAMPLES,
    ) -> None:
        """Create an empty curve with explicit physical limits."""
        if not math.isfinite(bin_width_c) or bin_width_c <= 0:
            raise ValueError("bin width must be finite and positive")
        if max_age <= timedelta(0) or min_bin_samples < 1:
            raise ValueError("sample age and bin size must be positive")
        self.name = name
        self.unit = unit
        self.bin_width_c = float(bin_width_c)
        self.value_bounds = value_bounds
        self.max_age = max_age
        self.min_bin_samples = min_bin_samples
        self._bins: dict[int, deque[CurveSample]] = {}

    @property
    def sample_count(self) -> int:
        """Return the number of retained samples across all bins."""
        return sum(len(samples) for samples in self._bins.values())

    def add_sample(self, at: datetime, outdoor_c: float, value: float) -> bool:
        """Accept one bounded sample; reject invalid, out-of-bounds, or rapid input."""
        if not _aware(at):
            raise ValueError("curve samples must be timezone-aware")
        if not all(math.isfinite(item) for item in (outdoor_c, value)):
            return False
        if not _OUTDOOR_LIMITS_C[0] <= outdoor_c <= _OUTDOOR_LIMITS_C[1]:
            return False
        if not self.value_bounds.minimum <= value <= self.value_bounds.maximum:
            return False
        key = self._key(outdoor_c)
        samples = self._bins.get(key)
        if samples is None:
            if len(self._bins) >= MAX_BINS:
                return False
            samples = deque(maxlen=MAX_SAMPLES_PER_BIN)
            self._bins[key] = samples
        if samples and at - samples[-1].at < MIN_BIN_SAMPLE_INTERVAL:
            return False
        samples.append(CurveSample(at, float(outdoor_c), float(value)))
        return True

    def prune(self, now: datetime) -> None:
        """Forget samples older than the maximum age and any emptied bins."""
        for key in list(self._bins):
            kept = deque(
                (s for s in self._bins[key] if now - s.at <= self.max_age),
                maxlen=MAX_SAMPLES_PER_BIN,
            )
            if kept:
                self._bins[key] = kept
            else:
                del self._bins[key]

    def summaries(self, now: datetime) -> tuple[BinSummary, ...]:
        """Return robust statistics for every sufficiently populated bin."""
        result: list[BinSummary] = []
        for key in sorted(self._bins):
            values = [s.value for s in self._bins[key] if now - s.at <= self.max_age]
            if len(values) < self.min_bin_samples:
                continue
            median = statistics.median(values)
            mad = statistics.median(abs(value - median) for value in values)
            relative_spread = mad / max(abs(median), 1.0)
            confidence = min(len(values) / (self.min_bin_samples * 2), 1.0) * max(
                1 - relative_spread * 3, 0.0
            )
            result.append(
                BinSummary(
                    (key + 0.5) * self.bin_width_c, median, len(values), confidence
                )
            )
        return tuple(result)

    def usable(self, now: datetime, minimum_confidence: float) -> bool:
        """Return whether enough confident bins exist to describe a curve."""
        return len(self._confident(now, minimum_confidence)) >= MIN_POPULATED_BINS

    def estimate(
        self, outdoor_c: float, now: datetime, minimum_confidence: float
    ) -> CurveEstimate | None:
        """Look up the curve: exact bin, linear interpolation, or nearest bin."""
        if not math.isfinite(outdoor_c):
            raise ValueError("outdoor temperature must be finite")
        bins = self._confident(now, minimum_confidence)
        if len(bins) < MIN_POPULATED_BINS:
            return None
        for item in bins:
            if abs(item.center_c - outdoor_c) <= self.bin_width_c / 2:
                return CurveEstimate(
                    item.median, item.confidence, "bin", item.sample_count
                )
        if outdoor_c < bins[0].center_c:
            nearest = bins[0]
        elif outdoor_c > bins[-1].center_c:
            nearest = bins[-1]
        else:
            lower = max(
                (item for item in bins if item.center_c < outdoor_c),
                key=lambda item: item.center_c,
            )
            upper = min(
                (item for item in bins if item.center_c > outdoor_c),
                key=lambda item: item.center_c,
            )
            fraction = (outdoor_c - lower.center_c) / (upper.center_c - lower.center_c)
            return CurveEstimate(
                lower.median + fraction * (upper.median - lower.median),
                min(lower.confidence, upper.confidence),
                "interpolated",
                lower.sample_count + upper.sample_count,
            )
        return CurveEstimate(
            nearest.median,
            nearest.confidence * _EXTRAPOLATION_CONFIDENCE_FACTOR,
            "nearest",
            nearest.sample_count,
        )

    def reset(self) -> None:
        """Forget every sample."""
        self._bins.clear()

    def serialize(self) -> list[list[float | str]]:
        """Return bounded JSON-compatible samples."""
        return [
            [s.at.isoformat(), round(s.outdoor_c, 2), round(s.value, 3)]
            for key in sorted(self._bins)
            for s in self._bins[key]
        ]

    def restore(self, payload: object, *, now: datetime) -> None:
        """Re-add bounded persisted samples, ignoring malformed or future ones."""
        if not isinstance(payload, list) or len(payload) > MAX_BINS * (
            MAX_SAMPLES_PER_BIN
        ):
            raise ValueError("invalid curve sample list")
        samples: list[CurveSample] = []
        for item in payload:
            if not isinstance(item, list) or len(item) != 3:  # noqa: PLR2004
                raise ValueError("invalid curve sample")
            at = datetime.fromisoformat(str(item[0]))
            if not _aware(at):
                raise ValueError("curve sample timestamp must be timezone-aware")
            if at > now + timedelta(minutes=5):
                continue
            samples.append(CurveSample(at, float(item[1]), float(item[2])))
        samples.sort(key=lambda s: s.at)
        for sample in samples:
            if now - sample.at <= self.max_age:
                self.add_sample(sample.at, sample.outdoor_c, sample.value)

    def diagnostics(self, now: datetime, minimum_confidence: float) -> dict[str, Any]:
        """Return bounded, entity-free curve diagnostics."""
        return {
            "unit": self.unit,
            "bin_width_c": self.bin_width_c,
            "sample_count": self.sample_count,
            "bin_count": len(self._bins),
            "usable": self.usable(now, minimum_confidence),
            "bins": [
                {
                    "center_c": item.center_c,
                    "median": round(item.median, 3),
                    "sample_count": item.sample_count,
                    "confidence": round(item.confidence, 3),
                }
                for item in self.summaries(now)
            ],
        }

    def _key(self, outdoor_c: float) -> int:
        return math.floor(outdoor_c / self.bin_width_c)

    def _confident(
        self, now: datetime, minimum_confidence: float
    ) -> tuple[BinSummary, ...]:
        return tuple(
            item
            for item in self.summaries(now)
            if item.confidence >= minimum_confidence
        )


@dataclass(frozen=True, slots=True)
class CurveConfig:
    """Activation gate and physical limits for learned temperature curves."""

    enabled: bool
    bin_width_c: float
    minimum_confidence: float
    supply_bounds: ParameterBounds


class TemperatureCurveSet:
    """Own the learned curves, their persistence, and safe lookups."""

    def __init__(self, config: CurveConfig) -> None:
        """Create empty curves from validated configuration."""
        self.config = config
        self.heating_curve = OutdoorBinnedCurve(
            name="heating_curve",
            unit="°C",
            bin_width_c=config.bin_width_c,
            value_bounds=config.supply_bounds,
        )
        self.revision = 0

    @property
    def curves(self) -> dict[str, OutdoorBinnedCurve]:
        """Return every learned curve by name."""
        return {self.heating_curve.name: self.heating_curve}

    def observe(
        self,
        *,
        now: datetime,
        outdoor_c: float | None,
        supply_target_c: float | None,
    ) -> bool:
        """Record one refresh; return whether any curve accepted a sample."""
        if not self.config.enabled or outdoor_c is None:
            return False
        accepted = False
        if supply_target_c is not None:
            accepted = self.heating_curve.add_sample(now, outdoor_c, supply_target_c)
        if accepted:
            self.revision += 1
            self.heating_curve.prune(now)
        return accepted

    def supply_temperature_for(
        self, outdoor_c: float, *, now: datetime, fallback_c: float
    ) -> float:
        """Return the learned supply target or the current measured target."""
        if not self.config.enabled:
            return fallback_c
        estimate = self.heating_curve.estimate(
            outdoor_c, now, self.config.minimum_confidence
        )
        return fallback_c if estimate is None else estimate.value

    def heating_curve_usable(self, now: datetime) -> bool:
        """Return whether the learned heating curve replaces the measured target."""
        return self.config.enabled and self.heating_curve.usable(
            now, self.config.minimum_confidence
        )

    def reset(self) -> None:
        """Forget all learned curve samples; configuration is untouched."""
        for curve in self.curves.values():
            curve.reset()
        self.revision += 1

    def serialize(self) -> dict[str, Any]:
        """Serialize bounded samples for every curve."""
        return {
            "schema_version": CURVE_SCHEMA_VERSION,
            "curves": {name: curve.serialize() for name, curve in self.curves.items()},
        }

    def restore(self, payload: object, *, now: datetime) -> bool:
        """Restore persisted samples; malformed payloads leave the curves empty."""
        if not isinstance(payload, Mapping):
            return False
        if payload.get("schema_version") != CURVE_SCHEMA_VERSION:
            return False
        stored = payload.get("curves")
        if not isinstance(stored, Mapping):
            return False
        try:
            for name, curve in self.curves.items():
                if name in stored:
                    curve.restore(stored[name], now=now)
        except TypeError, ValueError, OverflowError:
            self.reset()
            return False
        self.revision += 1
        return True

    def diagnostics(self, now: datetime) -> dict[str, Any]:
        """Return bounded diagnostics for every curve."""
        return {
            "enabled": self.config.enabled,
            "minimum_confidence": self.config.minimum_confidence,
            "curves": {
                name: curve.diagnostics(now, self.config.minimum_confidence)
                for name, curve in self.curves.items()
            },
        }


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None

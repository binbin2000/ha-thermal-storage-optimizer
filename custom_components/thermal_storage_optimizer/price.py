"""Strict, isolated electricity-price forecast normalization."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PriceInterval:
    """One normalized marginal electricity-cost interval."""

    start: datetime
    end: datetime
    duration: timedelta
    marginal_cost_per_kwh: float


@dataclass(frozen=True, slots=True)
class PriceForecast:
    """A normalized variable-length forecast and publication identity."""

    intervals: tuple[PriceInterval, ...]
    source_token: str
    publication_key: str
    forecast_end: datetime
    rejected_items: int = 0


@dataclass(frozen=True, slots=True)
class PriceNormalizationConfig:
    """Explicit unit and marginal-cost adjustments."""

    multiplier: float = 1.0
    additive_cost_per_kwh: float = 0.0

    def __post_init__(self) -> None:
        """Reject invalid economic settings."""
        if not math.isfinite(self.multiplier) or self.multiplier < 0:
            msg = "price multiplier must be finite and non-negative"
            raise ValueError(msg)
        if not math.isfinite(self.additive_cost_per_kwh):
            msg = "additive price cost must be finite"
            raise ValueError(msg)


class PriceForecastError(ValueError):
    """A forecast cannot be safely normalized."""


class PriceProvider(Protocol):
    """Boundary implemented by source-specific Home Assistant adapters."""

    def get_forecast(self) -> PriceForecast:
        """Return the current normalized forecast or raise a clear error."""
        ...


_UNIT_FACTORS: dict[str, float] = {
    "sek/kwh": 1.0,
    "eur/kwh": 1.0,
    "nok/kwh": 1.0,
    "dkk/kwh": 1.0,
    "pln/kwh": 1.0,
    "sek/mwh": 0.001,
    "eur/mwh": 0.001,
    "nok/mwh": 0.001,
    "dkk/mwh": 0.001,
    "pln/mwh": 0.001,
    "öre/kwh": 0.01,
    "ore/kwh": 0.01,
    "cent/kwh": 0.01,
}


def normalize_price_forecast(
    items: object,
    *,
    unit: object,
    source_token: object,
    config: PriceNormalizationConfig,
) -> PriceForecast:
    """Normalize the documented timestamped-item contract.

    Each item must be a mapping with ``start``, ``end``, and ``price``. Bare
    numeric arrays are deliberately rejected because timestamps cannot be inferred
    safely across variable resolutions and daylight-saving transitions.
    """
    if not isinstance(unit, str) or not unit.strip():
        message = "price unit is missing"
        raise PriceForecastError(message)
    factor = _UNIT_FACTORS.get(unit.strip().casefold())
    if factor is None:
        message = f"unsupported price unit: {unit}"
        raise PriceForecastError(message)
    if (
        not isinstance(items, Sequence)
        or isinstance(items, (str, bytes, bytearray))
        or not items
    ):
        message = "prices must be a non-empty sequence"
        raise PriceForecastError(message)

    normalized: list[PriceInterval] = []
    rejected = 0
    for item in items:
        try:
            normalized.append(_normalize_item(item, factor=factor, config=config))
        except KeyError, PriceForecastError, TypeError, ValueError, OverflowError:
            rejected += 1
    if not normalized:
        message = "forecast contains no valid timestamped intervals"
        raise PriceForecastError(message)
    normalized.sort(key=lambda period: period.start.timestamp())
    for previous, current in pairwise(normalized):
        if current.start.timestamp() < previous.end.timestamp():
            message = "forecast intervals overlap"
            raise PriceForecastError(message)
    token = str(source_token).strip()
    end = normalized[-1].end
    key = f"{token}|{end.isoformat()}"
    return PriceForecast(tuple(normalized), token, key, end, rejected)


def _normalize_item(
    item: object,
    *,
    factor: float,
    config: PriceNormalizationConfig,
) -> PriceInterval:
    """Normalize one item without retaining source-specific objects."""
    if not isinstance(item, Mapping):
        message = "price item must be a mapping"
        raise PriceForecastError(message)
    start = _aware_datetime(item.get("start"), "start")
    end = _aware_datetime(item.get("end"), "end")
    elapsed_seconds = end.timestamp() - start.timestamp()
    if elapsed_seconds <= 0:
        message = "price interval end must be after start"
        raise PriceForecastError(message)
    raw_price = float(item["price"])
    if not math.isfinite(raw_price):
        message = "price must be finite"
        raise PriceForecastError(message)
    adjusted = raw_price * factor * config.multiplier + config.additive_cost_per_kwh
    if not math.isfinite(adjusted):
        message = "adjusted price must be finite"
        raise PriceForecastError(message)
    return PriceInterval(start, end, timedelta(seconds=elapsed_seconds), adjusted)


def _aware_datetime(value: object, field: str) -> datetime:
    """Parse one ISO timestamp and require an explicit UTC offset."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value)
    else:
        message = f"{field} timestamp is missing"
        raise PriceForecastError(message)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        message = f"{field} timestamp must be timezone-aware"
        raise PriceForecastError(message)
    return parsed


def forecast_coverage_hours(*, forecast_end: datetime, now: datetime) -> float:
    """Return non-negative elapsed forecast coverage across timezone changes."""
    if any(
        value.tzinfo is None or value.utcoffset() is None
        for value in (forecast_end, now)
    ):
        message = "forecast coverage timestamps must be timezone-aware"
        raise ValueError(message)
    return max((forecast_end.timestamp() - now.timestamp()) / 3600.0, 0.0)

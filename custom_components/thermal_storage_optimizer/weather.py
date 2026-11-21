"""Pure, bounded hourly outdoor-temperature forecast for per-interval planning."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Final

from .inputs import convert_temperature_to_celsius

MAX_FORECAST_POINTS: Final = 96
MAX_FORECAST_AGE: Final = timedelta(hours=12)
MINIMUM_FORECAST_POINTS: Final = 2
BIAS_DECAY_HOURS: Final = 6.0
_COVERAGE_GRACE: Final = timedelta(hours=1)


class WeatherForecastError(ValueError):
    """A weather forecast response cannot be safely normalized."""


@dataclass(frozen=True, slots=True)
class ForecastPoint:
    """One timestamped forecast temperature in degrees Celsius."""

    at: datetime
    temperature_c: float


@dataclass(frozen=True, slots=True)
class OutdoorForecast:
    """Sorted, bounded, timezone-aware hourly outdoor-temperature forecast."""

    points: tuple[ForecastPoint, ...]
    fetched_at: datetime
    source_token: str

    def __post_init__(self) -> None:
        """Reject forecasts the planner could not use safely."""
        if not MINIMUM_FORECAST_POINTS <= len(self.points) <= MAX_FORECAST_POINTS:
            msg = "forecast must contain a bounded number of points"
            raise ValueError(msg)
        if not _aware(self.fetched_at):
            msg = "forecast fetch time must be timezone-aware"
            raise ValueError(msg)
        for point in self.points:
            if not _aware(point.at) or not math.isfinite(point.temperature_c):
                msg = "forecast points must be timezone-aware and finite"
                raise ValueError(msg)
        timestamps = [point.at.timestamp() for point in self.points]
        if any(later <= earlier for earlier, later in pairwise(timestamps)):
            msg = "forecast points must be strictly increasing in time"
            raise ValueError(msg)

    @property
    def first_at(self) -> datetime:
        """Return the earliest forecast timestamp."""
        return self.points[0].at

    @property
    def last_at(self) -> datetime:
        """Return the latest forecast timestamp."""
        return self.points[-1].at

    def is_fresh(self, now: datetime) -> bool:
        """Return whether the forecast was fetched recently enough to trust."""
        return timedelta(0) <= now - self.fetched_at <= MAX_FORECAST_AGE

    def temperature_at(self, instant: datetime) -> float | None:
        """Interpolate linearly inside coverage; return None outside it."""
        target = instant.timestamp()
        first = self.points[0]
        last = self.points[-1]
        if target < first.at.timestamp() - _COVERAGE_GRACE.total_seconds():
            return None
        if target > last.at.timestamp() + _COVERAGE_GRACE.total_seconds():
            return None
        if target <= first.at.timestamp():
            return first.temperature_c
        if target >= last.at.timestamp():
            return last.temperature_c
        for earlier, later in pairwise(self.points):
            start = earlier.at.timestamp()
            end = later.at.timestamp()
            if start <= target <= end:
                fraction = (target - start) / (end - start)
                return earlier.temperature_c + fraction * (
                    later.temperature_c - earlier.temperature_c
                )
        return None  # pragma: no cover - loop always finds the bracketing pair

    def interval_temperature(
        self,
        start: datetime,
        end: datetime,
        *,
        measured_c: float,
        measured_at: datetime,
    ) -> float:
        """Return the interval's forecast temperature corrected toward measurement.

        The forecast is sampled at the interval midpoint. The difference between
        the current measurement and the forecast for the current instant is
        applied as a bias that decays linearly to zero over ``BIAS_DECAY_HOURS``.
        Outside coverage, or when the forecast is stale, the measured value is used.
        """
        if not math.isfinite(measured_c):
            msg = "measured outdoor temperature must be finite"
            raise ValueError(msg)
        if not self.is_fresh(measured_at):
            return measured_c
        midpoint = start + (end - start) / 2
        forecast = self.temperature_at(midpoint)
        if forecast is None:
            return measured_c
        current = self.temperature_at(measured_at)
        bias = measured_c - current if current is not None else 0.0
        hours_ahead = max((midpoint - measured_at).total_seconds() / 3600.0, 0.0)
        weight = max(1.0 - hours_ahead / BIAS_DECAY_HOURS, 0.0)
        return forecast + bias * weight


def parse_forecast_response(
    response: object,
    entity_id: str,
    *,
    temperature_unit: object,
    fetched_at: datetime,
) -> OutdoorForecast:
    """Normalize the ``weather.get_forecasts`` hourly response contract.

    The response maps the entity ID to ``{"forecast": [...]}`` where each item
    carries an ISO ``datetime`` and a ``temperature`` in the entity's display unit.
    Malformed items are skipped; too few valid points raise an explicit error.
    """
    if not isinstance(response, Mapping):
        msg = "weather forecast response must be a mapping"
        raise WeatherForecastError(msg)
    entity_payload = response.get(entity_id)
    if not isinstance(entity_payload, Mapping):
        msg = "weather forecast response does not contain the configured entity"
        raise WeatherForecastError(msg)
    items = entity_payload.get("forecast")
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes, bytearray)):
        msg = "weather forecast list is missing"
        raise WeatherForecastError(msg)
    unit = str(temperature_unit).strip() if temperature_unit is not None else "°C"
    points: dict[float, ForecastPoint] = {}
    for item in items:
        point = _parse_point(item, unit)
        if point is not None and len(points) < MAX_FORECAST_POINTS:
            points.setdefault(point.at.timestamp(), point)
    ordered = tuple(points[key] for key in sorted(points))
    if len(ordered) < MINIMUM_FORECAST_POINTS:
        msg = "weather forecast contains too few valid hourly points"
        raise WeatherForecastError(msg)
    digest = hashlib.sha256(
        "|".join(
            f"{point.at.isoformat()}:{point.temperature_c:.2f}" for point in ordered
        ).encode()
    ).hexdigest()[:16]
    return OutdoorForecast(ordered, fetched_at, digest)


def _parse_point(item: object, unit: str) -> ForecastPoint | None:
    if not isinstance(item, Mapping):
        return None
    raw_time = item.get("datetime")
    raw_temperature = item.get("temperature")
    if raw_temperature is None or isinstance(raw_temperature, bool):
        return None
    try:
        parsed = (
            raw_time
            if isinstance(raw_time, datetime)
            else datetime.fromisoformat(str(raw_time))
        )
        temperature = float(raw_temperature)
    except TypeError, ValueError:
        return None
    if not _aware(parsed) or not math.isfinite(temperature):
        return None
    celsius = convert_temperature_to_celsius(temperature, unit)
    if celsius is None or not math.isfinite(celsius):
        return None
    return ForecastPoint(parsed, celsius)


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None

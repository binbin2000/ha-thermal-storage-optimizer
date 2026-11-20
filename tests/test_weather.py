"""Pure hourly outdoor-forecast normalization and per-interval sampling tests."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.thermal_storage_optimizer.weather import (
    MAX_FORECAST_AGE,
    ForecastPoint,
    OutdoorForecast,
    WeatherForecastError,
    parse_forecast_response,
)

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def _forecast(*temperatures: float, fetched_at: datetime = NOW) -> OutdoorForecast:
    """Build an hourly forecast starting at NOW."""
    return OutdoorForecast(
        tuple(
            ForecastPoint(NOW + timedelta(hours=index), value)
            for index, value in enumerate(temperatures)
        ),
        fetched_at,
        "token",
    )


def test_parse_response_converts_units_sorts_and_skips_malformed_items() -> None:
    """The core response contract is normalized to sorted Celsius points."""
    response = {
        "weather.home": {
            "forecast": [
                {"datetime": (NOW + timedelta(hours=1)).isoformat(), "temperature": 32},
                {"datetime": NOW.isoformat(), "temperature": 41.0},
                {"datetime": "not-a-time", "temperature": 10},
                {"datetime": NOW.isoformat(), "temperature": "nan"},
                {"datetime": NOW.replace(tzinfo=None).isoformat(), "temperature": 1},
                {"temperature": 5},
                "junk",
            ]
        }
    }
    result = parse_forecast_response(
        response, "weather.home", temperature_unit="°F", fetched_at=NOW
    )
    assert [point.temperature_c for point in result.points] == pytest.approx([5, 0])
    assert result.first_at == NOW
    assert result.last_at == NOW + timedelta(hours=1)
    assert len(result.source_token) == 16


@pytest.mark.parametrize(
    "response",
    [
        None,
        {},
        {"weather.home": {}},
        {"weather.home": {"forecast": "oops"}},
        {
            "weather.home": {
                "forecast": [{"datetime": NOW.isoformat(), "temperature": 1}]
            }
        },
    ],
)
def test_parse_response_rejects_unusable_payloads(response: object) -> None:
    """Missing entities, lists, or too few points are explicit errors."""
    with pytest.raises(WeatherForecastError):
        parse_forecast_response(
            response, "weather.home", temperature_unit="°C", fetched_at=NOW
        )


def test_parse_response_rejects_unknown_temperature_unit() -> None:
    """Unknown units are never guessed."""
    response = {
        "weather.home": {
            "forecast": [
                {"datetime": NOW.isoformat(), "temperature": 1},
                {"datetime": (NOW + timedelta(hours=1)).isoformat(), "temperature": 2},
            ]
        }
    }
    with pytest.raises(WeatherForecastError):
        parse_forecast_response(
            response, "weather.home", temperature_unit="rankine", fetched_at=NOW
        )


def test_interpolation_and_coverage_limits() -> None:
    """Values interpolate inside coverage and are undefined far outside it."""
    forecast = _forecast(0, 10, 20)
    assert forecast.temperature_at(NOW + timedelta(minutes=30)) == pytest.approx(5)
    assert forecast.temperature_at(NOW - timedelta(minutes=30)) == 0
    assert forecast.temperature_at(NOW + timedelta(hours=2, minutes=30)) == 20
    assert forecast.temperature_at(NOW - timedelta(hours=2)) is None
    assert forecast.temperature_at(NOW + timedelta(hours=4)) is None


def test_interval_temperature_applies_decaying_measurement_bias() -> None:
    """A measurement offset corrects the near term and fades over six hours."""
    forecast = _forecast(*([-10.0] * 12))
    now_value = forecast.interval_temperature(
        NOW, NOW + timedelta(hours=1), measured_c=-7, measured_at=NOW
    )
    later_value = forecast.interval_temperature(
        NOW + timedelta(hours=8),
        NOW + timedelta(hours=9),
        measured_c=-7,
        measured_at=NOW,
    )
    assert now_value == pytest.approx(-7.25)
    assert later_value == pytest.approx(-10)


def test_interval_temperature_falls_back_to_measurement() -> None:
    """Stale forecasts and uncovered intervals use the measured temperature."""
    forecast = _forecast(5, 6)
    beyond = forecast.interval_temperature(
        NOW + timedelta(hours=10),
        NOW + timedelta(hours=11),
        measured_c=2,
        measured_at=NOW,
    )
    stale = forecast.interval_temperature(
        NOW,
        NOW + timedelta(hours=1),
        measured_c=2,
        measured_at=NOW + MAX_FORECAST_AGE + timedelta(minutes=1),
    )
    assert beyond == 2
    assert stale == 2
    with pytest.raises(ValueError, match="finite"):
        forecast.interval_temperature(
            NOW, NOW + timedelta(hours=1), measured_c=float("nan"), measured_at=NOW
        )


@pytest.mark.parametrize(
    "points",
    [
        (),
        (ForecastPoint(NOW, 1),),
        (ForecastPoint(NOW, 1), ForecastPoint(NOW, 2)),
        (ForecastPoint(NOW.replace(tzinfo=None), 1), ForecastPoint(NOW, 2)),
        (ForecastPoint(NOW, float("inf")), ForecastPoint(NOW + timedelta(hours=1), 2)),
    ],
)
def test_forecast_model_rejects_invalid_points(
    points: tuple[ForecastPoint, ...],
) -> None:
    """The model refuses unsorted, naive, non-finite, or too-short point sets."""
    with pytest.raises(ValueError, match="forecast"):
        OutdoorForecast(points, NOW, "token")

"""Pure tests for strict price normalization and DST-safe durations."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.thermal_storage_optimizer.price import (
    PriceForecastError,
    PriceNormalizationConfig,
    forecast_coverage_hours,
    normalize_price_forecast,
)

QUARTER_HOUR_DAY_INTERVALS = 96
EXPECTED_PUBLICATION_KEYS = 3
PUBLICATION_COVERAGE_HOURS = 35
PRE_PUBLICATION_COVERAGE_HOURS = 11


def item(start: datetime, end: datetime, price: float) -> dict[str, object]:
    """Build one representative timestamped provider item."""
    return {"start": start.isoformat(), "end": end.isoformat(), "price": price}


def test_variable_durations_units_and_adjustments() -> None:
    """Normalize arbitrary lengths and cent-style units without hourly assumptions."""
    start = datetime.fromisoformat("2026-09-07T13:00:00+02:00")
    raw = [
        item(start, start + timedelta(minutes=15), 50),
        item(start + timedelta(minutes=15), start + timedelta(hours=1), 100),
        item(start + timedelta(hours=1), start + timedelta(hours=3), -20),
    ]
    forecast = normalize_price_forecast(
        raw,
        unit="öre/kWh",
        source_token="publication-1",
        config=PriceNormalizationConfig(multiplier=1.2, additive_cost_per_kwh=0.3),
    )
    assert [period.duration for period in forecast.intervals] == [
        timedelta(minutes=15),
        timedelta(minutes=45),
        timedelta(hours=2),
    ]
    assert [
        period.marginal_cost_per_kwh for period in forecast.intervals
    ] == pytest.approx([0.9, 1.5, 0.06])


def test_nordpool_currency_per_mwh_is_converted_to_per_kwh() -> None:
    """Convert the official Nord Pool action response unit exactly once."""
    start = datetime.fromisoformat("2026-09-07T11:00:00+00:00")
    result = normalize_price_forecast(
        [item(start, start + timedelta(minutes=15), 625.0)],
        unit="SEK/MWh",
        source_token="nordpool",
        config=PriceNormalizationConfig(),
    )
    assert result.intervals[0].marginal_cost_per_kwh == pytest.approx(0.625)


@pytest.mark.parametrize("count", [11, 23, 25, 35, 96])
def test_forecast_length_is_not_fixed(count: int) -> None:
    """Accept representative short, DST-day, publication, and quarter-hour lengths."""
    start = datetime.fromisoformat("2026-01-01T00:00:00+01:00")
    step = timedelta(minutes=15 if count == QUARTER_HOUR_DAY_INTERVALS else 60)
    raw = [
        item(start + index * step, start + (index + 1) * step, index)
        for index in range(count)
    ]
    result = normalize_price_forecast(
        raw,
        unit="SEK/kWh",
        source_token="variable",
        config=PriceNormalizationConfig(),
    )
    assert len(result.intervals) == count


def test_dst_elapsed_durations_use_absolute_time() -> None:
    """Use elapsed time rather than wall-clock subtraction across DST."""
    stockholm = ZoneInfo("Europe/Stockholm")
    spring_start = datetime(2026, 3, 29, 1, 30, tzinfo=stockholm)
    spring_end = datetime(2026, 3, 29, 3, 30, tzinfo=stockholm)
    autumn_start = datetime(2026, 10, 25, 1, 30, tzinfo=stockholm)
    autumn_end = datetime(2026, 10, 25, 3, 30, tzinfo=stockholm)
    result = normalize_price_forecast(
        [item(spring_start, spring_end, 1), item(autumn_start, autumn_end, 2)],
        unit="SEK/kWh",
        source_token="dst",
        config=PriceNormalizationConfig(),
    )
    assert result.intervals[0].duration == timedelta(hours=1)
    assert result.intervals[1].duration == timedelta(hours=3)


def test_malformed_individual_item_is_bounded_and_rejected() -> None:
    """Keep valid periods while reporting rejected malformed items."""
    start = datetime.fromisoformat("2026-09-07T13:00:00+02:00")
    result = normalize_price_forecast(
        [item(start, start + timedelta(hours=1), 1), {"price": "bad"}],
        unit="SEK/kWh",
        source_token="partial",
        config=PriceNormalizationConfig(),
    )
    assert len(result.intervals) == 1
    assert result.rejected_items == 1


@pytest.mark.parametrize(
    ("items", "unit"),
    [
        ([1.0, 2.0], "SEK/kWh"),
        ([], "SEK/kWh"),
        (
            [
                {
                    "start": "2026-01-01T00:00:00",
                    "end": "2026-01-01T01:00:00",
                    "price": 1,
                }
            ],
            "SEK/kWh",
        ),
        (
            [
                {
                    "start": "2026-01-01T00:00:00+01:00",
                    "end": "2026-01-01T01:00:00+01:00",
                    "price": 1,
                }
            ],
            None,
        ),
    ],
)
def test_ambiguous_schema_and_unit_are_not_guessed(items: object, unit: object) -> None:
    """Reject bare arrays, naive timestamps, empty data, and missing units."""
    with pytest.raises(PriceForecastError):
        normalize_price_forecast(
            items,
            unit=unit,
            source_token="invalid",
            config=PriceNormalizationConfig(),
        )


def test_publication_identity_uses_source_or_final_timestamp() -> None:
    """A source change or extended final timestamp creates a new publication key."""
    start = datetime.fromisoformat("2026-09-07T13:00:00+02:00")
    config = PriceNormalizationConfig()
    first = normalize_price_forecast(
        [item(start, start + timedelta(hours=1), 1)],
        unit="SEK/kWh",
        source_token="a",
        config=config,
    )
    source_changed = normalize_price_forecast(
        [item(start, start + timedelta(hours=1), 1)],
        unit="SEK/kWh",
        source_token="b",
        config=config,
    )
    end_changed = normalize_price_forecast(
        [item(start, start + timedelta(hours=2), 1)],
        unit="SEK/kWh",
        source_token="a",
        config=config,
    )
    assert (
        len(
            {
                first.publication_key,
                source_changed.publication_key,
                end_changed.publication_key,
            }
        )
        == EXPECTED_PUBLICATION_KEYS
    )


def test_known_daily_publication_coverage_shrinks_from_35_to_11_hours() -> None:
    """Model normal publication coverage and the pre-update short horizon."""
    publication = datetime.fromisoformat("2026-09-07T13:00:00+02:00")
    forecast_end = datetime.fromisoformat("2026-09-09T00:00:00+02:00")
    before_next_release = datetime.fromisoformat("2026-09-08T13:00:00+02:00")
    assert (
        forecast_coverage_hours(forecast_end=forecast_end, now=publication)
        == PUBLICATION_COVERAGE_HOURS
    )
    assert (
        forecast_coverage_hours(forecast_end=forecast_end, now=before_next_release)
        == PRE_PUBLICATION_COVERAGE_HOURS
    )

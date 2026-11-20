"""Pure tests for outdoor-temperature binned curves and the heating-curve set."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.thermal_storage_optimizer.adaptive import ParameterBounds
from custom_components.thermal_storage_optimizer.cop import (
    CopSource,
    FixedCopModel,
    carnot_cop,
)
from custom_components.thermal_storage_optimizer.curves import (
    MAX_BINS,
    MAX_SAMPLE_AGE,
    MAX_SAMPLES_PER_BIN,
    MIN_BIN_SAMPLE_INTERVAL,
    CurveConfig,
    OutdoorBinnedCurve,
    TemperatureCurveSet,
)

NOW = datetime(2026, 11, 20, 12, tzinfo=UTC)


def _curve(**overrides: object) -> OutdoorBinnedCurve:
    settings: dict[str, object] = {
        "name": "heating_curve",
        "unit": "°C",
        "bin_width_c": 3.0,
        "value_bounds": ParameterBounds(10, 90),
    }
    settings.update(overrides)
    return OutdoorBinnedCurve(**settings)  # type: ignore[arg-type]


def _fill(curve: OutdoorBinnedCurve, outdoor_c: float, values: list[float]) -> None:
    """Add spaced samples to one bin."""
    for index, value in enumerate(values):
        assert curve.add_sample(NOW + index * MIN_BIN_SAMPLE_INTERVAL, outdoor_c, value)


def _supply(outdoor_c: float) -> float:
    """Return the reference linear heating curve (20 °C at +17 °C, slope -1.2)."""
    return 20 + 1.2 * (17 - outdoor_c)


def test_curve_learns_bins_interpolates_and_extrapolates_flat() -> None:
    """Populated bins give medians; gaps interpolate; outside uses the nearest."""
    curve = _curve()
    for outdoor in (-9.5, -3.5, 2.5, 8.5):
        _fill(curve, outdoor, [_supply(outdoor) + offset for offset in (-1, 0, 1)] * 4)
    later = NOW + timedelta(hours=6)
    assert curve.usable(later, 0.6)
    exact = curve.estimate(-3.0, later, 0.6)
    between = curve.estimate(-0.5, later, 0.6)
    below = curve.estimate(-20, later, 0.6)
    above = curve.estimate(15, later, 0.6)
    assert exact is not None
    assert between is not None
    assert below is not None
    assert above is not None
    assert exact.source == "bin"
    assert exact.value == pytest.approx(_supply(-3.5))
    assert between.source == "interpolated"
    # Interpolation runs between bin centres (-4.5 and 1.5 °C for 3 °C bins).
    fraction = (-0.5 - -4.5) / (1.5 - -4.5)
    assert between.value == pytest.approx(
        _supply(-3.5) + fraction * (_supply(2.5) - _supply(-3.5)), abs=0.01
    )
    assert below.source == "nearest"
    assert below.value == pytest.approx(_supply(-9.5))
    assert above.value == pytest.approx(_supply(8.5))
    assert below.confidence < exact.confidence


def test_curve_requires_two_confident_bins_and_rejects_bad_samples() -> None:
    """Sparse, noisy, out-of-bounds, or rapid samples never create a curve."""
    curve = _curve()
    _fill(curve, 2.0, [40.0] * 6)
    assert not curve.usable(NOW + timedelta(hours=3), 0.6)
    assert curve.estimate(2.0, NOW + timedelta(hours=3), 0.6) is None
    assert not curve.add_sample(NOW, 2.0, 41.0)  # inside the per-bin interval
    assert not curve.add_sample(NOW + timedelta(days=1), 2.0, 95.0)  # above bounds
    assert not curve.add_sample(NOW + timedelta(days=1), float("nan"), 40.0)
    assert not curve.add_sample(NOW + timedelta(days=1), 100.0, 40.0)
    with pytest.raises(ValueError, match="aware"):
        curve.add_sample(NOW.replace(tzinfo=None), 2.0, 40.0)
    noisy = _curve()
    _fill(noisy, 2.0, [20, 60, 25, 55, 30, 50, 22, 58])
    _fill(noisy, 8.0, [20, 60, 25, 55, 30, 50, 22, 58])
    assert not noisy.usable(NOW + timedelta(hours=4), 0.6)


def test_curve_is_bounded_and_forgets_old_samples() -> None:
    """Per-bin, bin-count, and age limits keep memory and relevance bounded."""
    curve = _curve()
    for index in range(MAX_SAMPLES_PER_BIN + 10):
        curve.add_sample(NOW + index * MIN_BIN_SAMPLE_INTERVAL, 2.0, 40.0)
    assert curve.sample_count == MAX_SAMPLES_PER_BIN
    for index in range(MAX_BINS + 5):
        curve.add_sample(NOW, -40 + index * 3.0, 40.0)
    assert curve.diagnostics(NOW, 0.6)["bin_count"] == MAX_BINS
    assert curve.sample_count == MAX_SAMPLES_PER_BIN + MAX_BINS - 1
    aged = _curve()
    _fill(aged, 2.0, [40.0] * 8)
    _fill(aged, 8.0, [34.0] * 8)
    assert aged.usable(NOW + timedelta(hours=4), 0.6)
    future = NOW + MAX_SAMPLE_AGE + timedelta(days=1)
    assert not aged.usable(future, 0.6)
    aged.prune(future)
    assert aged.sample_count == 0


def test_curve_serialization_round_trip_and_rejection() -> None:
    """Persisted samples restore in order; malformed payloads raise."""
    curve = _curve()
    _fill(curve, 2.0, [40.0, 41.0, 39.0] * 2)
    restored = _curve()
    restored.restore(curve.serialize(), now=NOW + timedelta(hours=3))
    assert restored.sample_count == curve.sample_count
    assert restored.serialize() == curve.serialize()
    with pytest.raises(ValueError, match="invalid"):
        restored.restore({"not": "a list"}, now=NOW)
    with pytest.raises(ValueError, match="invalid"):
        restored.restore([[NOW.isoformat(), 1.0]], now=NOW)
    future_only = _curve()
    future_only.restore([[(NOW + timedelta(days=2)).isoformat(), 2.0, 40.0]], now=NOW)
    assert future_only.sample_count == 0


def test_curve_set_gates_on_enable_confidence_and_resets() -> None:
    """The set only replaces the measured supply target with a confident curve."""
    config = CurveConfig(
        enabled=True,
        bin_width_c=3.0,
        minimum_confidence=0.6,
        supply_bounds=ParameterBounds(10, 90),
        cop_bounds=ParameterBounds(1, 7),
    )
    curves = TemperatureCurveSet(config)
    assert curves.supply_temperature_for(0.0, now=NOW, fallback_c=45) == 45
    for index in range(16):
        outdoor = -4.0 if index % 2 else 4.0
        at = NOW + index * MIN_BIN_SAMPLE_INTERVAL
        curves.observe(now=at, outdoor_c=outdoor, supply_target_c=_supply(outdoor))
    later = NOW + timedelta(hours=8)
    assert curves.heating_curve_usable(later)
    assert curves.supply_temperature_for(-4.0, now=later, fallback_c=45) == (
        pytest.approx(_supply(-4.0))
    )
    assert curves.supply_temperature_for(0.0, now=later, fallback_c=45) == (
        pytest.approx((_supply(-4.0) + _supply(4.0)) / 2, abs=0.05)
    )
    assert not curves.observe(now=later, outdoor_c=None, supply_target_c=40)
    payload = curves.serialize()
    assert payload["schema_version"] == 1
    fresh = TemperatureCurveSet(config)
    assert fresh.restore(payload, now=later)
    assert fresh.heating_curve_usable(later)
    assert not fresh.restore({"schema_version": 99}, now=later)
    assert not fresh.restore(
        {"schema_version": 1, "curves": {"heating_curve": 1}}, now=later
    )
    assert fresh.heating_curve.sample_count == 0
    curves.reset()
    assert not curves.heating_curve_usable(later)
    assert curves.diagnostics(later)["curves"]["heating_curve"]["sample_count"] == 0
    disabled = TemperatureCurveSet(
        CurveConfig(
            enabled=False,
            bin_width_c=3.0,
            minimum_confidence=0.6,
            supply_bounds=ParameterBounds(10, 90),
            cop_bounds=ParameterBounds(1, 7),
        )
    )
    assert not disabled.observe(now=NOW, outdoor_c=2.0, supply_target_c=40)
    assert disabled.supply_temperature_for(2.0, now=NOW, fallback_c=45) == 45


@pytest.mark.parametrize(
    ("bin_width", "min_bin_samples"),
    [(0, 6), (float("nan"), 6), (3.0, 0)],
)
def test_curve_rejects_invalid_configuration(
    bin_width: float, min_bin_samples: int
) -> None:
    """Non-positive widths or sample minimums are configuration errors."""
    with pytest.raises(ValueError, match="positive"):
        _curve(bin_width_c=bin_width, min_bin_samples=min_bin_samples)


def _cop_reference(outdoor_c: float) -> float:
    """Return a reference air-to-water COP that collapses in cold weather."""
    return max(1.6, min(4.2, 3.0 + 0.08 * outdoor_c))


def test_cop_curve_learns_only_while_running_and_extrapolates_with_carnot() -> None:
    """Measured COP fills bins when the pump runs; cold gaps use learned Carnot."""
    config = CurveConfig(
        enabled=True,
        bin_width_c=3.0,
        minimum_confidence=0.6,
        supply_bounds=ParameterBounds(10, 90),
        cop_bounds=ParameterBounds(1, 7),
    )
    curves = TemperatureCurveSet(config)
    fallback = FixedCopModel(3.0)
    assert curves.cop_model(NOW, fallback) is fallback
    assert curves.carnot_efficiency(NOW) is None
    idle = curves.observe(
        now=NOW,
        outdoor_c=2.0,
        supply_target_c=None,
        measured_cop=3.2,
        heat_pump_power_kw=0.0,
    )
    assert not idle
    assert curves.cop_curve.sample_count == 0
    for index in range(24):
        outdoor = (2.0, -4.0, 8.0)[index % 3]
        at = NOW + index * MIN_BIN_SAMPLE_INTERVAL
        curves.observe(
            now=at,
            outdoor_c=outdoor,
            supply_target_c=_supply(outdoor),
            measured_cop=_cop_reference(outdoor),
            heat_pump_power_kw=1.4,
        )
    later = NOW + timedelta(hours=12)
    assert curves.cop_curve_usable(later)
    assert curves.any_usable(later)
    efficiency = curves.carnot_efficiency(later)
    assert efficiency is not None
    assert 0.1 < efficiency < 1.0
    model = curves.cop_model(later, fallback)
    assert model is not fallback
    inside = model.explain(outdoor_temperature_c=-4.0, supply_temperature_c=45)
    between = model.explain(outdoor_temperature_c=-1.0, supply_temperature_c=45)
    cold = model.explain(outdoor_temperature_c=-20.0, supply_temperature_c=55)
    assert inside.source is CopSource.LEARNED_CURVE
    assert inside.value == pytest.approx(_cop_reference(-4.0))
    assert between.source is CopSource.LEARNED_CURVE
    assert cold.source is CopSource.CARNOT_EXTRAPOLATION
    assert cold.value == pytest.approx(
        efficiency * carnot_cop(outdoor_temperature_c=-20.0, supply_temperature_c=55)
    )
    assert cold.value < inside.value
    assert cold.confidence < inside.confidence
    assert model.estimate(outdoor_temperature_c=-4.0, supply_temperature_c=45) == (
        inside.value
    )
    payload = curves.serialize()
    assert set(payload["curves"]) == {"heating_curve", "cop_curve", "carnot_efficiency"}
    restored = TemperatureCurveSet(config)
    assert restored.restore(payload, now=later)
    assert restored.cop_curve_usable(later)
    diagnostics = restored.diagnostics(later)["curves"]
    assert diagnostics["cop_curve"]["usable"]
    assert len(diagnostics["carnot_efficiency"]["bins"]) >= 1

"""Fixed synthetic and historical-style Milestone 8 calibration datasets."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.thermal_storage_optimizer.adaptive import (
    MAX_CALIBRATION_SAMPLES,
    AdaptiveCalibration,
    CalibrationConfig,
    CapacityCycle,
    DemandSample,
    EnergyRatioSample,
    FiringSessionSample,
    Observation,
    ParameterBounds,
    calibrate_capacity,
    calibrate_cop,
    calibrate_demand,
    calibrate_firing_sessions,
)

NOW = datetime(2026, 1, 20, 18, tzinfo=UTC)


def config(*, enabled: bool = True) -> CalibrationConfig:
    """Return conservative fixed test configuration."""
    return CalibrationConfig(
        enabled=enabled,
        minimum_confidence=0.7,
        capacity_fallback_kwh=30,
        heat_loss_fallback_kw_per_k=0.3,
        balance_fallback_c=17,
        cop_fallback=3,
        charging_power_fallback_kw=6,
        residual_fallback_kwh=1,
        capacity_bounds=ParameterBounds(15, 50),
        heat_loss_bounds=ParameterBounds(0.1, 0.8),
        balance_bounds=ParameterBounds(12, 22),
        cop_bounds=ParameterBounds(1, 6),
        charging_power_bounds=ParameterBounds(2, 15),
        residual_bounds=ParameterBounds(0, 5),
    )


def test_fixed_synthetic_models_converge() -> None:
    """Clean fixed datasets converge on transparent known parameters."""
    demand = [DemandSample(outdoor, 0.42 * (18 - outdoor)) for outdoor in range(-8, 13)]
    heat_loss, balance = calibrate_demand(
        demand, ParameterBounds(0.1, 0.8), ParameterBounds(12, 22), now=NOW
    )
    cop = calibrate_cop(
        [
            EnergyRatioSample(1 + index / 10, (1 + index / 10) * 3.6)
            for index in range(12)
        ],
        ParameterBounds(1, 6),
        now=NOW,
    )
    capacity = calibrate_capacity(
        [CapacityCycle(20, 24), CapacityCycle(-15, -18), CapacityCycle(10, 12)],
        ParameterBounds(15, 50),
        configured_capacity_kwh=30,
        now=NOW,
    )
    assert heat_loss.value == pytest.approx(0.42)
    assert balance.value == pytest.approx(18)
    assert cop.value == pytest.approx(3.6)
    assert capacity.value == pytest.approx(36)
    assert heat_loss.usable(0.7)
    assert cop.usable(0.7)


def test_historical_style_firing_sessions_converge_and_reject_outlier() -> None:
    """Robust medians keep one anomalous session from corrupting stove fits."""
    sessions = [
        FiringSessionSample(
            NOW + timedelta(days=index, minutes=index % 3 * 5),
            2,
            14 + (index % 2) * 0.2,
            1.5 + (index % 2) * 0.1,
        )
        for index in range(10)
    ]
    sessions.append(FiringSessionSample(NOW, 0.5, 100, 30))
    power, residual, start, duration = calibrate_firing_sessions(
        sessions,
        ParameterBounds(2, 15),
        ParameterBounds(0, 5),
        now=NOW,
    )
    assert power.value == pytest.approx(7.05, abs=0.1)
    assert residual.value == pytest.approx(1.55, abs=0.1)
    assert start.value == pytest.approx(18 * 60 + 5, abs=5)
    assert duration.value == pytest.approx(120)


def test_insufficient_bad_data_and_bounds_keep_fallback() -> None:
    """Bad, sparse, or bound-hitting fits are never active."""
    cop = calibrate_cop(
        [EnergyRatioSample(0, 5), EnergyRatioSample(1, -2)],
        ParameterBounds(1, 6),
        now=NOW,
    )
    heat_loss, _ = calibrate_demand(
        [DemandSample(5, 2)] * 20,
        ParameterBounds(0.1, 0.8),
        ParameterBounds(12, 22),
        now=NOW,
    )
    capacity = calibrate_capacity(
        [CapacityCycle(10, 100)] * 6,
        ParameterBounds(15, 50),
        configured_capacity_kwh=30,
        now=NOW,
    )
    assert not cop.usable()
    assert not heat_loss.usable()
    assert capacity.value == 50
    assert capacity.fallback_reason == "estimate reached a configured physical bound"
    assert capacity.selected(30, 0.7) == 30


def test_observations_are_throttled_bounded_and_counter_resets_ignored() -> None:
    """State changes cannot create unbounded storage or invalid meter deltas."""
    calibration = AdaptiveCalibration(config())
    for index in range(MAX_CALIBRATION_SAMPLES + 20):
        calibration.observe(
            Observation(
                NOW + timedelta(minutes=index * 5),
                10,
                2,
                100 - index,
                50 - index,
                firing_active=False,
            )
        )
    assert len(calibration.cop_samples) == 0
    assert len(calibration.observations) == MAX_CALIBRATION_SAMPLES + 20
    assert not calibration.observe(
        Observation(NOW + timedelta(hours=1), 10, 2, 0, 0, firing_active=False)
    )


def test_restart_migration_reset_and_disabled_fallback() -> None:
    """Persisted samples survive restart; reset and opt-out restore defaults."""
    original = AdaptiveCalibration(config())
    original.cop_samples.extend([EnergyRatioSample(1, 3.5)] * 12)
    original._recalibrate(NOW)  # noqa: SLF001 - fixed-state restart fixture
    payload = original.serialize()
    payload["schema_version"] = 1
    restored = AdaptiveCalibration(config())
    assert restored.restore(payload, now=NOW + timedelta(hours=1))
    assert restored.value("cop", 3) == pytest.approx(3.5)
    restored.reset()
    assert restored.value("cop", 3) == 3
    assert restored.parameters["cop"].sample_count == 0
    disabled = AdaptiveCalibration(config(enabled=False))
    disabled.cop_samples.extend([EnergyRatioSample(1, 4)] * 12)
    disabled._recalibrate(NOW)  # noqa: SLF001 - activation-gate fixture
    assert disabled.value("cop", 3) == 3


def test_performance_report_never_claims_unmeasured_savings() -> None:
    """Validation labels modeled cost separately from unavailable measurements."""
    calibration = AdaptiveCalibration(config())
    calibration.observe(
        Observation(
            NOW, 10, 0, 100, 50, firing_active=False, predicted_heat_power_kw=7.2
        )
    )
    calibration.observe(
        Observation(
            NOW + timedelta(hours=1),
            10,
            0,
            107.2,
            52,
            firing_active=False,
            predicted_heat_power_kw=7.2,
        )
    )
    report = calibration.performance_report(12.5)
    assert report.modeled_heat_kwh == pytest.approx(7.2)
    assert report.observed_heat_kwh == pytest.approx(7.2)
    assert report.measured_savings is None
    assert "modeled" in report.savings_label


@pytest.mark.parametrize("missing", ["electric", "heat", "age"])
def test_trusted_cop_falls_back_and_old_samples_cannot_reactivate(missing: str) -> None:
    """A formerly trusted fit loses eligibility with absent or old evidence."""
    calibration = AdaptiveCalibration(config())
    calibration.cop_samples.extend([EnergyRatioSample(1, 3.5)] * 12)
    calibration._recalibrate(NOW)  # noqa: SLF001
    assert calibration.value("cop", 3) == pytest.approx(3.5)
    calibration.check_health(
        now=NOW + timedelta(days=2 if missing == "age" else 0),
        tank_valid=True,
        outdoor=0,
        heat_meter=None if missing == "heat" else 10,
        electric_meter=None if missing == "electric" else 5,
    )
    assert calibration.value("cop", 3) == 3
    assert not calibration.cop_samples
    calibration._recalibrate(NOW + timedelta(days=2))  # noqa: SLF001
    assert calibration.value("cop", 3) == 3


def test_demand_fit_falls_back_when_weather_disappears() -> None:
    """A previously trusted demand fit cannot survive missing outdoor evidence."""
    calibration = AdaptiveCalibration(config())
    calibration.demand_samples.extend(
        DemandSample(t, 0.42 * (18 - t)) for t in range(-8, 13)
    )
    calibration._recalibrate(NOW)  # noqa: SLF001
    assert calibration.value("heat_loss_coefficient_kw_per_k", 0.3) == pytest.approx(
        0.42
    )
    calibration.check_health(
        now=NOW, tank_valid=True, outdoor=None, heat_meter=100, electric_meter=50
    )
    assert calibration.value("heat_loss_coefficient_kw_per_k", 0.3) == 0.3
    assert calibration.value("balance_temperature_c", 17) == 17


def test_restart_keeps_independent_feature_evidence_age() -> None:
    """Recent stove evidence must not refresh a stale COP fit on restart."""
    original = AdaptiveCalibration(config())
    original.cop_samples.extend([EnergyRatioSample(1, 3.5)] * 12)
    original._recalibrate(NOW)  # noqa: SLF001
    payload = original.serialize()
    payload["last_calibrated_at"] = (NOW + timedelta(days=2)).isoformat()
    restored = AdaptiveCalibration(config())
    assert restored.restore(payload, now=NOW + timedelta(days=2))
    assert restored.value("cop", 3) == 3

"""Pure three-layer accumulator energy estimation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

WATER_ENERGY_KWH_PER_LITRE_K: Final = 0.001163


class DataQuality(StrEnum):
    """Conservative quality classification for a thermal estimate."""

    GOOD = "good"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class EnergyTrend(StrEnum):
    """Direction of the tank's usable-energy change."""

    CHARGING = "charging"
    DISCHARGING = "discharging"
    IDLE = "idle"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class TankTemperatures:
    """Normalized temperatures required by the energy model, in degrees Celsius."""

    top_c: float | None
    middle_c: float | None
    bottom_c: float | None
    return_c: float | None
    supply_target_c: float | None


@dataclass(frozen=True, slots=True)
class ThermalEnergyConfig:
    """Validated physical and calibration settings for the energy model."""

    total_volume_l: float
    layer_volumes_l: tuple[float, float, float]
    minimum_useful_delta_c: float
    usable_capacity_kwh: float
    trend_deadband_kwh: float = 0.1

    def __post_init__(self) -> None:
        """Reject invalid or internally inconsistent physical settings."""
        values = (
            self.total_volume_l,
            *self.layer_volumes_l,
            self.minimum_useful_delta_c,
            self.usable_capacity_kwh,
            self.trend_deadband_kwh,
        )
        if not all(math.isfinite(value) for value in values):
            msg = "thermal energy settings must be finite"
            raise ValueError(msg)
        if self.total_volume_l <= 0 or any(
            volume <= 0 for volume in self.layer_volumes_l
        ):
            msg = "tank and layer volumes must be positive"
            raise ValueError(msg)
        if not math.isclose(
            sum(self.layer_volumes_l), self.total_volume_l, rel_tol=0, abs_tol=0.01
        ):
            msg = "layer volumes must sum to total tank volume"
            raise ValueError(msg)
        if self.minimum_useful_delta_c < 0:
            msg = "minimum useful delta cannot be negative"
            raise ValueError(msg)
        if self.usable_capacity_kwh <= 0:
            msg = "usable capacity must be positive"
            raise ValueError(msg)
        if self.trend_deadband_kwh < 0:
            msg = "trend deadband cannot be negative"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ThermalState:
    """Explainable output of one thermal energy calculation."""

    usable_energy_kwh: float | None
    high_grade_energy_kwh: float | None
    state_of_charge_percent: float | None
    reference_temperature_c: float | None
    stratification_delta_c: float | None
    trend: EnergyTrend
    quality: DataQuality
    confidence: float
    missing_values: tuple[str, ...]


def estimate_thermal_state(
    temperatures: TankTemperatures,
    config: ThermalEnergyConfig,
    *,
    previous_usable_energy_kwh: float | None = None,
) -> ThermalState:
    """Estimate usable and high-grade energy from normalized layer temperatures."""
    readings = {
        "top": temperatures.top_c,
        "middle": temperatures.middle_c,
        "bottom": temperatures.bottom_c,
        "return": temperatures.return_c,
        "supply_target": temperatures.supply_target_c,
    }
    missing = tuple(name for name, value in readings.items() if value is None)
    if missing:
        return ThermalState(
            usable_energy_kwh=None,
            high_grade_energy_kwh=None,
            state_of_charge_percent=None,
            reference_temperature_c=None,
            stratification_delta_c=None,
            trend=EnergyTrend.UNKNOWN,
            quality=DataQuality.UNAVAILABLE,
            confidence=0.0,
            missing_values=missing,
        )

    numeric = tuple(float(value) for value in readings.values() if value is not None)
    if not all(math.isfinite(value) for value in numeric):
        msg = "temperatures must be finite or missing"
        raise ValueError(msg)

    top, middle, bottom, return_temperature, supply_target = numeric
    reference = return_temperature + config.minimum_useful_delta_c
    layers = tuple(zip(config.layer_volumes_l, (top, middle, bottom), strict=True))
    usable = WATER_ENERGY_KWH_PER_LITRE_K * sum(
        volume * max(temperature - reference, 0.0) for volume, temperature in layers
    )
    high_grade = WATER_ENERGY_KWH_PER_LITRE_K * sum(
        volume * max(temperature - supply_target, 0.0) for volume, temperature in layers
    )
    soc = min(max(usable / config.usable_capacity_kwh * 100.0, 0.0), 100.0)
    stratification_delta = top - bottom
    is_stratified = top >= middle >= bottom
    quality = DataQuality.GOOD if is_stratified else DataQuality.DEGRADED
    confidence = 1.0 if is_stratified else 0.5
    return ThermalState(
        usable_energy_kwh=usable,
        high_grade_energy_kwh=high_grade,
        state_of_charge_percent=soc,
        reference_temperature_c=reference,
        stratification_delta_c=stratification_delta,
        trend=detect_energy_trend(
            usable,
            previous_usable_energy_kwh,
            deadband_kwh=config.trend_deadband_kwh,
        ),
        quality=quality,
        confidence=confidence,
        missing_values=(),
    )


def detect_energy_trend(
    current_usable_energy_kwh: float,
    previous_usable_energy_kwh: float | None,
    *,
    deadband_kwh: float,
) -> EnergyTrend:
    """Classify energy change using a deterministic deadband."""
    if not math.isfinite(current_usable_energy_kwh):
        msg = "current energy must be finite"
        raise ValueError(msg)
    if not math.isfinite(deadband_kwh) or deadband_kwh < 0:
        msg = "trend deadband must be finite and non-negative"
        raise ValueError(msg)
    if previous_usable_energy_kwh is None:
        return EnergyTrend.UNKNOWN
    if not math.isfinite(previous_usable_energy_kwh):
        msg = "previous energy must be finite or missing"
        raise ValueError(msg)
    change = current_usable_energy_kwh - previous_usable_energy_kwh
    if change > deadband_kwh:
        return EnergyTrend.CHARGING
    if change < -deadband_kwh:
        return EnergyTrend.DISCHARGING
    return EnergyTrend.IDLE

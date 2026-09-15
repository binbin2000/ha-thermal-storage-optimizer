"""Immutable calculated runtime data owned by a loaded config entry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .cop import CopEstimate
    from .energy import ThermalState
    from .inputs import InputIssue, NormalizedInputSnapshot, NormalizedValue
    from .optimizer import OptimizationPlan, Recommendation


class IntegrationStatus(StrEnum):
    """Concise input-layer status."""

    READY = "ready"
    WAITING_FOR_DATA = "waiting_for_data"
    INVALID_DATA = "invalid_data"


class PlanStatus(StrEnum):
    """Source and continuity status of the rolling dry-run plan."""

    FULL_FORECAST = "full_forecast"
    SAVED_PLAN = "saved_plan"
    WAITING = "waiting"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    """Normalized inputs and deterministic Milestone 3 calculations."""

    inputs: NormalizedInputSnapshot
    thermal: ThermalState
    hourly_heat_demand_kwh: float | None
    cop: CopEstimate | None
    plan: OptimizationPlan | None = None
    plan_status: PlanStatus = PlanStatus.WAITING
    plan_reason: str = "Waiting for a valid timestamped price forecast"
    recommendation: Recommendation | None = None
    forecast_rejected_items: int = 0

    @property
    def captured_at(self) -> datetime:
        """Forward the atomic input capture time."""
        return self.inputs.captured_at

    @property
    def values(self) -> Mapping[str, NormalizedValue]:
        """Forward normalized values for existing consumers."""
        return self.inputs.values

    @property
    def issues(self) -> tuple[InputIssue, ...]:
        """Forward all normalization issues."""
        return self.inputs.issues

    @property
    def required_issues(self) -> tuple[InputIssue, ...]:
        """Forward required normalization issues."""
        return self.inputs.required_issues

    @property
    def is_valid(self) -> bool:
        """Return whether all required normalized inputs are present."""
        return self.inputs.is_valid

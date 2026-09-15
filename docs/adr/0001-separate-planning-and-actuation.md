# ADR 0001: Separate planning from physical actuation

- Status: Accepted
- Date: 2026-09-06

## Context

The optimizer will eventually recommend whether stored heat should be used or
reserved. A later controller may translate that recommendation into a command
to a shunt-offset entity. Planning can be incomplete, stale, or wrong without
being allowed to bypass independent heating-system safety controls.

## Decision

Planning and recommendation will be implemented as deterministic, testable
logic that has no Home Assistant service-call capability. Physical actuation
will live behind a separate supervisory controller boundary with explicit
enablement, safety precedence, validation, startup grace, dwell time, and a
de-energized fallback. Milestone 1 contains neither an output entity reference
nor any service call that could actuate equipment.

## Consequences

Recommendations can be developed and field-validated in dry-run mode before a
controller exists. Controller tests can independently prove fail-safe behavior,
and future planner changes cannot directly energize the physical output. The
separation adds an interface between plan and controller, but that interface is
intentional and auditable.


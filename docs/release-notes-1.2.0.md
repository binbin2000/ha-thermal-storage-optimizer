# Thermal Storage Optimizer 1.2.0

## Fixed

- The firing deadline no longer jumps past every price peak when a valuable
  period is already in progress. The session now completes before the most
  valuable periods that one tank load can cover, so it lands ahead of the
  highest peak instead of after it.

# Price forecast adapter contract

## Official Home Assistant Nord Pool integration

The configured price input may be a `Current price` sensor created by Home
Assistant's official `nordpool` integration. That sensor itself exposes only the
current price. The adapter resolves its Nord Pool config entry, market area, and
currency through Home Assistant's entity/config-entry registries, then calls the
official `nordpool.get_prices_for_date` response action for today and tomorrow.

The official response supplies timezone-aware UTC `start`/`end` timestamps and
prices in the selected currency per MWh. The adapter converts per MWh to per kWh
before applying the configured multiplier and additive per-kWh cost. It retains
the intervals' actual duration, including the transition between 60-minute and
15-minute market time units and DST days. An unavailable tomorrow response is
not fatal: today's intervals remain usable, and the planner retains a longer
last-valid plan rather than replacing it with a shorter horizon.

Official Nord Pool price corrections and tomorrow publication are recognized
from a deterministic hash of the returned timestamped data, not from an assumed
13:00 clock event. A source-entity update refreshes the response action without
blocking Home Assistant's event loop.

The official Nord Pool prices are base energy prices. VAT, energy tax, grid, and
retailer additions must be represented explicitly by the optimizer's multiplier
and additive-cost options if they are part of the installation's marginal cost.

## Generic and custom Nord Pool attribute contracts

The adapter also accepts a generic entity with a `prices` attribute:

```yaml
state: published
attributes:
  unit_of_measurement: SEK/kWh
  publication_id: "2026-09-07"
  prices:
    - start: "2026-09-07T13:00:00+02:00"
      end: "2026-09-07T13:15:00+02:00"
      price: 0.62
    - start: "2026-09-07T13:15:00+02:00"
      end: "2026-09-07T14:00:00+02:00"
      price: 0.55
```

Every item must have timezone-aware `start` and `end` timestamps and a finite
numeric `price`. Invalid individual items are ignored and counted; an empty or
fully invalid forecast is rejected. Intervals may have gaps but may not overlap.
Supported declared units are `SEK/kWh`, `NOK/kWh`, `DKK/kWh`, `EUR/kWh`,
`PLN/kWh`, their `/MWh` equivalents, `öre/kWh`, `ore/kWh`, and `cent/kWh`.

For compatibility with the established custom Nord Pool integration schema,
timestamped `raw_today` and `raw_tomorrow` lists are also combined. Their
`value` field is mapped to normalized `price`. Bare `today`/`tomorrow` numeric
arrays are deliberately rejected because interval timestamps and DST behavior
cannot be inferred safely.

Publication identity combines `publication_id` (or `source_updated_at`, then the
entity state as a fallback) with the final forecast timestamp. Either a source
revision or an extended/changed horizon therefore triggers re-optimization;
13:00 is modeled as an expected operational behavior, never an exact trigger.

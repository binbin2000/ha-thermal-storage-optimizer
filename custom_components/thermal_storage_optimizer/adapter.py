"""Home Assistant state adapter for normalized optimizer inputs."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import timedelta
from typing import Final

import voluptuous as vol
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ACTUAL_SUPPLY_TEMPERATURE,
    CONF_FLOW_RATE,
    CONF_FORECAST_STALE_AFTER,
    CONF_HEAT_PUMP_ELECTRICAL_ENERGY,
    CONF_HEAT_PUMP_ELECTRICAL_POWER,
    CONF_HEAT_PUMP_PRODUCED_HEAT,
    CONF_INDOOR_TEMPERATURE,
    CONF_MEASURED_COP,
    CONF_NOTIFICATION_TARGET,
    CONF_OUTDOOR_TEMPERATURE,
    CONF_PRICE_FORECAST,
    CONF_RESERVE_OUTPUT,
    CONF_RETURN_TEMPERATURE,
    CONF_SENSOR_STALE_AFTER,
    CONF_STOVE_CHARGING_PUMP,
    CONF_STOVE_FLOW_TEMPERATURE,
    CONF_SUPPLEMENTARY_HEATER_POWER,
    CONF_SUPPLEMENTARY_HEATER_SHARE,
    CONF_SUPPLY_TARGET,
    CONF_TANK_BOTTOM,
    CONF_TANK_MIDDLE,
    CONF_TANK_TOP,
    CONF_WEATHER,
    DEFAULT_FORECAST_STALE_AFTER,
    DEFAULT_SENSOR_STALE_AFTER,
    HEAT_PUMP_RUNNING_KW,
    OPTIONAL_ENTITY_KEYS,
    REQUIRED_ENTITY_KEYS,
)
from .inputs import (
    InputKind,
    InputProblem,
    NormalizedInputSnapshot,
    RawInput,
    normalize_inputs,
)
from .price import (
    PriceForecast,
    PriceForecastError,
    PriceNormalizationConfig,
    normalize_price_forecast,
)
from .weather import OutdoorForecast, WeatherForecastError, parse_forecast_response

_KINDS: Final = {
    CONF_TANK_TOP: InputKind.TEMPERATURE,
    CONF_TANK_MIDDLE: InputKind.TEMPERATURE,
    CONF_TANK_BOTTOM: InputKind.TEMPERATURE,
    CONF_RETURN_TEMPERATURE: InputKind.TEMPERATURE,
    CONF_SUPPLY_TARGET: InputKind.TEMPERATURE,
    CONF_OUTDOOR_TEMPERATURE: InputKind.TEMPERATURE,
    CONF_PRICE_FORECAST: InputKind.AVAILABILITY,
    CONF_RESERVE_OUTPUT: InputKind.DIGITAL,
    CONF_ACTUAL_SUPPLY_TEMPERATURE: InputKind.TEMPERATURE,
    CONF_INDOOR_TEMPERATURE: InputKind.TEMPERATURE,
    CONF_WEATHER: InputKind.AVAILABILITY,
    CONF_HEAT_PUMP_ELECTRICAL_POWER: InputKind.POWER,
    CONF_HEAT_PUMP_ELECTRICAL_ENERGY: InputKind.ENERGY,
    CONF_HEAT_PUMP_PRODUCED_HEAT: InputKind.ENERGY,
    CONF_MEASURED_COP: InputKind.COP,
    CONF_STOVE_CHARGING_PUMP: InputKind.DIGITAL,
    CONF_STOVE_FLOW_TEMPERATURE: InputKind.TEMPERATURE,
    CONF_FLOW_RATE: InputKind.FLOW_RATE,
    CONF_SUPPLEMENTARY_HEATER_POWER: InputKind.POWER,
    CONF_SUPPLEMENTARY_HEATER_SHARE: InputKind.PERCENTAGE,
    CONF_NOTIFICATION_TARGET: InputKind.AVAILABILITY,
}
# Many heat pumps report no COP while the compressor is idle.
_IDLE_COP_PROBLEMS: Final = frozenset(
    {InputProblem.UNKNOWN, InputProblem.UNAVAILABLE, InputProblem.STALE}
)
_LOGGER = logging.getLogger(__name__)
_NORDPOOL_DOMAIN: Final = "nordpool"
_NORDPOOL_GET_PRICES: Final = "get_prices_for_date"
_WEATHER_DOMAIN: Final = "weather"
_WEATHER_GET_FORECASTS: Final = "get_forecasts"
_WEATHER_TEMPERATURE_UNIT: Final = "temperature_unit"


class HomeAssistantInputAdapter:
    """Read raw HA state objects and hand pure values to the normalizer."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_data: dict[str, object],
        options: dict[str, object],
    ) -> None:
        """Initialize the adapter with immutable configuration copies."""
        self._hass = hass
        self._entry_data = entry_data
        self._sensor_stale_after = timedelta(
            seconds=float(
                str(options.get(CONF_SENSOR_STALE_AFTER, DEFAULT_SENSOR_STALE_AFTER))
            )
        )
        self._forecast_stale_after = timedelta(
            seconds=float(
                str(
                    options.get(CONF_FORECAST_STALE_AFTER, DEFAULT_FORECAST_STALE_AFTER)
                )
            )
        )
        self._nordpool_forecast: PriceForecast | None = None
        self._nordpool_error: str | None = None
        self._outdoor_forecast: OutdoorForecast | None = None
        self._outdoor_forecast_error: str | None = None

    @property
    def price_entity_id(self) -> str | None:
        """Return the configured price entity ID when present."""
        configured = self._entry_data.get(CONF_PRICE_FORECAST)
        return str(configured) if configured else None

    @property
    def weather_entity_id(self) -> str | None:
        """Return the optional weather entity used for hourly forecasts."""
        configured = self._entry_data.get(CONF_WEATHER)
        return str(configured) if configured else None

    @property
    def outdoor_forecast(self) -> OutdoorForecast | None:
        """Return the last successfully normalized hourly outdoor forecast."""
        return self._outdoor_forecast

    @property
    def outdoor_forecast_error(self) -> str | None:
        """Return why the latest weather forecast refresh was not usable."""
        return self._outdoor_forecast_error

    @property
    def uses_official_nordpool(self) -> bool:
        """Return whether the selected entity belongs to core Nord Pool."""
        return self._official_nordpool_source() is not None

    @property
    def entity_ids(self) -> tuple[str, ...]:
        """Return all configured state-bearing entities for event subscription."""
        return tuple(
            str(self._entry_data[key])
            for key in (*REQUIRED_ENTITY_KEYS, *OPTIONAL_ENTITY_KEYS)
            if self._entry_data.get(key)
        )

    def snapshot(self) -> NormalizedInputSnapshot:
        """Read and normalize one atomic best-effort view of configured states."""
        now = dt_util.utcnow()
        raw_inputs: list[RawInput] = []
        for key in (*REQUIRED_ENTITY_KEYS, *OPTIONAL_ENTITY_KEYS):
            configured = self._entry_data.get(key)
            if not configured:
                if key in REQUIRED_ENTITY_KEYS:
                    raw_inputs.append(
                        RawInput(
                            key=key,
                            entity_id="",
                            kind=_KINDS[key],
                            required=True,
                            state=None,
                            unit=None,
                            updated_at=None,
                            stale_after=None,
                        )
                    )
                continue
            entity_id = str(configured)
            state = self._hass.states.get(entity_id)
            kind = _KINDS[key]
            stale_after: timedelta | None = self._sensor_stale_after
            if key == CONF_PRICE_FORECAST:
                stale_after = self._forecast_stale_after
            elif kind is InputKind.DIGITAL or key in {
                CONF_WEATHER,
                CONF_NOTIFICATION_TARGET,
            }:
                stale_after = None
            raw_inputs.append(
                RawInput(
                    key=key,
                    entity_id=entity_id,
                    kind=kind,
                    required=key in REQUIRED_ENTITY_KEYS,
                    state=state.state if state is not None else None,
                    unit=(
                        state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
                        if state is not None
                        else None
                    ),
                    # Freshness follows the last report, not the last change: a
                    # healthy sensor that keeps reporting the same value (an idle
                    # heat pump's power, a steady setpoint) must not turn stale.
                    updated_at=state.last_reported if state is not None else None,
                    stale_after=stale_after,
                )
            )
        return _drop_idle_cop_issue(normalize_inputs(tuple(raw_inputs), now))

    def price_forecast(self, config: PriceNormalizationConfig) -> PriceForecast:
        """Adapt cached official Nord Pool or timestamped entity attributes."""
        configured = self._entry_data.get(CONF_PRICE_FORECAST)
        if not configured:
            message = "price forecast entity is not configured"
            raise PriceForecastError(message)
        state = self._hass.states.get(str(configured))
        if state is None:
            message = "price forecast entity is missing"
            raise PriceForecastError(message)
        attributes = state.attributes
        timestamped_items = _timestamped_attribute_items(attributes)
        if timestamped_items is None and self.uses_official_nordpool:
            if self._nordpool_forecast is not None:
                return self._nordpool_forecast
            message = self._nordpool_error or "Nord Pool forecast has not been fetched"
            raise PriceForecastError(message)
        source_token = attributes.get(
            "publication_id", attributes.get("source_updated_at", state.state)
        )
        return normalize_price_forecast(
            timestamped_items,
            unit=attributes.get(ATTR_UNIT_OF_MEASUREMENT),
            source_token=source_token,
            config=config,
        )

    async def async_prepare_price_forecast(
        self, config: PriceNormalizationConfig
    ) -> None:
        """Fetch today/tomorrow through the official Nord Pool response action."""
        source = self._official_nordpool_source()
        if source is None:
            return
        config_entry_id, area, currency = source
        today = dt_util.now().date()
        combined: list[object] = []
        for offset in (0, 1):
            try:
                response = await self._hass.services.async_call(
                    _NORDPOOL_DOMAIN,
                    _NORDPOOL_GET_PRICES,
                    {
                        "config_entry": config_entry_id,
                        "date": today + timedelta(days=offset),
                        "areas": [area],
                        "currency": currency,
                    },
                    blocking=True,
                    return_response=True,
                )
            except (HomeAssistantError, vol.Invalid) as err:
                if offset == 0 and self._nordpool_forecast is None:
                    self._nordpool_error = f"Nord Pool current-day fetch failed: {err}"
                else:
                    _LOGGER.debug(
                        "Nord Pool tomorrow prices are not available: %s", err
                    )
                continue
            items = response.get(area) if isinstance(response, Mapping) else None
            if isinstance(items, Sequence) and not isinstance(
                items, (str, bytes, bytearray)
            ):
                combined.extend(items)
        if not combined:
            return
        token_payload = json.dumps(combined, sort_keys=True, default=str)
        source_token = hashlib.sha256(token_payload.encode()).hexdigest()[:16]
        try:
            self._nordpool_forecast = normalize_price_forecast(
                combined,
                unit=f"{currency}/MWh",
                source_token=f"nordpool:{config_entry_id}:{area}:{source_token}",
                config=config,
            )
        except PriceForecastError as err:
            self._nordpool_error = f"Nord Pool response invalid: {err}"
            return
        self._nordpool_error = None

    async def async_prepare_outdoor_forecast(self) -> None:
        """Fetch the hourly forecast through the core weather response action.

        A failed or malformed refresh keeps the previous forecast; its fetch time
        bounds how long the planner continues to trust it.
        """
        entity_id = self.weather_entity_id
        if entity_id is None:
            return
        state = self._hass.states.get(entity_id)
        unit = state.attributes.get(_WEATHER_TEMPERATURE_UNIT) if state else None
        try:
            response = await self._hass.services.async_call(
                _WEATHER_DOMAIN,
                _WEATHER_GET_FORECASTS,
                {"type": "hourly", "entity_id": entity_id},
                blocking=True,
                return_response=True,
            )
        except (HomeAssistantError, vol.Invalid) as err:
            self._outdoor_forecast_error = f"weather forecast fetch failed: {err}"
            _LOGGER.debug("Hourly weather forecast unavailable: %s", err)
            return
        try:
            self._outdoor_forecast = parse_forecast_response(
                response,
                entity_id,
                temperature_unit=unit,
                fetched_at=dt_util.utcnow(),
            )
        except WeatherForecastError as err:
            self._outdoor_forecast_error = f"weather forecast invalid: {err}"
            return
        self._outdoor_forecast_error = None

    def _official_nordpool_source(  # noqa: PLR0911
        self,
    ) -> tuple[str, str, str] | None:
        """Resolve config entry, market area, and currency from a Nord Pool sensor."""
        entity_id = self.price_entity_id
        if entity_id is None:
            return None
        state = self._hass.states.get(entity_id)
        if (
            state is not None
            and _timestamped_attribute_items(state.attributes) is not None
        ):
            return None
        registry_entry = er.async_get(self._hass).async_get(entity_id)
        if (
            registry_entry is None
            or registry_entry.platform != _NORDPOOL_DOMAIN
            or registry_entry.config_entry_id is None
        ):
            return None
        config_entry = self._hass.config_entries.async_get_entry(
            registry_entry.config_entry_id
        )
        if config_entry is None:
            return None
        area = registry_entry.unique_id.partition("-")[0].upper()
        configured_areas = config_entry.data.get("areas")
        if (
            not area
            or not isinstance(configured_areas, Sequence)
            or area not in configured_areas
        ):
            return None
        currency = config_entry.data.get("currency")
        if not isinstance(currency, str) or not currency:
            return None
        return config_entry.entry_id, area, currency.upper()


def _timestamped_attribute_items(attributes: Mapping[str, object]) -> object:
    """Read generic prices or Nord Pool custom-integration raw day lists."""
    if attributes.get("prices") is not None:
        return attributes["prices"]
    combined: list[object] = []
    found = False
    for key in ("raw_today", "raw_tomorrow"):
        raw = attributes.get(key)
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
            continue
        found = True
        for item in raw:
            if isinstance(item, Mapping) and "value" in item and "price" not in item:
                combined.append({**item, "price": item["value"]})
            else:
                combined.append(item)
    return combined if found else None


def _drop_idle_cop_issue(snapshot: NormalizedInputSnapshot) -> NormalizedInputSnapshot:
    """Hide a missing measured COP while the heat pump is known to be idle.

    A COP is undefined without electrical input, so an unknown, unavailable or
    stale COP sensor is expected then. The issue is kept whenever the heat pump
    power is not known, because nothing then shows that the pump is idle.
    """
    power = snapshot.values.get(CONF_HEAT_PUMP_ELECTRICAL_POWER)
    if power is None or not isinstance(power.value, int | float):
        return snapshot
    if power.value > HEAT_PUMP_RUNNING_KW:
        return snapshot
    issues = tuple(
        issue
        for issue in snapshot.issues
        if not (issue.key == CONF_MEASURED_COP and issue.problem in _IDLE_COP_PROBLEMS)
    )
    if len(issues) == len(snapshot.issues):
        return snapshot
    return replace(snapshot, issues=issues)

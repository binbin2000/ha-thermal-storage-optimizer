"""Binary diagnostic entities for Thermal Storage Optimizer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import InputCoordinator
from .optimizer import Recommendation

if TYPE_CHECKING:
    from .controller import SupervisoryController


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: ConfigEntry[InputCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up input-validity diagnostics."""
    async_add_entities(
        [
            ThermalStorageOptimizerDataValidBinarySensor(entry),
            ThermalStorageOptimizerReleaseRecommendedBinarySensor(entry),
            ThermalStorageOptimizerOutputActiveBinarySensor(entry),
            ThermalStorageOptimizerChargeRecommendedBinarySensor(entry),
            ThermalStorageOptimizerStoveFiringBinarySensor(entry),
        ]
    )


class ThermalStorageOptimizerDataValidBinarySensor(
    CoordinatorEntity[InputCoordinator], BinarySensorEntity
):
    """Indicate whether all required configured inputs are valid."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_translation_key = "data_valid"

    def __init__(self, entry: ConfigEntry[InputCoordinator]) -> None:
        """Initialize the physical-output diagnostic."""
        """Initialize the validity entity."""
        super().__init__(entry.runtime_data)
        self._attr_unique_id = f"{entry.entry_id}_data_valid"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def is_on(self) -> bool | None:
        """Return whether all required source readings are valid."""
        return self.coordinator.data.is_valid


class ThermalStorageOptimizerReleaseRecommendedBinarySensor(
    CoordinatorEntity[InputCoordinator], BinarySensorEntity
):
    """Expose the optimizer recommendation without actuating any output."""

    _attr_has_entity_name = True
    _attr_translation_key = "release_recommended"

    def __init__(self, entry: ConfigEntry[InputCoordinator]) -> None:
        """Initialize the dry-run recommendation entity."""
        super().__init__(entry.runtime_data)
        self._attr_unique_id = f"{entry.entry_id}_release_recommended"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def is_on(self) -> bool | None:
        """Return true only when the current interval received tank energy."""
        return self.coordinator.data.recommendation is Recommendation.USE_TANK


class ThermalStorageOptimizerOutputActiveBinarySensor(BinarySensorEntity):
    """Expose the last successfully requested physical output state."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_translation_key = "output_active"

    def __init__(self, entry: ConfigEntry[InputCoordinator]) -> None:
        """Initialize the output-command diagnostic."""
        self._controller: SupervisoryController = entry.runtime_data.controller
        self._attr_unique_id = f"{entry.entry_id}_output_active"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def is_on(self) -> bool | None:
        """Return the command confirmed by the most recent successful service call."""
        return self._controller.output_active

    async def async_added_to_hass(self) -> None:
        """Subscribe after the entity is attached to Home Assistant."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._controller.async_add_listener(self.async_write_ha_state)
        )


class _AdvisorBinarySensor(BinarySensorEntity):
    """Base for advisory state that cannot actuate the shunt."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry[InputCoordinator], key: str) -> None:
        self._advisor = entry.runtime_data.advisor
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self.internal_integration_suggested_object_id = f"thermal_storage_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self._advisor.async_add_listener(self.async_write_ha_state)
        )


class ThermalStorageOptimizerChargeRecommendedBinarySensor(_AdvisorBinarySensor):
    """Indicate a currently feasible manual charging recommendation."""

    _attr_translation_key = "charge_recommended"

    def __init__(self, entry: ConfigEntry[InputCoordinator]) -> None:
        """Initialize the charge-recommendation entity."""
        super().__init__(entry, "charge_recommended")

    @property
    def is_on(self) -> bool | None:
        """Return whether manual charging is currently recommended."""
        return self._advisor.state.charge_recommended


class ThermalStorageOptimizerStoveFiringBinarySensor(_AdvisorBinarySensor):
    """Indicate a detected or manually declared stove session."""

    _attr_translation_key = "stove_firing"

    def __init__(self, entry: ConfigEntry[InputCoordinator]) -> None:
        """Initialize the active-session entity."""
        super().__init__(entry, "stove_firing")

    @property
    def is_on(self) -> bool | None:
        """Return whether an active session is detected."""
        return self._advisor.state.firing_active

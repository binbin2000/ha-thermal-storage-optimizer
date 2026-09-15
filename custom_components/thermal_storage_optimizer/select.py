"""User mode selection for the supervisory controller."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .controller import SupervisoryController, UserMode

if TYPE_CHECKING:
    from .coordinator import InputCoordinator


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: ConfigEntry[InputCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the persisted user-mode select."""
    async_add_entities([ThermalStorageOptimizerModeSelect(entry)])


class ThermalStorageOptimizerModeSelect(SelectEntity):
    """Expose mode independently from active-control permission."""

    _attr_has_entity_name = True
    _attr_translation_key = "mode"

    def __init__(self, entry: ConfigEntry[InputCoordinator]) -> None:
        """Initialize the mode entity."""
        self._attr_options = [mode.value for mode in UserMode]
        self._controller: SupervisoryController = entry.runtime_data.controller
        self._attr_unique_id = f"{entry.entry_id}_mode"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def current_option(self) -> str:
        """Return the persisted current mode."""
        return self._controller.mode.value

    async def async_select_option(self, option: str) -> None:
        """Set one validated select option."""
        await self._controller.async_set_mode(UserMode(option))

    async def async_added_to_hass(self) -> None:
        """Subscribe to controller updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._controller.async_add_listener(self.async_write_ha_state)
        )

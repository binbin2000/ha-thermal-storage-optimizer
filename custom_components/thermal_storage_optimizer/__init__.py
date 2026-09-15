"""Thermal Storage Optimizer integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.storage import Store

from .adapter import HomeAssistantInputAdapter
from .const import (
    CONF_ACTIVE_CONTROL,
    CONFIG_ENTRY_MINOR_VERSION,
    CONFIG_ENTRY_VERSION,
    DEFAULT_ACTIVE_CONTROL,
    DEVICE_MODEL,
    DOMAIN,
    INTEGRATION_NAME,
    VERSION,
)
from .coordinator import InputCoordinator
from .frontend import async_register_frontend, async_unregister_frontend
from .services import async_setup_actions, async_unload_actions

_LOGGER = logging.getLogger(__name__)

PLATFORMS: tuple[Platform, ...] = (
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
)
MILESTONE_2_ENTRY_VERSION = 2
MILESTONE_4_ENTRY_VERSION = 3
MILESTONE_5_ENTRY_VERSION = 4
MILESTONE_7_ENTRY_VERSION = 5
type ThermalStorageOptimizerConfigEntry = ConfigEntry[InputCoordinator]


async def async_migrate_entry(
    hass: HomeAssistant, entry: ThermalStorageOptimizerConfigEntry
) -> bool:
    """Migrate supported config entries without silently changing control intent."""
    if entry.version < 1 or entry.version > CONFIG_ENTRY_VERSION:
        _LOGGER.error(
            "Unsupported config entry version %s.%s; expected at most %s.%s",
            entry.version,
            entry.minor_version,
            CONFIG_ENTRY_VERSION,
            CONFIG_ENTRY_MINOR_VERSION,
        )
        return False
    if (
        entry.version == CONFIG_ENTRY_VERSION
        and entry.minor_version > CONFIG_ENTRY_MINOR_VERSION
    ):
        _LOGGER.error(
            "Unsupported config entry minor version %s.%s; expected at most %s.%s",
            entry.version,
            entry.minor_version,
            CONFIG_ENTRY_VERSION,
            CONFIG_ENTRY_MINOR_VERSION,
        )
        return False

    options = dict(entry.options)
    if entry.version == 1:
        hass.config_entries.async_update_entry(entry, version=2)
    if entry.version == MILESTONE_2_ENTRY_VERSION:
        hass.config_entries.async_update_entry(entry, version=MILESTONE_4_ENTRY_VERSION)
    if entry.version == MILESTONE_4_ENTRY_VERSION:
        # Versions before actuation existed cannot carry a valid control opt-in.
        options[CONF_ACTIVE_CONTROL] = DEFAULT_ACTIVE_CONTROL
        hass.config_entries.async_update_entry(
            entry, options=options, version=MILESTONE_5_ENTRY_VERSION
        )
    if entry.version == MILESTONE_5_ENTRY_VERSION:
        # Advisor options have conservative runtime defaults and grant no actuation.
        hass.config_entries.async_update_entry(entry, version=MILESTONE_7_ENTRY_VERSION)
    if entry.version == MILESTONE_7_ENTRY_VERSION:
        # Adaptive calibration remains explicitly disabled on upgrade.
        hass.config_entries.async_update_entry(
            entry,
            minor_version=CONFIG_ENTRY_MINOR_VERSION,
            version=CONFIG_ENTRY_VERSION,
        )
    elif (
        entry.version == CONFIG_ENTRY_VERSION
        and entry.minor_version < CONFIG_ENTRY_MINOR_VERSION
    ):
        hass.config_entries.async_update_entry(
            entry, minor_version=CONFIG_ENTRY_MINOR_VERSION
        )
    return True


async def async_remove_entry(
    hass: HomeAssistant, entry: ThermalStorageOptimizerConfigEntry
) -> None:
    """Remove all private state after Home Assistant removes the config entry."""
    for suffix in ("plan", "calibration", "controller", "advisor"):
        await Store[dict[str, object]](
            hass, 1, f"{DOMAIN}.{entry.entry_id}.{suffix}"
        ).async_remove()


async def async_setup_entry(
    hass: HomeAssistant, entry: ThermalStorageOptimizerConfigEntry
) -> bool:
    """Set up Thermal Storage Optimizer from a config entry."""
    adapter = HomeAssistantInputAdapter(hass, dict(entry.data), dict(entry.options))
    entry.runtime_data = InputCoordinator(hass, entry, adapter)
    await entry.runtime_data.controller.async_start()
    try:
        await async_register_frontend(hass)
        await entry.runtime_data.async_start()
        await entry.runtime_data.advisor.async_start()
        await async_setup_actions(entry)
    except Exception as err:
        _LOGGER.exception("Integration load failed; requesting safe fallback")
        await entry.runtime_data.controller.async_handle_fault(f"load failed: {err}")
        raise

    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=INTEGRATION_NAME,
        model=DEVICE_MODEL,
        sw_version=VERSION,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ThermalStorageOptimizerConfigEntry
) -> bool:
    """Unload a Thermal Storage Optimizer config entry."""
    async_unload_actions(entry)
    async_unregister_frontend(hass)
    await entry.runtime_data.advisor.async_shutdown()
    await entry.runtime_data.controller.async_shutdown()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

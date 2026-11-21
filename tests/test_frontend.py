"""Bundled dashboard-card registration tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermal_storage_optimizer.const import (
    CONFIG_ENTRY_VERSION,
    DOMAIN,
    INTEGRATION_NAME,
    UNIQUE_ID,
)
from custom_components.thermal_storage_optimizer.frontend import (
    CARD_FILENAMES,
    DATA_STATIC_PATH_REGISTERED,
    card_module_url,
    card_url_path,
)

from .helpers import REQUIRED_CONFIG, set_valid_required_states


async def test_setup_registers_and_unload_removes_card_module(
    hass: HomeAssistant,
) -> None:
    """Serve the bundled card once and inject it only while loaded."""
    set_valid_required_states(hass)
    output_service = AsyncMock()
    hass.services.async_register("switch", "turn_on", output_service)
    hass.services.async_register("switch", "turn_off", output_service)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=INTEGRATION_NAME,
        unique_id=UNIQUE_ID,
        data=REQUIRED_CONFIG,
        version=CONFIG_ENTRY_VERSION,
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, "frontend", {})

    with patch.object(
        hass.http,
        "async_register_static_paths",
        wraps=hass.http.async_register_static_paths,
    ) as register_paths:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    module_urls = [card_module_url(filename) for filename in CARD_FILENAMES]
    assert len(CARD_FILENAMES) == 2
    for module_url in module_urls:
        assert module_url in hass.data[DATA_EXTRA_MODULE_URL].urls
    assert hass.data[DATA_STATIC_PATH_REGISTERED] is True
    configs = register_paths.await_args.args[0]
    assert len(configs) == len(CARD_FILENAMES)
    for config, filename in zip(configs, CARD_FILENAMES, strict=True):
        assert config.url_path == card_url_path(filename)
        assert config.path.endswith(filename)
        assert config.cache_headers is True

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    for module_url in module_urls:
        assert module_url not in hass.data[DATA_EXTRA_MODULE_URL].urls

    with patch.object(
        hass.http,
        "async_register_static_paths",
        wraps=hass.http.async_register_static_paths,
    ) as register_paths_after_reload:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert register_paths_after_reload.await_count == 0
    for module_url in module_urls:
        assert module_url in hass.data[DATA_EXTRA_MODULE_URL].urls
    assert await hass.config_entries.async_unload(entry.entry_id)

"""Register the bundled Lovelace cards."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

from homeassistant.components import frontend
from homeassistant.components.http.server import StaticPathConfig

from .const import DOMAIN, VERSION

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

CARD_FILENAMES: Final = (
    "thermal-storage-plan-card.js",
    "thermal-storage-day-chart-card.js",
)
DATA_STATIC_PATH_REGISTERED: Final = f"{DOMAIN}_frontend_static_path_registered"


def card_url_path(filename: str) -> str:
    """Return the static path one bundled card is served from."""
    return f"/{DOMAIN}/{filename}"


def card_module_url(filename: str) -> str:
    """Return the cache-busted module URL injected into the frontend."""
    return f"{card_url_path(filename)}?v={VERSION}"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve and load the integration's frontend modules."""
    if not hass.data.get(DATA_STATIC_PATH_REGISTERED):
        directory = Path(__file__).parent / "frontend"
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    card_url_path(filename),
                    str(directory / filename),
                    cache_headers=True,
                )
                for filename in CARD_FILENAMES
            ]
        )
        hass.data[DATA_STATIC_PATH_REGISTERED] = True
    for filename in CARD_FILENAMES:
        frontend.add_extra_js_url(hass, card_module_url(filename))


def async_unregister_frontend(hass: HomeAssistant) -> None:
    """Stop injecting the frontend modules when the entry unloads."""
    for filename in CARD_FILENAMES:
        frontend.remove_extra_js_url(hass, card_module_url(filename))

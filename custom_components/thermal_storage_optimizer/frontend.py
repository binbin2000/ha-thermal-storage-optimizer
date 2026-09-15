"""Register the bundled Lovelace plan card."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

from homeassistant.components import frontend
from homeassistant.components.http.server import StaticPathConfig

from .const import DOMAIN, VERSION

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

CARD_FILENAME: Final = "thermal-storage-plan-card.js"
CARD_URL_PATH: Final = f"/{DOMAIN}/{CARD_FILENAME}"
CARD_MODULE_URL: Final = f"{CARD_URL_PATH}?v={VERSION}"
DATA_STATIC_PATH_REGISTERED: Final = f"{DOMAIN}_frontend_static_path_registered"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve and load the integration's frontend module."""
    if not hass.data.get(DATA_STATIC_PATH_REGISTERED):
        card_path = Path(__file__).parent / "frontend" / CARD_FILENAME
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL_PATH, str(card_path), cache_headers=True)]
        )
        hass.data[DATA_STATIC_PATH_REGISTERED] = True
    frontend.add_extra_js_url(hass, CARD_MODULE_URL)


def async_unregister_frontend(hass: HomeAssistant) -> None:
    """Stop injecting the frontend module when the entry unloads."""
    frontend.remove_extra_js_url(hass, CARD_MODULE_URL)

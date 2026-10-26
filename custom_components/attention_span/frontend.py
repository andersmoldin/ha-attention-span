"""Serverar AttentionSpan-kortet och laddar det i HA:s frontend."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STATIC_URL = f"/{DOMAIN}_static"
CARD_FILE = "attention-span-card.js"


async def async_register_card(hass: HomeAssistant) -> None:
    """Servera kortet och ladda det i varje webbläsare som öppnar HA."""
    www = Path(__file__).parent / "www"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(www), cache_headers=True)]
    )
    # Versionen i URL:en gör att webbläsare och appen hämtar nytt kort efter en uppdatering,
    # så att kortet alltid följer integrationens version.
    version = (await async_get_integration(hass, DOMAIN)).version
    try:
        add_extra_js_url(hass, f"{STATIC_URL}/{CARD_FILE}?v={version}")
    except KeyError:
        _LOGGER.warning("HA:s frontend är inte laddad, så AttentionSpan-kortet registreras inte")

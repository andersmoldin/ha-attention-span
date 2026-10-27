"""Det Home Assistant och HACS ser av paketet: ikon, version och hacs.json."""

import json
import pathlib
import struct
import tomllib

from awesomeversion import AwesomeVersion
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
from homeassistant.setup import async_setup_component

from custom_components.attention_span.const import DOMAIN

REPO = pathlib.Path(__file__).parents[1]
PYPROJECT = REPO / "pyproject.toml"

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Bitdjup 8 och färgtyp 6 (RGBA): genomskinliga hörn, som ha-bussars ikon.
RGBA_8_BIT = (8, 6)


def _png_format(data: bytes) -> tuple[int, int, int, int]:
    """Bredd, höjd, bitdjup och färgtyp ur PNG-filens IHDR-block."""
    assert data[:8] == PNG_SIGNATURE
    width, height, bit_depth, color_type = struct.unpack(">IIBB", data[16:26])
    return width, height, bit_depth, color_type


async def test_home_assistant_serves_the_integrations_icon(hass: HomeAssistant, hass_client):
    """HA:s brands-endpoint hittar ikonen i brand/, i de storlekar HA:s frontend hämtar."""
    assert await async_setup_component(hass, "brands", {})
    client = await hass_client()

    for image, size in (("icon.png", 256), ("icon@2x.png", 512)):
        resp = await client.get(f"/api/brands/integration/{DOMAIN}/{image}?placeholder=no")

        assert resp.status == 200, image
        assert resp.headers["Content-Type"] == "image/png"
        assert _png_format(await resp.read()) == (size, size, *RGBA_8_BIT), image


async def test_integration_version_matches_the_python_project(hass: HomeAssistant):
    """Versionen HA visar för integrationen är samma som projektets, så en höjning gäller båda."""
    project = tomllib.loads(PYPROJECT.read_text())["project"]

    integration = await async_get_integration(hass, DOMAIN)

    assert integration.version == project["version"]


async def test_hacs_shows_the_integrations_name_and_a_supported_minimum_home_assistant(
    hass: HomeAssistant,
):
    """HACS läser hacs.json: namnet som visas i HACS och den lägsta HA-version paketet kräver.

    Namnet är detsamma som HA visar, och den lägsta versionen får inte vara nyare än den HA
    som testerna kör mot.
    """
    hacs = json.loads((REPO / "hacs.json").read_text())

    integration = await async_get_integration(hass, DOMAIN)

    assert hacs["name"] == integration.name
    assert AwesomeVersion(hacs["homeassistant"]) <= AwesomeVersion(HA_VERSION)

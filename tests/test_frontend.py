import json
import pathlib
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from .conftest import add_integration

MANIFEST = pathlib.Path(__file__).parents[1] / "custom_components/attention_span/manifest.json"
STATIC = "/attention_span_static"


async def test_card_is_served_and_registered_with_the_integrations_version(
    hass: HomeAssistant, hass_client
):
    assert await async_setup_component(hass, "http", {})
    version = json.loads(MANIFEST.read_text())["version"]

    with patch("custom_components.attention_span.frontend.add_extra_js_url") as add_js:
        await add_integration(hass)

    (registered_url,) = [call.args[1] for call in add_js.call_args_list]
    assert registered_url == f"{STATIC}/attention-span-card.js?v={version}"
    client = await hass_client()
    for path in (f"{STATIC}/attention-span-card.js", f"{STATIC}/card-model.js"):
        resp = await client.get(path)
        assert resp.status == 200, path
        assert "javascript" in resp.headers["Content-Type"]


async def test_card_is_registered_once_across_reloads(hass: HomeAssistant):
    assert await async_setup_component(hass, "http", {})

    with patch("custom_components.attention_span.frontend.add_extra_js_url") as add_js:
        entry = await add_integration(hass)
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    assert add_js.call_count == 1

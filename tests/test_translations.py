import json
import pathlib

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from custom_components.attention_span.const import DOMAIN, SUBENTRY_RULE

from .conftest import BILEN, add_integration, add_rule, start_rule, start_rule_reconfigure

TRANSLATIONS = pathlib.Path(__file__).parents[1] / "custom_components" / DOMAIN / "translations"


def _flatten(tree: dict, prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}
    for key, value in tree.items():
        if isinstance(value, dict):
            flat |= _flatten(value, f"{prefix}{key}.")
        else:
            flat[f"{prefix}{key}"] = value
    return flat


def _form_keys(prefix: str, result) -> set[str]:
    """Rubriken, varje fält och varje val i formuläret som flödet visar."""
    step = f"{prefix}.step.{result['step_id']}"
    keys = {f"{step}.title"}
    for field, selector in result["data_schema"].schema.items():
        keys.add(f"{step}.data.{field}")
        config = getattr(selector, "config", {})
        if translation_key := config.get("translation_key"):
            keys |= {f"selector.{translation_key}.options.{o}" for o in config["options"]}
    return keys


async def _shown_keys(hass: HomeAssistant) -> set[str]:
    """Nycklarna som de riktiga flödena och regelns sensor behöver."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    keys = _form_keys("config", result) | {"config.abort.single_instance_allowed"}
    entry = await add_integration(hass)

    rule = "config_subentries.rule"
    keys |= {
        f"{rule}.entry_type",
        f"{rule}.initiate_flow.user",
        f"{rule}.initiate_flow.reconfigure",
    }
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_RULE), context={"source": config_entries.SOURCE_USER}
    )
    keys |= _form_keys(rule, result)
    result = await start_rule(hass, entry, "value")
    keys |= _form_keys(rule, result) | {f"{rule}.error.name_required"}

    subentry_id = await add_rule(hass, entry, "value", BILEN)
    result = await start_rule_reconfigure(hass, entry, subentry_id)
    keys |= _form_keys(rule, result) | {f"{rule}.abort.reconfigure_successful"}

    state = hass.states.get("sensor.attention_span_bilen")
    keys |= {f"entity.sensor.rule.state.{option}" for option in state.attributes["options"]}
    return keys


@pytest.mark.parametrize("language", ["en", "sv"])
async def test_forms_and_states_are_translated(hass: HomeAssistant, language: str):
    translated = _flatten(json.loads((TRANSLATIONS / f"{language}.json").read_text()))

    missing = sorted(key for key in await _shown_keys(hass) if not translated.get(key))

    assert missing == []

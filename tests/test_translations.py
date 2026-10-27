import json
import pathlib

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from custom_components.attention_span.const import DOMAIN, LEVELS, SUBENTRY_RULE

from .conftest import (
    ALWAYS_GLANCE,
    BILEN,
    add_integration,
    add_rule,
    level_modes,
    start_rule,
    start_rule_reconfigure,
    submit_reason,
)

UPCOMING = {"name": "Buss", "entities": ["sensor.buss_nasta"], "count": 3}
PROGRESS = {"name": "Disk", "entity": "sensor.disk_kvar"}
CUSTOM = {"name": "Vädret", "card": {"type": "weather-forecast", "entity": "weather.hemma"}}

TRANSLATIONS = pathlib.Path(__file__).parents[1] / "custom_components" / DOMAIN / "translations"


async def reach_reason(hass: HomeAssistant, entry, rule_type: str, fields: dict):
    """Fyll i en regel av Typen fram till orsaken."""
    result = await start_rule(hass, entry, rule_type)
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], fields)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], level_modes({"glance": "always"})
    )
    return await hass.config_entries.subentries.async_configure(result["flow_id"], {})


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
            keys |= {f"selector.{translation_key}.options.{o}" for o in config.get("options", [])}
            keys |= {
                f"selector.{translation_key}.fields.{f}.name" for f in config.get("fields", {})
            }
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
    for rule_type in ("progress", "upcoming", "custom"):
        keys |= _form_keys(rule, await start_rule(hass, entry, rule_type))
    keys |= {
        f"{rule}.error.progress_entity",
        f"{rule}.error.entities_required",
        f"{rule}.error.invalid_card",
    }
    result = await start_rule(hass, entry, "status")
    keys |= _form_keys(rule, result)
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], BILEN)
    keys |= _form_keys(rule, result) | {f"{rule}.error.level_required"}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], dict.fromkeys(LEVELS, "condition")
    )
    keys |= _form_keys(rule, result) | {
        f"{rule}.error.condition_required",
        f"{rule}.error.invalid_condition",
    }

    # Orsaken med valen för varje Typ, och åtgärderna.
    hass.states.async_set("sensor.disk_kvar", "40", {"device_class": "duration"})
    for rule_type, fields in (
        ("status", BILEN),
        ("progress", PROGRESS),
        ("value", BILEN),
        ("upcoming", UPCOMING),
        ("custom", CUSTOM),
    ):
        result = await reach_reason(hass, entry, rule_type, fields)
        keys |= _form_keys(rule, result)
    result = await submit_reason(hass, result, {"reason": "none"})
    keys |= _form_keys(rule, result) | {
        f"{rule}.error.template_required",
        f"{rule}.error.invalid_action",
    }
    # Orden i de färdiga mallarna för orsaken.
    keys |= {
        f"reason.{word}"
        for word in (
            "state_for",
            "time_left",
            "next",
            "minutes",
            "hours",
            "days",
            "unavailable",
            "unknown",
        )
    }

    subentry_id = await add_rule(hass, entry, "value", BILEN, ALWAYS_GLANCE)
    result = await start_rule_reconfigure(hass, entry, subentry_id)
    keys |= _form_keys(rule, result) | {f"{rule}.abort.reconfigure_successful"}
    # Ändra-formuläret visar fälten för regelns typ.
    for rule_type, fields in (("upcoming", UPCOMING), ("custom", CUSTOM)):
        subentry_id = await add_rule(hass, entry, rule_type, fields, ALWAYS_GLANCE)
        keys |= _form_keys(rule, await start_rule_reconfigure(hass, entry, subentry_id))

    state = hass.states.get("sensor.attention_span_bilen")
    keys |= {f"entity.sensor.rule.state.{option}" for option in state.attributes["options"]}
    return keys


@pytest.mark.parametrize("language", ["en", "sv"])
async def test_forms_and_states_are_translated(hass: HomeAssistant, language: str):
    translated = _flatten(json.loads((TRANSLATIONS / f"{language}.json").read_text()))

    missing = sorted(key for key in await _shown_keys(hass) if not translated.get(key))

    assert missing == []

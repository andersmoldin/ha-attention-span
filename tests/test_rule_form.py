from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult, FlowResultType

from .conftest import add_integration, add_rule, level_modes, start_rule, start_rule_reconfigure

YTTERDORREN = {"name": "Ytterdörren", "icon": "mdi:door", "entity": "binary_sensor.ytterdorr"}
# En template som användaren skrev den, så att den kan visas igen i formuläret.
DOOR_OPEN = {
    "condition": "template",
    "value_template": "{{ is_state('binary_sensor.ytterdorr', 'on') }}",
}


async def submit(hass: HomeAssistant, result: FlowResult, user_input: dict) -> FlowResult:
    return await hass.config_entries.subentries.async_configure(result["flow_id"], user_input)


def suggested(result: FlowResult) -> dict:
    """Det formuläret visar i fälten från början."""
    return {
        str(key): (key.description or {}).get("suggested_value")
        for key in result["data_schema"].schema
    }


async def test_a_rule_needs_at_least_one_level(hass: HomeAssistant):
    entry = await add_integration(hass)
    result = await submit(hass, await start_rule(hass, entry, "status"), YTTERDORREN)

    result = await submit(hass, result, level_modes({}))

    assert result["step_id"] == "levels"
    assert result["errors"] == {"base": "level_required"}


async def test_a_level_with_condition_needs_a_condition(hass: HomeAssistant):
    entry = await add_integration(hass)
    result = await submit(hass, await start_rule(hass, entry, "status"), YTTERDORREN)
    result = await submit(hass, result, level_modes({"ongoing": "condition"}))

    result = await submit(hass, result, {"ongoing": []})

    assert result["step_id"] == "conditions"
    assert result["errors"] == {"ongoing": "condition_required"}
    assert entry.subentries == {}


async def test_an_invalid_condition_is_rejected(hass: HomeAssistant):
    entry = await add_integration(hass)
    result = await submit(hass, await start_rule(hass, entry, "status"), YTTERDORREN)
    result = await submit(hass, result, level_modes({"ongoing": "condition"}))

    result = await submit(
        hass,
        result,
        {"ongoing": [DOOR_OPEN], "hide": [{"condition": "state", "state": "on"}]},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"hide": "invalid_condition"}
    assert entry.subentries == {}


async def test_changing_a_rule_shows_its_levels_and_conditions_as_written(hass: HomeAssistant):
    entry = await add_integration(hass)
    hide = [{"condition": "state", "entity_id": "input_boolean.vadring", "state": "on"}]
    rule = await add_rule(
        hass,
        entry,
        "status",
        YTTERDORREN,
        levels={"ongoing": "condition", "quiet": "always"},
        conditions={"ongoing": [DOOR_OPEN], "hide": hide},
    )

    result = await start_rule_reconfigure(hass, entry, rule)
    result = await submit(hass, result, YTTERDORREN)
    assert {
        str(key): key.default() for key in result["data_schema"].schema
    } == level_modes({"ongoing": "condition", "quiet": "always"})
    result = await submit(hass, result, level_modes({"ongoing": "condition", "quiet": "always"}))

    assert result["step_id"] == "conditions"
    assert suggested(result) == {"ongoing": [DOOR_OPEN], "hide": hide}

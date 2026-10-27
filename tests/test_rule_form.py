import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult, FlowResultType, InvalidData

from .conftest import add_integration, add_rule, level_modes, start_rule, start_rule_reconfigure

YTTERDORREN = {"name": "Ytterdörren", "icon": "mdi:door", "entity": "binary_sensor.ytterdorr"}
# En template som användaren skrev den, så att den kan visas igen i formuläret.
DOOR_OPEN_TEMPLATE = {
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
        {"ongoing": [DOOR_OPEN_TEMPLATE], "hide": [{"condition": "state", "state": "on"}]},
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
        conditions={"ongoing": [DOOR_OPEN_TEMPLATE], "hide": hide},
    )

    result = await start_rule_reconfigure(hass, entry, rule)
    result = await submit(hass, result, YTTERDORREN)
    assert {
        str(key): key.default() for key in result["data_schema"].schema
    } == level_modes({"ongoing": "condition", "quiet": "always"})
    result = await submit(hass, result, level_modes({"ongoing": "condition", "quiet": "always"}))

    assert result["step_id"] == "conditions"
    assert suggested(result) == {"ongoing": [DOOR_OPEN_TEMPLATE], "hide": hide}


async def reach_reason(hass: HomeAssistant, entry, rule_type: str, fields: dict) -> FlowResult:
    """Fyll i regeln fram till orsaken, med nivån Pågår alltid."""
    result = await submit(hass, await start_rule(hass, entry, rule_type), fields)
    result = await submit(hass, result, level_modes({"ongoing": "always"}))
    result = await submit(hass, result, {})
    assert result["step_id"] == "reason"
    return result


def reason_options(result: FlowResult) -> list[str]:
    return result["data_schema"].schema["reason"].config["options"]


@pytest.mark.parametrize(
    ("rule_type", "fields", "options"),
    [
        ("status", YTTERDORREN, ["none", "state_for", "custom"]),
        ("progress", {"name": "Disk", "entity": "timer.disk"}, ["none", "time_left", "custom"]),
        ("value", {"name": "Bilen", "entity": "sensor.bilen"}, ["none", "value", "custom"]),
        (
            "upcoming",
            {"name": "Buss", "entities": ["sensor.buss"], "count": 1},
            ["none", "next", "custom"],
        ),
        ("custom", {"name": "Vädret", "card": {"type": "weather-forecast"}}, ["none", "custom"]),
    ],
)
async def test_the_reason_offers_the_presets_of_the_type_and_an_own_template(
    hass: HomeAssistant, rule_type: str, fields: dict, options: list[str]
):
    hass.states.async_set("timer.disk", "idle")
    entry = await add_integration(hass)

    result = await reach_reason(hass, entry, rule_type, fields)

    assert reason_options(result) == options


async def test_a_new_choice_shows_its_preview_before_the_flow_goes_on(
    hass: HomeAssistant, freezer
):
    freezer.move_to("2026-10-26T08:00:00+00:00")
    hass.states.async_set("sensor.bilen", "52", {"unit_of_measurement": "%"})
    entry = await add_integration(hass)
    result = await reach_reason(hass, entry, "value", {"name": "Bilen", "entity": "sensor.bilen"})
    assert result["description_placeholders"] == {"preview": "–"}

    result = await submit(hass, result, {"reason": "value"})
    assert result["step_id"] == "reason"
    assert result["description_placeholders"] == {"preview": "52 %"}

    template = "Laddat {{ states('sensor.bilen') }} av 80 %"
    result = await submit(hass, result, {"reason": "custom", "reason_template": template})
    assert result["step_id"] == "reason"
    assert result["description_placeholders"] == {"preview": "Laddat 52 av 80 %"}

    result = await submit(hass, result, {"reason": "custom", "reason_template": template})
    assert result["step_id"] == "actions"


async def test_an_own_template_needs_a_valid_template(hass: HomeAssistant):
    entry = await add_integration(hass)
    result = await reach_reason(hass, entry, "status", YTTERDORREN)

    result = await submit(hass, result, {"reason": "custom"})
    assert result["errors"] == {"reason_template": "template_required"}

    with pytest.raises(InvalidData):
        await submit(hass, result, {"reason": "custom", "reason_template": "{{ 1 + }}"})


async def test_changing_a_rule_shows_its_reason_and_actions_as_saved(hass: HomeAssistant):
    hass.states.async_set("binary_sensor.ytterdorr", "on")
    entry = await add_integration(hass)
    template = "Öppen {{ states('binary_sensor.ytterdorr') }}"
    restart = [{"action": "lock.lock", "target": {"entity_id": "lock.ytterdorr"}}]
    rule = await add_rule(
        hass,
        entry,
        "status",
        YTTERDORREN,
        levels={"ongoing": "always"},
        reason={"reason": "custom", "reason_template": template},
        actions=[{"name": "Lås", "action": restart, "confirmation": "Lås dörren?"}],
    )

    result = await start_rule_reconfigure(hass, entry, rule)
    result = await submit(hass, result, YTTERDORREN)
    result = await submit(hass, result, level_modes({"ongoing": "always"}))
    result = await submit(hass, result, {})
    assert result["step_id"] == "reason"
    (choice,) = (key for key in result["data_schema"].schema if key == "reason")
    assert choice.default() == "custom"
    assert suggested(result)["reason_template"] == template
    assert result["description_placeholders"] == {"preview": "Öppen on"}

    result = await submit(hass, result, {"reason": "custom", "reason_template": template})
    assert result["step_id"] == "actions"
    assert suggested(result) == {
        "actions": [{"name": "Lås", "action": restart, "confirmation": "Lås dörren?"}]
    }
    result = await submit(hass, result, {"actions": []})

    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    state = hass.states.get("sensor.attention_span_ytterdorren")
    assert state.attributes["actions"] == []
    assert state.attributes["reason"] == "Öppen on"

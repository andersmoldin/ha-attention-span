"""Placeringen: var en regel står bland regler som kan hamna på samma nivå."""

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult, FlowResultType

from .conftest import (
    ALWAYS_GLANCE,
    ALWAYS_QUIET,
    BILEN,
    ELPRIS,
    add_integration,
    add_rule,
    level_modes,
    reconfigure_rule,
    start_rule,
    start_rule_reconfigure,
    submit_reason_and_actions,
)

INNE = {"name": "Inne", "icon": "mdi:thermometer", "entity": "sensor.inne"}


async def submit(hass: HomeAssistant, result: FlowResult, user_input: dict) -> FlowResult:
    return await hass.config_entries.subentries.async_configure(result["flow_id"], user_input)


def placement_options(result: FlowResult) -> list[tuple[str, str]]:
    """Valen i placeringen som (värde, text)."""
    options = result["data_schema"].schema["placement"].config["options"]
    return [(option["value"], option["label"]) for option in options]


def priorities(hass: HomeAssistant, *names: str) -> list[int]:
    states = [hass.states.get(f"sensor.attention_span_{name}") for name in names]
    return [state.attributes["priority"] for state in states]


async def test_the_placement_lists_first_and_the_rules_that_share_a_level(hass: HomeAssistant):
    hass.config.language = "sv"
    entry = await add_integration(hass)
    bilen = await add_rule(hass, entry, "value", BILEN, ALWAYS_GLANCE)
    elpris = await add_rule(hass, entry, "value", ELPRIS, ALWAYS_GLANCE)

    result = await submit(hass, await start_rule(hass, entry, "value"), INNE)
    result = await submit(hass, result, level_modes(ALWAYS_GLANCE))
    result = await submit(hass, result, {})

    assert result["step_id"] == "placement"
    assert placement_options(result) == [
        ("first", "Först"),
        (bilen, "Efter Bilen"),
        (elpris, "Efter Elpris"),
    ]

    result = await submit(hass, result, {"placement": bilen})
    assert result["step_id"] == "reason"


async def test_a_new_rule_placed_after_another_gets_the_priority_after_it(hass: HomeAssistant):
    entry = await add_integration(hass)
    bilen = await add_rule(hass, entry, "value", BILEN, ALWAYS_GLANCE)
    await add_rule(hass, entry, "value", ELPRIS, ALWAYS_GLANCE)

    await add_rule(hass, entry, "value", INNE, ALWAYS_GLANCE, placement=bilen)

    assert priorities(hass, "bilen", "inne", "elpris") == [1, 2, 3]


async def test_first_places_the_rule_before_the_rules_that_share_a_level(hass: HomeAssistant):
    entry = await add_integration(hass)
    await add_rule(hass, entry, "value", ELPRIS, ALWAYS_QUIET)
    await add_rule(hass, entry, "value", BILEN, ALWAYS_GLANCE)

    await add_rule(hass, entry, "value", INNE, ALWAYS_GLANCE, placement="first")

    assert priorities(hass, "elpris", "inne", "bilen") == [1, 2, 3]


async def test_rules_without_a_shared_level_are_not_offered(hass: HomeAssistant):
    entry = await add_integration(hass)
    await add_rule(hass, entry, "value", ELPRIS, ALWAYS_QUIET)
    bilen = await add_rule(
        hass, entry, "value", BILEN, {"problem": "always", "glance": "always"}
    )

    result = await submit(hass, await start_rule(hass, entry, "value"), INNE)
    result = await submit(hass, result, level_modes({"problem": "always", "alarm": "always"}))
    result = await submit(hass, result, {})

    assert [value for value, _ in placement_options(result)] == ["first", bilen]


async def test_without_rules_on_the_same_level_the_form_does_not_ask_and_the_rule_comes_last(
    hass: HomeAssistant,
):
    entry = await add_integration(hass)
    await add_rule(hass, entry, "value", BILEN, ALWAYS_GLANCE)

    result = await submit(hass, await start_rule(hass, entry, "value"), ELPRIS)
    result = await submit(hass, result, level_modes(ALWAYS_QUIET))
    result = await submit(hass, result, {})
    assert result["step_id"] == "reason"
    result = await submit_reason_and_actions(hass, result, None, None)
    await hass.async_block_till_done()

    assert priorities(hass, "bilen", "elpris") == [1, 2]


async def test_a_new_rule_is_placed_last_by_default(hass: HomeAssistant):
    entry = await add_integration(hass)
    await add_rule(hass, entry, "value", BILEN, ALWAYS_GLANCE)
    elpris = await add_rule(hass, entry, "value", ELPRIS, ALWAYS_GLANCE)

    result = await submit(hass, await start_rule(hass, entry, "value"), INNE)
    result = await submit(hass, result, level_modes(ALWAYS_GLANCE))
    result = await submit(hass, result, {})

    (field,) = result["data_schema"].schema
    assert field.default() == elpris


async def test_changing_a_rule_shows_where_it_stands_and_moving_it_renumbers_the_order(
    hass: HomeAssistant,
):
    entry = await add_integration(hass)
    bilen = await add_rule(hass, entry, "value", BILEN, ALWAYS_GLANCE)
    elpris = await add_rule(hass, entry, "value", ELPRIS, ALWAYS_GLANCE)
    inne = await add_rule(hass, entry, "value", INNE, ALWAYS_GLANCE)

    result = await start_rule_reconfigure(hass, entry, inne)
    result = await submit(hass, result, INNE)
    result = await submit(hass, result, level_modes(ALWAYS_GLANCE))
    result = await submit(hass, result, {})
    assert result["step_id"] == "placement"
    assert [value for value, _ in placement_options(result)] == ["first", bilen, elpris]
    (field,) = result["data_schema"].schema
    assert field.default() == elpris

    await reconfigure_rule(hass, entry, inne, INNE, ALWAYS_GLANCE, placement="first")
    assert priorities(hass, "inne", "bilen", "elpris") == [1, 2, 3]

    await reconfigure_rule(hass, entry, bilen, BILEN, ALWAYS_GLANCE, placement="first")
    assert priorities(hass, "bilen", "inne", "elpris") == [1, 2, 3]

    result = await start_rule_reconfigure(hass, entry, elpris)
    result = await submit(hass, result, ELPRIS)
    result = await submit(hass, result, level_modes(ALWAYS_GLANCE))
    result = await submit(hass, result, {})
    (field,) = result["data_schema"].schema
    assert field.default() == inne


async def test_changing_a_rule_without_moving_it_keeps_every_priority(hass: HomeAssistant):
    entry = await add_integration(hass)
    await add_rule(hass, entry, "value", BILEN, ALWAYS_GLANCE)
    elpris = await add_rule(hass, entry, "value", ELPRIS, ALWAYS_GLANCE)
    inne = await add_rule(hass, entry, "value", INNE, ALWAYS_GLANCE)
    # En borttagen regel lämnar en lucka i ordningen; den står kvar så länge ingen flyttas.
    assert hass.config_entries.async_remove_subentry(entry, elpris)
    await hass.async_block_till_done()

    await reconfigure_rule(hass, entry, inne, INNE, ALWAYS_GLANCE)

    assert priorities(hass, "bilen", "inne") == [1, 3]


async def test_the_form_starts_over_when_the_rule_it_places_after_is_removed(hass: HomeAssistant):
    entry = await add_integration(hass)
    bilen = await add_rule(hass, entry, "value", BILEN, ALWAYS_GLANCE)
    result = await submit(hass, await start_rule(hass, entry, "value"), INNE)
    result = await submit(hass, result, level_modes(ALWAYS_GLANCE))
    result = await submit(hass, result, {})
    result = await submit(hass, result, {"placement": bilen})

    assert hass.config_entries.async_remove_subentry(entry, bilen)
    await hass.async_block_till_done()
    result = await submit_reason_and_actions(hass, result, None, None)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "rules_changed"
    assert len(entry.subentries) == 0

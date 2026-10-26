from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from .conftest import (
    ALWAYS_GLANCE,
    ALWAYS_QUIET,
    BILEN,
    ELPRIS,
    FIXTURE_TIME,
    add_integration,
    add_rule,
    contract_example,
    reconfigure_rule,
    start_rule,
    state_as_contract,
)


async def test_rule_always_at_a_level_becomes_a_sensor_in_contract_v1(hass: HomeAssistant, freezer):
    freezer.move_to(FIXTURE_TIME)
    entry = await add_integration(hass)

    await add_rule(hass, entry, "value", BILEN, ALWAYS_GLANCE)
    await add_rule(hass, entry, "value", ELPRIS, ALWAYS_QUIET)

    for name in ("value_glance", "value_quiet"):
        expected = contract_example(name)
        assert state_as_contract(hass, expected["entity_id"]) == expected


async def test_changing_the_level_changes_the_state(hass: HomeAssistant, freezer):
    freezer.move_to(FIXTURE_TIME)
    entry = await add_integration(hass)
    rule = await add_rule(hass, entry, "value", BILEN, ALWAYS_GLANCE)
    freezer.move_to("2026-10-26T09:30:00+00:00")

    await reconfigure_rule(hass, entry, rule, BILEN, ALWAYS_QUIET)

    state = hass.states.get("sensor.attention_span_bilen")
    assert state.state == "quiet"
    assert state.attributes["since"] == "2026-10-26T09:30:00+00:00"
    assert state.attributes["priority"] == 1


async def test_removing_the_rule_removes_the_entity(hass: HomeAssistant):
    entry = await add_integration(hass)
    rule = await add_rule(hass, entry, "value", BILEN, ALWAYS_GLANCE)
    assert hass.states.get("sensor.attention_span_bilen") is not None

    assert hass.config_entries.async_remove_subentry(entry, rule)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.attention_span_bilen") is None
    assert er.async_get(hass).async_get("sensor.attention_span_bilen") is None


async def test_a_new_rule_with_the_name_of_a_removed_one_starts_now(
    hass: HomeAssistant, freezer
):
    freezer.move_to(FIXTURE_TIME)
    entry = await add_integration(hass)
    rule = await add_rule(hass, entry, "value", BILEN, ALWAYS_GLANCE)
    assert hass.config_entries.async_remove_subentry(entry, rule)
    await hass.async_block_till_done()
    freezer.move_to("2026-10-26T09:30:00+00:00")

    await add_rule(hass, entry, "value", BILEN, ALWAYS_GLANCE)

    state = hass.states.get("sensor.attention_span_bilen")
    assert state.state == "glance"
    assert state.attributes["since"] == "2026-10-26T09:30:00+00:00"


async def test_adding_another_rule_keeps_when_the_level_began(hass: HomeAssistant, freezer):
    freezer.move_to(FIXTURE_TIME)
    entry = await add_integration(hass)
    await add_rule(hass, entry, "value", BILEN, ALWAYS_GLANCE)
    freezer.move_to("2026-10-26T09:30:00+00:00")

    await add_rule(hass, entry, "value", ELPRIS, ALWAYS_QUIET)

    assert hass.states.get("sensor.attention_span_bilen").attributes["since"] == FIXTURE_TIME


async def test_a_rule_needs_a_name(hass: HomeAssistant):
    entry = await add_integration(hass)
    result = await start_rule(hass, entry, "value")

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], BILEN | {"name": "  "}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"name": "name_required"}
    assert entry.subentries == {}

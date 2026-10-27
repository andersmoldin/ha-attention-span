"""Åtgärderna: tjänsteanrop som kortet visar som knappar, genom det riktiga flödet."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import (
    FIXTURE_TIME,
    add_integration,
    add_rule,
    contract_example,
    level_modes,
    start_rule,
    state_as_contract,
    submit_reason,
)

FINDUS = {"name": "Findus", "icon": "mdi:robot-vacuum", "entity": "vacuum.findus"}
ALWAYS_PROBLEM = {"problem": "always"}

# Så som HA:s åtgärdsväljare skickar ett tjänsteanrop.
RESTART = [
    {
        "action": "button.press",
        "metadata": {},
        "data": {},
        "target": {"entity_id": "button.findus_restart"},
    }
]
DOCK = [{"action": "vacuum.return_to_base", "target": {"entity_id": "vacuum.findus"}}]


def actions(hass: HomeAssistant, entity_id: str) -> list[dict]:
    return hass.states.get(entity_id).attributes["actions"]


async def reach_actions(hass: HomeAssistant, entry):
    result = await start_rule(hass, entry, "status")
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], FINDUS)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], level_modes(ALWAYS_PROBLEM)
    )
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {})
    result = await submit_reason(hass, result, {"reason": "none"})
    assert result["step_id"] == "actions"
    return result


async def test_actions_become_the_attribute_actions_with_an_optional_confirmation(
    hass: HomeAssistant,
):
    entry = await add_integration(hass)

    await add_rule(
        hass,
        entry,
        "status",
        FINDUS,
        ALWAYS_PROBLEM,
        actions=[
            {"name": "Starta om", "action": RESTART, "confirmation": "Starta om Findus?"},
            {"name": "Docka", "action": DOCK},
        ],
    )

    assert actions(hass, "sensor.attention_span_findus") == [
        {
            "name": "Starta om",
            "action": "button.press",
            "target": {"entity_id": "button.findus_restart"},
            "data": {},
            "confirmation": "Starta om Findus?",
        },
        {
            "name": "Docka",
            "action": "vacuum.return_to_base",
            "target": {"entity_id": "vacuum.findus"},
            "data": {},
            "confirmation": None,
        },
    ]


async def test_a_rule_without_actions_has_an_empty_list(hass: HomeAssistant):
    entry = await add_integration(hass)

    await add_rule(hass, entry, "status", FINDUS, ALWAYS_PROBLEM)

    assert actions(hass, "sensor.attention_span_findus") == []


@pytest.mark.parametrize(
    "action",
    [
        # Två anrop i samma åtgärd.
        RESTART + DOCK,
        # Något annat än ett tjänsteanrop.
        [{"delay": {"seconds": 5}}],
        # En template, som kortet inte kan rendera.
        [{"action": "button.press", "target": {"entity_id": "{{ 'button.findus_restart' }}"}}],
        # Inget tjänsteanrop alls.
        [],
    ],
)
async def test_an_action_must_be_one_service_call_without_templates(
    hass: HomeAssistant, action: list
):
    entry = await add_integration(hass)
    result = await reach_actions(hass, entry)

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"actions": [{"name": "Starta om", "action": action}]}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"actions": "invalid_action"}


async def test_an_action_needs_a_name(hass: HomeAssistant):
    entry = await add_integration(hass)
    result = await reach_actions(hass, entry)

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"actions": [{"name": "  ", "action": RESTART}]}
    )

    assert result["errors"] == {"actions": "invalid_action"}


async def test_a_rule_with_reason_and_actions_matches_the_shared_example(
    hass: HomeAssistant, freezer
):
    freezer.move_to("2026-10-26T07:50:00+00:00")
    hass.states.async_set("binary_sensor.frysdorr", "on")
    freezer.move_to(FIXTURE_TIME)
    entry = await add_integration(hass)

    await add_rule(
        hass,
        entry,
        "status",
        {"name": "Frysen", "icon": "mdi:fridge", "entity": "binary_sensor.frysdorr"},
        ALWAYS_PROBLEM,
        reason={
            "reason": "custom",
            "reason_template": "{{ 'Dörren står öppen' if is_state(entity, 'on') else '' }}",
        },
        actions=[
            {
                "name": "Tysta larmet",
                "action": [{"action": "siren.turn_off", "target": {"entity_id": "siren.frysen"}}],
                "confirmation": "Tysta frysens larm?",
            }
        ],
    )

    expected = contract_example("status_problem_reason_actions")
    assert state_as_contract(hass, expected["entity_id"]) == expected

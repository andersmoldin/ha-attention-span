from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from .conftest import (
    FIXTURE_TIME,
    add_integration,
    add_rule,
    contract_example,
    state_as_contract,
)

FINDUS = {"name": "Findus", "icon": "mdi:robot-vacuum", "entity": "vacuum.findus"}
OFFLINE = {"condition": "state", "entity_id": "vacuum.findus", "state": "unavailable"}
OFFLINE_2H = OFFLINE | {"for": {"hours": 2}}


async def tick(hass: HomeAssistant, freezer, delta: timedelta) -> None:
    """Låt tiden gå, så att tidsbaserade villkor räknas om."""
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


@pytest.mark.parametrize("order", [("problem", "alarm"), ("alarm", "problem")])
async def test_the_most_severe_level_that_holds_wins_whatever_the_order(
    hass: HomeAssistant, freezer, order
):
    freezer.move_to(FIXTURE_TIME)
    hass.states.async_set("vacuum.findus", "unavailable")
    entry = await add_integration(hass)
    conditions = {"problem": [OFFLINE], "alarm": [OFFLINE_2H]}

    await add_rule(
        hass,
        entry,
        "status",
        FINDUS,
        levels={level: "condition" for level in order},
        conditions={level: conditions[level] for level in order},
    )
    assert hass.states.get("sensor.attention_span_findus").state == "problem"

    await tick(hass, freezer, timedelta(hours=2))
    assert hass.states.get("sensor.attention_span_findus").state == "problem"

    # HA:s «i 2 h» gäller först när mer än 2 h har gått.
    await tick(hass, freezer, timedelta(seconds=1))

    state = hass.states.get("sensor.attention_span_findus")
    assert state.state == "alarm"
    assert state.attributes["since"] == "2026-10-26T10:00:01+00:00"


YTTERDORREN = {"name": "Ytterdörren", "icon": "mdi:door", "entity": "binary_sensor.ytterdorr"}
DOOR_OPEN = {"condition": "state", "entity_id": "binary_sensor.ytterdorr", "state": "on"}
AIRING = {"condition": "state", "entity_id": "input_boolean.vadring", "state": "on"}


async def add_door_rule(hass: HomeAssistant, entry) -> None:
    """Ytterdörren: Pågår när den är öppen, Problem efter 5 min, dold under vädring."""
    await add_rule(
        hass,
        entry,
        "status",
        YTTERDORREN,
        levels={"problem": "condition", "ongoing": "condition"},
        conditions={
            "problem": [DOOR_OPEN | {"for": {"minutes": 5}}],
            "ongoing": [DOOR_OPEN],
            "hide": [AIRING],
        },
    )


async def test_hide_when_beats_every_level_condition(hass: HomeAssistant, freezer):
    freezer.move_to(FIXTURE_TIME)
    hass.states.async_set("binary_sensor.ytterdorr", "on")
    hass.states.async_set("input_boolean.vadring", "off")
    entry = await add_integration(hass)
    await add_door_rule(hass, entry)
    await tick(hass, freezer, timedelta(minutes=10))
    assert hass.states.get("sensor.attention_span_ytterdorren").state == "problem"

    hass.states.async_set("input_boolean.vadring", "on")
    await hass.async_block_till_done()

    assert hass.states.get("sensor.attention_span_ytterdorren").state == "hidden"


async def test_a_rule_is_hidden_when_no_condition_holds(hass: HomeAssistant):
    hass.states.async_set("binary_sensor.ytterdorr", "on")
    hass.states.async_set("input_boolean.vadring", "off")
    entry = await add_integration(hass)
    await add_door_rule(hass, entry)
    assert hass.states.get("sensor.attention_span_ytterdorren").state == "ongoing"

    hass.states.async_set("binary_sensor.ytterdorr", "off")
    await hass.async_block_till_done()

    assert hass.states.get("sensor.attention_span_ytterdorren").state == "hidden"


TVATTEN = {"name": "Tvätten", "icon": "mdi:washing-machine", "entity": "sensor.tvattmaskin"}
# Pågår både när tvätten kör och när den är klar men inte urplockad.
WASH_ONGOING = {
    "condition": "or",
    "conditions": [
        {"condition": "state", "entity_id": "sensor.tvattmaskin", "state": "running"},
        {
            "condition": "and",
            "conditions": [
                {"condition": "state", "entity_id": "sensor.tvattmaskin", "state": "done"},
                {"condition": "state", "entity_id": "input_boolean.urplockad", "state": "off"},
            ],
        },
    ],
}


async def add_wash_rule(hass: HomeAssistant, entry) -> None:
    await add_rule(
        hass,
        entry,
        "status",
        TVATTEN,
        levels={"ongoing": "condition"},
        conditions={"ongoing": [WASH_ONGOING]},
    )


async def test_several_conditions_for_one_level_combine_with_or(hass: HomeAssistant):
    hass.states.async_set("sensor.tvattmaskin", "running")
    hass.states.async_set("input_boolean.urplockad", "off")
    entry = await add_integration(hass)
    await add_wash_rule(hass, entry)
    assert hass.states.get("sensor.attention_span_tvatten").state == "ongoing"

    hass.states.async_set("sensor.tvattmaskin", "done")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.attention_span_tvatten").state == "ongoing"

    hass.states.async_set("input_boolean.urplockad", "on")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.attention_span_tvatten").state == "hidden"


async def test_since_moves_when_the_level_changes_and_only_then(hass: HomeAssistant, freezer):
    freezer.move_to(FIXTURE_TIME)
    hass.states.async_set("sensor.tvattmaskin", "running")
    hass.states.async_set("input_boolean.urplockad", "off")
    entry = await add_integration(hass)
    await add_wash_rule(hass, entry)

    freezer.move_to("2026-10-26T09:00:00+00:00")
    hass.states.async_set("sensor.tvattmaskin", "done")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.attention_span_tvatten").attributes["since"] == FIXTURE_TIME

    freezer.move_to("2026-10-26T11:00:00+00:00")
    hass.states.async_set("input_boolean.urplockad", "on")
    await hass.async_block_till_done()
    state = hass.states.get("sensor.attention_span_tvatten")
    assert state.state == "hidden"
    assert state.attributes["since"] == "2026-10-26T11:00:00+00:00"


async def test_a_rule_whose_conditions_no_longer_work_is_unavailable(hass: HomeAssistant):
    """Till exempel ett villkor på en enhet som har tagits bort efteråt."""
    other = MockConfigEntry(domain="test")
    other.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("test", "lampa")}
    )
    lamp = er.async_get(hass).async_get_or_create(
        "light", "test", "lampa", device_id=device.id, config_entry=other
    )
    hass.states.async_set(lamp.entity_id, "on")
    entry = await add_integration(hass)
    lamp_on = {
        "condition": "device",
        "device_id": device.id,
        "domain": "light",
        "type": "is_on",
        "entity_id": lamp.id,
    }
    await add_rule(
        hass,
        entry,
        "status",
        {"name": "Lampan", "entity": lamp.entity_id},
        levels={"glance": "condition"},
        conditions={"glance": [lamp_on]},
    )
    assert hass.states.get("sensor.attention_span_lampan").state == "glance"

    dr.async_get(hass).async_remove_device(device.id)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.attention_span_lampan").state == "unavailable"


async def test_a_condition_that_cannot_be_worked_out_does_not_hold(
    hass: HomeAssistant, freezer, caplog
):
    """Till exempel en gräns på en sensor som inte visar ett tal. Felet loggas en gång."""
    hass.states.async_set("sensor.inne", "trasig")
    entry = await add_integration(hass)
    too_warm = {"condition": "numeric_state", "entity_id": "sensor.inne", "above": 26}
    await add_rule(
        hass,
        entry,
        "value",
        {"name": "Inne", "entity": "sensor.inne"},
        levels={"problem": "condition", "glance": "always"},
        conditions={"problem": [too_warm]},
    )
    hass.states.async_set("sensor.inne", "inte heller")
    await hass.async_block_till_done()

    assert hass.states.get("sensor.attention_span_inne").state == "glance"
    assert caplog.text.count("Villkoren i regeln sensor.attention_span_inne") == 1

    hass.states.async_set("sensor.inne", "27")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.attention_span_inne").state == "problem"


async def test_rules_with_level_conditions_match_the_shared_examples(hass: HomeAssistant, freezer):
    freezer.move_to("2026-10-26T05:00:00+00:00")
    hass.states.async_set("vacuum.findus", "unavailable")
    freezer.move_to("2026-10-26T07:50:00+00:00")
    hass.states.async_set("binary_sensor.ytterdorr", "on")
    hass.states.async_set("input_boolean.vadring", "off")
    hass.states.async_set("sensor.tvattmaskin", "running")
    hass.states.async_set("input_boolean.urplockad", "off")
    freezer.move_to(FIXTURE_TIME)
    entry = await add_integration(hass)

    await add_rule(
        hass,
        entry,
        "status",
        FINDUS,
        levels={"problem": "condition", "alarm": "condition"},
        conditions={"problem": [OFFLINE], "alarm": [OFFLINE_2H]},
    )
    await add_door_rule(hass, entry)
    await add_wash_rule(hass, entry)

    for name in ("status_alarm", "status_problem", "status_ongoing"):
        expected = contract_example(name)
        assert state_as_contract(hass, expected["entity_id"]) == expected

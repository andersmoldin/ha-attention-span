"""Villkorskontrollerna lämnar inga spår kvar i HA:s trace.

HA sparar varje villkorskontroll som ett trace-element. Utanför en automation töms den
tracen aldrig, så kontroller som upprepas dygnet runt får inte lägga till i den.
"""

import gc
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.trace import TraceElement
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .conftest import FIXTURE_TIME, add_integration, add_rule

FINDUS = {"name": "Findus", "icon": "mdi:robot-vacuum", "entity": "vacuum.findus"}
OFFLINE = {"condition": "state", "entity_id": "vacuum.findus", "state": "unavailable"}
OFFLINE_2H = OFFLINE | {"for": {"hours": 2}}


async def tick(hass: HomeAssistant, freezer, delta: timedelta) -> None:
    """Låt tiden gå, så att tidsbaserade villkor räknas om."""
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def trace_elements() -> int:
    """Hur många trace-element som finns kvar i minnet."""
    gc.collect()
    return sum(isinstance(item, TraceElement) for item in gc.get_objects())


async def add_findus_rule(hass: HomeAssistant, freezer) -> None:
    """Findus: Problem när den är offline, Larm när den har varit offline i 2 h."""
    freezer.move_to(FIXTURE_TIME)
    hass.states.async_set("vacuum.findus", "unavailable")
    entry = await add_integration(hass)
    await add_rule(
        hass,
        entry,
        "status",
        FINDUS,
        levels={"problem": "condition", "alarm": "condition"},
        conditions={"problem": [OFFLINE], "alarm": [OFFLINE_2H]},
    )


async def test_checks_every_second_leave_no_trace_behind(hass: HomeAssistant, freezer):
    await add_findus_rule(hass, freezer)
    before = trace_elements()

    for _ in range(10):
        await tick(hass, freezer, timedelta(seconds=1))

    assert trace_elements() == before


async def test_checks_when_an_entity_changes_leave_no_trace_behind(hass: HomeAssistant, freezer):
    await add_findus_rule(hass, freezer)
    before = trace_elements()

    for state in ["docked", "unavailable"] * 5:
        hass.states.async_set("vacuum.findus", state)
        await hass.async_block_till_done()

    assert trace_elements() == before


YTTERDORREN = {"name": "Ytterdörren", "icon": "mdi:door", "entity": "binary_sensor.ytterdorr"}
AIRING = {"condition": "state", "entity_id": "input_boolean.vadring", "state": "on"}


async def test_a_check_during_an_automation_leaves_its_trace_alone(
    hass: HomeAssistant, hass_ws_client
):
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {"vadring": {}}})
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "id": "vadra",
                "triggers": [{"trigger": "event", "event_type": "vadra"}],
                "actions": [
                    {
                        "action": "input_boolean.turn_on",
                        "target": {"entity_id": "input_boolean.vadring"},
                    }
                ],
            }
        },
    )
    entry = await add_integration(hass)
    await add_rule(
        hass,
        entry,
        "status",
        YTTERDORREN,
        levels={"problem": "condition"},
        conditions={"problem": [AIRING | {"for": {"minutes": 5}}]},
    )

    # Automationen slår på vädringen, och regeln kontrollerar sina villkor medan den körs.
    hass.bus.async_fire("vadra")
    await hass.async_block_till_done()
    assert hass.states.get("input_boolean.vadring").state == "on"

    client = await hass_ws_client()
    await client.send_json_auto_id({"type": "trace/list", "domain": "automation"})
    (run,) = (await client.receive_json())["result"]
    await client.send_json_auto_id(
        {
            "type": "trace/get",
            "domain": "automation",
            "item_id": "vadra",
            "run_id": run["run_id"],
        }
    )
    trace = (await client.receive_json())["result"]["trace"]
    assert {path: len(steps) for path, steps in trace.items()} == {"trigger/0": 1, "action/0": 1}

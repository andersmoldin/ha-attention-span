"""Tidsvillkor och nivåer överlever en omstart av Home Assistant."""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.attention_span.const import DOMAIN

from .conftest import FIXTURE_TIME, add_integration, add_rule, reconfigure_rule, restart

FINDUS = {"name": "Findus", "icon": "mdi:robot-vacuum", "entity": "vacuum.findus"}
OFFLINE = {"condition": "state", "entity_id": "vacuum.findus", "state": "unavailable"}
OFFLINE_2H = OFFLINE | {"for": {"hours": 2}}


async def tick(hass: HomeAssistant, freezer, delta: timedelta) -> None:
    """Låt tiden gå, så att tidsbaserade villkor räknas om."""
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def add_findus_rule(hass: HomeAssistant) -> None:
    """Findus: Problem när den är offline, Larm när den har varit offline i 2 h."""
    entry = await add_integration(hass)
    await add_rule(
        hass,
        entry,
        "status",
        FINDUS,
        levels={"problem": "condition", "alarm": "condition"},
        conditions={"problem": [OFFLINE], "alarm": [OFFLINE_2H]},
    )


async def start(hass: HomeAssistant) -> None:
    """Starta den omstartade instansen, med AttentionSpan och källentiteterna laddade."""
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    await hass.async_start()
    await hass.async_block_till_done()


async def test_an_alarm_is_still_an_alarm_with_the_same_since_after_a_restart(
    hass: HomeAssistant, freezer
):
    freezer.move_to(FIXTURE_TIME)
    hass.states.async_set("vacuum.findus", "unavailable")
    await add_findus_rule(hass)
    await tick(hass, freezer, timedelta(hours=2, seconds=1))
    assert hass.states.get("sensor.attention_span_findus").state == "alarm"
    freezer.move_to("2026-10-26T11:00:00+00:00")

    async with restart(hass) as hass:
        # Källentiteten får ett nytt last_changed när dess integration laddas.
        hass.states.async_set("vacuum.findus", "unavailable")
        await start(hass)

        state = hass.states.get("sensor.attention_span_findus")
        assert state.state == "alarm"
        assert state.attributes["since"] == "2026-10-26T10:00:01+00:00"


async def test_an_escalation_from_problem_to_alarm_is_still_an_alarm_after_a_restart(
    hass: HomeAssistant, freezer
):
    """Problem efter 30 min och Larm efter 2 h; Findus har varit offline sedan länge."""
    freezer.move_to("2026-10-26T05:00:00+00:00")
    hass.states.async_set("vacuum.findus", "unavailable")
    freezer.move_to(FIXTURE_TIME)
    entry = await add_integration(hass)
    await add_rule(
        hass,
        entry,
        "status",
        FINDUS,
        levels={"problem": "condition", "alarm": "condition"},
        conditions={"problem": [OFFLINE | {"for": {"minutes": 30}}], "alarm": [OFFLINE_2H]},
    )
    assert hass.states.get("sensor.attention_span_findus").state == "alarm"
    freezer.move_to("2026-10-26T09:00:00+00:00")

    async with restart(hass) as hass:
        hass.states.async_set("vacuum.findus", "unavailable")
        await start(hass)

        state = hass.states.get("sensor.attention_span_findus")
        assert state.state == "alarm"
        assert state.attributes["since"] == FIXTURE_TIME


async def test_a_condition_that_stopped_holding_during_the_restart_has_let_go(
    hass: HomeAssistant, freezer
):
    freezer.move_to(FIXTURE_TIME)
    hass.states.async_set("vacuum.findus", "unavailable")
    await add_findus_rule(hass)
    await tick(hass, freezer, timedelta(hours=2, seconds=1))
    assert hass.states.get("sensor.attention_span_findus").state == "alarm"
    freezer.move_to("2026-10-26T11:00:00+00:00")

    async with restart(hass) as hass:
        hass.states.async_set("vacuum.findus", "docked")
        await start(hass)

        state = hass.states.get("sensor.attention_span_findus")
        assert state.state == "hidden"
        assert state.attributes["since"] == "2026-10-26T11:00:00+00:00"

        # Offline igen: tiden räknas från nu, inte från förra gången.
        hass.states.async_set("vacuum.findus", "unavailable")
        await hass.async_block_till_done()
        await tick(hass, freezer, timedelta(hours=2))
        assert hass.states.get("sensor.attention_span_findus").state == "problem"
        await tick(hass, freezer, timedelta(seconds=1))
        state = hass.states.get("sensor.attention_span_findus")
        assert state.state == "alarm"
        assert state.attributes["since"] == "2026-10-26T13:00:01+00:00"


async def test_a_timed_condition_counts_the_time_before_the_restart(hass: HomeAssistant, freezer):
    """Offline i 1,5 h före omstarten: Larm en halvtimme efter den, inte två timmar efter."""
    freezer.move_to(FIXTURE_TIME)
    hass.states.async_set("vacuum.findus", "unavailable")
    await add_findus_rule(hass)
    await tick(hass, freezer, timedelta(hours=1, minutes=30))
    assert hass.states.get("sensor.attention_span_findus").state == "problem"

    async with restart(hass) as hass:
        hass.states.async_set("vacuum.findus", "unavailable")
        await start(hass)
        assert hass.states.get("sensor.attention_span_findus").state == "problem"

        await tick(hass, freezer, timedelta(minutes=30, seconds=1))

        state = hass.states.get("sensor.attention_span_findus")
        assert state.state == "alarm"
        assert state.attributes["since"] == "2026-10-26T10:00:01+00:00"


YTTERDORREN = {"name": "Ytterdörren", "icon": "mdi:door", "entity": "binary_sensor.ytterdorr"}
DOOR_OPEN = {"condition": "state", "entity_id": "binary_sensor.ytterdorr", "state": "on"}


async def test_status_shows_how_long_the_state_has_held_across_a_restart(
    hass: HomeAssistant, freezer
):
    freezer.move_to("2026-10-26T07:50:00+00:00")
    hass.states.async_set("binary_sensor.ytterdorr", "on")
    freezer.move_to(FIXTURE_TIME)
    entry = await add_integration(hass)
    await add_rule(
        hass, entry, "status", YTTERDORREN, {"ongoing": "condition"}, {"ongoing": [DOOR_OPEN]}
    )
    state = hass.states.get("sensor.attention_span_ytterdorren")
    assert state.attributes["state_since"] == "2026-10-26T07:50:00+00:00"
    freezer.move_to("2026-10-26T09:00:00+00:00")

    async with restart(hass) as hass:
        hass.states.async_set("binary_sensor.ytterdorr", "on")
        await start(hass)

        state = hass.states.get("sensor.attention_span_ytterdorren")
        assert state.attributes["state_since"] == "2026-10-26T07:50:00+00:00"

        freezer.move_to("2026-10-26T09:10:00+00:00")
        hass.states.async_set("binary_sensor.ytterdorr", "off")
        await hass.async_block_till_done()
        state = hass.states.get("sensor.attention_span_ytterdorren")
        assert state.attributes["state_since"] == "2026-10-26T09:10:00+00:00"


async def test_status_counts_from_the_restart_when_the_state_changed_during_it(
    hass: HomeAssistant, freezer
):
    freezer.move_to(FIXTURE_TIME)
    hass.states.async_set("binary_sensor.ytterdorr", "on")
    entry = await add_integration(hass)
    await add_rule(hass, entry, "status", YTTERDORREN, {"glance": "always"})
    freezer.move_to("2026-10-26T09:00:00+00:00")

    async with restart(hass) as hass:
        hass.states.async_set("binary_sensor.ytterdorr", "off")
        await start(hass)

        state = hass.states.get("sensor.attention_span_ytterdorren")
        assert state.attributes["state_since"] == "2026-10-26T09:00:00+00:00"


async def test_timed_conditions_inside_other_conditions_survive_a_restart(
    hass: HomeAssistant, freezer
):
    """Tid i ett villkor inom Eller, och i ett villkor som en integration erbjuder."""
    freezer.move_to(FIXTURE_TIME)
    hass.states.async_set("binary_sensor.ytterdorr", "on")
    hass.states.async_set("light.hallen", "on")
    assert await async_setup_component(hass, "light", {})
    entry = await add_integration(hass)
    light_on_10_min = {
        "condition": "light.is_on",
        "target": {"entity_id": "light.hallen"},
        "options": {"behavior": "any", "for": {"minutes": 10}},
    }
    door_or_light = {
        "condition": "or",
        "enabled": True,
        "conditions": [DOOR_OPEN | {"for": {"minutes": 10}}, light_on_10_min],
    }
    await add_rule(
        hass,
        entry,
        "status",
        YTTERDORREN,
        {"problem": "condition", "ongoing": "condition"},
        {"problem": [door_or_light], "ongoing": [DOOR_OPEN]},
    )
    await tick(hass, freezer, timedelta(minutes=10, seconds=1))
    assert hass.states.get("sensor.attention_span_ytterdorren").state == "problem"

    async with restart(hass) as hass:
        hass.states.async_set("binary_sensor.ytterdorr", "on")
        hass.states.async_set("light.hallen", "on")
        assert await async_setup_component(hass, "light", {})
        await start(hass)
        assert hass.states.get("sensor.attention_span_ytterdorren").state == "problem"

        # Lampan har varit tänd i mer än 10 min, också när dörren inte längre är öppen.
        hass.states.async_set("binary_sensor.ytterdorr", "off")
        await hass.async_block_till_done()
        assert hass.states.get("sensor.attention_span_ytterdorren").state == "problem"

        hass.states.async_set("light.hallen", "off")
        await hass.async_block_till_done()
        assert hass.states.get("sensor.attention_span_ytterdorren").state == "hidden"


async def test_status_follows_the_entity_the_rule_shows_now(hass: HomeAssistant, freezer):
    freezer.move_to("2026-10-26T07:00:00+00:00")
    hass.states.async_set("binary_sensor.ytterdorr", "on")
    freezer.move_to(FIXTURE_TIME)
    hass.states.async_set("binary_sensor.altandorr", "on")
    entry = await add_integration(hass)
    rule = await add_rule(hass, entry, "status", YTTERDORREN, {"glance": "always"})

    await reconfigure_rule(
        hass, entry, rule, YTTERDORREN | {"entity": "binary_sensor.altandorr"}, {"glance": "always"}
    )

    state = hass.states.get("sensor.attention_span_ytterdorren")
    assert state.attributes["state_since"] == FIXTURE_TIME


async def test_an_entity_waiting_for_its_integration_after_a_restart_keeps_its_times(
    hass: HomeAssistant, freezer
):
    """HA visar entiteten som otillgänglig (restored) tills dess integration har laddats."""
    freezer.move_to("2026-10-26T07:50:00+00:00")
    hass.states.async_set("binary_sensor.ytterdorr", "on")
    freezer.move_to(FIXTURE_TIME)
    entry = await add_integration(hass)
    await add_rule(
        hass,
        entry,
        "status",
        YTTERDORREN,
        {"alarm": "condition", "ongoing": "condition"},
        {"alarm": [DOOR_OPEN | {"for": {"minutes": 30}}], "ongoing": [DOOR_OPEN]},
    )
    await tick(hass, freezer, timedelta(minutes=20, seconds=1))
    state = hass.states.get("sensor.attention_span_ytterdorren")
    assert state.state == "alarm"
    assert state.attributes["since"] == "2026-10-26T08:20:01+00:00"
    freezer.move_to("2026-10-26T09:00:00+00:00")

    async with restart(hass) as hass:
        hass.states.async_set("binary_sensor.ytterdorr", "unavailable", {"restored": True})
        await start(hass)
        await tick(hass, freezer, timedelta(seconds=5))

        state = hass.states.get("sensor.attention_span_ytterdorren")
        assert state.state == "alarm"
        assert state.attributes["since"] == "2026-10-26T08:20:01+00:00"
        # Det återställda tillståndet är inte det som gällde före omstarten.
        assert state.attributes["state_since"] is None

        hass.states.async_set("binary_sensor.ytterdorr", "on")
        await hass.async_block_till_done()

        state = hass.states.get("sensor.attention_span_ytterdorren")
        assert state.state == "alarm"
        assert state.attributes["since"] == "2026-10-26T08:20:01+00:00"
        assert state.attributes["state_since"] == "2026-10-26T07:50:00+00:00"


async def test_status_keeps_its_time_while_the_entity_waits_with_the_same_state(
    hass: HomeAssistant, freezer
):
    """Findus är fortfarande offline efter omstarten, och dess integration går inte att ladda."""
    freezer.move_to(FIXTURE_TIME)
    hass.states.async_set("vacuum.findus", "unavailable")
    await add_findus_rule(hass)
    await tick(hass, freezer, timedelta(hours=2, seconds=1))
    assert hass.states.get("sensor.attention_span_findus").state == "alarm"
    freezer.move_to("2026-10-26T11:00:00+00:00")

    async with restart(hass) as hass:
        hass.states.async_set("vacuum.findus", "unavailable", {"restored": True})
        await start(hass)

        state = hass.states.get("sensor.attention_span_findus")
        assert state.state == "alarm"
        assert state.attributes["since"] == "2026-10-26T10:00:01+00:00"
        assert state.attributes["state_since"] == FIXTURE_TIME


async def add_lamp_in_hallen(hass: HomeAssistant) -> tuple[str, str]:
    """Lampan i hallen och dess område, som HA läser in ur sina register vid start."""
    area = ar.async_get(hass).async_get_or_create("Hallen")
    entities = er.async_get(hass)
    lamp = entities.async_get_or_create("light", "test", "hallen", suggested_object_id="hallen")
    entities.async_update_entity(lamp.entity_id, area_id=area.id)
    assert await async_setup_component(hass, "light", {})
    return lamp.entity_id, area.id


async def test_a_timed_condition_on_an_area_keeps_its_time_while_the_entity_waits(
    hass: HomeAssistant, freezer
):
    """Villkoret pekar ut lampan genom dess område, inte genom entity_id."""
    freezer.move_to(FIXTURE_TIME)
    lamp, area = await add_lamp_in_hallen(hass)
    hass.states.async_set(lamp, "on")
    entry = await add_integration(hass)
    await add_rule(
        hass,
        entry,
        "status",
        YTTERDORREN | {"entity": lamp},
        {"alarm": "condition"},
        {
            "alarm": [
                {
                    "condition": "light.is_on",
                    "target": {"area_id": area},
                    "options": {"behavior": "any", "for": {"minutes": 10}},
                }
            ]
        },
    )
    await tick(hass, freezer, timedelta(minutes=10, seconds=1))
    assert hass.states.get("sensor.attention_span_ytterdorren").state == "alarm"
    freezer.move_to("2026-10-26T09:00:00+00:00")

    async with restart(hass) as hass:
        await add_lamp_in_hallen(hass)
        hass.states.async_set(lamp, "unavailable", {"restored": True})
        await start(hass)
        await tick(hass, freezer, timedelta(seconds=5))

        state = hass.states.get("sensor.attention_span_ytterdorren")
        assert state.state == "alarm"
        assert state.attributes["since"] == "2026-10-26T08:10:01+00:00"

        hass.states.async_set(lamp, "on")
        await hass.async_block_till_done()

        state = hass.states.get("sensor.attention_span_ytterdorren")
        assert state.state == "alarm"
        assert state.attributes["since"] == "2026-10-26T08:10:01+00:00"

"""Kvittera: ett Larm som hushållet känner till ligger kvar i kompakt form."""

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.attention_span.const import DOMAIN

from .conftest import (
    FIXTURE_TIME,
    add_integration,
    add_rule,
    contract_example,
    restart,
    state_as_contract,
    watch,
)

LACKAN = {"name": "Läckan", "icon": "mdi:water-alert", "entity": "binary_sensor.lacka"}
WET = {"condition": "state", "entity_id": "binary_sensor.lacka", "state": "on"}
DAMP = {"condition": "state", "entity_id": "binary_sensor.lacka", "state": "damp"}


async def tick(hass: HomeAssistant, freezer, delta: timedelta) -> None:
    """Låt tiden gå."""
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def add_leak_rule(hass: HomeAssistant, **kwargs) -> str:
    """Läckan: Larm när givaren är blöt, Pågår när den är fuktig."""
    entry = await add_integration(hass)
    return await add_rule(
        hass,
        entry,
        "status",
        LACKAN,
        levels={"alarm": "condition", "ongoing": "condition"},
        conditions={"alarm": [WET], "ongoing": [DAMP]},
        **kwargs,
    )


async def acknowledge(hass: HomeAssistant, entity_id: str = "sensor.attention_span_lackan"):
    await hass.services.async_call(DOMAIN, "acknowledge", {"entity_id": entity_id}, blocking=True)


async def test_acknowledging_an_alarm_marks_it_acknowledged_until_it_alarms_again(
    hass: HomeAssistant, freezer
):
    freezer.move_to(FIXTURE_TIME)
    hass.states.async_set("binary_sensor.lacka", "on")
    await add_leak_rule(hass)
    state = hass.states.get("sensor.attention_span_lackan")
    assert state.state == "alarm"
    assert state.attributes["acknowledged"] is False
    assert state.attributes["realarm_at"] is None

    await acknowledge(hass)

    state = hass.states.get("sensor.attention_span_lackan")
    assert state.state == "alarm"
    assert state.attributes["acknowledged"] is True
    assert state.attributes["realarm_at"] == "2026-10-27T08:00:00+00:00"


async def test_acknowledging_anything_but_an_alarm_is_an_error(hass: HomeAssistant):
    hass.states.async_set("binary_sensor.lacka", "damp")
    await add_leak_rule(hass)
    assert hass.states.get("sensor.attention_span_lackan").state == "ongoing"

    with pytest.raises(ServiceValidationError) as error:
        await acknowledge(hass)

    # HA:s gränssnitt visar felet på användarens språk; loggen har det på engelska.
    assert error.value.translation_key == "not_alarm"
    assert str(error.value) == (
        "sensor.attention_span_lackan is not an Alarm. Only Alarms can be acknowledged"
    )
    state = hass.states.get("sensor.attention_span_lackan")
    assert state.attributes["acknowledged"] is False
    assert state.attributes["realarm_at"] is None


async def test_an_acknowledged_alarm_that_lasts_alarms_again_when_realarm_at_has_passed(
    hass: HomeAssistant, freezer
):
    freezer.move_to(FIXTURE_TIME)
    hass.states.async_set("binary_sensor.lacka", "on")
    await add_leak_rule(hass)
    await acknowledge(hass)

    await tick(hass, freezer, timedelta(hours=23, minutes=59))
    assert hass.states.get("sensor.attention_span_lackan").attributes["acknowledged"] is True

    await tick(hass, freezer, timedelta(minutes=1))

    state = hass.states.get("sensor.attention_span_lackan")
    assert state.state == "alarm"
    assert state.attributes["acknowledged"] is False
    assert state.attributes["realarm_at"] is None
    # Larmet har gällt hela tiden; det är bara kvitteringen som har gått ut.
    assert state.attributes["since"] == FIXTURE_TIME


async def set_leak(hass: HomeAssistant, state: str) -> None:
    hass.states.async_set("binary_sensor.lacka", state)
    await hass.async_block_till_done()


async def test_a_short_break_in_the_alarm_keeps_the_acknowledgement(hass: HomeAssistant, freezer):
    freezer.move_to(FIXTURE_TIME)
    await set_leak(hass, "on")
    await add_leak_rule(hass)
    await acknowledge(hass)

    await set_leak(hass, "off")
    assert hass.states.get("sensor.attention_span_lackan").state == "hidden"
    await tick(hass, freezer, timedelta(minutes=4, seconds=59))
    await set_leak(hass, "on")

    state = hass.states.get("sensor.attention_span_lackan")
    assert state.state == "alarm"
    assert state.attributes["acknowledged"] is True
    assert state.attributes["realarm_at"] == "2026-10-27T08:00:00+00:00"


async def test_the_acknowledgement_lets_go_when_the_alarm_has_been_gone_longer_than_the_flap_limit(
    hass: HomeAssistant, freezer
):
    freezer.move_to(FIXTURE_TIME)
    await set_leak(hass, "on")
    await add_leak_rule(hass)
    await acknowledge(hass)

    # Läckan har slutat men det är fortfarande fuktigt: Pågår, under Larm.
    await set_leak(hass, "damp")
    state = hass.states.get("sensor.attention_span_lackan")
    assert state.state == "ongoing"
    assert state.attributes["acknowledged"] is False
    await tick(hass, freezer, timedelta(minutes=5))
    await set_leak(hass, "on")

    state = hass.states.get("sensor.attention_span_lackan")
    assert state.state == "alarm"
    assert state.attributes["acknowledged"] is False
    assert state.attributes["realarm_at"] is None


async def test_breaks_shorter_than_the_flap_limit_do_not_add_up(hass: HomeAssistant, freezer):
    freezer.move_to(FIXTURE_TIME)
    await set_leak(hass, "on")
    await add_leak_rule(hass)
    await acknowledge(hass)

    for _ in range(3):
        await set_leak(hass, "off")
        await tick(hass, freezer, timedelta(minutes=3))
        await set_leak(hass, "on")
        await tick(hass, freezer, timedelta(minutes=1))

    assert hass.states.get("sensor.attention_span_lackan").attributes["acknowledged"] is True


async def test_acknowledging_does_not_reload_the_rules_or_make_them_unavailable(
    hass: HomeAssistant,
):
    await set_leak(hass, "on")
    await add_leak_rule(hass)
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    gone, unloads = watch(hass, entry)

    await acknowledge(hass)

    assert gone == []
    assert unloads == []


async def test_the_acknowledgement_is_still_there_after_the_integration_is_reloaded(
    hass: HomeAssistant, freezer
):
    freezer.move_to(FIXTURE_TIME)
    await set_leak(hass, "on")
    await add_leak_rule(hass)
    await acknowledge(hass)
    (entry,) = hass.config_entries.async_entries(DOMAIN)

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.attention_span_lackan")
    assert state.state == "alarm"
    assert state.attributes["acknowledged"] is True
    assert state.attributes["realarm_at"] == "2026-10-27T08:00:00+00:00"

    # Och det larmar igen när tiden har gått, också efter omladdningen.
    await tick(hass, freezer, timedelta(hours=24))
    assert hass.states.get("sensor.attention_span_lackan").attributes["acknowledged"] is False


async def start(hass: HomeAssistant) -> None:
    """Starta den omstartade instansen, med AttentionSpan laddat."""
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    await hass.async_start()
    await hass.async_block_till_done()


async def test_the_acknowledgement_survives_a_restart(hass: HomeAssistant, freezer):
    freezer.move_to(FIXTURE_TIME)
    await set_leak(hass, "on")
    await add_leak_rule(hass)
    await acknowledge(hass)
    freezer.move_to("2026-10-26T09:00:00+00:00")

    async with restart(hass) as hass:
        hass.states.async_set("binary_sensor.lacka", "on")
        await start(hass)

        state = hass.states.get("sensor.attention_span_lackan")
        assert state.state == "alarm"
        assert state.attributes["acknowledged"] is True
        assert state.attributes["realarm_at"] == "2026-10-27T08:00:00+00:00"


async def test_a_break_that_started_before_a_restart_counts_toward_the_flap_limit(
    hass: HomeAssistant, freezer
):
    freezer.move_to(FIXTURE_TIME)
    await set_leak(hass, "on")
    await add_leak_rule(hass)
    await acknowledge(hass)
    await set_leak(hass, "off")
    await tick(hass, freezer, timedelta(minutes=3))

    async with restart(hass) as hass:
        hass.states.async_set("binary_sensor.lacka", "off")
        await start(hass)
        await tick(hass, freezer, timedelta(minutes=2, seconds=1))
        hass.states.async_set("binary_sensor.lacka", "on")
        await hass.async_block_till_done()

        state = hass.states.get("sensor.attention_span_lackan")
        assert state.state == "alarm"
        assert state.attributes["acknowledged"] is False


async def test_a_break_longer_than_the_flap_limit_across_a_restart_lets_go_when_the_alarm_is_back(
    hass: HomeAssistant, freezer
):
    freezer.move_to(FIXTURE_TIME)
    await set_leak(hass, "on")
    await add_leak_rule(hass)
    await acknowledge(hass)
    await set_leak(hass, "off")
    await tick(hass, freezer, timedelta(minutes=3))

    async with restart(hass) as hass:
        freezer.tick(timedelta(minutes=7))
        hass.states.async_set("binary_sensor.lacka", "on")
        await start(hass)

        state = hass.states.get("sensor.attention_span_lackan")
        assert state.state == "alarm"
        assert state.attributes["acknowledged"] is False
        assert state.attributes["realarm_at"] is None


async def test_an_alarm_set_to_alarm_again_after_2_hours_does_so(hass: HomeAssistant, freezer):
    freezer.move_to(FIXTURE_TIME)
    await set_leak(hass, "on")
    await add_leak_rule(hass, timing={"realarm_after": {"hours": 2}, "flap_limit": {"minutes": 5}})

    await acknowledge(hass)
    assert (
        hass.states.get("sensor.attention_span_lackan").attributes["realarm_at"]
        == "2026-10-26T10:00:00+00:00"
    )

    await tick(hass, freezer, timedelta(hours=2))
    assert hass.states.get("sensor.attention_span_lackan").attributes["acknowledged"] is False


async def test_an_alarm_with_no_time_to_alarm_again_stays_acknowledged(
    hass: HomeAssistant, freezer
):
    freezer.move_to(FIXTURE_TIME)
    await set_leak(hass, "on")
    await add_leak_rule(hass, timing={"flap_limit": {"minutes": 5}})

    await acknowledge(hass)
    await tick(hass, freezer, timedelta(days=30))

    state = hass.states.get("sensor.attention_span_lackan")
    assert state.attributes["acknowledged"] is True
    assert state.attributes["realarm_at"] is None


async def test_the_flap_limit_is_set_per_rule(hass: HomeAssistant, freezer):
    freezer.move_to(FIXTURE_TIME)
    await set_leak(hass, "on")
    await add_leak_rule(hass, timing={"realarm_after": {"hours": 24}, "flap_limit": {"minutes": 1}})
    await acknowledge(hass)

    await set_leak(hass, "off")
    await tick(hass, freezer, timedelta(minutes=1))
    await set_leak(hass, "on")

    assert hass.states.get("sensor.attention_span_lackan").attributes["acknowledged"] is False


async def test_an_acknowledged_alarm_matches_the_shared_example(hass: HomeAssistant, freezer):
    freezer.move_to("2026-10-26T05:00:00+00:00")
    hass.states.async_set("vacuum.findus", "unavailable")
    freezer.move_to(FIXTURE_TIME)
    entry = await add_integration(hass)
    offline = {"condition": "state", "entity_id": "vacuum.findus", "state": "unavailable"}
    await add_rule(
        hass,
        entry,
        "status",
        {"name": "Findus", "icon": "mdi:robot-vacuum", "entity": "vacuum.findus"},
        levels={"alarm": "condition"},
        conditions={"alarm": [offline | {"for": {"hours": 2}}]},
    )

    await acknowledge(hass, "sensor.attention_span_findus")

    expected = contract_example("status_alarm_acknowledged")
    assert state_as_contract(hass, expected["entity_id"]) == expected

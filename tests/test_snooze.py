"""Lägga åt sidan: ett Problem eller en Pågår-notis flyttas undan för hela hushållet."""

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

DORREN = {"name": "Dörren", "icon": "mdi:door-open", "entity": "binary_sensor.dorren"}
OPEN = {"condition": "state", "entity_id": "binary_sensor.dorren", "state": "on"}
AJAR = {"condition": "state", "entity_id": "binary_sensor.dorren", "state": "ajar"}
BROKEN = {"condition": "state", "entity_id": "binary_sensor.dorren", "state": "broken"}
ENTITY = "sensor.attention_span_dorren"


async def tick(hass: HomeAssistant, freezer, delta: timedelta) -> None:
    """Låt tiden gå."""
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def set_door(hass: HomeAssistant, state: str) -> None:
    hass.states.async_set("binary_sensor.dorren", state)
    await hass.async_block_till_done()


async def add_door_rule(hass: HomeAssistant, **kwargs) -> str:
    """Dörren: Larm när låset är trasigt, Problem när den står öppen, Pågår när den står på
    glänt."""
    entry = await add_integration(hass)
    return await add_rule(
        hass,
        entry,
        "status",
        DORREN,
        levels={"alarm": "condition", "problem": "condition", "ongoing": "condition"},
        conditions={"alarm": [BROKEN], "problem": [OPEN], "ongoing": [AJAR]},
        **kwargs,
    )


async def snooze(hass: HomeAssistant, until: str | None = None, entity_id: str = ENTITY) -> None:
    data = {"entity_id": entity_id}
    if until is not None:
        data["until"] = until
    await hass.services.async_call(DOMAIN, "snooze", data, blocking=True)


async def test_snoozing_until_a_time_marks_the_notice_snoozed_until_then(
    hass: HomeAssistant, freezer
):
    freezer.move_to(FIXTURE_TIME)
    await set_door(hass, "on")
    await add_door_rule(hass)
    state = hass.states.get(ENTITY)
    assert state.state == "problem"
    assert state.attributes["snoozed"] is False
    assert state.attributes["snoozed_until"] is None

    await snooze(hass, "2026-10-26T19:00:00+00:00")

    state = hass.states.get(ENTITY)
    assert state.state == "problem"
    assert state.attributes["snoozed"] is True
    assert state.attributes["snoozed_until"] == "2026-10-26T19:00:00+00:00"


async def test_snoozing_without_a_time_snoozes_until_it_is_fixed(hass: HomeAssistant, freezer):
    freezer.move_to(FIXTURE_TIME)
    await set_door(hass, "ajar")
    await add_door_rule(hass)

    await snooze(hass)

    state = hass.states.get(ENTITY)
    assert state.state == "ongoing"
    assert state.attributes["snoozed"] is True
    assert state.attributes["snoozed_until"] is None

    # «Tills det är lagat» har ingen sluttid.
    await tick(hass, freezer, timedelta(days=30))
    assert hass.states.get(ENTITY).attributes["snoozed"] is True


@pytest.mark.parametrize(
    ("door", "levels", "level"),
    [
        ("broken", {"alarm": "condition"}, "alarm"),
        ("on", {"glance": "always"}, "glance"),
        ("on", {"quiet": "always"}, "quiet"),
        ("off", {"problem": "condition"}, "hidden"),
    ],
)
async def test_only_problems_and_ongoing_notices_can_be_snoozed(
    hass: HomeAssistant, door: str, levels: dict[str, str], level: str
):
    await set_door(hass, door)
    entry = await add_integration(hass)
    conditions = {"alarm": [BROKEN], "problem": [OPEN]}
    await add_rule(
        hass,
        entry,
        "status",
        DORREN,
        levels=levels,
        conditions={key: value for key, value in conditions.items() if key in levels},
    )
    assert hass.states.get(ENTITY).state == level

    with pytest.raises(ServiceValidationError) as error:
        await snooze(hass, "2026-10-26T19:00:00+00:00")

    # HA:s gränssnitt visar felet på användarens språk; loggen har det på engelska.
    assert error.value.translation_key == "not_snoozable"
    assert str(error.value) == (
        "sensor.attention_span_dorren is not a Problem or Ongoing. "
        "Only Problems and Ongoing notices can be snoozed"
    )
    state = hass.states.get(ENTITY)
    assert state.attributes["snoozed"] is False
    assert state.attributes["snoozed_until"] is None


async def test_a_snoozed_notice_comes_back_when_the_time_has_passed(hass: HomeAssistant, freezer):
    freezer.move_to(FIXTURE_TIME)
    await set_door(hass, "on")
    await add_door_rule(hass)
    await snooze(hass, "2026-10-26T09:00:00+00:00")

    await tick(hass, freezer, timedelta(minutes=59))
    assert hass.states.get(ENTITY).attributes["snoozed"] is True

    await tick(hass, freezer, timedelta(minutes=1))

    state = hass.states.get(ENTITY)
    assert state.state == "problem"
    assert state.attributes["snoozed"] is False
    assert state.attributes["snoozed_until"] is None
    # Problemet har gällt hela tiden; det är bara åt sidan som har gått ut.
    assert state.attributes["since"] == FIXTURE_TIME


async def test_a_snoozed_notice_comes_back_at_a_new_occurrence(hass: HomeAssistant, freezer):
    freezer.move_to(FIXTURE_TIME)
    await set_door(hass, "on")
    await add_door_rule(hass)
    await snooze(hass)

    # Dörren stängs, och står sedan öppen igen efter fladdergränsen.
    await set_door(hass, "off")
    await tick(hass, freezer, timedelta(minutes=5))
    await set_door(hass, "on")

    state = hass.states.get(ENTITY)
    assert state.state == "problem"
    assert state.attributes["snoozed"] is False
    assert state.attributes["snoozed_until"] is None


async def test_a_break_shorter_than_the_flap_limit_is_no_new_occurrence(
    hass: HomeAssistant, freezer
):
    freezer.move_to(FIXTURE_TIME)
    await set_door(hass, "on")
    await add_door_rule(hass)
    await snooze(hass, "2026-10-26T19:00:00+00:00")

    for _ in range(3):
        await set_door(hass, "off")
        await tick(hass, freezer, timedelta(minutes=4, seconds=59))
        await set_door(hass, "on")
        await tick(hass, freezer, timedelta(minutes=1))

    state = hass.states.get(ENTITY)
    assert state.attributes["snoozed"] is True
    assert state.attributes["snoozed_until"] == "2026-10-26T19:00:00+00:00"


async def test_a_less_severe_level_is_below_the_snoozed_level_and_stays_snoozed_for_a_short_while(
    hass: HomeAssistant, freezer
):
    freezer.move_to(FIXTURE_TIME)
    await set_door(hass, "on")
    await add_door_rule(hass)
    await snooze(hass)

    # På glänt är Pågår, under Problemet som lades åt sidan.
    await set_door(hass, "ajar")
    assert hass.states.get(ENTITY).attributes["snoozed"] is True
    await tick(hass, freezer, timedelta(minutes=5))

    state = hass.states.get(ENTITY)
    assert state.state == "ongoing"
    assert state.attributes["snoozed"] is False


@pytest.mark.parametrize(("snoozed", "worse"), [("ajar", "on"), ("on", "broken")])
async def test_a_snoozed_notice_comes_back_at_once_when_its_level_gets_more_severe(
    hass: HomeAssistant, freezer, snoozed: str, worse: str
):
    freezer.move_to(FIXTURE_TIME)
    await set_door(hass, snoozed)
    await add_door_rule(hass)
    await snooze(hass, "2026-10-26T19:00:00+00:00")

    await set_door(hass, worse)

    state = hass.states.get(ENTITY)
    assert state.attributes["snoozed"] is False
    assert state.attributes["snoozed_until"] is None
    # Och den ligger inte åt sidan när nivån går tillbaka.
    await set_door(hass, snoozed)
    assert hass.states.get(ENTITY).attributes["snoozed"] is False


async def unsnooze(hass: HomeAssistant, entity_id: str = ENTITY) -> None:
    await hass.services.async_call(DOMAIN, "unsnooze", {"entity_id": entity_id}, blocking=True)


async def test_unsnoozing_brings_the_notice_back_at_once(hass: HomeAssistant, freezer):
    freezer.move_to(FIXTURE_TIME)
    await set_door(hass, "on")
    await add_door_rule(hass)
    await snooze(hass, "2026-10-26T19:00:00+00:00")

    await unsnooze(hass)

    state = hass.states.get(ENTITY)
    assert state.state == "problem"
    assert state.attributes["snoozed"] is False
    assert state.attributes["snoozed_until"] is None


async def test_unsnoozing_a_notice_that_is_not_snoozed_changes_nothing(hass: HomeAssistant):
    await set_door(hass, "on")
    await add_door_rule(hass)
    before = hass.states.get(ENTITY)

    await unsnooze(hass)

    assert hass.states.get(ENTITY) == before


async def test_snoozing_until_a_time_that_has_passed_is_an_error(hass: HomeAssistant, freezer):
    freezer.move_to(FIXTURE_TIME)
    await set_door(hass, "on")
    await add_door_rule(hass)

    with pytest.raises(ServiceValidationError) as error:
        await snooze(hass, "2026-10-26T08:00:00+00:00")

    assert error.value.translation_key == "until_passed"
    assert str(error.value) == (
        "2026-10-26T08:00:00+00:00 has already passed. "
        "Choose a later time to snooze sensor.attention_span_dorren until"
    )
    assert hass.states.get(ENTITY).attributes["snoozed"] is False


async def test_a_time_without_a_time_zone_is_in_the_homes_time_zone(hass: HomeAssistant, freezer):
    await hass.config.async_set_time_zone("Europe/Stockholm")
    freezer.move_to(FIXTURE_TIME)
    await set_door(hass, "on")
    await add_door_rule(hass)

    # Som HA:s datumväljare skickar tiden: utan tidszon.
    await snooze(hass, "2026-10-26 21:00:00")

    assert hass.states.get(ENTITY).attributes["snoozed_until"] == "2026-10-26T20:00:00+00:00"


async def test_snoozing_and_unsnoozing_do_not_reload_the_rules_or_make_them_unavailable(
    hass: HomeAssistant,
):
    await set_door(hass, "on")
    await add_door_rule(hass)
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    gone, unloads = watch(hass, entry)

    await snooze(hass)
    await unsnooze(hass)

    assert gone == []
    assert unloads == []


async def test_a_snoozed_notice_is_still_snoozed_after_the_integration_is_reloaded(
    hass: HomeAssistant, freezer
):
    freezer.move_to(FIXTURE_TIME)
    await set_door(hass, "on")
    await add_door_rule(hass)
    await snooze(hass, "2026-10-26T19:00:00+00:00")
    (entry,) = hass.config_entries.async_entries(DOMAIN)

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY)
    assert state.state == "problem"
    assert state.attributes["snoozed"] is True
    assert state.attributes["snoozed_until"] == "2026-10-26T19:00:00+00:00"

    # Och den kommer tillbaka när tiden har gått, också efter omladdningen.
    await tick(hass, freezer, timedelta(hours=11))
    assert hass.states.get(ENTITY).attributes["snoozed"] is False


async def start(hass: HomeAssistant) -> None:
    """Starta den omstartade instansen, med AttentionSpan laddat."""
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    await hass.async_start()
    await hass.async_block_till_done()


async def test_a_snoozed_notice_survives_a_restart(hass: HomeAssistant, freezer):
    freezer.move_to(FIXTURE_TIME)
    await set_door(hass, "ajar")
    await add_door_rule(hass)
    await snooze(hass)
    freezer.move_to("2026-10-26T09:00:00+00:00")

    async with restart(hass) as hass:
        hass.states.async_set("binary_sensor.dorren", "ajar")
        await start(hass)

        state = hass.states.get(ENTITY)
        assert state.state == "ongoing"
        assert state.attributes["snoozed"] is True
        assert state.attributes["snoozed_until"] is None


async def test_a_snooze_that_ran_out_during_a_restart_is_over(hass: HomeAssistant, freezer):
    freezer.move_to(FIXTURE_TIME)
    await set_door(hass, "on")
    await add_door_rule(hass)
    await snooze(hass, "2026-10-26T09:00:00+00:00")

    async with restart(hass) as hass:
        freezer.move_to("2026-10-26T10:00:00+00:00")
        hass.states.async_set("binary_sensor.dorren", "on")
        await start(hass)

        state = hass.states.get(ENTITY)
        assert state.state == "problem"
        assert state.attributes["snoozed"] is False


async def test_a_break_longer_than_the_flap_limit_across_a_restart_is_a_new_occurrence(
    hass: HomeAssistant, freezer
):
    freezer.move_to(FIXTURE_TIME)
    await set_door(hass, "on")
    await add_door_rule(hass)
    await snooze(hass)
    await set_door(hass, "off")
    await tick(hass, freezer, timedelta(minutes=3))

    async with restart(hass) as hass:
        freezer.tick(timedelta(minutes=7))
        hass.states.async_set("binary_sensor.dorren", "on")
        await start(hass)

        state = hass.states.get(ENTITY)
        assert state.state == "problem"
        assert state.attributes["snoozed"] is False


async def test_a_snoozed_problem_matches_the_shared_example(hass: HomeAssistant, freezer):
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
        levels={"problem": "condition"},
        conditions={"problem": [offline]},
    )

    await snooze(hass, "2026-10-26T20:00:00+00:00", "sensor.attention_span_findus")

    expected = contract_example("status_problem_snoozed")
    assert state_as_contract(hass, expected["entity_id"]) == expected

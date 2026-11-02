"""När en regel räknas om: på händelser och timer, med kontroll varje sekund som reserv.

Villkor med tid («i 2 h»), klockslag och templates räknas om när något kan ha ändrat
utfallet: en entitet ändras, tiden går ut, en gräns eller midnatt passeras, tidszonen byter
offset, eller det som en template läser ändras. Andra villkor som beror på tiden, till
exempel solen, kontrolleras varje sekund som förut.
"""

from datetime import timedelta
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.attention_span.evaluation import RuleLevel

from .conftest import add_integration, add_rule, reconfigure_rule

FINDUS = {"name": "Findus", "icon": "mdi:robot-vacuum", "entity": "vacuum.findus"}
OFFLINE = {"condition": "state", "entity_id": "vacuum.findus", "state": "unavailable"}
OFFLINE_2H = OFFLINE | {"for": {"hours": 2}}


async def tick(hass: HomeAssistant, freezer, delta: timedelta) -> None:
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def level(hass: HomeAssistant) -> str:
    return hass.states.get("sensor.attention_span_findus").state


async def add(hass: HomeAssistant, entry, conditions: dict) -> str:
    return await add_rule(
        hass,
        entry,
        "status",
        FINDUS,
        levels=dict.fromkeys(conditions.keys() - {"hide"}, "condition"),
        conditions=conditions,
    )


async def count_checks(hass: HomeAssistant, freezer, seconds: int) -> int:
    """Hur många gånger regeln räknas om medan tiden går så många sekunder."""
    checks = 0
    evaluate = RuleLevel.evaluate

    def counted(self: RuleLevel) -> str:
        nonlocal checks
        checks += 1
        return evaluate(self)

    with patch.object(RuleLevel, "evaluate", counted):
        for _ in range(seconds):
            await tick(hass, freezer, timedelta(seconds=1))
    return checks


# Villkor med tid


async def test_a_timed_condition_changes_level_the_moment_its_time_has_passed(
    hass: HomeAssistant, freezer
):
    """Villkoret gäller när det har gällt längre än tiden, inte redan på gränsen."""
    freezer.move_to("2026-10-26T08:00:00+00:00")
    hass.states.async_set("vacuum.findus", "docked")
    entry = await add_integration(hass)
    await add(hass, entry, {"problem": [OFFLINE], "alarm": [OFFLINE_2H]})
    hass.states.async_set("vacuum.findus", "unavailable")
    await hass.async_block_till_done()
    await tick(hass, freezer, timedelta(hours=2))
    assert level(hass) == "problem"
    await tick(hass, freezer, timedelta(microseconds=1))
    assert level(hass) == "alarm"


async def test_a_timed_condition_is_not_checked_every_second_while_it_waits(
    hass: HomeAssistant, freezer
):
    freezer.move_to("2026-10-26T08:00:00+00:00")
    hass.states.async_set("vacuum.findus", "docked")
    entry = await add_integration(hass)
    await add(hass, entry, {"problem": [OFFLINE], "alarm": [OFFLINE_2H]})
    hass.states.async_set("vacuum.findus", "unavailable")
    await hass.async_block_till_done()
    assert await count_checks(hass, freezer, 10) == 0


async def test_a_rule_added_mid_run_alarms_when_ha_knows_the_time_has_passed(
    hass: HomeAssistant, freezer
):
    """Källan har varit offline 1 h när regeln läggs till; HA vet det (last_changed)."""
    freezer.move_to("2026-10-26T07:00:00+00:00")
    hass.states.async_set("vacuum.findus", "unavailable")
    freezer.move_to("2026-10-26T08:00:00+00:00")
    entry = await add_integration(hass)
    await add(hass, entry, {"problem": [OFFLINE], "alarm": [OFFLINE_2H]})
    assert level(hass) == "problem"
    await tick(hass, freezer, timedelta(minutes=59, seconds=59))
    assert level(hass) == "problem"
    await tick(hass, freezer, timedelta(seconds=2))
    assert level(hass) == "alarm"


async def test_a_shorter_time_after_a_change_of_the_rule_alarms_at_once(
    hass: HomeAssistant, freezer
):
    freezer.move_to("2026-10-26T08:00:00+00:00")
    hass.states.async_set("vacuum.findus", "unavailable")
    entry = await add_integration(hass)
    rule = await add(hass, entry, {"problem": [OFFLINE], "alarm": [OFFLINE_2H]})
    await tick(hass, freezer, timedelta(hours=1, minutes=30))
    assert level(hass) == "problem"
    await reconfigure_rule(
        hass,
        entry,
        rule,
        FINDUS,
        {"problem": "condition", "alarm": "condition"},
        {"problem": [OFFLINE], "alarm": [OFFLINE | {"for": {"hours": 1}}]},
    )
    await hass.async_block_till_done()
    assert level(hass) == "alarm"


async def test_a_longer_time_after_a_change_of_the_rule_alarms_later(
    hass: HomeAssistant, freezer
):
    freezer.move_to("2026-10-26T08:00:00+00:00")
    hass.states.async_set("vacuum.findus", "unavailable")
    entry = await add_integration(hass)
    rule = await add(
        hass, entry, {"problem": [OFFLINE], "alarm": [OFFLINE | {"for": {"hours": 1}}]}
    )
    await tick(hass, freezer, timedelta(minutes=30))
    await reconfigure_rule(
        hass,
        entry,
        rule,
        FINDUS,
        {"problem": "condition", "alarm": "condition"},
        {"problem": [OFFLINE], "alarm": [OFFLINE | {"for": {"hours": 3}}]},
    )
    await hass.async_block_till_done()
    await tick(hass, freezer, timedelta(minutes=31))
    assert level(hass) == "problem"
    await tick(hass, freezer, timedelta(hours=2))
    assert level(hass) == "alarm"


async def test_a_timed_condition_counts_real_time_over_the_night_summer_time_ends(
    hass: HomeAssistant, freezer
):
    await hass.config.async_update(time_zone="Europe/Stockholm")
    freezer.move_to("2026-10-25T00:00:00+00:00")  # 02:00 sommartid
    hass.states.async_set("vacuum.findus", "unavailable")
    entry = await add_integration(hass)
    await add(hass, entry, {"problem": [OFFLINE], "alarm": [OFFLINE_2H]})
    await tick(hass, freezer, timedelta(hours=1, minutes=59, seconds=59))  # 02:59:59 vintertid
    assert level(hass) == "problem"
    await tick(hass, freezer, timedelta(seconds=2))
    assert level(hass) == "alarm"


# Templates

DOOR = {"condition": "template", "value_template": "{{ is_state('binary_sensor.door', 'on') }}"}


async def test_a_template_follows_the_entity_it_reads_without_waiting(hass: HomeAssistant):
    hass.states.async_set("binary_sensor.door", "off")
    entry = await add_integration(hass)
    await add(hass, entry, {"problem": [DOOR]})
    assert level(hass) == "hidden"
    hass.states.async_set("binary_sensor.door", "on")
    await hass.async_block_till_done()
    assert level(hass) == "problem"


async def test_a_template_is_not_checked_every_second(hass: HomeAssistant, freezer):
    hass.states.async_set("binary_sensor.door", "off")
    entry = await add_integration(hass)
    await add(hass, entry, {"problem": [DOOR]})
    assert await count_checks(hass, freezer, 10) == 0


async def test_a_template_over_all_states_follows_within_a_second(hass: HomeAssistant, freezer):
    hass.states.async_set("sensor.x", "off")
    entry = await add_integration(hass)
    await add(
        hass,
        entry,
        {
            "problem": [
                {
                    "condition": "template",
                    "value_template": (
                        "{{ states | selectattr('state', 'eq', 'boom') | list | count > 0 }}"
                    ),
                }
            ]
        },
    )
    await tick(hass, freezer, timedelta(seconds=5))
    hass.states.async_set("sensor.x", "boom")
    await tick(hass, freezer, timedelta(seconds=1))
    assert level(hass) == "problem"


async def test_a_template_with_now_is_worked_out_again_every_whole_minute(
    hass: HomeAssistant, freezer
):
    """now() räknas om en gång i minuten, på sekund 0, som HA:s egna template-entiteter."""
    freezer.move_to("2026-10-26T08:00:05+00:00")
    entry = await add_integration(hass)
    await add(
        hass,
        entry,
        {
            "problem": [
                {
                    "condition": "template",
                    "value_template": "{{ now() >= as_datetime('2026-10-26T08:00:35+00:00') }}",
                }
            ]
        },
    )
    assert level(hass) == "hidden"
    await tick(hass, freezer, timedelta(seconds=31))  # 08:00:36
    assert level(hass) == "hidden"
    await tick(hass, freezer, timedelta(seconds=24))  # 08:01:00
    assert level(hass) == "problem"


# Klockslag


async def _time_rule(hass: HomeAssistant, after: str, before: str | None = None) -> None:
    await hass.config.async_update(time_zone="Europe/Stockholm")
    entry = await add_integration(hass)
    time = {"condition": "time", "after": after}
    if before:
        time["before"] = before
    await add(hass, entry, {"problem": [time]})


async def test_a_time_condition_changes_at_its_bounds(hass: HomeAssistant, freezer):
    freezer.move_to("2026-10-26T05:59:00+00:00")  # 06:59 i Stockholm
    await _time_rule(hass, "07:00:00", "22:00:00")
    assert level(hass) == "hidden"
    await tick(hass, freezer, timedelta(seconds=59))
    assert level(hass) == "hidden"
    await tick(hass, freezer, timedelta(seconds=1))
    assert level(hass) == "problem"
    await tick(hass, freezer, timedelta(hours=15))
    assert level(hass) == "hidden"


async def test_a_time_condition_is_not_checked_every_second(hass: HomeAssistant, freezer):
    freezer.move_to("2026-10-26T05:59:00+00:00")  # 06:59 i Stockholm
    await _time_rule(hass, "07:00:00", "22:00:00")
    assert await count_checks(hass, freezer, 10) == 0


async def test_a_time_condition_on_weekdays_changes_at_midnight(hass: HomeAssistant, freezer):
    await hass.config.async_update(time_zone="Europe/Stockholm")
    freezer.move_to("2026-10-26T22:59:00+00:00")  # måndag 23:59 i Stockholm
    entry = await add_integration(hass)
    await add(hass, entry, {"problem": [{"condition": "time", "weekday": ["tue"]}]})
    assert level(hass) == "hidden"
    await tick(hass, freezer, timedelta(minutes=1))  # tisdag 00:00
    assert level(hass) == "problem"


async def test_a_time_condition_on_the_night_summer_time_begins(hass: HomeAssistant, freezer):
    """02:30 finns inte 2027-03-28: klockan går från 02:00 till 03:00 (01:00 UTC)."""
    freezer.move_to("2027-03-28T00:59:00+00:00")  # 01:59 i Stockholm
    await _time_rule(hass, "02:30:00")
    assert level(hass) == "hidden"
    await tick(hass, freezer, timedelta(minutes=1))  # 03:00 sommartid
    assert level(hass) == "problem"


async def test_a_time_condition_on_the_night_summer_time_ends(hass: HomeAssistant, freezer):
    """2026-10-25 går klockan från 03:00 tillbaka till 02:00 (01:00 UTC), så 02:30 kommer två
    gånger och efter 02:30 slutar gälla en halvtimme däremellan."""
    freezer.move_to("2026-10-25T00:29:00+00:00")  # 02:29 sommartid
    await _time_rule(hass, "02:30:00")
    assert level(hass) == "hidden"
    await tick(hass, freezer, timedelta(minutes=1))  # 02:30 sommartid
    assert level(hass) == "problem"
    await tick(hass, freezer, timedelta(minutes=30))  # 02:00 vintertid
    assert level(hass) == "hidden"
    await tick(hass, freezer, timedelta(minutes=30))  # 02:30 vintertid
    assert level(hass) == "problem"


async def test_a_time_condition_follows_a_new_time_zone(hass: HomeAssistant, freezer):
    freezer.move_to("2026-10-26T06:30:00+00:00")  # 07:30 i Stockholm, 06:30 i London
    await _time_rule(hass, "07:00:00")
    assert level(hass) == "problem"
    await hass.config.async_update(time_zone="Europe/London")
    await hass.async_block_till_done()
    assert level(hass) == "hidden"
    await tick(hass, freezer, timedelta(minutes=30))  # 07:00 i London
    assert level(hass) == "problem"


# Reserven


async def test_a_condition_on_the_sun_is_still_checked_every_second(
    hass: HomeAssistant, freezer
):
    entry = await add_integration(hass)
    await add(hass, entry, {"problem": [{"condition": "sun", "after": "sunset"}]})
    assert await count_checks(hass, freezer, 10) == 10

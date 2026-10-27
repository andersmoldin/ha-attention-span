"""Orsaken: en färdig mall för typen eller en egen template, genom det riktiga flödet."""

from datetime import timedelta

import pytest
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.attention_span.const import DOMAIN

from .conftest import FIXTURE_TIME, add_integration, add_rule, restart

YTTERDORREN = {"name": "Ytterdörren", "icon": "mdi:door", "entity": "binary_sensor.ytterdorr"}
ALWAYS_ONGOING = {"ongoing": "always"}


@pytest.fixture
async def swedish(hass: HomeAssistant) -> None:
    """Ett hem på svenska, med HA:s egna översättningar av tillstånden laddade."""
    hass.config.language = "sv"
    assert await async_setup_component(hass, "binary_sensor", {})
    assert await async_setup_component(hass, "timer", {})


def reason(hass: HomeAssistant, entity_id: str) -> str | None:
    return hass.states.get(entity_id).attributes["reason"]


async def test_the_preset_for_status_shows_the_state_and_how_long_in_the_household_language(
    hass: HomeAssistant, freezer, swedish
):
    freezer.move_to(FIXTURE_TIME)
    hass.states.async_set("binary_sensor.ytterdorr", "on", {"device_class": "door"})
    entry = await add_integration(hass)
    freezer.tick(timedelta(minutes=10))

    await add_rule(
        hass, entry, "status", YTTERDORREN, ALWAYS_ONGOING, reason={"reason": "state_for"}
    )

    assert reason(hass, "sensor.attention_span_ytterdorren") == "Öppen i 10 min"


async def test_the_reason_follows_the_state_and_the_clock(hass: HomeAssistant, freezer, swedish):
    freezer.move_to(FIXTURE_TIME)
    hass.states.async_set("binary_sensor.ytterdorr", "on", {"device_class": "door"})
    entry = await add_integration(hass)
    await add_rule(
        hass, entry, "status", YTTERDORREN, ALWAYS_ONGOING, reason={"reason": "state_for"}
    )

    freezer.tick(timedelta(minutes=90))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert reason(hass, "sensor.attention_span_ytterdorren") == "Öppen i 1 tim"

    hass.states.async_set("binary_sensor.ytterdorr", "off", {"device_class": "door"})
    await hass.async_block_till_done()
    assert reason(hass, "sensor.attention_span_ytterdorren") == "Stängd i 0 min"


async def test_an_own_template_is_rendered_as_text_and_follows_what_it_reads(
    hass: HomeAssistant,
):
    hass.states.async_set("sensor.fukt_tvattstuga", "78")
    entry = await add_integration(hass)
    template = "Torkar – {{ states('sensor.fukt_tvattstuga') }} % fukt"

    await add_rule(
        hass,
        entry,
        "value",
        {"name": "Tvättstugan", "entity": "sensor.fukt_tvattstuga"},
        ALWAYS_ONGOING,
        reason={"reason": "custom", "reason_template": template},
    )
    assert reason(hass, "sensor.attention_span_tvattstugan") == "Torkar – 78 % fukt"

    hass.states.async_set("sensor.fukt_tvattstuga", "71")
    await hass.async_block_till_done()
    assert reason(hass, "sensor.attention_span_tvattstugan") == "Torkar – 71 % fukt"


async def test_an_own_template_that_looks_like_a_number_stays_text(hass: HomeAssistant):
    entry = await add_integration(hass)

    await add_rule(
        hass,
        entry,
        "value",
        {"name": "Pris", "entity": "sensor.pris"},
        ALWAYS_ONGOING,
        reason={"reason": "custom", "reason_template": "{{ '1.50' }}"},
    )

    assert reason(hass, "sensor.attention_span_pris") == "1.50"


async def test_a_rule_without_reason_has_none(hass: HomeAssistant):
    hass.states.async_set("binary_sensor.ytterdorr", "on")
    entry = await add_integration(hass)

    await add_rule(hass, entry, "status", YTTERDORREN, ALWAYS_ONGOING)

    assert reason(hass, "sensor.attention_span_ytterdorren") is None


async def test_a_reason_that_renders_empty_or_fails_is_none(hass: HomeAssistant):
    hass.states.async_set("sensor.pris", "1")
    entry = await add_integration(hass)
    template = "{{ 'Dyrt' if states('sensor.pris') | float > 2 else '' }}"
    await add_rule(
        hass,
        entry,
        "value",
        {"name": "Pris", "entity": "sensor.pris"},
        ALWAYS_ONGOING,
        reason={"reason": "custom", "reason_template": template},
    )
    assert reason(hass, "sensor.attention_span_pris") is None

    hass.states.async_set("sensor.pris", "3")
    await hass.async_block_till_done()
    assert reason(hass, "sensor.attention_span_pris") == "Dyrt"

    hass.states.async_set("sensor.pris", "okänt")
    await hass.async_block_till_done()
    assert reason(hass, "sensor.attention_span_pris") is None


@pytest.mark.parametrize(
    ("entity_id", "state", "attributes", "expected"),
    [
        (
            "sensor.disk_klar",
            "2026-10-26T08:40:00+00:00",
            {"device_class": "timestamp"},
            "40 min kvar",
        ),
        (
            "sensor.disk_kvar",
            "90",
            {"device_class": "duration", "unit_of_measurement": "min"},
            "1 tim kvar",
        ),
        (
            "timer.agg",
            "active",
            {
                "duration": "0:08:00",
                "remaining": "0:08:00",
                "finishes_at": "2026-10-26T08:07:30+00:00",
            },
            "8 min kvar",
        ),
        ("timer.agg", "paused", {"duration": "0:08:00", "remaining": "0:03:00"}, "3 min kvar"),
        ("sensor.skrivare", "62", {"unit_of_measurement": "%"}, "62 %"),
        # Utan tid kvar eller ett tal visas tillståndet på hemmets språk, utan enhet.
        ("timer.agg", "idle", {"duration": "0:08:00"}, "Inaktiv"),
        ("sensor.skrivare", "unavailable", {"unit_of_measurement": "%"}, "Ej tillgänglig"),
        ("sensor.skrivare", "unknown", {"unit_of_measurement": "%"}, "Okänd"),
    ],
)
async def test_the_preset_for_progress_shows_the_time_left_or_the_percent(
    hass: HomeAssistant,
    freezer,
    swedish,
    entity_id: str,
    state: str,
    attributes: dict,
    expected: str,
):
    freezer.move_to(FIXTURE_TIME)
    hass.states.async_set(entity_id, state, attributes)
    entry = await add_integration(hass)

    await add_rule(
        hass,
        entry,
        "progress",
        {"name": "Förlopp", "entity": entity_id},
        ALWAYS_ONGOING,
        reason={"reason": "time_left"},
    )

    assert reason(hass, "sensor.attention_span_forlopp") == expected


async def test_the_preset_for_value_shows_the_number_with_its_unit(hass: HomeAssistant):
    hass.states.async_set("sensor.bilen", "52", {"unit_of_measurement": "%"})
    entry = await add_integration(hass)

    await add_rule(
        hass,
        entry,
        "value",
        {"name": "Bilen", "entity": "sensor.bilen"},
        ALWAYS_ONGOING,
        reason={"reason": "value"},
    )

    assert reason(hass, "sensor.attention_span_bilen") == "52 %"


@pytest.mark.parametrize(
    ("state", "expected"), [("unavailable", "Ej tillgänglig"), ("unknown", "Okänd")]
)
async def test_the_preset_for_value_shows_a_missing_value_in_the_household_language(
    hass: HomeAssistant, swedish, state: str, expected: str
):
    hass.states.async_set("sensor.bilen", state, {"unit_of_measurement": "%"})
    entry = await add_integration(hass)

    await add_rule(
        hass,
        entry,
        "value",
        {"name": "Bilen", "entity": "sensor.bilen"},
        ALWAYS_ONGOING,
        reason={"reason": "value"},
    )

    assert reason(hass, "sensor.attention_span_bilen") == expected


async def test_the_preset_for_status_shows_an_unavailable_state_in_the_household_language(
    hass: HomeAssistant, freezer, swedish
):
    freezer.move_to(FIXTURE_TIME)
    hass.states.async_set("binary_sensor.ytterdorr", "unavailable", {"device_class": "door"})
    entry = await add_integration(hass)
    freezer.tick(timedelta(minutes=10))

    await add_rule(
        hass, entry, "status", YTTERDORREN, ALWAYS_ONGOING, reason={"reason": "state_for"}
    )

    assert reason(hass, "sensor.attention_span_ytterdorren") == "Ej tillgänglig i 10 min"


async def test_a_new_state_is_written_once_with_its_reason_and_state_since(
    hass: HomeAssistant, freezer, swedish
):
    freezer.move_to(FIXTURE_TIME)
    hass.states.async_set("binary_sensor.ytterdorr", "on", {"device_class": "door"})
    entry = await add_integration(hass)
    await add_rule(
        hass, entry, "status", YTTERDORREN, ALWAYS_ONGOING, reason={"reason": "state_for"}
    )
    freezer.tick(timedelta(minutes=10))
    events = async_capture_events(hass, EVENT_STATE_CHANGED)

    hass.states.async_set("binary_sensor.ytterdorr", "off", {"device_class": "door"})
    await hass.async_block_till_done()

    written = [e for e in events if e.data["entity_id"] == "sensor.attention_span_ytterdorren"]
    assert len(written) == 1
    attributes = written[0].data["new_state"].attributes
    assert attributes["reason"] == "Stängd i 0 min"
    assert attributes["state_since"] == "2026-10-26T08:10:00+00:00"


async def test_new_occurrences_are_written_once_with_their_reason(
    hass: HomeAssistant, freezer, swedish
):
    await hass.config.async_set_time_zone("Europe/Stockholm")
    freezer.move_to(FIXTURE_TIME)
    hass.states.async_set(
        "sensor.buss_nasta", "2026-10-26T08:19:00+00:00", {"device_class": "timestamp"}
    )
    entry = await add_integration(hass)
    await add_rule(
        hass,
        entry,
        "upcoming",
        {"name": "Buss", "entities": ["sensor.buss_nasta"], "count": 3},
        ALWAYS_ONGOING,
        reason={"reason": "next"},
    )
    await hass.async_block_till_done()
    events = async_capture_events(hass, EVENT_STATE_CHANGED)

    hass.states.async_set(
        "sensor.buss_nasta", "2026-10-26T08:27:00+00:00", {"device_class": "timestamp"}
    )
    freezer.tick(timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    written = [e for e in events if e.data["entity_id"] == "sensor.attention_span_buss"]
    assert len(written) == 1
    attributes = written[0].data["new_state"].attributes
    assert attributes["reason"] == "Nästa: 09:27"
    assert [o["start"] for o in attributes["occurrences"]] == ["2026-10-26T09:27:00+01:00"]


async def test_the_preset_for_upcoming_shows_the_next_occurrence(
    hass: HomeAssistant, freezer, swedish
):
    await hass.config.async_set_time_zone("Europe/Stockholm")
    freezer.move_to(FIXTURE_TIME)
    hass.states.async_set(
        "sensor.buss_nasta", "2026-10-26T08:19:00+00:00", {"device_class": "timestamp"}
    )
    entry = await add_integration(hass)

    await add_rule(
        hass,
        entry,
        "upcoming",
        {"name": "Buss", "entities": ["sensor.buss_nasta"], "count": 3},
        ALWAYS_ONGOING,
        reason={"reason": "next"},
    )
    await hass.async_block_till_done()

    assert reason(hass, "sensor.attention_span_buss") == "Nästa: 09:19"


async def test_the_preset_is_in_english_in_an_english_home(hass: HomeAssistant, freezer):
    freezer.move_to(FIXTURE_TIME)
    hass.states.async_set(
        "sensor.disk_kvar", "40", {"device_class": "duration", "unit_of_measurement": "min"}
    )
    entry = await add_integration(hass)

    await add_rule(
        hass,
        entry,
        "progress",
        {"name": "Disk", "entity": "sensor.disk_kvar"},
        ALWAYS_ONGOING,
        reason={"reason": "time_left"},
    )

    assert reason(hass, "sensor.attention_span_disk") == "40 min left"


async def test_how_long_in_the_reason_counts_from_before_a_restart(
    hass: HomeAssistant, freezer, swedish
):
    freezer.move_to("2026-10-26T07:50:00+00:00")
    hass.states.async_set("binary_sensor.ytterdorr", "on", {"device_class": "door"})
    freezer.move_to(FIXTURE_TIME)
    entry = await add_integration(hass)
    await add_rule(
        hass, entry, "status", YTTERDORREN, ALWAYS_ONGOING, reason={"reason": "state_for"}
    )
    freezer.move_to("2026-10-26T08:20:00+00:00")

    async with restart(hass) as hass:
        hass.config.language = "sv"
        assert await async_setup_component(hass, "binary_sensor", {})
        # Källentiteten får ett nytt last_changed när dess integration laddas.
        hass.states.async_set("binary_sensor.ytterdorr", "on", {"device_class": "door"})
        assert await async_setup_component(hass, DOMAIN, {})
        await hass.async_start()
        await hass.async_block_till_done()

        assert reason(hass, "sensor.attention_span_ytterdorren") == "Öppen i 30 min"


async def test_a_saved_reason_that_does_not_exist_is_logged_and_left_out(
    hass: HomeAssistant, caplog
):
    hass.states.async_set("binary_sensor.ytterdorr", "on")
    entry = await add_integration(hass)
    rule = await add_rule(
        hass, entry, "status", YTTERDORREN, ALWAYS_ONGOING, reason={"reason": "state_for"}
    )

    # Till exempel en regel från en senare version med en färdig mall som inte finns här.
    subentry = entry.subentries[rule]
    hass.config_entries.async_update_subentry(
        entry, subentry, data={**subentry.data, "reason": "state_since"}
    )
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert reason(hass, "sensor.attention_span_ytterdorren") is None
    assert "har orsaken state_since, som inte finns" in caplog.text

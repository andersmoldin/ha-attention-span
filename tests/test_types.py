"""Typerna Förlopp, Kommande, Eget kort och Status för en grupp, genom det riktiga flödet."""

from datetime import date, datetime, timedelta

import pytest
from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.components.calendar.const import DATA_COMPONENT as CALENDAR_COMPONENT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .conftest import (
    FIXTURE_TIME,
    add_integration,
    add_rule,
    contract_example,
    reconfigure_rule,
    start_rule,
    start_rule_reconfigure,
    state_as_contract,
)

ALWAYS_ONGOING = {"ongoing": "always"}

DISKMASKINEN = {
    "name": "Diskmaskinen",
    "icon": "mdi:dishwasher",
    "entity": "sensor.diskmaskin_klar",
}


async def test_a_progress_rule_becomes_a_sensor_in_contract_v1(hass: HomeAssistant, freezer):
    freezer.move_to(FIXTURE_TIME)
    hass.states.async_set(
        "sensor.diskmaskin_klar", "2026-10-26T08:40:00+00:00", {"device_class": "timestamp"}
    )
    entry = await add_integration(hass)

    await add_rule(hass, entry, "progress", DISKMASKINEN, ALWAYS_ONGOING)

    expected = contract_example("progress_ongoing")
    assert state_as_contract(hass, expected["entity_id"]) == expected


@pytest.mark.parametrize(
    ("entity_id", "state", "attributes"),
    [
        ("sensor.diskmaskin_klar", "2026-10-26T08:40:00+00:00", {"device_class": "timestamp"}),
        ("sensor.skrivare_klar", "62", {"unit_of_measurement": "%"}),
        ("sensor.disk_kvar", "40", {"device_class": "duration", "unit_of_measurement": "min"}),
        ("timer.agg", "active", {"duration": "0:08:00", "remaining": "0:08:00"}),
    ],
)
async def test_progress_shows_time_left_or_percent(
    hass: HomeAssistant, entity_id: str, state: str, attributes: dict
):
    hass.states.async_set(entity_id, state, attributes)
    entry = await add_integration(hass)
    fields = {"name": "Förlopp", "entity": entity_id}

    await add_rule(hass, entry, "progress", fields, ALWAYS_ONGOING)

    assert hass.states.get("sensor.attention_span_forlopp").attributes["entities"] == [entity_id]


async def test_progress_rejects_an_entity_without_time_left_or_percent(hass: HomeAssistant):
    hass.states.async_set("sensor.inne", "21.4", {"unit_of_measurement": "°C"})
    entry = await add_integration(hass)
    result = await start_rule(hass, entry, "progress")

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Inne", "entity": "sensor.inne"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"entity": "progress_entity"}
    assert entry.subentries == {}


class Calendar(CalendarEntity):
    """En kalender med fasta händelser, som en riktig kalenderintegration."""

    def __init__(self, entity_id: str, events: list[CalendarEvent]) -> None:
        self.entity_id = entity_id
        self._attr_name = entity_id
        self.events = events

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        return next((e for e in self.events if e.end_datetime_local > now), None)

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return [
            e
            for e in self.events
            if e.end_datetime_local > start_date and e.start_datetime_local < end_date
        ]


def local(text: str) -> datetime:
    return dt_util.parse_datetime(text)


@pytest.fixture
async def add_calendar(hass: HomeAssistant):
    """Lägg till en kalender; den tas bort efter testet, så att dess tidur inte blir kvar."""
    added: list[str] = []

    async def add(
        entity_id: str, events: list[CalendarEvent], kind: type[Calendar] = Calendar
    ) -> None:
        assert await async_setup_component(hass, "calendar", {})
        await hass.data[CALENDAR_COMPONENT].async_add_entities([kind(entity_id, list(events))])
        await hass.async_block_till_done()
        added.append(entity_id)

    yield add
    for entity_id in added:
        await hass.data[CALENDAR_COMPONENT].async_remove_entity(entity_id)


SOPHAMTNING = (
    "calendar.sophamtning",
    [
        CalendarEvent(
            start=local("2026-10-20T06:30:00+02:00"),
            end=local("2026-10-20T07:00:00+02:00"),
            summary="Restavfall",
        ),
        CalendarEvent(
            start=local("2026-10-27T06:30:00+01:00"),
            end=local("2026-10-27T07:00:00+01:00"),
            summary="Restavfall",
        ),
        CalendarEvent(start=date(2026, 10, 29), end=date(2026, 10, 30), summary="Matavfall"),
        CalendarEvent(
            start=local("2026-11-03T06:30:00+01:00"),
            end=local("2026-11-03T07:00:00+01:00"),
            summary="Restavfall",
        ),
    ],
)
SOPOR = {
    "name": "Sophämtning",
    "icon": "mdi:trash-can",
    "entities": ["calendar.sophamtning"],
    "count": 2,
}


async def test_an_upcoming_rule_shows_the_next_occurrences_from_a_calendar(
    hass: HomeAssistant, freezer, add_calendar
):
    await hass.config.async_set_time_zone("Europe/Stockholm")
    freezer.move_to(FIXTURE_TIME)
    await add_calendar(*SOPHAMTNING)
    entry = await add_integration(hass)

    await add_rule(hass, entry, "upcoming", SOPOR, {"quiet": "always"})

    expected = contract_example("upcoming_quiet")
    assert state_as_contract(hass, expected["entity_id"]) == expected


def starts(hass: HomeAssistant, entity_id: str) -> list[str]:
    return [o["start"] for o in hass.states.get(entity_id).attributes["occurrences"]]


async def tick(hass: HomeAssistant, freezer, delta: timedelta) -> None:
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_upcoming_merges_sensors_with_timestamps_and_skips_those_that_have_passed(
    hass: HomeAssistant, freezer, add_calendar
):
    await hass.config.async_set_time_zone("Europe/Stockholm")
    freezer.move_to(FIXTURE_TIME)
    await add_calendar(*SOPHAMTNING)
    hass.states.async_set("sensor.buss_nasta", "2026-10-26T08:07:00+00:00")
    hass.states.async_set("sensor.buss_forra", "2026-10-26T07:55:00+00:00")
    entry = await add_integration(hass)

    await add_rule(
        hass,
        entry,
        "upcoming",
        SOPOR | {"entities": ["sensor.buss_forra", "calendar.sophamtning", "sensor.buss_nasta"]},
        {"quiet": "always"},
    )

    occurrences = hass.states.get("sensor.attention_span_sophamtning").attributes["occurrences"]
    assert occurrences == [
        {"start": "2026-10-26T09:07:00+01:00", "end": None, "summary": None},
        {
            "start": "2026-10-27T06:30:00+01:00",
            "end": "2026-10-27T07:00:00+01:00",
            "summary": "Restavfall",
        },
    ]


async def test_upcoming_follows_time_and_its_sources(hass: HomeAssistant, freezer, add_calendar):
    await hass.config.async_set_time_zone("Europe/Stockholm")
    freezer.move_to(FIXTURE_TIME)
    await add_calendar(*SOPHAMTNING)
    hass.states.async_set("sensor.buss_nasta", "2026-10-26T08:07:00+00:00")
    entry = await add_integration(hass)
    await add_rule(
        hass,
        entry,
        "upcoming",
        SOPOR | {"entities": ["calendar.sophamtning", "sensor.buss_nasta"]},
        {"quiet": "always"},
    )
    entity_id = "sensor.attention_span_sophamtning"
    assert starts(hass, entity_id) == ["2026-10-26T09:07:00+01:00", "2026-10-27T06:30:00+01:00"]

    # Bussen har gått, och nästa tillfälle tar dess plats.
    await tick(hass, freezer, timedelta(minutes=7))
    assert starts(hass, entity_id) == ["2026-10-27T06:30:00+01:00", "2026-10-29"]

    hass.states.async_set("sensor.buss_nasta", "2026-10-26T08:27:00+00:00")
    await tick(hass, freezer, timedelta(seconds=1))
    assert starts(hass, entity_id) == ["2026-10-26T09:27:00+01:00", "2026-10-27T06:30:00+01:00"]

    # En restavfallshämtning pågår tills den är slut.
    freezer.move_to("2026-10-27T05:45:00+00:00")
    await tick(hass, freezer, timedelta(seconds=1))
    assert starts(hass, entity_id) == ["2026-10-27T06:30:00+01:00", "2026-10-29"]
    freezer.move_to("2026-10-27T06:00:00+00:00")
    await tick(hass, freezer, timedelta(seconds=1))
    assert starts(hass, entity_id) == ["2026-10-29", "2026-11-03T06:30:00+01:00"]


async def test_upcoming_picks_up_changed_calendar_events(
    hass: HomeAssistant, freezer, add_calendar
):
    await hass.config.async_set_time_zone("Europe/Stockholm")
    freezer.move_to(FIXTURE_TIME)
    await add_calendar(*SOPHAMTNING)
    entry = await add_integration(hass)
    await add_rule(hass, entry, "upcoming", SOPOR, {"quiet": "always"})
    calendar = hass.data[CALENDAR_COMPONENT].get_entity("calendar.sophamtning")

    calendar.events.append(
        CalendarEvent(
            start=local("2026-10-26T18:00:00+01:00"),
            end=local("2026-10-26T18:30:00+01:00"),
            summary="Grovsopor",
        )
    )
    await tick(hass, freezer, timedelta(minutes=15))

    occurrences = hass.states.get("sensor.attention_span_sophamtning").attributes["occurrences"]
    assert [o["summary"] for o in occurrences] == ["Grovsopor", "Restavfall"]


class BrokenCalendar(Calendar):
    async def async_get_events(self, hass, start_date, end_date):
        raise HomeAssistantError("Servern svarar inte")


async def test_a_calendar_that_cannot_be_read_does_not_hide_the_other_sources(
    hass: HomeAssistant, freezer, add_calendar, caplog
):
    freezer.move_to(FIXTURE_TIME)
    await add_calendar("calendar.trasig", [], BrokenCalendar)
    hass.states.async_set("sensor.buss_nasta", "2026-10-26T08:07:00+00:00")
    entry = await add_integration(hass)

    await add_rule(
        hass,
        entry,
        "upcoming",
        SOPOR | {"entities": ["calendar.trasig", "sensor.buss_nasta"]},
        {"quiet": "always"},
    )

    assert len(starts(hass, "sensor.attention_span_sophamtning")) == 1
    assert "calendar.trasig" in caplog.text


async def test_upcoming_needs_a_calendar_or_a_sensor(hass: HomeAssistant):
    entry = await add_integration(hass)
    result = await start_rule(hass, entry, "upcoming")

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], SOPOR | {"entities": []}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"entities": "entities_required"}


VADRET = {
    "name": "Vädret",
    "icon": "mdi:weather-partly-cloudy",
    "card": {"type": "weather-forecast", "entity": "weather.hemma", "show_forecast": False},
}


async def test_a_custom_card_rule_puts_the_card_configuration_in_the_card_attribute(
    hass: HomeAssistant, freezer
):
    freezer.move_to(FIXTURE_TIME)
    entry = await add_integration(hass)

    await add_rule(hass, entry, "custom", VADRET, {"glance": "always"})

    expected = contract_example("custom_glance")
    assert state_as_contract(hass, expected["entity_id"]) == expected


@pytest.mark.parametrize("card", [{}, {"type": ""}, {"entity": "weather.hemma"}, ["type"]])
async def test_a_custom_card_needs_a_card_type(hass: HomeAssistant, card):
    entry = await add_integration(hass)
    result = await start_rule(hass, entry, "custom")

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], VADRET | {"card": card}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"card": "invalid_card"}
    assert entry.subentries == {}


async def test_changing_a_custom_card_shows_its_configuration(hass: HomeAssistant):
    entry = await add_integration(hass)
    rule = await add_rule(hass, entry, "custom", VADRET, {"glance": "always"})

    result = await start_rule_reconfigure(hass, entry, rule)

    card = next(key for key in result["data_schema"].schema if key == "card")
    assert card.description == {"suggested_value": VADRET["card"]}


async def test_a_status_rule_can_show_a_group(hass: HomeAssistant, freezer):
    """En grupphjälpare för fönstren: Pågår när något fönster är öppet."""
    freezer.move_to(FIXTURE_TIME)
    windows = ["binary_sensor.kok", "binary_sensor.sovrum", "binary_sensor.badrum"]
    for window, state in zip(windows, ["on", "on", "off"], strict=True):
        hass.states.async_set(window, state)
    assert await async_setup_component(
        hass,
        "binary_sensor",
        {"binary_sensor": {"platform": "group", "name": "Fönster", "entities": windows}},
    )
    await hass.async_block_till_done()
    entry = await add_integration(hass)

    await add_rule(
        hass,
        entry,
        "status",
        {"name": "Fönster", "icon": "mdi:window-open-variant", "entity": "binary_sensor.fonster"},
        {"ongoing": "condition"},
        {"ongoing": [{"condition": "state", "entity_id": "binary_sensor.fonster", "state": "on"}]},
    )

    expected = contract_example("status_group_ongoing")
    assert state_as_contract(hass, expected["entity_id"]) == expected


async def test_changing_an_upcoming_rule_shows_and_keeps_its_sources_and_count(
    hass: HomeAssistant, freezer, add_calendar
):
    freezer.move_to(FIXTURE_TIME)
    await add_calendar(*SOPHAMTNING)
    entry = await add_integration(hass)
    rule = await add_rule(hass, entry, "upcoming", SOPOR, {"quiet": "always"})

    result = await start_rule_reconfigure(hass, entry, rule)
    shown = ("name", "entities", "count")
    defaults = {str(key): key.default() for key in result["data_schema"].schema if key in shown}
    assert defaults == {"name": "Sophämtning", "entities": ["calendar.sophamtning"], "count": 2}

    await reconfigure_rule(hass, entry, rule, SOPOR | {"count": 3}, {"quiet": "always"})

    occurrences = hass.states.get("sensor.attention_span_sophamtning").attributes["occurrences"]
    assert len(occurrences) == 3

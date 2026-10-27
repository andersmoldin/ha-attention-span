"""Typen Kommande: de närmaste tillfällena ur kalendrar och sensorer med tidpunkter."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any, cast

from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
    split_entity_id,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

# Hur långt fram i kalendrarna tillfällena hämtas: ett år, så att även årliga händelser syns.
LOOKAHEAD = timedelta(days=366)
# Hur ofta kalendrarna läses om, så att tillagda och ändrade händelser syns. Kalendern
# själv ändras bara när en händelse börjar eller slutar.
REFRESH_INTERVAL = timedelta(minutes=15)
# Samlar tätt efterföljande ändringar till en hämtning.
COOLDOWN = 1.0

# Ett tillfälle: när det börjar, för sortering, och det som står i dataformatet.
type _Found = tuple[datetime, dict[str, Any]]


def _parse(value: str) -> date | datetime | None:
    """Ett datum för en heldagshändelse, annars en tidpunkt; utan tidszon gäller HA:s."""
    if (day := dt_util.parse_date(value)) is not None:
        return day
    if (moment := dt_util.parse_datetime(value)) is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt_util.get_default_time_zone())


def _as_moment(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return dt_util.start_of_local_day(value)


def _as_text(value: date | datetime) -> str:
    """Tidpunkter i HA:s tidszon; datum som datum, så att heldag syns."""
    return dt_util.as_local(value).isoformat() if isinstance(value, datetime) else value.isoformat()


async def _async_calendar(hass: HomeAssistant, entity_id: str, now: datetime) -> list[_Found]:
    try:
        response = await hass.services.async_call(
            "calendar",
            "get_events",
            {"entity_id": entity_id, "start_date_time": now, "duration": LOOKAHEAD},
            blocking=True,
            return_response=True,
        )
    except HomeAssistantError as err:
        _LOGGER.warning("Händelserna i %s gick inte att läsa: %s", entity_id, err)
        return []
    # Svaret från calendar.get_events: {entity_id: {"events": [{"start", "end", "summary", …}]}}.
    events = cast(dict[str, Any], response or {}).get(entity_id, {}).get("events", [])
    found: list[_Found] = []
    for event in cast(list[dict[str, Any]], events):
        start, end = _parse(event["start"]), _parse(event["end"])
        if start is None or end is None:
            continue
        found.append(
            (
                _as_moment(start),
                {"start": _as_text(start), "end": _as_text(end), "summary": event.get("summary")},
            )
        )
    return found


def _timestamp(hass: HomeAssistant, entity_id: str, now: datetime) -> list[_Found]:
    """En sensor med en tidpunkt; en tidpunkt som har passerat är inget kommande tillfälle."""
    state = hass.states.get(entity_id)
    moment = _parse(state.state) if state is not None else None
    if not isinstance(moment, datetime) or moment <= now:
        return []
    return [(moment, {"start": _as_text(moment), "end": None, "summary": None})]


async def async_occurrences(
    hass: HomeAssistant, entity_ids: list[str], count: int
) -> list[dict[str, Any]]:
    """De count närmaste tillfällena från alla källor, det tidigaste först.

    En kalenderhändelse som pågår räknas tills den slutar.
    """
    now = dt_util.now()
    found: list[_Found] = []
    for entity_id in entity_ids:
        if split_entity_id(entity_id)[0] == "calendar":
            found += await _async_calendar(hass, entity_id, now)
        else:
            found += _timestamp(hass, entity_id, now)
    found.sort(key=lambda item: item[0])
    return [occurrence for _, occurrence in found[:count]]


def _passes(occurrence: dict[str, Any]) -> datetime:
    """När tillfället inte längre är kommande: när det slutar, eller börjar om det saknar slut."""
    moment = _parse(occurrence["end"] or occurrence["start"])
    assert moment is not None
    return _as_moment(moment)


class Upcoming:
    """Håller de närmaste tillfällena aktuella och lämnar dem till on_change.

    Tillfällena läses om när en källa ändras, när det första tillfället passerar och,
    med kalendrar bland källorna, med jämna mellanrum.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entity_ids: list[str],
        count: int,
        on_change: Callable[[list[dict[str, Any]]], None],
    ) -> None:
        self._hass = hass
        self._entity_ids = entity_ids
        self._count = count
        self._on_change = on_change
        self._unsub_passes: CALLBACK_TYPE | None = None
        self._debouncer = Debouncer(
            hass, _LOGGER, cooldown=COOLDOWN, immediate=True, function=self._async_refresh
        )

    async def _async_refresh(self) -> None:
        occurrences = await async_occurrences(self._hass, self._entity_ids, self._count)
        self._cancel_passes()
        if occurrences:
            self._unsub_passes = async_track_point_in_utc_time(
                self._hass, self._refresh, _passes(occurrences[0])
            )
        self._on_change(occurrences)

    @callback
    def _refresh(self, *_: Any) -> None:
        self._hass.async_create_task(self._debouncer.async_call())

    def _cancel_passes(self) -> None:
        if self._unsub_passes is not None:
            self._unsub_passes()
            self._unsub_passes = None

    async def async_start(self) -> CALLBACK_TYPE:
        """Läs tillfällena nu och håll dem aktuella tills det som returneras anropas."""

        @callback
        def changed(_: Event[EventStateChangedData]) -> None:
            self._refresh()

        unsubs = [async_track_state_change_event(self._hass, self._entity_ids, changed)]
        if any(split_entity_id(entity_id)[0] == "calendar" for entity_id in self._entity_ids):
            unsubs.append(async_track_time_interval(self._hass, self._refresh, REFRESH_INTERVAL))
        await self._debouncer.async_call()

        @callback
        def stop() -> None:
            for unsub in unsubs:
                unsub()
            self._cancel_passes()
            self._debouncer.async_shutdown()

        return stop

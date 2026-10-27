"""Notice lifecycle: kvittering av ett Larm och att lägga ett Problem eller en Pågår-notis åt
sidan, med «larma igen» och fladdergränsen.

Båda gäller för hela hushållet tills en tidpunkt, eller tills regeln har varit under nivån de
gäller på i fladdergränsen. Ett kortare avbrott, till exempel en givare som slår av och på,
behåller dem. Når regeln nivån igen efter ett längre avbrott är det en New occurrence.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any, TypedDict

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .const import ALARM, CONF_FLAP_LIMIT, CONF_REALARM_AFTER, LEVELS, SNOOZABLE

# Standard för regler som inte har ställt in något, också regler från före kvitteringen.
DEFAULT_REALARM_AFTER = timedelta(hours=24)
DEFAULT_FLAP_LIMIT = timedelta(minutes=5)


def _realarm_after(rule: Mapping[str, Any]) -> timedelta | None:
    """Hur länge ett kvitterat Larm väntar innan det larmar igen; None för aldrig."""
    if CONF_REALARM_AFTER not in rule:
        return DEFAULT_REALARM_AFTER
    value = rule[CONF_REALARM_AFTER]
    return None if value is None else cv.time_period_dict(value)


def _flap_limit(rule: Mapping[str, Any]) -> timedelta:
    """Hur länge regeln måste ha varit under nivån innan villkoret räknas som släppt."""
    if CONF_FLAP_LIMIT not in rule:
        return DEFAULT_FLAP_LIMIT
    return cv.time_period_dict(rule[CONF_FLAP_LIMIT])


def _severity(level: object) -> int:
    """Lägre för allvarligare nivåer. Dold är under alla nivåer."""
    return LEVELS.index(level) if level in LEVELS else len(LEVELS)


class SavedAcknowledgement(TypedDict):
    """En kvittering som sparas. Tider i ISO 8601."""

    # När Larmet larmar igen, eller None för aldrig.
    realarm_at: str | None
    # När regeln lämnade Larm efter kvitteringen, eller None medan den är Larm.
    released: str | None


class SavedSnooze(TypedDict):
    """En notis som ligger åt sidan och sparas. Tider i ISO 8601."""

    # Nivån notisen lades åt sidan på.
    level: str
    # Till när, eller None för «tills det är lagat».
    until: str | None
    # När regeln kom under nivån, eller None medan den har nivån.
    released: str | None


def _parse(value: str | None) -> datetime | None:
    return None if value is None else dt_util.parse_datetime(value, raise_on_error=True)


def _format(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


class _Hold:
    """Ett läge som en Rules notis hålls i på en nivå: till until, eller tills regeln har varit
    under nivån i fladdergränsen ur regeln.

    on_change anropas när läget har gått ut medan nivån står still, så att regeln kan visa det.
    När det går ut vid en omräkning ser regeln det på attributen.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        rule: Mapping[str, Any],
        on_change: Callable[[], None],
    ) -> None:
        self._hass = hass
        self._flap = _flap_limit(rule)
        self._on_change = on_change
        # Nivån läget gäller på, eller None när det inte gäller; när det går ut; och när regeln
        # kom under nivån, eller None medan den har nivån. Subklasserna läser in ett sparat läge.
        self._level: str | None = None
        self._until: datetime | None = None
        self._released: datetime | None = None
        self._unsub_timer: CALLBACK_TYPE | None = None
        # När timern går, så att den inte byggs om vid varje omräkning.
        self._timer_at: datetime | None = None

    @property
    def held(self) -> bool:
        return self._level is not None

    @callback
    def _async_hold(self, level: str, until: datetime | None) -> None:
        """Håll notisen på nivån, som regeln har nu."""
        self._level = level
        self._until = until
        self._released = None
        self._async_schedule()

    @callback
    def async_release(self) -> None:
        """Släpp läget direkt."""
        self.async_unload()
        self._level = self._until = self._released = None

    @callback
    def async_level(self, level: str) -> None:
        """Regelns nivå efter en omräkning. Ett avbrott eller en tid som redan har gått ut räknas
        innan nivån ändrar dem, också när det skedde under en omstart."""
        if self._level is None or self._async_expired():
            return
        if _severity(level) <= _severity(self._level):
            self._released = None
        elif self._released is None:
            self._released = dt_util.utcnow()
        if not self._async_expired():
            self._async_schedule()

    @callback
    def async_unload(self) -> None:
        if self._unsub_timer is not None:
            self._unsub_timer()
        self._unsub_timer = None
        self._timer_at = None

    def _deadline(self) -> datetime | None:
        """När läget går ut, om inget ändras."""
        deadlines = [self._until] if self._until else []
        if self._released is not None:
            deadlines.append(self._released + self._flap)
        return min(deadlines, default=None)

    @callback
    def _async_expired(self) -> bool:
        """Släpp läget om det har gått ut, och säg om det har det."""
        deadline = self._deadline()
        if deadline is None or deadline > dt_util.utcnow():
            return False
        self.async_release()
        return True

    @callback
    def _async_schedule(self) -> None:
        deadline = self._deadline()
        if deadline == self._timer_at:
            return
        self.async_unload()
        if deadline is None:
            return

        @callback
        def expire(_: datetime) -> None:
            self._unsub_timer = None
            self._timer_at = None
            if self._async_expired():
                self._on_change()
            else:
                self._async_schedule()

        self._unsub_timer = async_track_point_in_utc_time(self._hass, expire, deadline)
        self._timer_at = deadline


class Acknowledgement(_Hold):
    """Kvitteringen av en Rules Larm, med «larma igen» och fladdergränsen ur regeln."""

    def __init__(
        self,
        hass: HomeAssistant,
        rule: Mapping[str, Any],
        saved: SavedAcknowledgement | None,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(hass, rule, on_change)
        if saved is not None:
            self._level = ALARM
            self._until = _parse(saved["realarm_at"])
            self._released = _parse(saved["released"])
        self._realarm = _realarm_after(rule)

    @property
    def saved(self) -> SavedAcknowledgement | None:
        if not self.held:
            return None
        return SavedAcknowledgement(
            realarm_at=_format(self._until), released=_format(self._released)
        )

    def attributes(self, level: object) -> dict[str, Any]:
        """Attributen acknowledged och realarm_at för regelns nivå. Kvitteringen syns bara på
        Larm."""
        acknowledged = self.held and level == ALARM
        return {
            "acknowledged": acknowledged,
            "realarm_at": _format(self._until) if acknowledged else None,
        }

    @callback
    def async_acknowledge(self) -> None:
        """Kvittera Larmet, som regeln har nu."""
        self._async_hold(ALARM, dt_util.utcnow() + self._realarm if self._realarm else None)


class Snooze(_Hold):
    """Att en Rules Problem eller Pågår-notis ligger åt sidan. Den kommer också tillbaka direkt
    när regeln når en allvarligare nivå än den lades åt sidan på."""

    def __init__(
        self,
        hass: HomeAssistant,
        rule: Mapping[str, Any],
        saved: SavedSnooze | None,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(hass, rule, on_change)
        if saved is not None:
            self._level = saved["level"]
            self._until = _parse(saved["until"])
            self._released = _parse(saved["released"])

    @property
    def saved(self) -> SavedSnooze | None:
        if self._level is None:
            return None
        return SavedSnooze(
            level=self._level, until=_format(self._until), released=_format(self._released)
        )

    def attributes(self, level: object) -> dict[str, Any]:
        """Attributen snoozed och snoozed_until för regelns nivå. Åt sidan syns bara på Problem
        och Pågår."""
        snoozed = self.held and level in SNOOZABLE
        return {
            "snoozed": snoozed,
            "snoozed_until": _format(self._until) if snoozed else None,
        }

    @callback
    def async_snooze(self, level: str, until: datetime | None) -> None:
        """Lägg notisen åt sidan på nivån, som regeln har nu, till until eller tills det är
        lagat."""
        self._async_hold(level, until)

    @callback
    def async_level(self, level: str) -> None:
        if self._level is not None and _severity(level) < _severity(self._level):
            self.async_release()
        super().async_level(level)

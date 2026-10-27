"""Notice lifecycle: kvittering av ett Larm, «larma igen» och fladdergränsen.

Kvitteringen gäller tills tiden för «larma igen» har gått, eller tills regeln har varit
under Larm i fladdergränsen. Ett kortare avbrott, till exempel en givare som slår av och på,
behåller den.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any, TypedDict

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .const import ALARM, CONF_FLAP_LIMIT, CONF_REALARM_AFTER

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


class SavedAcknowledgement(TypedDict):
    """En kvittering som sparas. Tider i ISO 8601."""

    # När Larmet larmar igen, eller None för aldrig.
    realarm_at: str | None
    # När regeln lämnade Larm efter kvitteringen, eller None medan den är Larm.
    released: str | None


def _parse(value: str | None) -> datetime | None:
    return None if value is None else dt_util.parse_datetime(value, raise_on_error=True)


class Acknowledgement:
    """Kvitteringen av en Rules Larm, med «larma igen» och fladdergränsen ur regeln.

    on_change anropas när kvitteringen har gått ut medan nivån står still, så att regeln kan
    visa det. När den går ut vid en omräkning ser regeln det på attributen.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        rule: Mapping[str, Any],
        saved: SavedAcknowledgement | None,
        on_change: Callable[[], None],
    ) -> None:
        self._hass = hass
        self._realarm = _realarm_after(rule)
        self._flap = _flap_limit(rule)
        self._on_change = on_change
        self._acknowledged = saved is not None
        self._realarm_at = _parse(saved["realarm_at"]) if saved else None
        self._released = _parse(saved["released"]) if saved else None
        self._unsub_timer: CALLBACK_TYPE | None = None
        # När timern går, så att den inte byggs om vid varje omräkning.
        self._timer_at: datetime | None = None

    @property
    def saved(self) -> SavedAcknowledgement | None:
        if not self._acknowledged:
            return None
        return SavedAcknowledgement(
            realarm_at=self._realarm_at.isoformat() if self._realarm_at else None,
            released=self._released.isoformat() if self._released else None,
        )

    def attributes(self, level: object) -> dict[str, Any]:
        """Attributen acknowledged och realarm_at för regelns nivå. Kvitteringen syns bara på
        Larm."""
        acknowledged = self._acknowledged and level == ALARM
        return {
            "acknowledged": acknowledged,
            "realarm_at": (
                self._realarm_at.isoformat() if acknowledged and self._realarm_at else None
            ),
        }

    @callback
    def async_acknowledge(self) -> None:
        """Kvittera Larmet, som regeln har nu."""
        self._acknowledged = True
        self._realarm_at = dt_util.utcnow() + self._realarm if self._realarm else None
        self._released = None
        self._async_schedule()

    @callback
    def async_level(self, level: str) -> None:
        """Regelns nivå efter en omräkning. Ett avbrott eller en «larma igen» som redan har gått
        ut räknas innan nivån ändrar dem, också när det skedde under en omstart."""
        if self._acknowledged:
            self._async_expired()
        if level == ALARM:
            self._released = None
        elif self._released is None:
            self._released = dt_util.utcnow()
        if self._acknowledged and not self._async_expired():
            self._async_schedule()

    @callback
    def async_unload(self) -> None:
        if self._unsub_timer is not None:
            self._unsub_timer()
        self._unsub_timer = None
        self._timer_at = None

    def _deadline(self) -> datetime | None:
        """När kvitteringen går ut, om inget ändras."""
        deadlines = [self._realarm_at] if self._realarm_at else []
        if self._released is not None:
            deadlines.append(self._released + self._flap)
        return min(deadlines, default=None)

    @callback
    def _async_expired(self) -> bool:
        """Glöm kvitteringen om den har gått ut, och säg om den har det."""
        deadline = self._deadline()
        if deadline is None or deadline > dt_util.utcnow():
            return False
        self.async_unload()
        self._acknowledged = False
        self._realarm_at = None
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

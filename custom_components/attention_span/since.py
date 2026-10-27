"""När en Rules villkor och visade tillstånd började gälla, och kvitteringen av dess Larm,
sparat i HA:s Store så att det överlever en omstart.

Källentiteterna får nya last_changed när deras integrationer laddas efter en omstart, så
HA:s egna villkor och tider räknar då från omstarten.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import Any, TypedDict

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN
from .lifecycle import SavedAcknowledgement

STORAGE_KEY = f"{DOMAIN}.since"
STORAGE_VERSION = 1
# Ändringar samlas ihop i så här många sekunder innan de skrivs. HA skriver det som
# återstår när den stängs av.
SAVE_DELAY = 10

DATA_SINCE: HassKey[SinceStore] = HassKey(f"{DOMAIN}_since")


class SavedState(TypedDict):
    """Tillståndet som Typen Status visar och när entiteten fick det."""

    entity: str
    state: str
    since: str


class SavedRule(TypedDict, total=False):
    """Det som sparas för en Rule. Tider i ISO 8601."""

    # Villkoret med tid, utan tiden, som JSON -> när det började gälla.
    conditions: dict[str, str]
    state: SavedState
    # Saknas när Larmet inte är kvitterat.
    acknowledgement: SavedAcknowledgement


class SinceStore:
    """Det som ska överleva en omstart, per Rule (subentryns id)."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store = Store[dict[str, Any]](hass, STORAGE_VERSION, STORAGE_KEY)
        self._rules: dict[str, SavedRule] = {}

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        self._rules = stored["rules"] if stored else {}

    def get(self, rule: str) -> SavedRule:
        return copy.deepcopy(self._rules.get(rule, SavedRule()))

    @callback
    def async_set(self, rule: str, data: SavedRule) -> None:
        if self._rules.get(rule) == data:
            return
        self._rules[rule] = copy.deepcopy(data)
        self._async_save()

    @callback
    def async_keep(self, rules: Iterable[str]) -> None:
        """Glöm reglerna som inte finns längre."""
        kept = {rule: self._rules[rule] for rule in rules if rule in self._rules}
        if kept != self._rules:
            self._rules = kept
            self._async_save()

    async def async_remove(self) -> None:
        self._rules = {}
        await self._store.async_remove()

    @callback
    def _async_save(self) -> None:
        self._store.async_delay_save(lambda: {"rules": self._rules}, SAVE_DELAY)

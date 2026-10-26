"""Rule evaluation: vilken nivå en Rule har just nu (ADR 0002).

Villkoren är Home Assistants egna, så att samma villkorsväljare och samma
villkorstyper fungerar som i automationer.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConditionError
from homeassistant.helpers import condition
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.condition import ConditionChecker
from homeassistant.helpers.event import async_track_time_interval

from .const import ALWAYS, HIDDEN, LEVELS

_LOGGER = logging.getLogger(__name__)

# Hur ofta villkor som HA inte kan bevaka räknas om: tid («i 2 h»), klockslag och
# templates. Samma intervall som HA:s egen prenumeration på villkor.
POLL_INTERVAL = timedelta(seconds=1)


async def async_validate_conditions(hass: HomeAssistant, conditions: list[Any]) -> list[Any]:
    """Kontrollera villkor som HA gör för automationer.

    Ger probatio.Invalid eller HomeAssistantError för ogiltiga villkor. Indata ändras inte,
    så att villkoren kan sparas som användaren skrev dem.
    """
    validated = cv.CONDITIONS_SCHEMA(copy.deepcopy(conditions))
    return await condition.async_validate_conditions_config(hass, validated)


async def _async_checker(hass: HomeAssistant, conditions: list[Any]) -> ConditionChecker:
    validated = await async_validate_conditions(hass, conditions)
    return await condition.async_from_config(
        hass, {"condition": "and", "conditions": validated}
    )


class RuleLevel:
    """Räknar fram en Rules nivå ur dess nivåvillkor och Dölj när.

    Den allvarligaste nivån vars villkor gäller vinner, oavsett ordning, och Dölj när
    slår allt. Gäller inget är regeln dold.
    """

    def __init__(
        self,
        name: str,
        levels: dict[str, ConditionChecker | None],
        hide: ConditionChecker | None,
    ) -> None:
        self._name = name
        # Nivå -> villkoret, eller None för «Alltid». Nivåer utan villkor saknas.
        self._levels = levels
        self._hide = hide
        self._failing = False

    @classmethod
    async def async_create(
        cls,
        hass: HomeAssistant,
        name: str,
        levels: Mapping[str, Any],
        hide: list[Any] | None,
    ) -> RuleLevel:
        """Bygg villkoren ur regelns konfiguration.

        Ger probatio.Invalid eller HomeAssistantError om ett villkor inte går att bygga.
        """
        checkers: dict[str, ConditionChecker | None] = {}
        for level, value in levels.items():
            checkers[level] = None if value == ALWAYS else await _async_checker(hass, value)
        return cls(name, checkers, await _async_checker(hass, hide) if hide else None)

    def evaluate(self) -> str:
        """Nivån som gäller just nu, eller dold."""
        errors: list[str] = []
        level = HIDDEN
        if self._hide is None or not self._holds(self._hide, errors):
            level = next(
                (
                    level
                    for level in LEVELS
                    if level in self._levels
                    and (
                        (checker := self._levels[level]) is None or self._holds(checker, errors)
                    )
                ),
                HIDDEN,
            )
        # Ett villkor som inte går att räkna ut gäller inte. Säg det när det börjar, inte vid
        # varje omräkning, så att loggen inte fylls medan felet består.
        if errors and not self._failing:
            _LOGGER.warning(
                "Villkoren i regeln %s gick inte att räkna ut:\n%s", self._name, "\n".join(errors)
            )
        self._failing = bool(errors)
        return level

    @staticmethod
    def _holds(checker: ConditionChecker, errors: list[str]) -> bool:
        try:
            return checker.async_check() is True
        except ConditionError as err:
            errors.append(str(err))
            return False

    def _checkers(self) -> list[ConditionChecker]:
        checkers = [checker for checker in self._levels.values() if checker is not None]
        return checkers if self._hide is None else [*checkers, self._hide]

    async def async_track(self, hass: HomeAssistant, action: Callable[[], None]) -> CALLBACK_TYPE:
        """Anropa action när nivån kan ha ändrats: när en entitet i villkoren ändras, och
        på timer för villkor som beror på tid eller templates."""
        unsubs = [await checker.async_track_changes(action) for checker in self._checkers()]
        if any(checker.needs_polling for checker in self._checkers()):

            @callback
            def poll(_: datetime) -> None:
                action()

            unsubs.append(
                async_track_time_interval(
                    hass, poll, POLL_INTERVAL, name=f"attention_span {self._name}"
                )
            )

        @callback
        def unsubscribe() -> None:
            for unsub in unsubs:
                unsub()

        return unsubscribe

    def async_unload(self) -> None:
        for checker in self._checkers():
            checker.async_unload()

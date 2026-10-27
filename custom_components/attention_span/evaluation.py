"""Rule evaluation: vilken nivå en Rule har just nu (ADR 0002).

Villkoren är Home Assistants egna, så att samma villkorsväljare och samma
villkorstyper fungerar som i automationer.
"""

from __future__ import annotations

import copy
import json
import logging
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any, Unpack, override

import voluptuous as vol
from homeassistant.const import (
    ATTR_RESTORED,
    CONF_CONDITION,
    CONF_CONDITIONS,
    CONF_ENABLED,
    CONF_FOR,
    CONF_OPTIONS,
    CONF_TARGET,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConditionError, ConditionErrorMessage, TemplateError
from homeassistant.helpers import condition
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.condition import (
    AndConditionChecker,
    CompoundConditionChecker,
    ConditionChecker,
    ConditionCheckParams,
    EntityConditionBase,
    NotConditionChecker,
    OrConditionChecker,
)
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.target import TargetSelection, async_extract_referenced_entity_ids
from homeassistant.helpers.template import render_complex
from homeassistant.util import dt as dt_util

from .const import ALWAYS, HIDDEN, LEVELS

_LOGGER = logging.getLogger(__name__)

# Hur ofta villkor som HA inte kan bevaka räknas om: tid («i 2 h»), klockslag och
# templates. Samma intervall som HA:s egen prenumeration på villkor.
POLL_INTERVAL = timedelta(seconds=1)


async def async_validate_conditions(hass: HomeAssistant, conditions: list[Any]) -> list[Any]:
    """Kontrollera villkor som HA gör för automationer.

    Ger vol.Invalid eller HomeAssistantError för ogiltiga villkor. Indata ändras inte,
    så att villkoren kan sparas som användaren skrev dem.
    """
    validated = cv.CONDITIONS_SCHEMA(copy.deepcopy(conditions))
    return await condition.async_validate_conditions_config(hass, validated)


async def _async_checker(hass: HomeAssistant, config: Any) -> ConditionChecker:
    (validated,) = await async_validate_conditions(hass, [config])
    return await condition.async_from_config(hass, validated)


# Villkoren som består av andra villkor, med HA:s egna klasser så att de räknas som i HA.
_COMPOUNDS: dict[str, type[CompoundConditionChecker]] = {
    "and": AndConditionChecker,
    "or": OrConditionChecker,
    "not": NotConditionChecker,
}


def _duration(config: Any) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Var villkorets tid («i 2 h») står, och villkoret utan den; None utan tid.

    Tiden står i for, eller i options.for för villkoren som integrationer erbjuder. Det
    första är dicten med for, det andra hela villkoret utan tiden.
    """
    if not isinstance(config, dict):
        return None
    if CONF_FOR in config:
        return config, {key: value for key, value in config.items() if key != CONF_FOR}
    options = config.get(CONF_OPTIONS)
    if isinstance(options, dict) and CONF_FOR in options:
        untimed = {key: value for key, value in options.items() if key != CONF_FOR}
        return options, config | {CONF_OPTIONS: untimed}
    return None


def _compound(config: Any) -> tuple[str, list[Any]] | None:
    """Vilket slags sammansatt villkor det är och dess villkor, eller None.

    Ett sammansatt villkor som är avstängt, eller avstängt med en template, byggs av HA som
    det är; villkor med tid i det räknar då från källentitetens last_changed.
    """
    config = cv.expand_condition_shorthand(config)
    if (
        isinstance(config, dict)
        and config.get(CONF_CONDITION) in _COMPOUNDS
        and config.get(CONF_ENABLED, True) is True
        and isinstance(config.get(CONF_CONDITIONS), list)
    ):
        return config[CONF_CONDITION], config[CONF_CONDITIONS]
    return None


def _has_duration(config: Any) -> bool:
    if (compound := _compound(config)) is not None:
        return any(_has_duration(part) for part in compound[1])
    return _duration(config) is not None


async def _async_build(
    hass: HomeAssistant, config: Any, started: dict[str, datetime]
) -> tuple[ConditionChecker, list[_LastingCondition]]:
    """Bygg villkoret så att villkor med tid räknar från när de började gälla.

    started är när villkoren med tid började gälla och delas av dem. Ger också villkoren
    med tid, så att regeln kan hålla reda på när de började.
    """
    if not _has_duration(config):
        return await _async_checker(hass, config), []
    if (compound := _compound(config)) is None:
        timed = await _LastingCondition.async_create(hass, config, started)
        return timed, [timed]
    kind, parts = compound
    checkers: list[ConditionChecker] = []
    lasting: list[_LastingCondition] = []
    for part in parts:
        checker, part_lasting = await _async_build(hass, part, started)
        checkers.append(checker)
        lasting.extend(part_lasting)
    compound_checker = _COMPOUNDS[kind](hass, checkers)
    await compound_checker.async_setup()
    return compound_checker, lasting


class _LastingCondition(ConditionChecker):
    """Ett villkor med tid («i 2 h») som räknar från när villkoret började gälla.

    HA räknar tiden från källentitetens last_changed, som sätts om när källans integration
    laddas efter en omstart. Här räknas den i stället från när villkoret utan tid började
    gälla, som regeln sparar och ger tillbaka efter en omstart.

    När ett tillstånd matchar men flera entiteter kan göra det (match: any) räknas tiden
    från när någon av dem började, inte från när den som matchar nu började som i HA.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        key: str,
        timed: ConditionChecker,
        untimed: ConditionChecker,
        duration: Any,
        entities: set[str],
        target: TargetSelection,
        started: dict[str, datetime],
    ) -> None:
        super().__init__(hass)
        # Villkoret utan tid. Villkor som bara skiljer sig i tid har samma nyckel och delar
        # därför när de började gälla, också efter en omstart eller en ändring av regeln.
        self._key = key
        self._timed = timed
        self._untimed = untimed
        self._duration = duration
        self._entities = entities
        # Villkorets target. Vilka entiteter ett område, en enhet, en våning eller en etikett
        # pekar ut kan ändras, så de slås upp vid varje kontroll.
        self._target = target
        # Nyckel -> när villkoret utan tid började gälla. Saknas nyckeln gäller det inte.
        self._started = started

    @classmethod
    async def async_create(
        cls, hass: HomeAssistant, config: dict[str, Any], started: dict[str, datetime]
    ) -> _LastingCondition:
        duration = _duration(config)
        assert duration is not None
        untimed_config = duration[1]
        (validated,) = await async_validate_conditions(hass, [config])
        timed_validated = validated
        if CONF_FOR not in validated:
            timed_validated = validated[CONF_OPTIONS]
        checker = cls(
            hass,
            json.dumps(untimed_config, sort_keys=True),
            await condition.async_from_config(hass, validated),
            await _async_checker(hass, untimed_config),
            timed_validated[CONF_FOR],
            condition.async_extract_entities(validated),
            TargetSelection(validated.get(CONF_TARGET, {})),
            started,
        )
        await checker.async_setup()
        return checker

    @property
    def key(self) -> str:
        return self._key

    @property
    @override
    def needs_polling(self) -> bool:
        return True

    @override
    async def _async_track_changes(self, action: Callable[[], None]) -> CALLBACK_TYPE:
        return await self._untimed.async_track_changes(action)

    @override
    def _async_unload(self) -> None:
        self._timed.async_unload()
        self._untimed.async_unload()

    def _cutoff(self) -> datetime:
        """Villkoret gäller om det började gälla före den här tiden."""
        try:
            duration = cv.positive_time_period(render_complex(self._duration, None))
        except (TemplateError, vol.Invalid) as err:
            raise ConditionErrorMessage("for", f"tiden går inte att räkna ut: {err}") from err
        return dt_util.utcnow() - duration

    def _waiting(self) -> bool:
        """Om en entitet i villkoret väntar på att dess integration ska laddas.

        HA visar den då som otillgänglig med restored: true, vilket inte säger något om
        villkoret. Till dess gäller villkoret som före omstarten, och när det började gälla
        sparas tills entiteten har ett riktigt tillstånd.
        """
        entities = self._entities
        # Ett villkor på target tittar bara på de utpekade entiteter som det självt väljer ut,
        # till exempel lamporna i området, som i HA.
        if isinstance(self._untimed, EntityConditionBase):
            targeted = async_extract_referenced_entity_ids(
                self._hass,
                self._target,
                expand_group=False,
                primary_entities_only=self._untimed._primary_entities_only,
            )
            entities = self._untimed.entity_filter(
                targeted.referenced | targeted.indirectly_referenced
            )
        return any(
            (state := self._hass.states.get(entity_id)) is not None
            and state.attributes.get(ATTR_RESTORED) is True
            for entity_id in entities
        )

    @callback
    def async_update(self) -> None:
        """Håll reda på när villkoret började gälla. Anropas före varje kontroll."""
        if self._waiting():
            return
        # Ett villkor som inte går att räkna ut gäller inte, som i HA.
        try:
            holds = self._untimed.async_check() is True
        except ConditionError:
            holds = False
        if not holds:
            self._started.pop(self._key, None)
            return
        since = self._started.setdefault(self._key, dt_util.utcnow())
        # HA kan veta att villkoret har gällt längre än så, till exempel när regeln läggs
        # till och källentiteten redan har haft sitt tillstånd länge.
        try:
            if self._timed.async_check() is True:
                self._started[self._key] = min(since, self._cutoff())
        except ConditionError:
            pass

    @override
    def _async_check(self, **kwargs: Unpack[ConditionCheckParams]) -> bool | None:
        # Ett avstängt villkor (enabled) gäller varken eller, som i HA.
        if (held := self._timed.async_check(**kwargs)) is not False:
            return held
        since = self._started.get(self._key)
        return since is not None and since < self._cutoff()


class RuleLevel:
    """Räknar fram en Rules nivå ur dess nivåvillkor och dölj-villkor.

    Den allvarligaste nivån vars villkor gäller vinner, oavsett ordning, och dölj-villkoret
    slår allt. Gäller inget är regeln dold.
    """

    def __init__(
        self,
        name: str,
        levels: dict[str, ConditionChecker | None],
        hide: ConditionChecker | None,
        lasting: list[_LastingCondition],
        started: dict[str, datetime],
    ) -> None:
        self._name = name
        # Nivå -> villkoret, eller None för «Alltid». Nivåer utan villkor saknas.
        self._levels = levels
        self._hide = hide
        # Villkoren med tid, var de än står bland nivåvillkoren och dölj-villkoret, och när
        # de började gälla.
        self._lasting = lasting
        self._started = started
        self._failing = False

    @classmethod
    async def async_create(
        cls,
        hass: HomeAssistant,
        name: str,
        levels: Mapping[str, Any],
        hide: list[Any] | None,
        started: Mapping[str, datetime],
    ) -> RuleLevel:
        """Bygg villkoren ur regelns konfiguration.

        started är när villkoren med tid började gälla, som started gav förra gången. De
        som fortfarande gäller vid första omräkningen räknar därifrån; övriga har släppt.
        Ger vol.Invalid eller HomeAssistantError om ett villkor inte går att bygga.
        """
        since = dict(started)
        lasting: list[_LastingCondition] = []

        async def build(conditions: list[Any]) -> ConditionChecker:
            checker, built = await _async_build(
                hass, {CONF_CONDITION: "and", CONF_CONDITIONS: conditions}, since
            )
            lasting.extend(built)
            return checker

        checkers: dict[str, ConditionChecker | None] = {}
        for level, value in levels.items():
            checkers[level] = None if value == ALWAYS else await build(value)
        hide_checker = await build(hide) if hide else None
        # Det som sparades för villkor som inte finns längre glöms.
        for key in since.keys() - {timed.key for timed in lasting}:
            del since[key]
        return cls(name, checkers, hide_checker, lasting, since)

    @property
    def started(self) -> dict[str, datetime]:
        """När villkoren med tid som gäller just nu började gälla."""
        return dict(self._started)

    def evaluate(self) -> str:
        """Nivån som gäller just nu, eller dold."""
        # Alla villkor med tid följs, också de som inte behöver kontrolleras den här gången.
        for timed in self._lasting:
            timed.async_update()
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

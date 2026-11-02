"""Rule evaluation: vilken nivå en Rule har just nu (ADR 0002).

Villkoren är Home Assistants egna, så att samma villkorsväljare och samma
villkorstyper fungerar som i automationer.
"""

from __future__ import annotations

import contextvars
import copy
import json
import logging
from collections.abc import Callable, Collection, Mapping
from datetime import datetime, timedelta
from datetime import time as dt_time
from typing import Any, Unpack, override

import voluptuous as vol
from homeassistant.const import (
    ATTR_RESTORED,
    CONF_AFTER,
    CONF_BEFORE,
    CONF_CONDITION,
    CONF_CONDITIONS,
    CONF_ENABLED,
    CONF_FOR,
    CONF_OPTIONS,
    CONF_TARGET,
    CONF_VALUE_TEMPLATE,
    EVENT_CORE_CONFIG_UPDATE,
)
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback, valid_entity_id
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
from homeassistant.helpers.event import (
    TrackTemplate,
    TrackTemplateResult,
    async_track_point_in_utc_time,
    async_track_template_result,
    async_track_time_interval,
)
from homeassistant.helpers.target import TargetSelection, async_extract_referenced_entity_ids
from homeassistant.helpers.template import render_complex
from homeassistant.helpers.trace import trace_clear
from homeassistant.util import dt as dt_util

from .const import ALWAYS, HIDDEN, LEVELS

_LOGGER = logging.getLogger(__name__)

# Villkor räknas om när något kan ha ändrat utfallet, inte varje sekund (ADR 0005): när en
# entitet ändras, när tiden («i 2 h») går ut, vid ett klockslags gränser, midnatt och byte av
# UTC-offset, och när det som en template läser ändras. Villkor som varken HA eller
# AttentionSpan kan bevaka kontrolleras som reserv så här ofta, samma intervall som HA:s egen
# prenumeration på villkor: solen, månen, device, zon, numeric_state med value_template,
# klockslag från en entitet, en tid som är en template och okända villkor från integrationer.
# Så kontrolleras också ett villkor med tid medan dess start är obekräftad.
POLL_INTERVAL = timedelta(seconds=1)
# Hur ofta en template som läser alla tillstånd räknas om som oftast, i sekunder. HA:s egna
# template-entiteter använder 60 s; 1 s är lika ofta som kontrollen varje sekund.
TEMPLATE_RATE_LIMIT = 1.0


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


class _Wake:
    """En timer som väcker regeln vid en tidpunkt. Att ställa den tar bort den förra."""

    def __init__(self, hass: HomeAssistant, action: Callable[[], None]) -> None:
        self._hass = hass
        self._action = action
        self._unsub: CALLBACK_TYPE | None = None

    @callback
    def async_set(self, at: datetime | None) -> None:
        """Väck vid at, eller inte alls med None."""
        self.async_cancel()
        if at is not None:
            self._unsub = async_track_point_in_utc_time(self._hass, self._woken, at)

    @callback
    def async_cancel(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    @callback
    def _woken(self, _: datetime) -> None:
        self._unsub = None
        self._action()


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


def _follower(config: Any) -> type[_FollowedCondition] | None:
    """Klassen som följer ett villkor utan tid som HA bara kan kontrollera varje sekund.

    None för villkor som HA bevakar själv, och för dem som kontrolleras varje sekund som
    reserv, till exempel solen.
    """
    if not isinstance(config, dict) or config.get(CONF_ENABLED, True) is not True:
        return None
    if config.get(CONF_CONDITION) == "template":
        return _TemplateCondition
    # Ett klockslag som läses från en entitet kan ändras när som helst.
    if config.get(CONF_CONDITION) == "time" and not any(
        isinstance(value := config.get(key), str) and valid_entity_id(value)
        for key in (CONF_AFTER, CONF_BEFORE)
    ):
        return _TimeCondition
    return None


def _built_here(config: Any) -> bool:
    """Om villkoret, eller ett villkor i det, byggs här i stället för av HA: villkor med tid
    och villkor som AttentionSpan följer själv."""
    if (compound := _compound(config)) is not None:
        return any(_built_here(part) for part in compound[1])
    return _duration(config) is not None or _follower(config) is not None


async def _async_build(
    hass: HomeAssistant, config: Any, started: dict[str, datetime], unseen: set[str]
) -> tuple[ConditionChecker, list[_LastingCondition]]:
    """Bygg villkoret så att villkor med tid räknar från när de började gälla, och så att
    templates och klockslag räknas om när de kan ha ändrats i stället för varje sekund.

    started är när villkoren med tid började gälla och unseen de villkor vars start sattes
    utan att övergången sågs; båda delas av villkoren med tid. Ger också villkoren med tid,
    så att regeln kan hålla reda på när de började.
    """
    if not _built_here(config):
        return await _async_checker(hass, config), []
    if (compound := _compound(config)) is None:
        if (follower := _follower(config)) is not None:
            return await follower.async_create(hass, config), []
        timed = await _LastingCondition.async_create(hass, config, started, unseen)
        return timed, [timed]
    kind, parts = compound
    checkers: list[ConditionChecker] = []
    lasting: list[_LastingCondition] = []
    for part in parts:
        checker, part_lasting = await _async_build(hass, part, started, unseen)
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
        unseen: set[str],
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
        # Nycklarna vars start sattes utan att övergången sågs, till exempel när regeln lades
        # till medan villkoret redan gällde. HA kan då veta att villkoret började tidigare
        # (se async_update). Delas som started, eftersom starten gäller alla med nyckeln.
        self._unseen = unseen
        # Väcker regeln när tiden går ut, medan regeln följer villkoret.
        self._wake: _Wake | None = None

    @classmethod
    async def async_create(
        cls,
        hass: HomeAssistant,
        config: dict[str, Any],
        started: dict[str, datetime],
        unseen: set[str],
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
            unseen,
        )
        await checker.async_setup()
        return checker

    @property
    def key(self) -> str:
        return self._key

    @property
    @override
    def needs_polling(self) -> bool:
        # En tid som är en template kan räknas ut olika när som helst.
        return self._untimed.needs_polling or not isinstance(self._duration, timedelta)

    @override
    async def _async_track_changes(self, action: Callable[[], None]) -> CALLBACK_TYPE:
        unsub = await self._untimed.async_track_changes(action)
        wake = self._wake = _Wake(self._hass, action)
        self.async_schedule()

        @callback
        def unsubscribe() -> None:
            unsub()
            wake.async_cancel()
            self._wake = None

        return unsubscribe

    @callback
    def async_schedule(self) -> None:
        """Väck regeln i första ögonblicket då villkoret gäller för att tiden har gått.

        Anropas efter varje kontroll. Villkoret gäller när det började gälla före nu minus
        tiden, alltså 1 µs efter gränsen. Medan starten är obekräftad väcks regeln också varje
        sekund, tills tiden har gått, så att den ser när HA:s eget villkor gäller. Då har tiden
        också gått, eftersom starten flyttas dit.
        """
        if self._wake is not None:
            self._wake.async_set(self._next_wake())

    def _next_wake(self) -> datetime | None:
        since = self._started.get(self._key)
        if since is None or not isinstance(self._duration, timedelta):
            return None
        now = dt_util.utcnow()
        at = since + self._duration + timedelta(microseconds=1)
        if at <= now:
            return None
        return min(at, now + POLL_INTERVAL) if self._key in self._unseen else at

    @override
    def _async_unload(self) -> None:
        if self._wake is not None:
            self._wake.async_cancel()
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
        # När villkoret slutar gälla ses nästa övergång.
        if not holds:
            self._started.pop(self._key, None)
            self._unseen.discard(self._key)
            return
        since = self._started.setdefault(self._key, dt_util.utcnow())
        # HA kan veta att villkoret har gällt längre än så, till exempel när regeln läggs
        # till och källentiteten redan har haft sitt tillstånd länge. HA säger det bara som ja
        # eller nej för just den här tiden, så en obekräftad start kontrolleras varje sekund
        # tills HA bekräftar eller tiden har gått (se async_schedule). Den förblir obekräftad,
        # eftersom ett villkor med längre tid och samma nyckel kan ha börjat ännu tidigare.
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


class _FollowedCondition(ConditionChecker):
    """HA:s eget villkor, som följs här för att HA bara kan kontrollera det varje sekund."""

    def __init__(self, hass: HomeAssistant, checker: ConditionChecker, config: Any) -> None:
        super().__init__(hass)
        self._checker = checker
        # Villkoret som HA har validerat det.
        self._config = config

    @classmethod
    async def async_create(cls, hass: HomeAssistant, config: Any) -> _FollowedCondition:
        (validated,) = await async_validate_conditions(hass, [config])
        checker = cls(hass, await condition.async_from_config(hass, validated), validated)
        await checker.async_setup()
        return checker

    @property
    @override
    def needs_polling(self) -> bool:
        return False

    @override
    def _async_check(self, **kwargs: Unpack[ConditionCheckParams]) -> bool | None:
        return self._checker.async_check(**kwargs)

    @override
    def _async_unload(self) -> None:
        self._checker.async_unload()


class _TemplateCondition(_FollowedCondition):
    """En template räknas om när det den läser ändras, som HA:s template-entiteter.

    En template som läser tiden (now()) räknas om en gång i minuten, på sekund 0, och en
    som läser alla tillstånd högst en gång i sekunden. Det som HA inte följer, till exempel
    area_entities() eller random, räknas om först när något som följs ändras.
    """

    @override
    async def _async_track_changes(self, action: Callable[[], None]) -> CALLBACK_TYPE:
        @callback
        def rendered(_: Any, __: list[TrackTemplateResult]) -> None:
            action()

        @callback
        def ignore(_: int, __: str) -> None:
            """Fel loggas av regeln när villkoret kontrolleras, en gång tills det är rättat."""

        info = async_track_template_result(
            self._hass,
            [TrackTemplate(self._config[CONF_VALUE_TEMPLATE], None, TEMPLATE_RATE_LIMIT)],
            rendered,
            log_fn=ignore,
        )
        return info.async_remove


def _next_offset_change(start: datetime, end: datetime) -> datetime | None:
    """Första ögonblicket efter start då hemmets tidszon byter UTC-offset, om det är före end."""
    zone = dt_util.get_default_time_zone()

    def offset(moment: datetime) -> timedelta | None:
        return moment.astimezone(zone).utcoffset()

    if offset(start) == offset(end):
        return None
    low, high = start, end
    while high - low > timedelta(microseconds=1):
        middle = low + (high - low) / 2
        if offset(middle) == offset(start):
            low = middle
        else:
            high = middle
    return high


class _TimeCondition(_FollowedCondition):
    """Ett klockslag räknas om vid sina gränser, vid midnatt (veckodagarna), när hemmets
    tidszon byter UTC-offset (sommartid) och när tidszonen byts.

    Vid sommartid kan utfallet ändras utan att en gräns passeras: efter 02:30 gäller redan
    03:00 den natt då 02:30 inte finns, och slutar gälla 02:00 den natt då 02:30 kommer två
    gånger.
    """

    def _next_change(self, now: datetime) -> datetime:
        """Första ögonblicket efter now då villkorets utfall kan ändras."""
        bounds = [
            bound
            for bound in (self._config.get(CONF_AFTER), self._config.get(CONF_BEFORE))
            if isinstance(bound, dt_time)
        ] + [dt_time(0)]
        zone = dt_util.get_default_time_zone()
        today = now.astimezone(zone).date()
        # Varje gräns i dag och i morgon, båda gångerna när klockan ställs tillbaka. Räknat
        # i UTC: aritmetik på lokal tid tappar vilken av gångerna det är (fold).
        moments = [
            datetime.combine(day, bound, zone).replace(fold=fold).astimezone(dt_util.UTC)
            for day in (today, today + timedelta(days=1))
            for bound in bounds
            for fold in (0, 1)
        ]
        at = min(moment for moment in moments if moment > now)
        return _next_offset_change(now, at) or at

    @override
    async def _async_track_changes(self, action: Callable[[], None]) -> CALLBACK_TYPE:
        @callback
        def changed() -> None:
            wake.async_set(self._next_change(dt_util.utcnow()))
            action()

        @callback
        def config_changed(_: Event) -> None:
            # Tidszonen kan ha bytts.
            changed()

        wake = _Wake(self._hass, changed)
        wake.async_set(self._next_change(dt_util.utcnow()))
        unsub_config = self._hass.bus.async_listen(EVENT_CORE_CONFIG_UPDATE, config_changed)

        @callback
        def unsubscribe() -> None:
            unsub_config()
            wake.async_cancel()

        return unsubscribe


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
        unseen: set[str],
    ) -> None:
        self._name = name
        # Nivå -> villkoret, eller None för «Alltid». Nivåer utan villkor saknas.
        self._levels = levels
        self._hide = hide
        # Villkoren med tid, var de än står bland nivåvillkoren och dölj-villkoret, och när
        # de började gälla.
        self._lasting = lasting
        self._started = started
        self._unseen = unseen
        self._failing = False

    @classmethod
    async def async_create(
        cls,
        hass: HomeAssistant,
        name: str,
        levels: Mapping[str, Any],
        hide: list[Any] | None,
        started: Mapping[str, datetime],
        unconfirmed: Collection[str],
    ) -> RuleLevel:
        """Bygg villkoren ur regelns konfiguration.

        started är när villkoren med tid började gälla, som started gav förra gången. De
        som fortfarande gäller vid första omräkningen räknar därifrån; övriga har släppt.
        unconfirmed är de av dem vars start är obekräftad, som unconfirmed gav förra gången;
        övriga räknas som sedda. Ett villkor utan sparad start som gäller vid första
        omräkningen får en obekräftad start.
        Ger vol.Invalid eller HomeAssistantError om ett villkor inte går att bygga.
        """
        since = dict(started)
        unseen: set[str] = set()
        lasting: list[_LastingCondition] = []

        async def build(conditions: list[Any]) -> ConditionChecker:
            checker, built = await _async_build(
                hass, {CONF_CONDITION: "and", CONF_CONDITIONS: conditions}, since, unseen
            )
            lasting.extend(built)
            return checker

        checkers: dict[str, ConditionChecker | None] = {}
        for level, value in levels.items():
            checkers[level] = None if value == ALWAYS else await build(value)
        hide_checker = await build(hide) if hide else None
        # Det som sparades för villkor som inte finns längre glöms.
        keys = {timed.key for timed in lasting}
        for key in since.keys() - keys:
            del since[key]
        unseen.update(keys - since.keys(), keys & set(unconfirmed))
        return cls(name, checkers, hide_checker, lasting, since, unseen)

    @property
    def started(self) -> dict[str, datetime]:
        """När villkoren med tid som gäller just nu började gälla."""
        return dict(self._started)

    @property
    def unconfirmed(self) -> set[str]:
        """De av villkoren i started vars start sattes utan att övergången sågs."""
        return self._unseen & self._started.keys()

    def evaluate(self) -> str:
        """Nivån som gäller just nu, eller dold."""
        # HA sparar varje villkorskontroll i en trace. Utanför en automation töms den aldrig,
        # och under en automation hamnar kontrollen i automationens trace. Kontrollerna görs
        # därför i en egen kopia av kontexten med en tom trace, som försvinner efteråt.
        return contextvars.copy_context().run(self._evaluate)

    def _evaluate(self) -> str:
        # Bara i kopian: kontexten som anropade evaluate behåller sin trace.
        trace_clear()
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
        # En timer behåller kontexten den ställdes i tills den går. Töm tracen först, så att
        # timrarna inte håller kvar kontrollernas spår.
        trace_clear()
        for timed in self._lasting:
            timed.async_schedule()
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
        """Anropa action när nivån kan ha ändrats: när något i villkoren ändras eller en
        timer går ut, och varje sekund för villkor som inte kan bevakas."""
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

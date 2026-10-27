"""Orsaken: texten som säger varför en notis visas, färdigrenderad i attributet reason.

Orsaken är en Home Assistant-template, antingen en färdig mall för regelns Typ eller en
egen. Båda renderas och bevakas av HA:s templatemotor, så att orsaken ändras när det den
läser ändras och varje minut när den läser klockan. De färdiga mallarna tar sina ord ur
översättningarna (kategorin reason), så att texten blir på hemmets språk (ADR 0001).

Variablerna som varje orsak kan läsa:
- entity: entiteten som notisen visar, eller None
- entities: alla entiteter som notisen visar
- state_since: när den visade entiteten fick sitt tillstånd, också över en omstart; bara Status
- occurrences: de närmaste tillfällena, som i attributet occurrences; bara Kommande
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, override

from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import TemplateError
from homeassistant.helpers.event import (
    TrackTemplate,
    TrackTemplateResult,
    TrackTemplateResultInfo,
    async_track_template_result,
)
from homeassistant.helpers.template import RenderInfo, Template
from homeassistant.helpers.translation import async_get_translations
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    TYPE_CUSTOM,
    TYPE_PROGRESS,
    TYPE_STATUS,
    TYPE_UPCOMING,
    TYPE_VALUE,
)

# Valen för orsaken i formuläret, utöver de färdiga mallarna.
REASON_NONE = "none"
REASON_CUSTOM = "custom"

# Hur länge, i hela minuter under en timme, i timmar under två dygn och därefter i dygn,
# som kortet räknar. Orden kommer ur variabeln words.
_DURATION = (
    "{%- macro duration(minutes) -%}"
    "{%- set m = [minutes | int(0), 0] | max -%}"
    "{%- if m < 60 -%}{{ words.minutes | replace('{count}', m) }}"
    "{%- elif m < 48 * 60 -%}{{ words.hours | replace('{count}', m // 60) }}"
    "{%- else -%}{{ words.days | replace('{count}', m // (24 * 60)) }}"
    "{%- endif -%}"
    "{%- endmacro -%}"
)

# Tillståndet på hemmets språk. HA översätter inte unavailable och unknown, så de orden
# kommer ur variabeln words, som kortet visar dem.
_STATE = (
    "{%- macro shown_state(entity) -%}"
    "{%- set raw = states(entity) -%}"
    "{{ words[raw] if raw in ('unavailable', 'unknown') else state_translated(entity) }}"
    "{%- endmacro -%}"
)

# Status: tillståndet och hur länge det har gällt, «Öppen i 10 min».
_STATE_FOR = _DURATION + _STATE + (
    "{%- if entity and state_since -%}"
    "{{ words.state_for | replace('{state}', shown_state(entity))"
    " | replace('{duration}', duration((now() - state_since).total_seconds() / 60)) }}"
    "{%- endif -%}"
)

# Förlopp: tid kvar, «40 min kvar», för en timer, en sluttid eller en sensor med tid kvar;
# annars tillståndet, till exempel procenten.
_TIME_LEFT = _DURATION + _STATE + (
    "{%- set s = states[entity] if entity else none -%}"
    "{%- set a = s.attributes if s else {} -%}"
    "{%- set units = {'ms': 0.001, 's': 1, 'min': 60, 'h': 3600, 'd': 86400} -%}"
    "{%- set ns = namespace(left=none) -%}"
    "{%- if s and s.domain == 'timer' -%}"
    "{%- if s.state == 'active' and as_datetime(a.finishes_at, none) -%}"
    "{%- set ns.left = (as_datetime(a.finishes_at) - now()).total_seconds() -%}"
    "{%- elif s.state == 'paused' and as_timedelta(a.remaining or '') -%}"
    "{%- set ns.left = as_timedelta(a.remaining).total_seconds() -%}"
    "{%- endif -%}"
    "{%- elif a.device_class == 'timestamp' and as_datetime(s.state, none) -%}"
    "{%- set ns.left = (as_datetime(s.state) - now()).total_seconds() -%}"
    "{%- elif a.device_class == 'duration' and a.unit_of_measurement in units"
    " and is_number(s.state) -%}"
    "{%- set ns.left = (s.state | float) * units[a.unit_of_measurement] -%}"
    "{%- endif -%}"
    "{%- if ns.left is not none -%}"
    "{{ words.time_left | replace('{duration}', duration((ns.left / 60) | round(0, 'ceil'))) }}"
    "{%- elif s -%}"
    "{{ states(entity, with_unit=True) if is_number(s.state) else shown_state(entity) }}"
    "{%- endif -%}"
)

# Värde: talet med enhet, «52 %», eller tillståndet när det inte är ett tal.
_VALUE = _STATE + (
    "{%- if entity and is_number(states(entity)) -%}"
    "{{ states(entity, rounded=True, with_unit=True) }}"
    "{%- elif entity -%}{{ shown_state(entity) }}"
    "{%- endif -%}"
)

# Kommande: nästa tillfälle, «Nästa: Sophämtning». Utan namn visas tiden, med datum när
# det inte är i dag.
_NEXT = (
    "{%- set o = occurrences | first if occurrences else none -%}"
    "{%- if o -%}"
    "{%- if o.summary -%}{%- set what = o.summary -%}"
    "{%- elif 'T' in o.start -%}"
    "{%- set at = as_local(as_datetime(o.start)) -%}"
    "{%- set what = at.strftime('%H:%M' if at.date() == now().date() else '%Y-%m-%d %H:%M') -%}"
    "{%- else -%}{%- set what = o.start -%}"
    "{%- endif -%}"
    "{{ words.next | replace('{next}', what) }}"
    "{%- endif -%}"
)

# De färdiga mallarna per Typ. Eget kort har bara egen template.
PRESETS: dict[str, dict[str, str]] = {
    TYPE_STATUS: {"state_for": _STATE_FOR},
    TYPE_PROGRESS: {"time_left": _TIME_LEFT},
    TYPE_VALUE: {"value": _VALUE},
    TYPE_UPCOMING: {"next": _NEXT},
    TYPE_CUSTOM: {},
}


def reason_choices(rule_type: str) -> tuple[str, ...]:
    """Valen för orsaken för en Typ: ingen, de färdiga mallarna och egen template."""
    return (REASON_NONE, *PRESETS[rule_type], REASON_CUSTOM)


def reason_source(rule_type: str, reason: str | None, template: str | None) -> str | None:
    """Templaten för orsaken, eller None när regeln inte har någon orsak."""
    if reason == REASON_CUSTOM:
        return template
    return PRESETS[rule_type].get(reason or REASON_NONE)


async def async_words(hass: HomeAssistant) -> dict[str, str]:
    """Orden som de färdiga mallarna använder, på hemmets språk."""
    prefix = f"component.{DOMAIN}.reason."
    translations = await async_get_translations(hass, hass.config.language, "reason", [DOMAIN])
    return {
        key.removeprefix(prefix): text
        for key, text in translations.items()
        if key.startswith(prefix)
    }


async def async_variables(
    hass: HomeAssistant, entities: list[str], **values: Any
) -> dict[str, Any]:
    """Variablerna som en orsak får. state_since och occurrences är tomma om de inte anges."""
    return {
        "entity": entities[0] if entities else None,
        "entities": list(entities),
        "state_since": None,
        "occurrences": [],
        "words": await async_words(hass),
        **values,
    }


def _text(result: Any) -> str | None:
    """Orsaken som text; en tom orsak är ingen orsak."""
    return str(result).strip() or None


class _TextTemplate(Template):
    """En template vars resultat alltid är text.

    HA tolkar annars resultatet som ett värde när det ser ut som ett, så att «1.50» blir 1.5
    och en lista får Pythons citattecken.
    """

    @override
    def async_render_to_info(
        self,
        variables: Any = None,
        strict: bool = False,
        log_fn: Callable[[int, str], None] | None = None,
        **kwargs: Any,
    ) -> RenderInfo:
        return super().async_render_to_info(
            variables, strict, log_fn, **(kwargs | {"parse_result": False})
        )


def async_render(hass: HomeAssistant, source: str, variables: Mapping[str, Any]) -> str | None:
    """Orsaken med aktuella värden, för förhandsvisningen. Ger TemplateError vid fel."""
    return _text(Template(source, hass).async_render(dict(variables), parse_result=False))


class Reason:
    """En regels orsak, som renderas om när det den läser ändras.

    on_change får den nya texten, eller None när orsaken är tom eller inte går att rendera.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        source: str,
        variables: dict[str, Any],
        on_change: Callable[[str | None], None],
    ) -> None:
        self._hass = hass
        self._variables = variables
        self._on_change = on_change
        self._template = TrackTemplate(_TextTemplate(source, hass), self._variables)
        self._info: TrackTemplateResultInfo | None = None

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        info = async_track_template_result(self._hass, [self._template], self._rendered)
        info.async_refresh()
        self._info = info
        return info.async_remove

    @callback
    def async_set(self, **variables: Any) -> None:
        """Ändra variabler, till exempel state_since, och rendera om."""
        if all(self._variables.get(key) == value for key, value in variables.items()):
            return
        self._variables.update(variables)
        if self._info is not None:
            self._info.async_refresh()

    @callback
    def _rendered(
        self,
        _: Event[EventStateChangedData] | None,
        updates: list[TrackTemplateResult],
    ) -> None:
        result = updates[-1].result
        # HA loggar felet; notisen visas utan orsak tills templaten går att rendera.
        self._on_change(None if isinstance(result, TemplateError) else _text(result))


def parse_since(value: str | None) -> datetime | None:
    """state_since som tidpunkt för templaten."""
    return dt_util.parse_datetime(value) if value else None

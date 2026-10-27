"""Config flow för AttentionSpan."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_NAME,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError, TemplateError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    ActionSelector,
    ConditionSelector,
    DurationSelector,
    DurationSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    IconSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    ObjectSelector,
    ObjectSelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TemplateSelector,
    TextSelector,
)
from homeassistant.helpers.template import is_template_string
from homeassistant.helpers.translation import async_get_translations

from .const import (
    ALARM,
    ALWAYS,
    CONF_ACTIONS,
    CONF_CARD,
    CONF_COUNT,
    CONF_ENTITIES,
    CONF_FLAP_LIMIT,
    CONF_HIDE,
    CONF_ICON,
    CONF_LEVELS,
    CONF_PRIORITY,
    CONF_REALARM_AFTER,
    CONF_REASON,
    CONF_REASON_TEMPLATE,
    CONF_TYPE,
    DOMAIN,
    LEVELS,
    SUBENTRY_RULE,
    TYPE_CUSTOM,
    TYPE_PROGRESS,
    TYPE_STATUS,
    TYPE_UPCOMING,
    TYPE_VALUE,
    TYPES,
)
from .evaluation import async_validate_conditions
from .lifecycle import DEFAULT_FLAP_LIMIT, DEFAULT_REALARM_AFTER
from .reason import (
    REASON_CUSTOM,
    REASON_NONE,
    async_render,
    async_variables,
    parse_since,
    reason_choices,
    reason_source,
)
from .schema import vol
from .upcoming import async_occurrences

# Formulärfält som inte sparas med samma form som i regeln.
CONF_ENTITY = "entity"
# Valen per nivå i formuläret. «Alltid» sparas som ALWAYS och «Villkor» som villkoren.
LEVEL_NONE = "none"
LEVEL_CONDITION = "condition"
LEVEL_MODES = (LEVEL_NONE, ALWAYS, LEVEL_CONDITION)
# Flest tillfällen som Kommande kan visa; fler får inte plats på en rad.
MAX_COUNT = 10
# Förhandsvisningen när orsaken är tom eller regeln inte har någon.
NO_PREVIEW = "–"
# En åtgärds fält i formuläret: knappens text, tjänsteanropet och en valfri bekräftelsetext.
ACTION_NAME = "name"
ACTION_CALL = "action"
ACTION_CONFIRMATION = "confirmation"
# Placeringen: först bland reglerna som kan hamna på samma nivå, annars id för regeln
# den står efter.
CONF_PLACEMENT = "placement"
PLACEMENT_FIRST = "first"
# Tiderna som formuläret föreslår, i durationsväljarens form.
SUGGESTED_REALARM_AFTER = {"hours": DEFAULT_REALARM_AFTER // timedelta(hours=1)}
SUGGESTED_FLAP_LIMIT = {"minutes": DEFAULT_FLAP_LIMIT // timedelta(minutes=1)}
# Det i ett tjänsteanrop från HA:s åtgärdsväljare som kortet kan anropa. metadata och alias
# lägger väljaren själv till och påverkar inte anropet.
_ACTION_KEYS = {"action", "target", "data", "metadata", "alias"}


class AttentionSpanConfigFlow(ConfigFlow, domain=DOMAIN):
    # En post per Home Assistant; manifestets single_config_entry stoppar en andra.
    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_RULE: RuleSubentryFlow}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="AttentionSpan", data={})
        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))


def _select(
    options: tuple[str, ...],
    translation_key: str,
    mode: SelectSelectorMode = SelectSelectorMode.LIST,
) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(options=list(options), translation_key=translation_key, mode=mode)
    )


class _ConditionField(ConditionSelector):
    """HA:s villkorsväljare, men värdet blir kvar som användaren skrev det.

    ConditionSelector gör om templates till objekt som inte går att spara i config
    entryn och inte går att visa igen i formuläret. Villkoren valideras i steget i stället.
    """

    def __call__(self, data: Any) -> Any:
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise vol.Invalid("Villkoren ska vara en lista")
        return data


def _shown_schema(rule_type: str, current: Mapping[str, Any]) -> dict[Any, Any]:
    """Fälten för det som typen visar."""
    if rule_type == TYPE_CUSTOM:
        return {
            vol.Required(CONF_CARD, description={"suggested_value": current.get(CONF_CARD)}): (
                ObjectSelector()
            ),
        }
    if rule_type == TYPE_UPCOMING:
        # Kalendrar och sensorer vars tillstånd är en tidpunkt.
        sources = EntitySelectorConfig(
            multiple=True,
            filter=[{"domain": "calendar"}, {"domain": "sensor", "device_class": "timestamp"}],
        )
        count = NumberSelectorConfig(
            min=1, max=MAX_COUNT, step=1, mode=NumberSelectorMode.BOX
        )
        return {
            vol.Required(CONF_ENTITIES, default=current.get(CONF_ENTITIES, vol.UNDEFINED)): (
                EntitySelector(sources)
            ),
            vol.Required(CONF_COUNT, default=current.get(CONF_COUNT, 1)): NumberSelector(count),
        }
    # Värde visar ett tal; Status och Förlopp visar vilken entitet som helst.
    entity = EntitySelectorConfig(domain="sensor") if rule_type == TYPE_VALUE else None
    return {
        vol.Required(CONF_ENTITY, default=current.get(CONF_ENTITY, vol.UNDEFINED)): (
            EntitySelector(entity)
        ),
    }


def _fields_schema(rule_type: str, current: Mapping[str, Any]) -> vol.Schema:
    """Fälten som typen kräver: namn, ikon och det som notisen visar."""
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=current.get(CONF_NAME, vol.UNDEFINED)): (
                TextSelector()
            ),
            vol.Optional(CONF_ICON, description={"suggested_value": current.get(CONF_ICON)}): (
                IconSelector()
            ),
            **_shown_schema(rule_type, current),
        }
    )


def _shown_data(rule_type: str, fields: Mapping[str, Any]) -> dict[str, Any]:
    """Det som typen visar, som det sparas i regeln, ur formulärets fält."""
    if rule_type == TYPE_CUSTOM:
        # Entiteterna står i kortkonfigurationen, i den form som kortet själv bestämmer.
        return {CONF_ENTITIES: [], CONF_CARD: fields[CONF_CARD]}
    if rule_type == TYPE_UPCOMING:
        return {CONF_ENTITIES: list(fields[CONF_ENTITIES]), CONF_COUNT: int(fields[CONF_COUNT])}
    return {CONF_ENTITIES: [fields[CONF_ENTITY]]}


def _shown_fields(data: Mapping[str, Any]) -> dict[str, Any]:
    """Formulärets fält för det som en sparad regel visar."""
    if data[CONF_TYPE] == TYPE_CUSTOM:
        return {CONF_CARD: data[CONF_CARD]}
    if data[CONF_TYPE] == TYPE_UPCOMING:
        return {CONF_ENTITIES: data[CONF_ENTITIES], CONF_COUNT: data[CONF_COUNT]}
    return {CONF_ENTITY: data[CONF_ENTITIES][0]}


def _shows_progress(state: State | None) -> bool:
    """Om entiteten visar tid kvar eller procent: en timer, en sluttid, tid kvar eller procent."""
    if state is None:
        return False
    attributes = state.attributes
    return (
        state.domain == "timer"
        or attributes.get(ATTR_DEVICE_CLASS)
        in (SensorDeviceClass.TIMESTAMP, SensorDeviceClass.DURATION)
        or attributes.get(ATTR_UNIT_OF_MEASUREMENT) == PERCENTAGE
    )


def _is_card(config: Any) -> bool:
    """Om det är en Lovelace-kortkonfiguration: något med en korttyp."""
    return (
        isinstance(config, Mapping)
        and isinstance(card_type := config.get("type"), str)
        and bool(card_type.strip())
    )


def _fields_errors(
    hass: HomeAssistant, rule_type: str, user_input: Mapping[str, Any]
) -> dict[str, str]:
    errors = {} if user_input[CONF_NAME].strip() else {CONF_NAME: "name_required"}
    if rule_type == TYPE_CUSTOM and not _is_card(user_input[CONF_CARD]):
        errors[CONF_CARD] = "invalid_card"
    if rule_type == TYPE_UPCOMING and not user_input[CONF_ENTITIES]:
        errors[CONF_ENTITIES] = "entities_required"
    if rule_type == TYPE_PROGRESS and not _shows_progress(
        hass.states.get(user_input[CONF_ENTITY])
    ):
        errors[CONF_ENTITY] = "progress_entity"
    return errors


def _level_modes(levels: Mapping[str, Any]) -> dict[str, str]:
    """Valet per nivå för en sparad regels nivåer."""
    return {
        level: ALWAYS if levels[level] == ALWAYS else LEVEL_CONDITION
        for level in LEVELS
        if level in levels
    }


def _reason_choice(user_input: Mapping[str, Any]) -> tuple[str, str | None]:
    """Orsaken som valts: valet och, för egen template, templaten."""
    reason = user_input.get(CONF_REASON, REASON_NONE)
    template = (user_input.get(CONF_REASON_TEMPLATE) or "").strip() or None
    return reason, template if reason == REASON_CUSTOM else None


def _reason_errors(choice: tuple[str, str | None]) -> dict[str, str]:
    """Fel i orsaken. Templatens syntax kontrolleras redan av HA:s templateväljare."""
    reason, template = choice
    if reason == REASON_CUSTOM and template is None:
        return {CONF_REASON_TEMPLATE: "template_required"}
    return {}


def _actions_selector() -> ObjectSelector:
    """En lista med åtgärder: knappens text, ett tjänsteanrop och en valfri bekräftelsetext."""
    return ObjectSelector(
        ObjectSelectorConfig(
            fields={
                ACTION_NAME: {"selector": TextSelector(), "required": True},
                ACTION_CALL: {"selector": ActionSelector(), "required": True},
                ACTION_CONFIRMATION: {"selector": TextSelector()},
            },
            multiple=True,
            label_field=ACTION_NAME,
            translation_key=CONF_ACTIONS,
        )
    )


def _has_template(value: Any) -> bool:
    """Om någon text i ett tjänsteanrop är en template."""
    if isinstance(value, str):
        return is_template_string(value)
    if isinstance(value, Mapping):
        return any(_has_template(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_template(item) for item in value)
    return False


def _action(field: Mapping[str, Any]) -> dict[str, Any]:
    """En åtgärd ur formuläret, som den sparas och visas i attributet actions.

    Ger vol.Invalid om den inte är precis ett tjänsteanrop utan templates, eftersom kortet
    anropar tjänsten som den står, som en knapp i Lovelace.
    """
    name = str(field.get(ACTION_NAME) or "").strip()
    calls = field.get(ACTION_CALL)
    calls = calls if isinstance(calls, list) else [calls]
    if not name or len(calls) != 1 or not isinstance(call := calls[0], Mapping):
        raise vol.Invalid("En åtgärd är en knapptext och ett tjänsteanrop")
    if set(call) - _ACTION_KEYS or _has_template(call):
        raise vol.Invalid("Bara tjänsteanrop utan templates går att visa som knapp")
    target = call.get("target") or {}
    data = call.get("data") or {}
    if not isinstance(target, Mapping) or not isinstance(data, Mapping):
        raise vol.Invalid("target och data ska vara objekt")
    action: dict[str, Any] = {
        "name": name,
        "action": cv.service(call.get("action")),
        "target": dict(target),
        "data": dict(data),
        "confirmation": str(field.get(ACTION_CONFIRMATION) or "").strip() or None,
    }
    return action


def _action_fields(action: Mapping[str, Any]) -> dict[str, Any]:
    """Formulärets fält för en sparad åtgärd."""
    call: dict[str, Any] = {"action": action["action"]}
    if action["target"]:
        call["target"] = action["target"]
    if action["data"]:
        call["data"] = action["data"]
    fields = {ACTION_NAME: action["name"], ACTION_CALL: [call]}
    if action["confirmation"]:
        fields[ACTION_CONFIRMATION] = action["confirmation"]
    return fields


class RuleSubentryFlow(ConfigSubentryFlow):
    """Lägg till eller ändra en Rule: Typ, typens fält, en rad per nivå och sist villkoren."""

    _type: str
    _fields: dict[str, Any]
    _modes: dict[str, str]
    _conditions: dict[str, Any]
    _reason: tuple[str, str | None]
    # Orsaken som förhandsvisningen visar: valet och, för egen template, templaten.
    _previewed: tuple[str, str | None] | None = None
    # Det formuläret visar från början: regeln som ändras, eller inget för en ny regel.
    _current: Mapping[str, Any] = {}
    # Placeringen som valts: PLACEMENT_FIRST eller regeln den står efter. None när formuläret
    # inte frågade, för att ingen annan regel kan hamna på samma nivå.
    _placement: str | None = None
    _actions: list[dict[str, Any]]

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            self._type = user_input[CONF_TYPE]
            return await self._async_step_fields(self._type)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_TYPE): _select(TYPES, CONF_TYPE)}),
        )

    async def async_step_status(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_step_fields(TYPE_STATUS, user_input)

    async def async_step_progress(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_step_fields(TYPE_PROGRESS, user_input)

    async def async_step_value(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_step_fields(TYPE_VALUE, user_input)

    async def async_step_upcoming(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_step_fields(TYPE_UPCOMING, user_input)

    async def async_step_custom(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_step_fields(TYPE_CUSTOM, user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ändra regeln. Typen behålls."""
        subentry = self._get_reconfigure_subentry()
        data = subentry.data
        self._type = data[CONF_TYPE]
        self._current = {
            CONF_NAME: subentry.title,
            CONF_ICON: data.get(CONF_ICON),
            **_shown_fields(data),
            CONF_LEVELS: data[CONF_LEVELS],
            CONF_HIDE: data.get(CONF_HIDE),
            CONF_REASON: data.get(CONF_REASON, REASON_NONE),
            CONF_REASON_TEMPLATE: data.get(CONF_REASON_TEMPLATE),
            CONF_ACTIONS: [_action_fields(action) for action in data.get(CONF_ACTIONS, [])],
            CONF_REALARM_AFTER: data.get(CONF_REALARM_AFTER, SUGGESTED_REALARM_AFTER),
            CONF_FLAP_LIMIT: data.get(CONF_FLAP_LIMIT, SUGGESTED_FLAP_LIMIT),
        }
        return await self._async_step_fields("reconfigure", user_input)

    async def _async_step_fields(
        self, step_id: str, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and not (
            errors := _fields_errors(self.hass, self._type, user_input)
        ):
            self._fields = user_input
            return await self.async_step_levels()
        return self.async_show_form(
            step_id=step_id,
            data_schema=_fields_schema(self._type, user_input or self._current),
            errors=errors,
        )

    async def async_step_levels(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Inget, Alltid eller Villkor för varje nivå."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._modes = {
                level: mode for level, mode in user_input.items() if mode != LEVEL_NONE
            }
            if self._modes:
                return await self.async_step_conditions()
            errors["base"] = "level_required"
        current = user_input or _level_modes(self._current.get(CONF_LEVELS, {}))
        return self.async_show_form(
            step_id="levels",
            data_schema=vol.Schema(
                {
                    # En rullgardin per nivå, så att fem nivåer får plats på en telefon.
                    vol.Required(level, default=current.get(level, LEVEL_NONE)): _select(
                        LEVEL_MODES, "level_mode", SelectSelectorMode.DROPDOWN
                    )
                    for level in LEVELS
                }
            ),
            errors=errors,
        )

    async def async_step_conditions(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Villkoren för nivåerna med Villkor, och dölj-villkoret («Dölj när»)."""
        with_condition = [level for level in LEVELS if self._modes.get(level) == LEVEL_CONDITION]
        errors: dict[str, str] = {}
        if user_input is not None:
            for field, conditions in user_input.items():
                if not conditions:
                    if field != CONF_HIDE:
                        errors[field] = "condition_required"
                    continue
                try:
                    await async_validate_conditions(self.hass, conditions)
                except (vol.Invalid, HomeAssistantError):
                    errors[field] = "invalid_condition"
            if not errors:
                self._conditions = user_input
                return await self.async_step_placement()
        current = user_input or {
            **{
                level: value
                for level, value in self._current.get(CONF_LEVELS, {}).items()
                if value != ALWAYS
            },
            CONF_HIDE: self._current.get(CONF_HIDE),
        }
        return self.async_show_form(
            step_id="conditions",
            data_schema=vol.Schema(
                {
                    **{
                        vol.Required(
                            level, description={"suggested_value": current.get(level)}
                        ): _ConditionField()
                        for level in with_condition
                    },
                    vol.Optional(
                        CONF_HIDE, description={"suggested_value": current.get(CONF_HIDE)}
                    ): _ConditionField(),
                }
            ),
            errors=errors,
        )

    async def async_step_placement(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Var regeln står bland reglerna som kan hamna på samma nivå: först eller efter en av dem.

        Hoppas över när ingen annan regel kan hamna på samma nivå.
        """
        peers = self._peers()
        if not peers:
            return await self.async_step_reason()
        if user_input is not None:
            self._placement = user_input[CONF_PLACEMENT]
            return await self.async_step_reason()
        words = await self._async_placement_words()
        options = [SelectOptionDict(value=PLACEMENT_FIRST, label=words["first"])] + [
            SelectOptionDict(value=peer.subentry_id, label=words["after"].format(rule=peer.title))
            for peer in peers
        ]
        return self.async_show_form(
            step_id="placement",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PLACEMENT, default=self._placement_now(peers)): (
                        SelectSelector(
                            SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
                        )
                    ),
                }
            ),
        )

    def _rules(self) -> list[ConfigSubentry]:
        """Alla regler i ordningen, lägst ordningstal först."""
        rules = self._get_entry().get_subentries_of_type(SUBENTRY_RULE)
        return sorted(rules, key=lambda rule: (rule.data[CONF_PRIORITY], rule.subentry_id))

    def _own_id(self) -> str | None:
        """Regeln som ändras, eller None för en ny regel."""
        if self.source != SOURCE_RECONFIGURE:
            return None
        return self._get_reconfigure_subentry().subentry_id

    def _peers(self) -> list[ConfigSubentry]:
        """De andra reglerna som delar minst en nivå med den här, i ordningen."""
        levels = set(self._modes)
        own = self._own_id()
        return [
            rule
            for rule in self._rules()
            if rule.subentry_id != own and levels & set(rule.data[CONF_LEVELS])
        ]

    def _placement_now(self, peers: list[ConfigSubentry]) -> str:
        """Förvalet: placeringen där regeln står nu, och för en ny regel sist."""
        position = self._position([peer.subentry_id for peer in peers])
        return peers[position - 1].subentry_id if position else PLACEMENT_FIRST

    def _position(self, peers: list[str]) -> int:
        """Hur många av reglerna på samma nivå som står före regeln nu; för en ny regel alla."""
        own = self._own_id()
        if own is None:
            return len(peers)
        ids = [rule.subentry_id for rule in self._rules()]
        return sum(ids.index(peer) < ids.index(own) for peer in peers)

    async def _async_placement_words(self) -> dict[str, str]:
        """Texterna för valen, på hemmets språk."""
        prefix = f"component.{DOMAIN}.placement."
        translations = await async_get_translations(
            self.hass, self.hass.config.language, "placement", [DOMAIN]
        )
        return {
            key.removeprefix(prefix): text
            for key, text in translations.items()
            if key.startswith(prefix)
        }

    async def async_step_reason(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Orsaken, med en förhandsvisning med aktuella värden.

        Ett nytt val visar först sin förhandsvisning; skickas samma val igen går flödet vidare.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            choice = _reason_choice(user_input)
            errors = _reason_errors(choice)
            if not errors and choice == self._previewed:
                self._reason = choice
                return await self.async_step_actions()
        current = user_input or self._current
        choice = _reason_choice(current)
        preview = NO_PREVIEW
        if not errors:
            self._previewed = choice
            preview = await self._async_preview(choice)
        return self.async_show_form(
            step_id="reason",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_REASON, default=choice[0]): _select(
                        reason_choices(self._type), CONF_REASON, SelectSelectorMode.DROPDOWN
                    ),
                    vol.Optional(
                        CONF_REASON_TEMPLATE,
                        description={"suggested_value": current.get(CONF_REASON_TEMPLATE)},
                    ): TemplateSelector(),
                }
            ),
            errors=errors,
            description_placeholders={"preview": preview},
        )

    async def _async_preview(self, choice: tuple[str, str | None]) -> str:
        """Orsaken med aktuella värden, som regeln skulle visa den nu."""
        source = reason_source(self._type, *choice)
        if source is None:
            return NO_PREVIEW
        try:
            text = async_render(self.hass, source, await self._async_reason_variables())
        except TemplateError as err:
            return str(err)
        return text or NO_PREVIEW

    async def _async_reason_variables(self) -> dict[str, Any]:
        """Variablerna som orsaken får, med aktuella värden."""
        entities = _shown_data(self._type, self._fields)[CONF_ENTITIES]
        values: dict[str, Any] = {}
        if self._type == TYPE_STATUS and (shown := self.hass.states.get(entities[0])):
            values["state_since"] = self._rule_state_since(shown.entity_id) or shown.last_changed
        if self._type == TYPE_UPCOMING:
            values["occurrences"] = await async_occurrences(
                self.hass, entities, int(self._fields[CONF_COUNT])
            )
        return await async_variables(self.hass, entities, **values)

    def _rule_state_since(self, entity: str) -> datetime | None:
        """När regeln såg den visade entiteten få sitt tillstånd, också över en omstart.

        Bara när en befintlig regel ändras och den visar samma entitet som förut.
        """
        if self.source != SOURCE_RECONFIGURE:
            return None
        subentry = self._get_reconfigure_subentry()
        if subentry.data[CONF_ENTITIES][:1] != [entity]:
            return None
        entity_id = er.async_get(self.hass).async_get_entity_id(
            "sensor", DOMAIN, subentry.subentry_id
        )
        rule = self.hass.states.get(entity_id) if entity_id else None
        return parse_since(rule.attributes.get("state_since")) if rule else None

    async def async_step_actions(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Åtgärderna: tjänsteanrop som kortet visar som knappar."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                actions = [_action(field) for field in user_input.get(CONF_ACTIONS) or []]
            except vol.Invalid:
                errors[CONF_ACTIONS] = "invalid_action"
            else:
                self._actions = actions
                return await self.async_step_timing()
        current = user_input or self._current
        return self.async_show_form(
            step_id="actions",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ACTIONS,
                        description={"suggested_value": current.get(CONF_ACTIONS) or None},
                    ): _actions_selector(),
                }
            ),
            errors=errors,
        )

    async def async_step_timing(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """«Larma igen efter kvittering», bara när regeln kan bli Larm, och fladdergränsen.

        Ett tomt «larma igen» betyder aldrig.
        """
        can_alarm = ALARM in self._modes
        errors: dict[str, str] = {}
        if user_input is not None:
            realarm = user_input.get(CONF_REALARM_AFTER)
            if realarm is not None and cv.time_period_dict(realarm) <= timedelta(0):
                errors[CONF_REALARM_AFTER] = "realarm_positive"
            else:
                return self._async_finish(user_input)
        current: Mapping[str, Any] = {
            CONF_REALARM_AFTER: SUGGESTED_REALARM_AFTER,
            CONF_FLAP_LIMIT: SUGGESTED_FLAP_LIMIT,
            **self._current,
        }
        if user_input is not None:
            current = {CONF_REALARM_AFTER: None, **user_input}
        fields: dict[Any, Any] = {}
        if can_alarm:
            fields[
                vol.Optional(
                    CONF_REALARM_AFTER,
                    description={"suggested_value": current[CONF_REALARM_AFTER]},
                )
            ] = DurationSelector(DurationSelectorConfig(enable_day=True))
        fields[
            vol.Required(CONF_FLAP_LIMIT, description={"suggested_value": current[CONF_FLAP_LIMIT]})
        ] = DurationSelector()
        return self.async_show_form(step_id="timing", data_schema=vol.Schema(fields), errors=errors)

    def _async_finish(self, timing: Mapping[str, Any]) -> SubentryFlowResult:
        actions = self._actions
        conditions = self._conditions
        data: dict[str, Any] = {
            CONF_TYPE: self._type,
            **_shown_data(self._type, self._fields),
            CONF_LEVELS: {
                level: ALWAYS if mode == ALWAYS else conditions[level]
                for level, mode in self._modes.items()
            },
        }
        if icon := self._fields.get(CONF_ICON):
            data[CONF_ICON] = icon
        if hide := conditions.get(CONF_HIDE):
            data[CONF_HIDE] = hide
        reason, template = self._reason
        if reason != REASON_NONE:
            data[CONF_REASON] = reason
        if template is not None:
            data[CONF_REASON_TEMPLATE] = template
        if actions:
            data[CONF_ACTIONS] = actions
        if ALARM in self._modes:
            data[CONF_REALARM_AFTER] = timing.get(CONF_REALARM_AFTER)
        data[CONF_FLAP_LIMIT] = timing[CONF_FLAP_LIMIT]
        title = self._fields[CONF_NAME].strip()
        priority = self._async_place()
        if priority is None:
            return self.async_abort(reason="rules_changed")
        data[CONF_PRIORITY] = priority
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_and_abort(
                self._get_entry(), self._get_reconfigure_subentry(), title=title, data=data
            )
        return self.async_create_entry(title=title, data=data)

    def _async_place(self) -> int | None:
        """Ställ regeln där placeringen säger och returnera dess ordningstal.

        Står regeln redan där bland reglerna på samma nivå behåller en ändrad regel sitt tal
        och en ny hamnar sist. Annars numreras alla regler om från 1, och de andra regler vars
        tal ändras sparas. None när regeln som placeringen utgår från har tagits bort under tiden.
        """
        rules = self._rules()
        own = self._own_id()
        peers = [peer.subentry_id for peer in self._peers()]
        if self._placement in (None, PLACEMENT_FIRST):
            position = 0
        elif self._placement in peers:
            position = peers.index(self._placement) + 1
        else:
            return None
        if self._placement is None or position == self._position(peers):
            if own is not None:
                return int(self._get_reconfigure_subentry().data[CONF_PRIORITY])
            return 1 + max((rule.data[CONF_PRIORITY] for rule in rules), default=0)
        ids: list[str | None] = [rule.subentry_id for rule in rules if rule.subentry_id != own]
        # Före den första regeln på samma nivå, eller direkt efter den som valts.
        index = ids.index(peers[0]) if position == 0 else ids.index(peers[position - 1]) + 1
        placed = [*ids[:index], own, *ids[index:]]
        entry = self._get_entry()
        for number, rule in enumerate(placed, start=1):
            subentry = entry.subentries[rule] if rule is not None and rule != own else None
            if subentry is not None and subentry.data[CONF_PRIORITY] != number:
                self.hass.config_entries.async_update_subentry(
                    entry, subentry, data={**subentry.data, CONF_PRIORITY: number}
                )
        return placed.index(own) + 1

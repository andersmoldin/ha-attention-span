"""Config flow för AttentionSpan."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    ConditionSelector,
    EntitySelector,
    EntitySelectorConfig,
    IconSelector,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    ALWAYS,
    CONF_ENTITIES,
    CONF_HIDE,
    CONF_ICON,
    CONF_LEVELS,
    CONF_PRIORITY,
    CONF_TYPE,
    DOMAIN,
    LEVELS,
    SUBENTRY_RULE,
    TYPE_STATUS,
    TYPE_VALUE,
    TYPES,
)
from .evaluation import async_validate_conditions
from .schema import vol

# Formulärfält som inte sparas med samma form som i regeln.
CONF_ENTITY = "entity"
# Valen per nivå i formuläret. «Alltid» sparas som ALWAYS och «Villkor» som villkoren.
LEVEL_NONE = "none"
LEVEL_CONDITION = "condition"
LEVEL_MODES = (LEVEL_NONE, ALWAYS, LEVEL_CONDITION)


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


def _fields_schema(rule_type: str, current: Mapping[str, Any]) -> vol.Schema:
    """Fälten som typen kräver: namn, ikon och entiteten som notisen visar."""
    # Värde visar ett tal; Status visar vilken entitet som helst.
    entity = EntitySelectorConfig(domain="sensor") if rule_type == TYPE_VALUE else None
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=current.get(CONF_NAME, vol.UNDEFINED)): (
                TextSelector()
            ),
            vol.Optional(CONF_ICON, description={"suggested_value": current.get(CONF_ICON)}): (
                IconSelector()
            ),
            vol.Required(CONF_ENTITY, default=current.get(CONF_ENTITY, vol.UNDEFINED)): (
                EntitySelector(entity)
            ),
        }
    )


def _name_errors(user_input: Mapping[str, Any]) -> dict[str, str]:
    return {} if user_input[CONF_NAME].strip() else {CONF_NAME: "name_required"}


def _level_modes(levels: Mapping[str, Any]) -> dict[str, str]:
    """Valet per nivå för en sparad regels nivåer."""
    return {
        level: ALWAYS if levels[level] == ALWAYS else LEVEL_CONDITION
        for level in LEVELS
        if level in levels
    }


class RuleSubentryFlow(ConfigSubentryFlow):
    """Lägg till eller ändra en Rule: Typ, typens fält, en rad per nivå och sist villkoren."""

    _type: str
    _fields: dict[str, Any]
    _modes: dict[str, str]
    # Det formuläret visar från början: regeln som ändras, eller inget för en ny regel.
    _current: Mapping[str, Any] = {}

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

    async def async_step_value(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self._async_step_fields(TYPE_VALUE, user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ändra regeln. Typ och placering behålls."""
        subentry = self._get_reconfigure_subentry()
        data = subentry.data
        self._type = data[CONF_TYPE]
        self._current = {
            CONF_NAME: subentry.title,
            CONF_ICON: data.get(CONF_ICON),
            CONF_ENTITY: data[CONF_ENTITIES][0],
            CONF_LEVELS: data[CONF_LEVELS],
            CONF_HIDE: data.get(CONF_HIDE),
        }
        return await self._async_step_fields("reconfigure", user_input)

    async def _async_step_fields(
        self, step_id: str, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and not (errors := _name_errors(user_input)):
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
        """Villkoren för nivåerna med Villkor, och Dölj när."""
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
                return self._async_finish(user_input)
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

    def _async_finish(self, conditions: Mapping[str, Any]) -> SubentryFlowResult:
        data: dict[str, Any] = {
            CONF_TYPE: self._type,
            CONF_ENTITIES: [self._fields[CONF_ENTITY]],
            CONF_LEVELS: {
                level: ALWAYS if mode == ALWAYS else conditions[level]
                for level, mode in self._modes.items()
            },
        }
        if icon := self._fields.get(CONF_ICON):
            data[CONF_ICON] = icon
        if hide := conditions.get(CONF_HIDE):
            data[CONF_HIDE] = hide
        title = self._fields[CONF_NAME].strip()
        if self.source == SOURCE_RECONFIGURE:
            subentry = self._get_reconfigure_subentry()
            data[CONF_PRIORITY] = subentry.data[CONF_PRIORITY]
            return self.async_update_and_abort(
                self._get_entry(), subentry, title=title, data=data
            )
        # Ny regel hamnar sist i ordningen.
        rules = self._get_entry().get_subentries_of_type(SUBENTRY_RULE)
        data[CONF_PRIORITY] = 1 + max((sub.data[CONF_PRIORITY] for sub in rules), default=0)
        return self.async_create_entry(title=title, data=data)

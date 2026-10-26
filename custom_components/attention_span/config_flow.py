"""Config flow för AttentionSpan."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
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
    ALWAYS_LEVELS,
    CONF_ENTITIES,
    CONF_ICON,
    CONF_LEVELS,
    CONF_PRIORITY,
    CONF_TYPE,
    DOMAIN,
    SUBENTRY_RULE,
    TYPE_VALUE,
    TYPES,
)
from .schema import vol

# Formulärfält som inte sparas med samma form som i regeln.
CONF_ENTITY = "entity"
CONF_LEVEL = "level"


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


def _select(options: tuple[str, ...], translation_key: str) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=list(options), translation_key=translation_key, mode=SelectSelectorMode.LIST
        )
    )


def _value_schema(current: Mapping[str, Any]) -> vol.Schema:
    """Fälten för typen Värde: namn, ikon, en numerisk sensor och nivån som alltid gäller."""
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=current.get(CONF_NAME, vol.UNDEFINED)): (
                TextSelector()
            ),
            vol.Optional(CONF_ICON, description={"suggested_value": current.get(CONF_ICON)}): (
                IconSelector()
            ),
            vol.Required(CONF_ENTITY, default=current.get(CONF_ENTITY, vol.UNDEFINED)): (
                EntitySelector(EntitySelectorConfig(domain="sensor"))
            ),
            vol.Required(CONF_LEVEL, default=current.get(CONF_LEVEL, vol.UNDEFINED)): _select(
                ALWAYS_LEVELS, CONF_LEVEL
            ),
        }
    )


def _name_errors(user_input: Mapping[str, Any]) -> dict[str, str]:
    return {} if user_input[CONF_NAME].strip() else {CONF_NAME: "name_required"}


def _rule_data(rule_type: str, user_input: Mapping[str, Any], priority: int) -> dict[str, Any]:
    data: dict[str, Any] = {
        CONF_TYPE: rule_type,
        CONF_ENTITIES: [user_input[CONF_ENTITY]],
        CONF_LEVELS: {user_input[CONF_LEVEL]: ALWAYS},
        CONF_PRIORITY: priority,
    }
    if icon := user_input.get(CONF_ICON):
        data[CONF_ICON] = icon
    return data


class RuleSubentryFlow(ConfigSubentryFlow):
    """Lägg till en Rule: först Typ, sedan fälten som typen kräver."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            return await self.async_step_value()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_TYPE): _select(TYPES, CONF_TYPE)}),
        )

    async def async_step_value(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and not (errors := _name_errors(user_input)):
            # Ny regel hamnar sist i ordningen.
            priority = 1 + max(
                (
                    sub.data[CONF_PRIORITY]
                    for sub in self._get_entry().get_subentries_of_type(SUBENTRY_RULE)
                ),
                default=0,
            )
            return self.async_create_entry(
                title=user_input[CONF_NAME].strip(),
                data=_rule_data(TYPE_VALUE, user_input, priority),
            )
        return self.async_show_form(
            step_id="value", data_schema=_value_schema(user_input or {}), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ändra namn, ikon, entitet och nivå. Typ och placering behålls."""
        subentry = self._get_reconfigure_subentry()
        data = subentry.data
        errors: dict[str, str] = {}
        if user_input is not None and not (errors := _name_errors(user_input)):
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=user_input[CONF_NAME].strip(),
                data=_rule_data(data[CONF_TYPE], user_input, data[CONF_PRIORITY]),
            )
        (level,) = data[CONF_LEVELS]
        current = user_input or {
            CONF_NAME: subentry.title,
            CONF_ICON: data.get(CONF_ICON),
            CONF_ENTITY: data[CONF_ENTITIES][0],
            CONF_LEVEL: level,
        }
        return self.async_show_form(
            step_id="reconfigure", data_schema=_value_schema(current), errors=errors
        )

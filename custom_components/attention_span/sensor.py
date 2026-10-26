"""En sensor per Rule, i dataformat version 1."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .const import (
    ALWAYS,
    CONF_ENTITIES,
    CONF_ICON,
    CONF_LEVELS,
    CONF_PRIORITY,
    CONF_TYPE,
    CONTRACT_VERSION,
    DOMAIN,
    HIDDEN,
    LEVELS,
    SOURCE_RULE,
    SUBENTRY_RULE,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    for subentry in entry.get_subentries_of_type(SUBENTRY_RULE):
        async_add_entities([RuleSensor(subentry)], config_subentry_id=subentry.subentry_id)


def _level(levels: dict[str, str]) -> str:
    """Den allvarligaste nivån som gäller, eller dold när ingen gör det (ADR 0002)."""
    return next((level for level in LEVELS if levels.get(level) == ALWAYS), HIDDEN)


class RuleSensor(SensorEntity, RestoreEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [*LEVELS, HIDDEN]
    _attr_translation_key = "rule"
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, subentry: ConfigSubentry) -> None:
        data = subentry.data
        self.entity_id = f"sensor.{DOMAIN}_{slugify(subentry.title)}"
        self._attr_unique_id = subentry.subentry_id
        self._attr_name = subentry.title
        self._attr_icon = data.get(CONF_ICON)
        self._attr_native_value = _level(data[CONF_LEVELS])
        self._attributes: dict[str, Any] = {
            "contract": CONTRACT_VERSION,
            "source": SOURCE_RULE,
            "type": data[CONF_TYPE],
            "priority": data[CONF_PRIORITY],
            "reason": None,
            "entities": list(data[CONF_ENTITIES]),
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Regeln läses in på nytt vid varje omladdning; nivån har gällt sedan förra gången
        # om den är densamma.
        last = await self.async_get_last_state()
        if (
            last is not None
            and last.state == self._attr_native_value
            and "since" in last.attributes
        ):
            since = last.attributes["since"]
        else:
            since = dt_util.utcnow().isoformat()
        self._attr_extra_state_attributes = self._attributes | {"since": since}

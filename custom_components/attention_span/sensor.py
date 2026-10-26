"""En sensor per Rule, i dataformat version 1."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData, RestoredExtraData, RestoreEntity
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .const import (
    CONF_ENTITIES,
    CONF_HIDE,
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
from .evaluation import RuleLevel


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    for subentry in entry.get_subentries_of_type(SUBENTRY_RULE):
        async_add_entities([RuleSensor(subentry)], config_subentry_id=subentry.subentry_id)


class RuleSensor(SensorEntity, RestoreEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [*LEVELS, HIDDEN]
    _attr_translation_key = "rule"
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, subentry: ConfigSubentry) -> None:
        data = subentry.data
        self._rule = data
        self.entity_id = f"sensor.{DOMAIN}_{slugify(subentry.title)}"
        self._attr_unique_id = subentry.subentry_id
        self._attr_name = subentry.title
        self._attr_icon = data.get(CONF_ICON)
        self._attr_extra_state_attributes: dict[str, Any] = {
            "contract": CONTRACT_VERSION,
            "source": SOURCE_RULE,
            "type": data[CONF_TYPE],
            "priority": data[CONF_PRIORITY],
            "reason": None,
            "entities": list(data[CONF_ENTITIES]),
            "since": dt_util.utcnow().isoformat(),
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Går ett villkor inte att bygga, till exempel för att dess enhet har tagits bort,
        # loggar HA felet och visar regeln som otillgänglig.
        rule = await RuleLevel.async_create(
            self.hass, self.entity_id, self._rule[CONF_LEVELS], self._rule.get(CONF_HIDE)
        )
        self.async_on_remove(rule.async_unload)
        self._evaluation = rule
        self._attr_native_value = rule.evaluate()
        # Regeln läses in på nytt vid varje omladdning; nivån har gällt sedan förra gången
        # om det är samma regel på samma nivå.
        last = await self.async_get_last_extra_data()
        if last is not None:
            stored = last.as_dict()
            if (
                stored.get("rule") == self.unique_id
                and stored.get("level") == self._attr_native_value
            ):
                self._attr_extra_state_attributes["since"] = stored["since"]
        self.async_on_remove(await rule.async_track(self.hass, self._async_reevaluate))

    @callback
    def _async_reevaluate(self) -> None:
        level = self._evaluation.evaluate()
        if level == self._attr_native_value:
            return
        self._attr_native_value = level
        self._attr_extra_state_attributes["since"] = dt_util.utcnow().isoformat()
        self.async_write_ha_state()

    @property
    def extra_restore_state_data(self) -> ExtraStoredData:
        return RestoredExtraData(
            {
                "rule": self.unique_id,
                "level": self._attr_native_value,
                "since": self._attr_extra_state_attributes["since"],
            }
        )

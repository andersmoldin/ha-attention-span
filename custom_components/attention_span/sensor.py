"""En sensor per Rule, i dataformat version 1."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import ATTR_RESTORED
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import ExtraStoredData, RestoredExtraData, RestoreEntity
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .const import (
    CONF_CARD,
    CONF_COUNT,
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
    TYPE_CUSTOM,
    TYPE_STATUS,
    TYPE_UPCOMING,
)
from .evaluation import RuleLevel
from .since import DATA_SINCE, SavedRule, SavedState
from .upcoming import Occurrence, Upcoming


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
        self._rule_id = subentry.subentry_id
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
        if data[CONF_TYPE] == TYPE_STATUS:
            # När den visade entiteten fick sitt tillstånd, för «hur länge». Entitetens
            # last_changed duger inte: den sätts om när dess integration laddas vid en omstart.
            self._attr_extra_state_attributes["state_since"] = None
        if data[CONF_TYPE] == TYPE_UPCOMING:
            self._attr_extra_state_attributes["occurrences"] = []
        if data[CONF_TYPE] == TYPE_CUSTOM:
            self._attr_extra_state_attributes["card"] = data[CONF_CARD]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # När villkoren och det visade tillståndet började gälla, från före omstarten.
        self._store = self.hass.data[DATA_SINCE]
        saved = self._store.get(self._rule_id)
        self._shown = saved.get("state")
        # Går ett villkor inte att bygga, till exempel för att dess enhet har tagits bort,
        # loggar HA felet och visar regeln som otillgänglig.
        evaluation = await RuleLevel.async_create(
            self.hass,
            self.entity_id,
            self._rule[CONF_LEVELS],
            self._rule.get(CONF_HIDE),
            {
                key: dt_util.parse_datetime(since, raise_on_error=True)
                for key, since in saved.get("conditions", {}).items()
            },
        )
        self.async_on_remove(evaluation.async_unload)
        self._evaluation = evaluation
        # Regeln läses in på nytt vid varje omladdning och omstart. Är det samma regel gäller
        # nivån från förra gången tills den har räknats om, och den har gällt sedan dess.
        last = await self.async_get_last_extra_data()
        stored = last.as_dict() if last is not None else {}
        if stored.get("rule") == self.unique_id:
            self._attr_native_value = stored["level"]
            self._attr_extra_state_attributes["since"] = stored["since"]
        # Under en omstart finns entiteterna i villkoren först när deras integrationer har
        # laddats, så nivån räknas ut när HA har startat.
        self.async_on_remove(async_at_started(self.hass, self._async_start))

    async def _async_start(self, hass: HomeAssistant) -> None:
        if self._rule[CONF_TYPE] == TYPE_STATUS:
            self._async_shown_changed()
            self.async_on_remove(
                async_track_state_change_event(
                    hass, self._rule[CONF_ENTITIES][0], self._async_shown_changed
                )
            )
        self._async_reevaluate()
        self.async_on_remove(await self._evaluation.async_track(hass, self._async_reevaluate))
        if self._rule[CONF_TYPE] == TYPE_UPCOMING:
            upcoming = Upcoming(
                hass, self._rule[CONF_ENTITIES], self._rule[CONF_COUNT], self._async_occurrences
            )
            self.async_on_remove(await upcoming.async_start())

    @callback
    def _async_occurrences(self, occurrences: list[Occurrence]) -> None:
        if occurrences == self._attr_extra_state_attributes["occurrences"]:
            return
        self._attr_extra_state_attributes["occurrences"] = occurrences
        self.async_write_ha_state()

    @callback
    def _async_shown_changed(self, _: Event[EventStateChangedData] | None = None) -> None:
        """Typen Status: håll reda på när den visade entiteten fick sitt tillstånd.

        Har den samma tillstånd som före omstarten har tillståndet gällt sedan dess, också
        medan den väntar på att dess integration ska laddas (restored). Saknas den, eller
        väntar den med ett annat tillstånd, är tiden okänd.
        """
        entity_id = self._rule[CONF_ENTITIES][0]
        shown = self.hass.states.get(entity_id)
        since = None
        if shown is not None:
            if (
                self._shown is not None
                and self._shown["entity"] == entity_id
                and self._shown["state"] == shown.state
            ):
                since = self._shown["since"]
            elif shown.attributes.get(ATTR_RESTORED) is not True:
                self._shown = SavedState(
                    entity=entity_id, state=shown.state, since=shown.last_changed.isoformat()
                )
                since = self._shown["since"]
        self._async_save()
        if since != self._attr_extra_state_attributes["state_since"]:
            self._attr_extra_state_attributes["state_since"] = since
            self.async_write_ha_state()

    @callback
    def _async_save(self) -> None:
        started = self._evaluation.started
        saved = SavedRule(conditions={key: since.isoformat() for key, since in started.items()})
        if self._shown is not None:
            saved["state"] = self._shown
        self._store.async_set(self._rule_id, saved)

    @callback
    def _async_reevaluate(self) -> None:
        level = self._evaluation.evaluate()
        self._async_save()
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

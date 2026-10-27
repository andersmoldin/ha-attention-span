"""AttentionSpan: hemskärmen visar bara det som är viktigt nu."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.config_entries import ConfigEntry, UpdateListenerType
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service
from homeassistant.helpers.condition import ConditionChecker
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType

from .const import CONF_PRIORITY, DOMAIN, SERVICE_ACKNOWLEDGE, SIGNAL_PRIORITY
from .frontend import async_register_card
from .since import DATA_SINCE, SinceStore

PLATFORMS = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    # En gång per HA-start, så att kortet inte registreras igen när regler läggs till.
    await async_register_card(hass)
    since = SinceStore(hass)
    await since.async_load()
    hass.data[DATA_SINCE] = since
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_ACKNOWLEDGE,
        entity_domain=SENSOR_DOMAIN,
        schema=None,
        func="async_acknowledge",
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Reglerna räknas om när villkoren ändras, med API:t som kom i HA 2026.10.
    if not hasattr(ConditionChecker, "async_track_changes"):
        raise ConfigEntryError("AttentionSpan kräver Home Assistant 2026.10.0 eller senare.")
    hass.data[DATA_SINCE].async_keep(entry.subentries)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload_on_change(entry)))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.data[DATA_SINCE].async_remove()


def _reload_on_change(entry: ConfigEntry) -> UpdateListenerType:
    """Ladda om när en regel har lagts till, ändrats eller tagits bort.

    När en regel flyttas får andra regler nya ordningstal. Har bara ordningstalen ändrats får
    sensorerna dem direkt, så att entiteterna inte blir otillgängliga under omladdningar.
    """
    rules = _rules(entry)

    async def _async_changed(hass: HomeAssistant, entry: ConfigEntry) -> None:
        nonlocal rules
        if _rules(entry) == rules:
            for subentry_id, subentry in entry.subentries.items():
                async_dispatcher_send(
                    hass, SIGNAL_PRIORITY.format(subentry_id), subentry.data[CONF_PRIORITY]
                )
            return
        # En flytt ändrar flera regler, och listenern anropas en gång per regel. Reglerna
        # sparas före omladdningen, så att de andra anropen inte laddar om igen.
        rules = _rules(entry)
        await hass.config_entries.async_reload(entry.entry_id)

    return _async_changed


def _rules(entry: ConfigEntry) -> dict[str, tuple[str, dict[str, Any]]]:
    """Reglernas namn och data utom ordningstalet."""
    return {
        subentry_id: (
            subentry.title,
            {key: value for key, value in subentry.data.items() if key != CONF_PRIORITY},
        )
        for subentry_id, subentry in entry.subentries.items()
    }

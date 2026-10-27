"""AttentionSpan: hemskärmen visar bara det som är viktigt nu."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.condition import ConditionChecker
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
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
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Reglerna räknas om när villkoren ändras, med API:t som kom i HA 2026.10.
    if not hasattr(ConditionChecker, "async_track_changes"):
        raise ConfigEntryError("AttentionSpan kräver Home Assistant 2026.10.0 eller senare.")
    hass.data[DATA_SINCE].async_keep(entry.subentries)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.data[DATA_SINCE].async_remove()


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    # En regel har lagts till, ändrats eller tagits bort.
    await hass.config_entries.async_reload(entry.entry_id)

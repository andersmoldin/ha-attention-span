import json
import pathlib

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.attention_span.const import DOMAIN

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

# Klockan när fixturernas notiser fick sin nivå.
FIXTURE_TIME = "2026-10-26T08:00:00+00:00"

# Formulärfälten för reglerna bakom fixturernas exempel.
BILEN = {"name": "Bilen", "icon": "mdi:car", "entity": "sensor.bilen_batteri", "level": "glance"}
ELPRIS = {"name": "Elpris", "icon": "mdi:flash", "entity": "sensor.elpris", "level": "quiet"}


def contract_example(name: str) -> dict:
    """Ett exempel i dataformat version 1, delat med kortets tester."""
    return json.loads((FIXTURES / "contract-v1.json").read_text())[name]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


async def add_integration(hass: HomeAssistant) -> ConfigEntry:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    return result["result"]


async def add_rule(hass: HomeAssistant, entry: ConfigEntry, rule_type: str, fields: dict) -> str:
    """Lägg till en Rule via subentry-flödet och returnera subentryns id."""
    before = set(entry.subentries)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "rule"), context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"type": rule_type}
    )
    assert result["step_id"] == rule_type
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], fields)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    (added,) = set(entry.subentries) - before
    return added


async def reconfigure_rule(
    hass: HomeAssistant, entry: ConfigEntry, subentry_id: str, fields: dict
) -> None:
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "rule"),
        context={"source": config_entries.SOURCE_RECONFIGURE, "subentry_id": subentry_id},
    )
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], fields)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()


def state_as_contract(hass: HomeAssistant, entity_id: str) -> dict | None:
    """Det automationer och kort ser av en entitet."""
    state = hass.states.get(entity_id)
    if state is None:
        return None
    return {
        "entity_id": state.entity_id,
        "state": state.state,
        "attributes": dict(state.attributes),
    }

import json
import pathlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from homeassistant import config_entries, loader
from homeassistant.config_entries import (
    SIGNAL_CONFIG_ENTRY_CHANGED,
    ConfigEntry,
    ConfigEntryChange,
    ConfigEntryState,
)
from homeassistant.const import EVENT_STATE_CHANGED, STATE_UNAVAILABLE
from homeassistant.core import CoreState, Event, HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult, FlowResultType
from homeassistant.helpers import restore_state
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from pytest_homeassistant_custom_component.common import (
    async_mock_load_restore_state_from_storage,
    async_test_home_assistant,
)

from custom_components.attention_span.const import DOMAIN, LEVELS, SUBENTRY_RULE

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

# Klockan när fixturernas notiser fick sin nivå.
FIXTURE_TIME = "2026-10-26T08:00:00+00:00"

# Formulärfälten för reglerna bakom fixturernas exempel.
BILEN = {"name": "Bilen", "icon": "mdi:car", "entity": "sensor.bilen_batteri"}
ELPRIS = {"name": "Elpris", "icon": "mdi:flash", "entity": "sensor.elpris"}
ALWAYS_GLANCE = {"glance": "always"}
ALWAYS_QUIET = {"quiet": "always"}


def contract_example(name: str) -> dict:
    """Ett exempel i dataformat version 1, delat med kortets tester."""
    return json.loads((FIXTURES / "contract-v1.json").read_text())[name]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@asynccontextmanager
async def restart(hass: HomeAssistant) -> AsyncIterator[HomeAssistant]:
    """Stäng av Home Assistant och starta en ny instans med samma lagring, som vid en omstart.

    Den nya instansen har laddat integrationerna men inte startat, så att testet kan sätta
    källentiteternas tillstånd först, som deras integrationer gör under en omstart. Starta
    den med hass.async_start().
    """
    # HA sparar entiteternas senaste tillstånd när den stängs av; testinstanserna gör det inte.
    await restore_state.async_get(hass).async_dump_states()
    await hass.async_stop()
    await unload(hass)
    async with async_test_home_assistant(
        config_dir=hass.config.config_dir, initial_state=CoreState.not_running
    ) as new:
        new.data.pop(loader.DATA_CUSTOM_COMPONENTS)
        await async_mock_load_restore_state_from_storage(new)
        await new.config_entries.async_initialize()
        try:
            yield new
        finally:
            await unload(new)
            await new.async_stop()


async def unload(hass: HomeAssistant) -> None:
    """Ladda ur integrationerna, så att testet inte lämnar timrar efter sig."""
    for entry in hass.config_entries.async_entries():
        if entry.state is config_entries.ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)


async def add_integration(hass: HomeAssistant) -> ConfigEntry:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    return result["result"]


async def start_rule(hass: HomeAssistant, entry: ConfigEntry, rule_type: str) -> FlowResult:
    """Öppna subentry-flödet för en ny Rule och välj Typ; returnerar typens formulär."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_RULE), context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"type": rule_type}
    )
    assert result["step_id"] == rule_type
    return result


async def start_rule_reconfigure(
    hass: HomeAssistant, entry: ConfigEntry, subentry_id: str
) -> FlowResult:
    return await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_RULE),
        context={"source": config_entries.SOURCE_RECONFIGURE, "subentry_id": subentry_id},
    )


def level_modes(levels: dict[str, str]) -> dict[str, str]:
    """Formulärets val för alla nivåer; en utelämnad nivå är Inget."""
    return {level: levels.get(level, "none") for level in LEVELS}


async def add_rule(
    hass: HomeAssistant,
    entry: ConfigEntry,
    rule_type: str,
    fields: dict,
    levels: dict[str, str],
    conditions: dict[str, list] | None = None,
    reason: dict | None = None,
    actions: list[dict] | None = None,
    placement: str | None = None,
    timing: dict | None = None,
) -> str:
    """Lägg till en Rule via subentry-flödet och returnera subentryns id.

    levels är Inget, Alltid eller Villkor per nivå (utelämnad nivå är Inget) och
    conditions villkoren för nivåerna med Villkor och för Dölj när. reason är
    orsaksstegets fält (utelämnat är ingen orsak) och actions åtgärderna. placement är
    placeringen, «first» eller regeln den står efter, när formuläret frågar efter den
    (utelämnad behåller förvalet). timing är tidernas fält, «larma igen» och fladdergränsen
    (utelämnat behåller det formuläret föreslår).
    """
    before = set(entry.subentries)
    result = await start_rule(hass, entry, rule_type)
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], fields)
    assert result["step_id"] == "levels"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], level_modes(levels)
    )
    assert result["step_id"] == "conditions"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], conditions or {}
    )
    result = await submit_placement(hass, result, placement)
    result = await submit_reason_and_actions(hass, result, reason, actions, timing)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    (added,) = set(entry.subentries) - before
    return added


async def reconfigure_rule(
    hass: HomeAssistant,
    entry: ConfigEntry,
    subentry_id: str,
    fields: dict,
    levels: dict[str, str],
    conditions: dict[str, list] | None = None,
    reason: dict | None = None,
    actions: list[dict] | None = None,
    placement: str | None = None,
    timing: dict | None = None,
) -> None:
    """Ändra en Rule; levels, conditions, reason, actions, placement och timing som i
    add_rule."""
    result = await start_rule_reconfigure(hass, entry, subentry_id)
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], fields)
    assert result["step_id"] == "levels"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], level_modes(levels)
    )
    assert result["step_id"] == "conditions"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], conditions or {}
    )
    result = await submit_placement(hass, result, placement)
    result = await submit_reason_and_actions(hass, result, reason, actions, timing)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()


async def submit_placement(
    hass: HomeAssistant, result: FlowResult, placement: str | None
) -> FlowResult:
    """Välj placeringen när formuläret frågar efter den; None behåller förvalet."""
    if result.get("step_id") != "placement":
        assert placement is None, "formuläret frågade inte efter placeringen"
        return result
    if placement is None:
        (field,) = result["data_schema"].schema
        placement = field.default()
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"placement": placement}
    )


async def submit_reason(hass: HomeAssistant, result: FlowResult, reason: dict) -> FlowResult:
    """Fyll i orsaken. Ett nytt val visar först sin förhandsvisning; skicka då samma igen."""
    assert result["step_id"] == "reason"
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], reason)
    if result.get("step_id") == "reason" and not result.get("errors"):
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], reason)
    return result


async def submit_reason_and_actions(
    hass: HomeAssistant,
    result: FlowResult,
    reason: dict | None,
    actions: list[dict] | None,
    timing: dict | None = None,
) -> FlowResult:
    """Fyll i orsaken, åtgärderna och tiderna; timing som i add_rule."""
    result = await submit_reason(hass, result, reason or {"reason": "none"})
    assert result["step_id"] == "actions"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"actions": actions or []}
    )
    assert result["step_id"] == "timing"
    if timing is None:
        # Som formuläret visar det: de föreslagna tiderna, och tomt där det inte föreslår någon.
        timing = {
            str(key): value
            for key in result["data_schema"].schema
            if (value := (key.description or {}).get("suggested_value")) is not None
        }
    return await hass.config_entries.subentries.async_configure(result["flow_id"], timing)


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


def watch(hass: HomeAssistant, entry: ConfigEntry) -> tuple[list[str], list[str]]:
    """Följ entiteterna och posten: entiteter som blir otillgängliga eller försvinner, och
    varje gång posten laddas ur."""
    gone: list[str] = []
    unloads: list[str] = []

    @callback
    def state_changed(event: Event) -> None:
        new = event.data["new_state"]
        if new is None or new.state == STATE_UNAVAILABLE:
            gone.append(event.data["entity_id"])

    @callback
    def entry_changed(change: ConfigEntryChange, changed: ConfigEntry) -> None:
        if changed.entry_id == entry.entry_id and changed.state is ConfigEntryState.NOT_LOADED:
            unloads.append(changed.entry_id)

    hass.bus.async_listen(EVENT_STATE_CHANGED, state_changed)
    async_dispatcher_connect(hass, SIGNAL_CONFIG_ENTRY_CHANGED, entry_changed)
    return gone, unloads

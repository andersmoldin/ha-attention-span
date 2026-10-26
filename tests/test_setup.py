from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.condition import ConditionChecker

from custom_components.attention_span.const import DOMAIN

from .conftest import add_integration


async def test_integration_can_only_be_added_once(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_setup_fails_clearly_on_home_assistant_before_2026_10(
    hass: HomeAssistant, monkeypatch
):
    monkeypatch.delattr(ConditionChecker, "async_track_changes")

    entry = await add_integration(hass)

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert entry.reason == "AttentionSpan kräver Home Assistant 2026.10.0 eller senare."

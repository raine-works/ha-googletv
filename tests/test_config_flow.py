"""Config flow tests: a real Home Assistant, the TV mocked."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant import config_entries  # noqa: E402
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.googletv.adb import (  # noqa: E402
    GoogleTvAuthError,
    GoogleTvError,
)
from custom_components.googletv.const import DOMAIN  # noqa: E402

PROPS = {
    "manufacturer": "TCL",
    "model": "Smart TV Pro",
    "android": "12",
    "serial": "ABC123",
}


@pytest.fixture(autouse=True)
def _custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load custom_components/googletv."""


def _client(pair: AsyncMock) -> AsyncMock:
    client = AsyncMock()
    client.async_pair = pair
    return client


def _patch_client(client: AsyncMock):
    return patch(
        "custom_components.googletv.config_flow.async_get_client",
        AsyncMock(return_value=client),
    )


def _patch_setup():
    return patch("custom_components.googletv.async_setup_entry", return_value=True)


async def test_adds_a_tv(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    client = _client(AsyncMock(return_value=PROPS))
    with _patch_client(client), _patch_setup():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: " 10.0.0.5 ", CONF_PORT: 5555}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "TCL Smart TV Pro"
    assert result["data"] == {CONF_HOST: "10.0.0.5", CONF_PORT: 5555}
    assert result["result"].unique_id == "ABC123"
    client.async_close.assert_awaited()


async def test_a_given_name_titles_it(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with _patch_client(_client(AsyncMock(return_value=PROPS))), _patch_setup():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "10.0.0.5", CONF_PORT: 5555, CONF_NAME: "Lott's TV"},
        )
    assert result["title"] == "Lott's TV"


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (GoogleTvAuthError("no"), "not_authorized"),
        (GoogleTvError("down"), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_errors_show_on_the_form(
    hass: HomeAssistant, error: Exception, reason: str
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with _patch_client(_client(AsyncMock(side_effect=error))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "10.0.0.5", CONF_PORT: 5555}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": reason}

    # And it recovers once the TV answers
    with _patch_client(_client(AsyncMock(return_value=PROPS))), _patch_setup():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "10.0.0.5", CONF_PORT: 5555}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_the_same_tv_at_a_new_address_updates_it(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="ABC123",
        data={CONF_HOST: "10.0.0.5", CONF_PORT: 5555},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with _patch_client(_client(AsyncMock(return_value=PROPS))), _patch_setup():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "10.0.0.9", CONF_PORT: 5555}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == "10.0.0.9"


async def test_reauth(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="ABC123",
        title="Lott's TV",
        data={CONF_HOST: "10.0.0.5", CONF_PORT: 5555},
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    with _patch_client(_client(AsyncMock(side_effect=GoogleTvAuthError("no")))):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["errors"] == {"base": "not_authorized"}

    with _patch_client(_client(AsyncMock(return_value=PROPS))), _patch_setup():
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"

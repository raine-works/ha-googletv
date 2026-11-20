"""Config flow tests: a real Home Assistant, the TV mocked."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from ipaddress import ip_address  # noqa: E402

from homeassistant import config_entries  # noqa: E402
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
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
    "bluetooth": "d0:76:02:55:7e:05",
}
TV_ID = "d0:76:02:55:7e:05"


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
    assert result["result"].unique_id == TV_ID
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
        unique_id=TV_ID,
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
        unique_id=TV_ID,
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


def test_without_bluetooth_the_serial_is_the_id() -> None:
    from custom_components.googletv.config_flow import _tv_id

    assert _tv_id({"serial": "ABC123"}) == "ABC123"
    assert _tv_id(PROPS) == TV_ID


def _discovery(address: str = "10.0.0.5", bt: str | None = "D0:76:02:55:7E:05"):
    return ZeroconfServiceInfo(
        ip_address=ip_address(address),
        ip_addresses=[ip_address(address)],
        hostname="Lott-s-TV.local.",
        name="Lott's TV._androidtvremote2._tcp.local.",
        port=6466,
        type="_androidtvremote2._tcp.local.",
        properties={"bt": bt} if bt else {},
    )


def _patch_probe(open_: bool):
    return patch(
        "custom_components.googletv.config_flow._adb_port_open",
        AsyncMock(return_value=open_),
    )


async def test_discovers_a_tv_with_adb_on(hass: HomeAssistant) -> None:
    with _patch_probe(True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_ZEROCONF},
            data=_discovery(),
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"
    assert result["description_placeholders"] == {
        "name": "Lott's TV",
        "host": "10.0.0.5",
    }

    with _patch_client(_client(AsyncMock(return_value=PROPS))), _patch_setup():
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Lott's TV"
    assert result["data"] == {CONF_HOST: "10.0.0.5", CONF_PORT: 5555}
    assert result["result"].unique_id == TV_ID


async def test_a_tv_with_adb_off_is_not_offered(hass: HomeAssistant) -> None:
    with _patch_probe(False):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_ZEROCONF},
            data=_discovery(),
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "adb_off"


async def test_a_known_tv_found_at_a_new_address(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=TV_ID, data={CONF_HOST: "10.0.0.5", CONF_PORT: 5555}
    )
    entry.add_to_hass(hass)
    with _patch_probe(True), _patch_setup():
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_ZEROCONF},
            data=_discovery("10.0.0.9"),
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == "10.0.0.9"


async def test_without_an_address_a_known_host_is_skipped(hass: HomeAssistant) -> None:
    MockConfigEntry(
        domain=DOMAIN, unique_id="ABC123", data={CONF_HOST: "10.0.0.5", CONF_PORT: 5555}
    ).add_to_hass(hass)
    with _patch_probe(True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_ZEROCONF},
            data=_discovery(bt=None),
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_turn_lookups_off(hass: HomeAssistant) -> None:
    from custom_components.googletv.const import CONF_ONLINE_LOOKUPS

    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=TV_ID, data={CONF_HOST: "10.0.0.5", CONF_PORT: 5555}
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    with _patch_setup():
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_ONLINE_LOOKUPS: False}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_ONLINE_LOOKUPS: False}


async def test_reconfigure_a_new_address(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=TV_ID, data={CONF_HOST: "10.0.0.5", CONF_PORT: 5555}
    )
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    with _patch_client(_client(AsyncMock(return_value=PROPS))), _patch_setup():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "10.0.0.9", CONF_PORT: 5556}
        )
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {CONF_HOST: "10.0.0.9", CONF_PORT: 5556}


async def test_reconfigure_refuses_another_tv(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=TV_ID, data={CONF_HOST: "10.0.0.5", CONF_PORT: 5555}
    )
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    other = {**PROPS, "bluetooth": "aa:bb:cc:dd:ee:ff", "serial": "OTHER"}
    with _patch_client(_client(AsyncMock(return_value=other))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "10.0.0.7", CONF_PORT: 5555}
        )
    assert result["reason"] == "wrong_device"
    assert entry.data[CONF_HOST] == "10.0.0.5"


async def test_reauth_an_entry_from_0_1(hass: HomeAssistant) -> None:
    # Entries added by 0.1 are known by the TV's serial
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="ABC123", data={CONF_HOST: "10.0.0.5", CONF_PORT: 5555}
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    with _patch_client(_client(AsyncMock(return_value=PROPS))), _patch_setup():
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["reason"] == "reauth_successful"


async def test_discovery_skips_a_tv_known_by_its_address(hass: HomeAssistant) -> None:
    # An entry from 0.1 (by serial) at the address the TV announces
    MockConfigEntry(
        domain=DOMAIN, unique_id="ABC123", data={CONF_HOST: "10.0.0.5", CONF_PORT: 5555}
    ).add_to_hass(hass)
    with _patch_probe(True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_ZEROCONF},
            data=_discovery(),
        )
    assert result["reason"] == "already_configured"

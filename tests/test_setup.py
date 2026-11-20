"""Setting up a TV end to end: a real Home Assistant, the TV's answers real."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import CONF_HOST, CONF_PORT  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402
from test_parsers import LOTTS_TCL_POLL  # noqa: E402

from custom_components.googletv.const import DOMAIN  # noqa: E402
from custom_components.googletv.parsers import App, parse_state  # noqa: E402

PROPS = {
    "manufacturer": "TCL",
    "model": "Smart TV Pro",
    "android": "12",
    "serial": "X1",
}
APPS = [
    App("com.netflix.ninja", "com.netflix.ninja.MainActivity", "Netflix"),
    App(
        "com.spotify.tv.android", "com.spotify.tv.android.SpotifyTVActivity", "Spotify"
    ),
]


@pytest.fixture(autouse=True)
def _custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load custom_components/googletv."""


@pytest.fixture
def client() -> AsyncMock:
    tv = AsyncMock()
    tv.async_get_props.return_value = PROPS
    tv.async_get_state.return_value = parse_state(LOTTS_TCL_POLL)
    tv.async_get_apps.return_value = APPS
    return tv


async def _set_up(hass: HomeAssistant, client: AsyncMock) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="X1",
        title="Lott's TV",
        data={CONF_HOST: "10.0.0.5", CONF_PORT: 5555},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.googletv.async_get_client",
        AsyncMock(return_value=client),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_the_tv_on_its_xbox_input(hass: HomeAssistant, client: AsyncMock) -> None:
    await _set_up(hass, client)
    tv = hass.states.get("media_player.lott_s_tv")
    assert tv is not None
    assert tv.state == "on"
    assert tv.attributes["source"] == "Xbox"
    assert tv.attributes["volume_level"] == 0.19
    assert tv.attributes["source_list"] == [
        "Netflix",
        "Spotify",
        "Xbox",
        "HDMI 2",
        "HDMI 3",
    ]
    assert tv.attributes["device_class"] == "tv"
    assert hass.states.get("remote.lott_s_tv").state == "on"


async def test_commands_reach_the_tv(hass: HomeAssistant, client: AsyncMock) -> None:
    await _set_up(hass, client)
    target = {"entity_id": "media_player.lott_s_tv"}
    await hass.services.async_call(
        "media_player", "select_source", {**target, "source": "Netflix"}, blocking=True
    )
    client.async_launch_app.assert_awaited_with(
        "com.netflix.ninja", "com.netflix.ninja.MainActivity"
    )
    await hass.services.async_call(
        "media_player", "select_source", {**target, "source": "HDMI 2"}, blocking=True
    )
    client.async_select_input.assert_awaited_with(
        "com.tcl.tvinput/.TvPassThroughService/HW16"
    )
    await hass.services.async_call(
        "media_player", "volume_set", {**target, "volume_level": 0.3}, blocking=True
    )
    client.async_set_volume.assert_awaited_with(0.3)
    await hass.services.async_call(
        "remote",
        "send_command",
        {"entity_id": "remote.lott_s_tv", "command": ["DPAD_UP", "BACK"]},
        blocking=True,
    )
    client.async_key.assert_any_await("DPAD_UP")
    client.async_key.assert_any_await("BACK")


async def test_unload_closes_the_connection(
    hass: HomeAssistant, client: AsyncMock
) -> None:
    entry = await _set_up(hass, client)
    assert await hass.config_entries.async_unload(entry.entry_id)
    client.async_close.assert_awaited()

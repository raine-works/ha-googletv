"""Setting up a TV end to end: a real Home Assistant, the TV's answers real.

The TV is mocked with its real poll, and the web with real replies saved
from Google Play, iTunes and TVmaze (``tests/fixtures``).
"""

from __future__ import annotations

from dataclasses import replace
import pathlib
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import CONF_HOST, CONF_PORT  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402
from pytest_homeassistant_custom_component.test_util.aiohttp import (  # noqa: E402
    AiohttpClientMocker,
)
from test_parsers import LOTTS_TCL_POLL  # noqa: E402

from custom_components.googletv.const import (  # noqa: E402
    CONF_ONLINE_LOOKUPS,
    DOMAIN,
)
from custom_components.googletv.lookups import (  # noqa: E402
    show_search_url,
    song_search_url,
    store_url,
)
from custom_components.googletv.parsers import (  # noqa: E402
    App,
    MediaSession,
    parse_state,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
PROPS = {
    "manufacturer": "TCL",
    "model": "Smart TV Pro",
    "android": "12",
    "serial": "X1",
}
# Netflix is known by name; the other two are named by their listings
OTHER_APP = "com.example.livetv"
APPS = [
    App("com.netflix.ninja", "com.netflix.ninja.MainActivity", "Netflix"),
    App(OTHER_APP, f"{OTHER_APP}.Main", OTHER_APP),
    App("com.tcl.tv", "com.tcl.tv.TVActivity", "com.tcl.tv"),
]
NETFLIX_ICON = (
    "https://play-lh.googleusercontent.com/ndMigyoaH5k4aZ5GyIHj5ZNXEJQ_YTkcCByrX-m-"
    "IZE1xGJYfQZ9Hr3u1rFDK3EByo4VcDtBohg0Aqp3d3SW0Jo=s256"
)
RICK_AND_MORTY = (
    "https://static.tvmaze.com/uploads/images/original_untouched/626/1566363.jpg"
)
YOUTUBE_TV = "com.google.android.youtube.tvunplugged"


@pytest.fixture(autouse=True)
def _custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load custom_components/googletv."""


@pytest.fixture
def web(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Google Play, iTunes and TVmaze, answering as they did."""
    aioclient_mock.get(
        store_url("com.netflix.ninja"),
        text=(FIXTURES / "store_netflix.html").read_text(),
    )
    aioclient_mock.get(
        store_url(OTHER_APP), text=(FIXTURES / "store_youtube_tv.html").read_text()
    )
    aioclient_mock.get(store_url("com.tcl.tv"), status=404)
    aioclient_mock.get(
        show_search_url("Rick and Morty"),
        text=(FIXTURES / "tvmaze_rick_and_morty.json").read_text(),
    )
    aioclient_mock.get(
        song_search_url("Everybody Grab a Broom", "J Scott Rakozy"),
        text=(FIXTURES / "itunes_broom.json").read_text(),
    )
    return aioclient_mock


@pytest.fixture
def client() -> AsyncMock:
    tv = AsyncMock()
    tv.async_get_props.return_value = PROPS
    tv.async_get_state.return_value = parse_state(LOTTS_TCL_POLL)
    tv.async_get_apps.return_value = APPS
    return tv


def _playing(package: str, title: str, subtitle: str):
    """Lott's TV, off the Xbox and playing something in an app."""
    state = parse_state(LOTTS_TCL_POLL)
    session = MediaSession(package, True, 3, 0, 0, 1.0, title, subtitle, None)
    return replace(state, app=package, input=None, sessions=[session])


async def _set_up(
    hass: HomeAssistant, client: AsyncMock, **options: bool
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="X1",
        title="Lott's TV",
        data={CONF_HOST: "10.0.0.5", CONF_PORT: 5555},
        options=options,
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.googletv.async_get_client",
        AsyncMock(return_value=client),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_the_tv_on_its_xbox_input(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    await _set_up(hass, client)
    tv = hass.states.get("media_player.lott_s_tv")
    assert tv is not None
    assert tv.state == "on"
    assert tv.attributes["source"] == "Xbox"
    assert tv.attributes["volume_level"] == 0.19
    assert tv.attributes["source_list"] == [
        "com.tcl.tv",
        "Netflix",
        "YouTube TV",
        "Xbox",
        "HDMI 2",
        "HDMI 3",
    ]
    assert tv.attributes["device_class"] == "tv"
    assert hass.states.get("remote.lott_s_tv").state == "on"

    tv_input = hass.states.get("select.lott_s_tv_input")
    assert tv_input.state == "Xbox"
    assert tv_input.attributes["options"] == ["Xbox", "HDMI 2", "HDMI 3"]


async def test_a_button_per_app_named_and_pictured(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    await _set_up(hass, client)
    netflix = hass.states.get("button.lott_s_tv_netflix")
    assert netflix.attributes["entity_picture"] == NETFLIX_ICON
    assert netflix.attributes["package"] == "com.netflix.ninja"
    # Named by its listing ("YouTube TV: Live TV & more" → "YouTube TV")
    assert hass.states.get("button.lott_s_tv_youtube_tv") is not None
    # Not on the Play Store: its package, and no picture
    tcl = hass.states.get("button.lott_s_tv_com_tcl_tv")
    assert "entity_picture" not in tcl.attributes

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.lott_s_tv_netflix"}, blocking=True
    )
    client.async_launch_app.assert_awaited_with(
        "com.netflix.ninja", "com.netflix.ninja.MainActivity"
    )


async def test_a_new_app_gets_a_button(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    entry = await _set_up(hass, client)
    coordinator = entry.runtime_data
    client.async_get_apps.return_value = [
        *APPS,
        App("com.netflix.extra", "com.netflix.extra.Main", "Extra"),
    ]
    coordinator._apps_read_at = None
    web.get(store_url("com.netflix.extra"), status=404)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("button.lott_s_tv_extra") is not None


async def test_a_shows_poster(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    client.async_get_state.return_value = _playing(
        YOUTUBE_TV, "Rick and Morty", "Adult Swim"
    )
    entry = await _set_up(hass, client)
    # Found in the background: shown from the next poll
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert entry.runtime_data.data.artwork == RICK_AND_MORTY
    tv = hass.states.get("media_player.lott_s_tv")
    assert tv.state == "playing"
    assert tv.attributes["entity_picture"].startswith("/api/media_player_proxy/")


async def test_a_songs_cover(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    client.async_get_state.return_value = _playing(
        "com.spotify.tv.android", "Everybody Grab a Broom", "J Scott Rakozy"
    )
    entry = await _set_up(hass, client)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    art = entry.runtime_data.data.artwork
    assert art and art.endswith("/600x600bb.jpg")


async def test_nothing_online_when_turned_off(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    client.async_get_state.return_value = _playing(
        YOUTUBE_TV, "Rick and Morty", "Adult Swim"
    )
    entry = await _set_up(hass, client, **{CONF_ONLINE_LOOKUPS: False})
    await hass.async_block_till_done()
    assert web.call_count == 0
    assert entry.runtime_data.data.artwork is None
    netflix = hass.states.get("button.lott_s_tv_netflix")
    assert "entity_picture" not in netflix.attributes


async def test_commands_reach_the_tv(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    await _set_up(hass, client)
    target = {"entity_id": "media_player.lott_s_tv"}
    await hass.services.async_call(
        "media_player", "select_source", {**target, "source": "Netflix"}, blocking=True
    )
    client.async_launch_app.assert_awaited_with(
        "com.netflix.ninja", "com.netflix.ninja.MainActivity"
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.lott_s_tv_input", "option": "HDMI 2"},
        blocking=True,
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


async def test_an_asleep_tv_wakes_to_open_an_app(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    client.async_get_state.return_value = replace(
        parse_state(LOTTS_TCL_POLL), awake=False
    )
    await _set_up(hass, client)
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.lott_s_tv_netflix"}, blocking=True
    )
    client.async_key.assert_awaited_with("WAKEUP")
    client.async_launch_app.assert_awaited()


async def test_unload_closes_the_connection(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    entry = await _set_up(hass, client)
    assert await hass.config_entries.async_unload(entry.entry_id)
    client.async_close.assert_awaited()

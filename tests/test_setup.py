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
    WIKIPEDIA_API,
    film_search_params,
    show_search_url,
    song_search_url,
    store_url,
)
from custom_components.googletv.parsers import (  # noqa: E402
    App,
    MediaSession,
    parse_diagnostics,
    parse_state,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
# The Master Suite Sony's diagnostics, verbatim: wired, 74% of /data used
SONY_DIAGNOSTICS = """\
@@net
lo 127.0.0.1/8
eth0 10.0.4.14/24
@@wifi
@@storage
/dev/block/mmcblk0p50   4285648 3064504   1116348  74% /data/user/0
@@memory
MemTotal:        2997848 kB
MemAvailable:     401020 kB
"""
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
        WIKIPEDIA_API,
        params=film_search_params("Cars"),
        text=(FIXTURES / "wikipedia_cars.json").read_text(),
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
    tv.async_get_diagnostics.return_value = parse_diagnostics(SONY_DIAGNOSTICS)
    return tv


def _playing(package: str, title: str, subtitle: str | None):
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
    # On the Xbox: its icon, on the select and the TV
    assert tv_input.attributes["icon"] == "mdi:microsoft-xbox"
    assert tv.attributes["icon"] == "mdi:microsoft-xbox"
    assert tv_input.attributes["inputs"][1] == {
        "name": "HDMI 2",
        "port": 2,
        "icon": "mdi:video-input-hdmi",
        "kind": "hdmi",
        "device": None,
    }


async def test_a_button_per_app_named_and_pictured(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    await _set_up(hass, client)
    netflix = hass.states.get("button.lott_s_tv_apps_netflix")
    assert netflix.attributes["entity_picture"] == NETFLIX_ICON
    assert netflix.attributes["package"] == "com.netflix.ninja"
    # Named by its listing ("YouTube TV: Live TV & more" → "YouTube TV")
    assert hass.states.get("button.lott_s_tv_apps_youtube_tv") is not None
    # Not on the Play Store: its package, and no picture
    tcl = hass.states.get("button.lott_s_tv_apps_com_tcl_tv")
    assert "entity_picture" not in tcl.attributes

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.lott_s_tv_apps_netflix"}, blocking=True
    )
    client.async_launch_app.assert_awaited_with(
        "com.netflix.ninja", "com.netflix.ninja.MainActivity"
    )


async def test_the_apps_are_a_device_under_the_tv(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from homeassistant.helpers import device_registry as dr, entity_registry as er

    await _set_up(hass, client)
    devices, entities = dr.async_get(hass), er.async_get(hass)
    tv = devices.async_get_device(identifiers={(DOMAIN, "X1")})
    apps = devices.async_get_device(identifiers={(DOMAIN, "X1_apps")})
    assert apps.name == "Lott's TV Apps" and apps.via_device_id == tv.id
    netflix = entities.async_get("button.lott_s_tv_apps_netflix")
    assert netflix.device_id == apps.id
    # The input and the remote's keys stay on the TV
    assert entities.async_get("select.lott_s_tv_input").device_id == tv.id
    assert entities.async_get("button.lott_s_tv_home").device_id == tv.id


async def test_the_remote_keys(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    await _set_up(hass, client)
    for entity, key in (
        ("button.lott_s_tv_home", "HOME"),
        ("button.lott_s_tv_back", "BACK"),
        ("button.lott_s_tv_up", "DPAD_UP"),
        ("button.lott_s_tv_ok", "DPAD_CENTER"),
        ("button.lott_s_tv_play_pause", "MEDIA_PLAY_PAUSE"),
        ("button.lott_s_tv_volume_up", "VOLUME_UP"),
        ("button.lott_s_tv_mute", "VOLUME_MUTE"),
        ("button.lott_s_tv_settings", "SETTINGS"),
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": entity}, blocking=True
        )
        client.async_key.assert_awaited_with(key)


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
    assert hass.states.get("button.lott_s_tv_apps_extra") is not None


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


async def test_a_films_poster(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    # Disney+ reports a film by its title alone: films are tried first
    client.async_get_state.return_value = _playing(
        "com.disney.disneyplus", "Cars", None
    )
    entry = await _set_up(hass, client)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert entry.runtime_data.data.artwork == (
        "https://upload.wikimedia.org/wikipedia/en/3/34/Cars_2006.jpg"
    )
    assert not any("tvmaze" in str(call[1]) for call in web.mock_calls)


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
    netflix = hass.states.get("button.lott_s_tv_apps_netflix")
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
    client.async_set_volume.assert_awaited_with(0.3, 100)
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
        "button", "press", {"entity_id": "button.lott_s_tv_apps_netflix"}, blocking=True
    )
    client.async_key.assert_awaited_with("WAKEUP")
    client.async_launch_app.assert_awaited()


async def test_unload_closes_the_connection(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    entry = await _set_up(hass, client)
    assert await hass.config_entries.async_unload(entry.entry_id)
    client.async_close.assert_awaited()


async def test_the_activity_sensor(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    entry = await _set_up(hass, client)
    coordinator = entry.runtime_data
    activity = "sensor.lott_s_tv_activity"
    # On the Xbox
    assert hass.states.get(activity).state == "input"
    assert hass.states.get(activity).attributes["input"] == "Xbox"
    for state, expected in (
        (_playing(YOUTUBE_TV, "Rick and Morty", "Adult Swim"), "playing"),
        (
            replace(
                _playing(YOUTUBE_TV, "Rick and Morty", "Adult Swim"),
                sessions=[
                    MediaSession(
                        YOUTUBE_TV, True, 2, 0, 0, 0.0, "Rick and Morty", "x", None
                    )
                ],
            ),
            "paused",
        ),
        (
            replace(
                parse_state(LOTTS_TCL_POLL),
                app="com.google.android.apps.tv.launcherx",
                input=None,
                sessions=[],
            ),
            "home",
        ),
        (
            replace(
                parse_state(LOTTS_TCL_POLL),
                app="com.netflix.ninja",
                input=None,
                sessions=[],
            ),
            "app",
        ),
        (replace(parse_state(LOTTS_TCL_POLL), screensaver=True), "screensaver"),
        (replace(parse_state(LOTTS_TCL_POLL), awake=False), "off"),
    ):
        client.async_get_state.return_value = state
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(activity).state == expected
    # The screensaver is idle, not off; off is off
    assert hass.states.get("media_player.lott_s_tv").state == "off"


async def test_an_app_in_front_ends_the_input(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    # The TV still reports its input session while Netflix, a launcher app
    # (and not one the integration knows by name), is in front
    client.async_get_apps.return_value = [
        *APPS,
        App("com.example.streamer", "com.example.streamer.Main", "Streamer"),
    ]
    client.async_get_state.return_value = replace(
        parse_state(LOTTS_TCL_POLL), app="com.example.streamer"
    )
    web.get(store_url("com.example.streamer"), status=404)
    await _set_up(hass, client)
    assert hass.states.get("select.lott_s_tv_input").state == "unknown"
    assert hass.states.get("sensor.lott_s_tv_activity").state == "app"


async def test_volume_on_the_tvs_own_scale(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    client.async_get_state.return_value = replace(
        parse_state(LOTTS_TCL_POLL), volume_max=15
    )
    await _set_up(hass, client)
    await hass.services.async_call(
        "media_player",
        "volume_set",
        {"entity_id": "media_player.lott_s_tv", "volume_level": 0.4},
        blocking=True,
    )
    client.async_set_volume.assert_awaited_with(0.4, 15)


async def test_diagnostic_sensors(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    await _set_up(hass, client)
    assert hass.states.get("sensor.lott_s_tv_connection").state == "ethernet"
    assert hass.states.get("sensor.lott_s_tv_storage_used").state == "74"
    # The TV's input app (the test lists it by its package)
    assert hass.states.get("sensor.lott_s_tv_current_app").state == "com.tcl.tv"
    # Wired: no Wi-Fi signal sensor
    assert hass.states.get("sensor.lott_s_tv_wi_fi_signal") is None
    assert hass.states.get("sensor.lott_s_tv_last_restart") is not None


async def test_diagnostics_download(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from custom_components.googletv.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry = await _set_up(hass, client)
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert report["entry"]["data"]["host"] == "**REDACTED**"
    assert report["entry"]["unique_id"] == "**REDACTED**"
    assert report["device"]["serial"] == "**REDACTED**"
    assert report["diagnostics"]["ip_address"] == "**REDACTED**"
    assert report["state"]["activity_state"] == "input"
    assert report["state"]["input"]["label"] == "Xbox"


async def test_playing_under_the_screensaver(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    client.async_get_state.return_value = replace(
        _playing("com.spotify.tv.android", "Everybody Grab a Broom", "J Scott Rakozy"),
        screensaver=True,
    )
    await _set_up(hass, client)
    assert hass.states.get("sensor.lott_s_tv_activity").state == "playing"
    assert hass.states.get("media_player.lott_s_tv").state == "playing"


async def test_the_position_isnt_redated_every_poll(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    # Paused at 60s: the position and its date stay put across polls
    state = _playing(YOUTUBE_TV, "Rick and Morty", "Adult Swim")
    paused = replace(
        state,
        sessions=[
            MediaSession(
                YOUTUBE_TV, True, 2, 60000, 0, 0.0, "Rick and Morty", "x", None
            )
        ],
    )
    client.async_get_state.return_value = paused
    entry = await _set_up(hass, client)
    first = hass.states.get("media_player.lott_s_tv").attributes
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    again = hass.states.get("media_player.lott_s_tv").attributes
    assert first["media_position"] == again["media_position"] == 60
    assert first["media_position_updated_at"] == again["media_position_updated_at"]


async def test_an_untrusted_key_asks_to_reconnect(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from custom_components.googletv.adb import GoogleTvAuthError

    entry = await _set_up(hass, client)
    client.async_get_state.side_effect = GoogleTvAuthError("not allowed")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_a_failed_first_update_closes_its_connection(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from homeassistant.config_entries import ConfigEntryState

    from custom_components.googletv.adb import GoogleTvError

    client.async_get_state.side_effect = GoogleTvError("timed out")
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="X1", data={CONF_HOST: "10.0.0.5", CONF_PORT: 5555}
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.googletv.async_get_client", AsyncMock(return_value=client)
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    client.async_close.assert_awaited()


async def test_a_wifi_signal_once_the_tv_is_on_wifi(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    entry = await _set_up(hass, client)
    assert hass.states.get("sensor.lott_s_tv_wi_fi_signal") is None
    client.async_get_diagnostics.return_value = parse_diagnostics(
        "@@net\nwlan0 10.0.4.20/24\n@@wifi\nRSSI: -61\n"
    )
    entry.runtime_data._apps_read_at = None
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.lott_s_tv_wi_fi_signal").state == "-61"

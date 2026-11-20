"""Setting up a TV end to end: a real Home Assistant, the TV's answers real.

The TV is mocked with its real poll, and the web with real replies saved
from Google Play, iTunes and TVmaze (``tests/fixtures``).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import hashlib
import json
import pathlib
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import CONF_HOST, CONF_PORT  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.util import dt as dt_util  # noqa: E402
from pytest_homeassistant_custom_component.common import (  # noqa: E402
    MockConfigEntry,
    async_fire_time_changed,
)
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
    movie_search_url,
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
# The integration's version: a TV app as old is up to date
VERSION = json.loads(
    (
        pathlib.Path(__file__).parent.parent
        / "custom_components/googletv/manifest.json"
    ).read_text()
)["version"]
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
    "mac_ethernet": "d0:65:b3:e2:d2:a7",
    "mac_wifi": "bc:09:b9:6f:8e:8c",
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
        movie_search_url("Cars"),
        text=(FIXTURES / "play_movies_cars.html").read_text(),
    )
    aioclient_mock.get(
        movie_search_url("Moana"), text="<html>Not on Google Play</html>"
    )
    aioclient_mock.get(
        WIKIPEDIA_API,
        params=film_search_params("Moana"),
        text=json.dumps(
            {
                "query": {
                    "pages": [
                        {
                            "index": 1,
                            "title": "Moana (2016 film)",
                            "original": {
                                "source": "https://upload.wikimedia.org/wikipedia"
                                "/en/2/26/Moana_Teaser_Poster.jpg?utm_source=x"
                            },
                        }
                    ]
                }
            }
        ),
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

    async def quick(previous):
        # The quick read, here a fresh full one (with what a test set it to)
        return await tv.async_get_state()

    tv.async_get_quick_state.side_effect = quick
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
    netflix = hass.states.get("button.lott_s_tv_app_netflix")
    assert netflix.attributes["entity_picture"] == NETFLIX_ICON
    assert netflix.attributes["package"] == "com.netflix.ninja"
    # Named by its listing ("YouTube TV: Live TV & more" → "YouTube TV")
    assert hass.states.get("button.lott_s_tv_app_youtube_tv") is not None
    # Not on the Play Store: its package, and no picture
    tcl = hass.states.get("button.lott_s_tv_app_com_tcl_tv")
    assert "entity_picture" not in tcl.attributes

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.lott_s_tv_app_netflix"}, blocking=True
    )
    client.async_launch_app.assert_awaited_with(
        "com.netflix.ninja", "com.netflix.ninja.MainActivity"
    )


async def test_the_apps_are_on_the_tv_device(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from homeassistant.helpers import device_registry as dr, entity_registry as er

    await _set_up(hass, client)
    devices, entities = dr.async_get(hass), er.async_get(hass)
    tv = devices.async_get_device(identifiers={(DOMAIN, "X1")})
    assert devices.async_get_device(identifiers={(DOMAIN, "X1_apps")}) is None
    assert entities.async_get("button.lott_s_tv_app_netflix").device_id == tv.id
    assert entities.async_get("select.lott_s_tv_input").device_id == tv.id
    assert entities.async_get("button.lott_s_tv_remote_home").device_id == tv.id
    # Named so each kind sorts together on the device's page
    names = {
        hass.states.get(e).name
        for e in ("button.lott_s_tv_app_netflix", "button.lott_s_tv_remote_home")
    }
    assert names == {"Lott's TV App · Netflix", "Lott's TV Remote · Home"}


async def test_the_apps_device_from_before_goes(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    """Its buttons move to the TV, a disabled one too; the device goes."""
    from homeassistant.helpers import device_registry as dr, entity_registry as er

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="X1",
        title="Lott's TV",
        data={CONF_HOST: "10.0.0.5", CONF_PORT: 5555},
    )
    entry.add_to_hass(hass)
    devices, entities = dr.async_get(hass), er.async_get(hass)
    devices.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "X1")}
    )
    old = devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "X1_apps")},
        name="Lott's TV Apps",
    )
    tcl = entities.async_get_or_create(
        "button",
        DOMAIN,
        "X1_app_com.tcl.tv",
        config_entry=entry,
        device_id=old.id,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    with patch(
        "custom_components.googletv.async_get_client",
        AsyncMock(return_value=client),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    tv = devices.async_get_device(identifiers={(DOMAIN, "X1")})
    assert devices.async_get(old.id) is None
    moved = entities.async_get(tcl.entity_id)
    assert moved.device_id == tv.id and moved.disabled


async def test_the_remote_keys(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    await _set_up(hass, client)
    for entity, key in (
        ("button.lott_s_tv_remote_home", "HOME"),
        ("button.lott_s_tv_remote_back", "BACK"),
        ("button.lott_s_tv_remote_up", "DPAD_UP"),
        ("button.lott_s_tv_remote_ok", "DPAD_CENTER"),
        ("button.lott_s_tv_remote_play_pause", "MEDIA_PLAY_PAUSE"),
        ("button.lott_s_tv_remote_volume_up", "VOLUME_UP"),
        ("button.lott_s_tv_remote_mute", "VOLUME_MUTE"),
        ("button.lott_s_tv_remote_settings", "SETTINGS"),
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
    assert hass.states.get("button.lott_s_tv_app_extra") is not None


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
    # Google Play's full-size poster; no show lookup, no Wikipedia
    assert entry.runtime_data.data.artwork == (
        "https://play-lh.googleusercontent.com/PF7TOtRoTfdxv-srjfHbhrsUMUCLr0kKFJNv5"
        "KH3WmUUruvMEpemIj5DT_Xs5vHckr1H4zjzbuvc_i5PAzc=s900"
    )
    assert not any(
        "tvmaze" in str(call[1]) or "wikipedia" in str(call[1])
        for call in web.mock_calls
    )


async def test_a_film_not_on_google_play(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    client.async_get_state.return_value = _playing(
        "com.disney.disneyplus", "Moana", None
    )
    entry = await _set_up(hass, client)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert entry.runtime_data.data.artwork == (
        "https://upload.wikimedia.org/wikipedia/en/2/26/Moana_Teaser_Poster.jpg"
    )


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
    netflix = hass.states.get("button.lott_s_tv_app_netflix")
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
        "button", "press", {"entity_id": "button.lott_s_tv_app_netflix"}, blocking=True
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


async def test_a_tv_off_its_network_is_off(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from custom_components.googletv.adb import GoogleTvError

    entry = await _set_up(hass, client)
    # It drops off its network in standby (a Sony without Remote start)
    client.async_get_state.side_effect = GoogleTvError("No route to host")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("media_player.lott_s_tv").state == "off"
    assert hass.states.get("sensor.lott_s_tv_activity").state == "off"
    assert hass.states.get("remote.lott_s_tv").state == "off"
    # What needs the TV is unavailable until it's back
    assert hass.states.get("button.lott_s_tv_remote_home").state == "unavailable"
    assert hass.states.get("select.lott_s_tv_input").state == "unavailable"
    # Turn on sends Wake-on-LAN to its MACs
    with patch("custom_components.googletv.coordinator.async_wake") as wake:
        await hass.services.async_call(
            "media_player",
            "turn_on",
            {"entity_id": "media_player.lott_s_tv"},
            blocking=True,
        )
    wake.assert_awaited_once_with(hass, ["d0:65:b3:e2:d2:a7", "bc:09:b9:6f:8e:8c"])
    # Back on its network
    client.async_get_state.side_effect = None
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.lott_s_tv_activity").state == "input"


async def test_set_up_with_the_tv_off_its_network(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from homeassistant.config_entries import ConfigEntryState

    from custom_components.googletv.adb import GoogleTvError
    from custom_components.googletv.const import CONF_PROPS

    # Home Assistant starting with the TV off: what's stored of it suffices
    client.async_connect.side_effect = GoogleTvError("No route to host")
    client.async_get_state.side_effect = GoogleTvError("No route to host")
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="X1",
        title="Lott's TV",
        data={CONF_HOST: "10.0.0.5", CONF_PORT: 5555, CONF_PROPS: PROPS},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.googletv.async_get_client", AsyncMock(return_value=client)
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("media_player.lott_s_tv").state == "off"


async def test_never_reached_and_nothing_stored_retries(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from homeassistant.config_entries import ConfigEntryState

    from custom_components.googletv.adb import GoogleTvError

    client.async_connect.side_effect = GoogleTvError("No route to host")
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


async def test_the_props_are_stored(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from custom_components.googletv.const import CONF_PROPS

    entry = await _set_up(hass, client)
    assert entry.data[CONF_PROPS] == PROPS
    # Storing them didn't reload it
    assert client.async_connect.await_count == 1


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


async def test_a_pause_shows_from_the_quick_read(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from custom_components.googletv.parsers import parse_quick

    playing = _playing(YOUTUBE_TV, "Rick and Morty", "Adult Swim")
    client.async_get_state.return_value = playing
    entry = await _set_up(hass, client)
    assert hass.states.get("sensor.lott_s_tv_activity").state == "playing"
    # Within the full read's interval: only the quick read runs, and the
    # pause it sees shows at once
    full_reads = client.async_get_state.await_count
    paused = (
        "@@power\n  mWakefulness=Awake\n@@uptime\n1294401.03 4698049.80\n"
        "@@sessions\n"
        f"      package={YOUTUBE_TV}\n      active=true\n"
        "      state=PlaybackState {state=2, position=5000, speed=0.0,"
        " updated=1294400000, actions=0}\n"
        "      metadata: size=5, description=Rick and Morty, Adult Swim, null\n"
    )
    client.async_get_quick_state.side_effect = lambda previous: parse_quick(
        paused, previous
    )
    await entry.runtime_data._async_refresh()
    await hass.async_block_till_done()
    assert client.async_get_state.await_count == full_reads
    assert hass.states.get("sensor.lott_s_tv_activity").state == "paused"
    assert hass.states.get("media_player.lott_s_tv").state == "paused"


# The TV app

BRIDGE = "http://10.0.0.5:8721"
BRIDGE_APP = App(
    "com.raineworks.tvbridge", "com.raineworks.tvbridge.MainActivity", "TV Bridge"
)


def _bridge_web(web: AiohttpClientMocker, token: str = "T0KEN") -> None:
    web.get(store_url("com.raineworks.tvbridge"), status=404)
    web.post(f"{BRIDGE}/api/pair/start", json={"pairing_id": "p1"})
    web.post(f"{BRIDGE}/api/pair/finish", json={"token": token})
    web.post(
        f"{BRIDGE}/api/notify",
        json={
            "popup": True,
            "panel": False,
            "blocked_by": None,
            "reason": None,
            "instance": "run-1",
        },
    )
    web.post(
        f"{BRIDGE}/api/rules",
        json={"blocked_apps": [], "blocked_inputs": [], "when_blocked": "panel"},
    )
    web.get(f"{BRIDGE}/api/rules", json=RULES)
    web.get(
        f"{BRIDGE}/api/info",
        json={
            "api": 1,
            "app_version": VERSION,
            "build": "abc1234",
            "paired": True,
            "features": ["events", "confirm_pairing", "device", "hidden_apps"],
            "installer": None,
        },
    )
    web.post(f"{BRIDGE}/api/client", json={"ok": True})
    # The event stream: the app's hello, then it ends (connected again later)
    web.get(f"{BRIDGE}/api/events", text='{"type": "hello", "instance": "run-1"}\n')


# The TV app's rules: YouTube TV left out of Home Assistant
RULES = {
    "hidden_apps": [OTHER_APP],
    "blocked_apps": [],
    "blocked_inputs": [],
    "when_blocked": "panel",
    "default_size": "small",
    "default_position": "top_right",
}


def _bridge_calls(web: AiohttpClientMocker, path: str) -> list:
    return [call for call in web.mock_calls if str(call[1]).endswith(path)]


async def test_tv_bridge_pairs_over_adb(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from custom_components.googletv.const import CONF_BRIDGE_TOKEN

    client.async_get_apps.return_value = [*APPS, BRIDGE_APP]
    # The app writes the code where only ADB reads it
    client.async_read_file.return_value = "p1 123456\n"
    _bridge_web(web)
    entry = await _set_up(hass, client)
    await hass.async_block_till_done()
    client.async_read_file.assert_awaited_with(
        "/sdcard/Android/data/com.raineworks.tvbridge/files/pairing_code"
    )
    finish = _bridge_calls(web, "/api/pair/finish")[0]
    assert finish[2] == {"pairing_id": "p1", "code": "123456"}
    assert entry.data[CONF_BRIDGE_TOKEN] == "T0KEN"
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("notify.lott_s_tv_notifications").state != "unavailable"
    assert hass.states.get("media_player.lott_s_tv").attributes["tv_bridge"] == "paired"


async def _paired(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> MockConfigEntry:
    from custom_components.googletv.const import CONF_BRIDGE_TOKEN

    client.async_get_apps.return_value = [*APPS, BRIDGE_APP]
    _bridge_web(web)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="X1",
        title="Lott's TV",
        data={CONF_HOST: "10.0.0.5", CONF_PORT: 5555, CONF_BRIDGE_TOKEN: "T0KEN"},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.googletv.async_get_client", AsyncMock(return_value=client)
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_a_notification_from_the_notify_entity(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    await _paired(hass, client, web)
    await hass.services.async_call(
        "notify",
        "send_message",
        {
            "entity_id": "notify.lott_s_tv_notifications",
            "title": "Laundry",
            "message": "The washer is done",
        },
        blocking=True,
    )
    call = _bridge_calls(web, "/api/notify")[-1]
    assert call[2]["title"] == "Laundry"
    assert call[2]["message"] == "The washer is done"
    # What's on screen, for the app's rules: the Xbox input
    assert call[2]["context"] == {
        "app": "com.tcl.tv",
        "input": "com.tcl.tvinput/.TvPassThroughService/HW15",
    }
    assert call[3]["Authorization"] == "Bearer T0KEN"


async def test_the_notify_action(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    hass.config.internal_url = "http://192.168.1.2:8123"
    await _paired(hass, client, web)
    reply = await hass.services.async_call(
        DOMAIN,
        "notify",
        {
            "entity_id": "media_player.lott_s_tv",
            "title": "Doorbell",
            "icon": "mdi:doorbell",
            "image": "/local/doorbell.jpg",
            "position": "bottom_right",
            "duration": 12,
            "size": "large",
        },
        blocking=True,
        return_response=True,
    )
    call = _bridge_calls(web, "/api/notify")[-1]
    # Signed, for the TV to load it without signing in
    assert call[2]["image_url"].startswith(
        "http://192.168.1.2:8123/local/doorbell.jpg?authSig="
    )
    assert call[2]["icon"] == "mdi:doorbell"
    assert (call[2]["position"], call[2]["duration"], call[2]["size"]) == (
        "bottom_right",
        12,
        "large",
    )
    assert reply["media_player.lott_s_tv"]["popup"] is True


async def test_notify_needs_something_to_show(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from homeassistant.exceptions import ServiceValidationError

    await _paired(hass, client, web)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "notify",
            {"entity_id": "media_player.lott_s_tv", "position": "top"},
            blocking=True,
        )


async def _live_door(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> MockConfigEntry:
    """The front door opens, and a pill says so until it closes."""
    hass.states.async_set("binary_sensor.front_door", "on")
    entry = await _paired(hass, client, web)
    web.post(f"{BRIDGE}/api/dismiss", json={"ok": True})
    reply = await hass.services.async_call(
        DOMAIN,
        "notify",
        {
            "entity_id": "media_player.lott_s_tv",
            "title": "Front door open",
            "icon": "mdi:door-open",
            "size": "compact",
            "until_entity": "binary_sensor.front_door",
        },
        blocking=True,
        return_response=True,
    )
    assert reply["media_player.lott_s_tv"]["tag"] == "until:binary_sensor.front_door"
    return entry


async def test_a_live_notification_until_the_door_closes(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    await _live_door(hass, client, web)
    call = _bridge_calls(web, "/api/notify")[-1]
    # Up until it's dismissed, under a tag to update and dismiss it by
    assert call[2]["duration"] == 0
    assert call[2]["tag"] == "until:binary_sensor.front_door"
    # A blip isn't the door closing
    hass.states.async_set("binary_sensor.front_door", "unavailable")
    await hass.async_block_till_done()
    assert not _bridge_calls(web, "/api/dismiss")
    hass.states.async_set("binary_sensor.front_door", "off")
    await hass.async_block_till_done()
    dismiss = _bridge_calls(web, "/api/dismiss")
    assert [c[2] for c in dismiss] == [{"tag": "until:binary_sensor.front_door"}]
    # Done: opening again isn't watched by the old one
    hass.states.async_set("binary_sensor.front_door", "on")
    hass.states.async_set("binary_sensor.front_door", "off")
    await hass.async_block_till_done()
    assert len(_bridge_calls(web, "/api/dismiss")) == 1


async def test_a_live_notification_until_a_state(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    hass.states.async_set("sensor.washer", "washing")
    await _paired(hass, client, web)
    web.post(f"{BRIDGE}/api/dismiss", json={"ok": True})
    await hass.services.async_call(
        DOMAIN,
        "notify",
        {
            "entity_id": "media_player.lott_s_tv",
            "title": "Washing",
            "progress": 40.4,
            "tag": "washer",
            "until_entity": "sensor.washer",
            "until_state": "idle",
        },
        blocking=True,
    )
    call = _bridge_calls(web, "/api/notify")[-1]
    assert (call[2]["tag"], call[2]["progress"]) == ("washer", 40)
    hass.states.async_set("sensor.washer", "rinsing")
    await hass.async_block_till_done()
    assert not _bridge_calls(web, "/api/dismiss")
    hass.states.async_set("sensor.washer", "idle")
    await hass.async_block_till_done()
    assert _bridge_calls(web, "/api/dismiss")[-1][2] == {"tag": "washer"}


async def test_a_live_notification_already_over_isnt_shown(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    hass.states.async_set("lock.front", "locked")
    await _paired(hass, client, web)
    reply = await hass.services.async_call(
        DOMAIN,
        "notify",
        {
            "entity_id": "media_player.lott_s_tv",
            "title": "Unlocked",
            "until_entity": "lock.front",
            "until_state": "locked",
        },
        blocking=True,
        return_response=True,
    )
    assert reply["media_player.lott_s_tv"]["reason"] == "until_met"
    assert not _bridge_calls(web, "/api/notify")


async def test_until_an_unknown_entity(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from homeassistant.exceptions import ServiceValidationError

    await _paired(hass, client, web)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "notify",
            {
                "entity_id": "media_player.lott_s_tv",
                "title": "Hi",
                "until_entity": "binary_sensor.nope",
            },
            blocking=True,
        )


async def test_dismissing_stops_watching(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    await _live_door(hass, client, web)
    await hass.services.async_call(
        DOMAIN,
        "dismiss_notifications",
        {"entity_id": "media_player.lott_s_tv"},
        blocking=True,
    )
    assert _bridge_calls(web, "/api/dismiss")[-1][2] == {}
    hass.states.async_set("binary_sensor.front_door", "off")
    await hass.async_block_till_done()
    assert len(_bridge_calls(web, "/api/dismiss")) == 1


async def test_live_notifications_come_back_when_the_app_restarts(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    entry = await _live_door(hass, client, web)
    coordinator = entry.runtime_data
    web.get(f"{BRIDGE}/api/state", json={"instance": "run-2", "popups": []})
    sent = len(_bridge_calls(web, "/api/notify"))
    await coordinator._async_check_live()
    calls = _bridge_calls(web, "/api/notify")
    assert len(calls) == sent + 1
    assert calls[-1][2]["tag"] == "until:binary_sensor.front_door"
    # The same run: nothing to show again
    await coordinator._async_check_live()
    assert len(_bridge_calls(web, "/api/notify")) == sent + 1


async def test_a_notification_after_the_app_restarts_doesnt_skip_the_replay(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    entry = await _live_door(hass, client, web)
    coordinator = entry.runtime_data
    # The app restarted (run-2), and a plain notification went out before
    # the check: its reply mustn't count as the live ones being shown again
    web.get(f"{BRIDGE}/api/state", json={"instance": "run-2", "popups": []})
    coordinator._bridge_instance = "run-1"
    await hass.services.async_call(
        "notify",
        "send_message",
        {"entity_id": "notify.lott_s_tv_notifications", "message": "Hi"},
        blocking=True,
    )
    sent = len(_bridge_calls(web, "/api/notify"))
    await coordinator._async_check_live()
    assert len(_bridge_calls(web, "/api/notify")) == sent + 1
    assert coordinator._bridge_instance == "run-2"


async def test_a_dismissal_that_fails_is_tried_again(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    import aiohttp
    from homeassistant.exceptions import HomeAssistantError

    entry = await _live_door(hass, client, web)
    coordinator = entry.runtime_data
    web.clear_requests()
    web.post(f"{BRIDGE}/api/dismiss", exc=aiohttp.ClientError("TV asleep"))
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            "dismiss_notifications",
            {
                "entity_id": "media_player.lott_s_tv",
                "tag": "until:binary_sensor.front_door",
            },
            blocking=True,
        )
    assert coordinator._dismiss_pending == {"until:binary_sensor.front_door"}
    web.clear_requests()
    web.post(f"{BRIDGE}/api/dismiss", json={"ok": True})
    await coordinator._async_check_live()
    assert coordinator._dismiss_pending == set()
    assert _bridge_calls(web, "/api/dismiss")


async def test_until_makes_it_live_whatever_the_duration(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    hass.states.async_set("binary_sensor.garage", "on")
    entry = await _paired(hass, client, web)
    await hass.services.async_call(
        DOMAIN,
        "notify",
        {
            "entity_id": "media_player.lott_s_tv",
            "title": "Garage open",
            "duration": 30,
            "until_entity": "binary_sensor.garage",
        },
        blocking=True,
    )
    assert _bridge_calls(web, "/api/notify")[-1][2]["duration"] == 0
    assert "until:binary_sensor.garage" in entry.runtime_data._live


async def test_a_live_notification_waits_for_its_entity_after_a_restart(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    entry = await _live_door(hass, client, web)
    await hass.config_entries.async_unload(entry.entry_id)
    # Home Assistant starting again: the door's integration isn't up yet
    hass.states.async_remove("binary_sensor.front_door")
    with patch(
        "custom_components.googletv.async_get_client", AsyncMock(return_value=client)
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    coordinator = entry.runtime_data
    assert "until:binary_sensor.front_door" in coordinator._live
    assert not coordinator._dismiss_pending
    # Then it's there, still open; then it closes
    hass.states.async_set("binary_sensor.front_door", "on")
    await hass.async_block_till_done()
    assert "until:binary_sensor.front_door" in coordinator._live
    hass.states.async_set("binary_sensor.front_door", "off")
    await hass.async_block_till_done()
    assert _bridge_calls(web, "/api/dismiss")[-1][2] == {
        "tag": "until:binary_sensor.front_door"
    }


async def test_live_notifications_outlast_a_restart(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    entry = await _live_door(hass, client, web)
    await hass.async_block_till_done()
    # Home Assistant stops (saving them); the door closes while it's down
    await hass.config_entries.async_unload(entry.entry_id)
    hass.states.async_set("binary_sensor.front_door", "off")
    with patch(
        "custom_components.googletv.async_get_client", AsyncMock(return_value=client)
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    coordinator = entry.runtime_data
    assert coordinator._live == {}
    await coordinator._async_check_live()
    assert _bridge_calls(web, "/api/dismiss")[-1][2] == {
        "tag": "until:binary_sensor.front_door"
    }


async def test_rules_by_name(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    await _paired(hass, client, web)
    await hass.services.async_call(
        DOMAIN,
        "set_notification_rules",
        {
            "entity_id": "media_player.lott_s_tv",
            "blocked_apps": ["Netflix", "com.example.other"],
            "blocked_inputs": ["xbox"],
            "when_blocked": "drop",
        },
        blocking=True,
        return_response=True,
    )
    call = _bridge_calls(web, "/api/rules")[-1]
    assert call[2] == {
        "blocked_apps": ["com.netflix.ninja", "com.example.other"],
        "blocked_inputs": ["com.tcl.tvinput/.TvPassThroughService/HW15"],
        "when_blocked": "drop",
    }


async def test_not_paired_says_so(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from homeassistant.exceptions import HomeAssistantError

    await _set_up(hass, client)
    with pytest.raises(HomeAssistantError, match="isn't installed and paired"):
        await hass.services.async_call(
            DOMAIN,
            "notify",
            {"entity_id": "media_player.lott_s_tv", "message": "Hi"},
            blocking=True,
        )


async def test_install_tv_bridge(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from custom_components.googletv.bridge import BRIDGE_DEV_APK_URL
    from custom_components.googletv.const import CONF_BRIDGE_TOKEN

    entry = await _set_up(hass, client)
    _bridge_web(web)
    apk = b"PK\x03\x04 an apk" * 50000
    web.get(BRIDGE_DEV_APK_URL, content=apk)
    web.get(f"{BRIDGE_DEV_APK_URL}.sha256", text=hashlib.sha256(apk).hexdigest() + "\n")
    client.async_read_file.return_value = "p1 123456\n"
    client.async_get_apps.return_value = [*APPS, BRIDGE_APP]
    with patch("custom_components.googletv.coordinator.BRIDGE_PAIRING_RETRY_S", 0):
        await hass.services.async_call(
            DOMAIN,
            "install_tv_bridge",
            {"entity_id": "media_player.lott_s_tv", "development": True},
            blocking=True,
        )
    # The whole APK, 750 KB, not the first chunk of it
    client.async_install_apk.assert_awaited_once_with(b"PK\x03\x04 an apk" * 50000)
    commands = [c.args[0] for c in client.async_shell.await_args_list]
    assert "appops set com.raineworks.tvbridge SYSTEM_ALERT_WINDOW allow" in commands
    assert any("com.raineworks.tvbridge.START" in c for c in commands)
    assert entry.data[CONF_BRIDGE_TOKEN] == "T0KEN"


# Home Assistant's media, through the TV app


def _media_web(web: AiohttpClientMocker) -> None:
    for path in ("/api/play", "/api/dashboard", "/api/stop", "/api/unpair"):
        web.post(f"{BRIDGE}{path}", json={"ok": True})


async def test_media_from_the_media_browser_plays_full_screen(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from homeassistant.components.media_source import PlayMedia

    hass.config.internal_url = "http://192.168.1.2:8123"
    await _paired(hass, client, web)
    _media_web(web)
    with patch(
        "homeassistant.components.media_source.async_resolve_media",
        AsyncMock(return_value=PlayMedia("/media/local/holiday.mp4", "video/mp4")),
    ):
        await hass.services.async_call(
            "media_player",
            "play_media",
            {
                "entity_id": "media_player.lott_s_tv",
                "media_content_type": "video",
                "media_content_id": "media-source://media_source/local/holiday.mp4",
                "extra": {"title": "Holiday"},
            },
            blocking=True,
        )
    call = _bridge_calls(web, "/api/play")[-1]
    assert call[2]["url"].startswith("http://192.168.1.2:8123/media/local/holiday.mp4")
    assert (call[2]["kind"], call[2]["mime"], call[2]["announce"]) == (
        "video",
        "video/mp4",
        False,
    )
    assert call[2]["title"] == "Holiday"


async def test_text_to_speech_is_announced_over_whats_on(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from homeassistant.components.media_source import PlayMedia

    hass.config.internal_url = "http://192.168.1.2:8123"
    await _paired(hass, client, web)
    _media_web(web)
    with patch(
        "homeassistant.components.media_source.async_resolve_media",
        AsyncMock(return_value=PlayMedia("/api/tts_proxy/abc.mp3", "audio/mpeg")),
    ):
        await hass.services.async_call(
            "media_player",
            "play_media",
            {
                "entity_id": "media_player.lott_s_tv",
                "media_content_type": "music",
                "media_content_id": "media-source://tts/tts.cloud?message=Dinner%27s+ready",
            },
            blocking=True,
        )
    call = _bridge_calls(web, "/api/play")[-1]
    assert call[2]["announce"] is True
    assert call[2]["kind"] == "audio"
    assert call[2]["message"] == "Dinner's ready"


async def test_a_link_still_opens_its_app(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    await _paired(hass, client, web)
    _media_web(web)
    await hass.services.async_call(
        "media_player",
        "play_media",
        {
            "entity_id": "media_player.lott_s_tv",
            "media_content_type": "url",
            "media_content_id": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        },
        blocking=True,
    )
    client.async_open_url.assert_awaited_once_with(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    )
    assert not _bridge_calls(web, "/api/play")


async def test_browsing_shows_what_the_tv_plays(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from homeassistant.components.media_player import BrowseMedia

    await _paired(hass, client, web)
    root = BrowseMedia(
        media_class="directory",
        media_content_id="media-source://",
        media_content_type="",
        title="Media",
        can_play=False,
        can_expand=True,
    )
    with patch(
        "homeassistant.components.media_source.async_browse_media",
        AsyncMock(return_value=root),
    ) as browse:
        player = hass.data["media_player"].get_entity("media_player.lott_s_tv")
        assert await player.async_browse_media() is root
    keep = browse.call_args.kwargs["content_filter"]

    def item(media_type: str) -> BrowseMedia:
        return BrowseMedia(
            media_class="music",
            media_content_id="x",
            media_content_type=media_type,
            title="x",
            can_play=True,
            can_expand=False,
        )

    assert keep(item("audio/mpeg"))
    assert not keep(item("application/pdf"))


async def test_stop_closes_home_assistants_media(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    entry = await _paired(hass, client, web)
    _media_web(web)
    coordinator = entry.runtime_data
    coordinator.async_set_updated_data(
        replace(
            coordinator.data,
            state=replace(coordinator.data.state, app="com.raineworks.tvbridge"),
        )
    )
    await hass.services.async_call(
        "media_player",
        "media_stop",
        {"entity_id": "media_player.lott_s_tv"},
        blocking=True,
    )
    assert _bridge_calls(web, "/api/stop")


async def test_a_dashboard_signs_in_as_the_tvs_own_user(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from custom_components.googletv.const import (
        CONF_DASHBOARD_TOKEN,
        CONF_DASHBOARD_USER,
    )

    hass.config.internal_url = "http://192.168.1.2:8123"
    await hass.auth.async_create_user("Lott")
    entry = await _paired(hass, client, web)
    _media_web(web)
    for _ in range(2):
        await hass.services.async_call(
            DOMAIN,
            "show_dashboard",
            {
                "entity_id": "media_player.lott_s_tv",
                "dashboard": "dashboard-tv",
                "view": "cameras",
            },
            blocking=True,
        )
    call = _bridge_calls(web, "/api/dashboard")[-1]
    assert call[2]["url"] == "http://192.168.1.2:8123/dashboard-tv/cameras"
    user = await hass.auth.async_get_user(entry.data[CONF_DASHBOARD_USER])
    assert user.name == "Lott's TV (TV)"
    assert not user.is_admin
    # Read-only unless the TV's options let dashboards control devices
    assert [g.id for g in user.groups] == ["system-read-only"]
    assert not user.is_owner
    assert user.local_only
    # One user and one token, however often it's shown
    assert len(user.refresh_tokens) == 1
    refresh = hass.auth.async_get_refresh_token(entry.data[CONF_DASHBOARD_TOKEN])
    assert refresh.token_type == "long_lived_access_token"
    assert hass.auth.async_validate_access_token(call[2]["token"]).user.id == user.id
    # Allowed to control: the same user, in the users' group
    with patch(
        "custom_components.googletv.async_get_client", AsyncMock(return_value=client)
    ):
        hass.config_entries.async_update_entry(
            entry, options={"online_lookups": True, "dashboard_controls": True}
        )
        await hass.async_block_till_done()
    await hass.services.async_call(
        DOMAIN,
        "show_dashboard",
        {"entity_id": "media_player.lott_s_tv"},
        blocking=True,
    )
    user = await hass.auth.async_get_user(entry.data[CONF_DASHBOARD_USER])
    assert [g.id for g in user.groups] == ["system-users"]
    assert len(user.refresh_tokens) == 1
    # Removing the TV removes its user, and the app forgets Home Assistant
    web.post(f"{BRIDGE}/api/dismiss", json={"ok": True})
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.auth.async_get_user(user.id) is None
    assert _bridge_calls(web, "/api/unpair")


# The TV app's events


async def test_the_event_stream_is_read_line_by_line(
    hass: HomeAssistant, web: AiohttpClientMocker
) -> None:
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from custom_components.googletv.bridge import BridgeClient

    web.get(
        f"{BRIDGE}/api/events",
        text=(
            '{"type": "hello", "instance": "run-1"}\n'
            "not json\n"
            '{"type": "ping"}\n'
            '{"type": "notification_action", "tag": "door", "action": "UNLOCK"}\n'
        ),
    )
    bridge = BridgeClient(async_get_clientsession(hass), "10.0.0.5", "T0KEN")
    events = [event async for event in bridge.async_events()]
    assert [e["type"] for e in events] == ["hello", "ping", "notification_action"]
    assert web.mock_calls[-1][3]["Authorization"] == "Bearer T0KEN"


async def test_a_button_pressed_on_the_tv(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from homeassistant.helpers import device_registry as dr

    entry = await _live_door(hass, client, web)
    coordinator = entry.runtime_data
    fired = []
    hass.bus.async_listen("googletv_event", fired.append)
    coordinator._async_handle_event({"type": "ping"})
    coordinator._async_handle_event(
        {
            "type": "notification_action",
            "tag": "until:binary_sensor.front_door",
            "action": "UNLOCK",
            "time": 1,
        }
    )
    await hass.async_block_till_done()
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, "X1")})
    assert [e.data for e in fired] == [
        {
            "type": "notification_action",
            "tag": "until:binary_sensor.front_door",
            "action": "UNLOCK",
            "device_id": device.id,
        }
    ]
    # The event entity has it
    state = hass.states.get("event.lott_s_tv_notification_events")
    assert state.attributes["event_type"] == "action"
    assert state.attributes["action"] == "UNLOCK"
    assert state.attributes["tag"] == "until:binary_sensor.front_door"
    # Down on the TV: the live notification isn't shown again, nor dismissed
    assert coordinator._live == {}
    hass.states.async_set("binary_sensor.front_door", "off")
    await hass.async_block_till_done()
    assert not _bridge_calls(web, "/api/dismiss")


async def test_the_player_refreshes_at_once_and_a_new_run_is_checked(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    entry = await _paired(hass, client, web)
    coordinator = entry.runtime_data
    with patch.object(coordinator, "async_request_refresh", AsyncMock()) as refresh:
        coordinator._async_handle_event({"type": "player", "state": "playing"})
        await hass.async_block_till_done()
    refresh.assert_awaited()
    coordinator._bridge_instance = "run-1"
    coordinator._live_checked_at = dt_util.utcnow()
    coordinator._async_handle_event({"type": "hello", "instance": "run-2"})
    assert coordinator._live_checked_at is None


async def test_buttons_on_a_notification(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    import voluptuous as vol

    await _paired(hass, client, web)
    reply = await hass.services.async_call(
        DOMAIN,
        "notify",
        {
            "entity_id": "media_player.lott_s_tv",
            "title": "Doorbell",
            "actions": [
                {"action": "UNLOCK", "title": "Unlock"},
                {"action": "IGNORE", "title": "Ignore"},
            ],
        },
        blocking=True,
        return_response=True,
    )
    call = _bridge_calls(web, "/api/notify")[-1]
    assert call[2]["actions"][0] == {"action": "UNLOCK", "title": "Unlock"}
    # Tagged, so its events name it
    assert call[2]["tag"] == reply["media_player.lott_s_tv"]["tag"]
    assert call[2]["tag"].startswith("actions-")
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "notify",
            {
                "entity_id": "media_player.lott_s_tv",
                "title": "Too many",
                "actions": [{"action": f"A{i}", "title": "x"} for i in range(4)],
            },
            blocking=True,
        )


async def test_the_app_installs_when_asked_at_setup(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from custom_components.googletv.bridge import BRIDGE_APK_URL

    _bridge_web(web)
    web.get(BRIDGE_APK_URL, content=b"PK\x03\x04 an apk")
    web.get(
        f"{BRIDGE_APK_URL}.sha256",
        text=hashlib.sha256(b"PK\x03\x04 an apk").hexdigest(),
    )
    client.async_read_file.return_value = "p1 123456\n"
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="X1",
        title="Lott's TV",
        data={CONF_HOST: "10.0.0.5", CONF_PORT: 5555, "install_tv_app": True},
    )
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.googletv.async_get_client",
            AsyncMock(return_value=client),
        ),
        patch("custom_components.googletv.coordinator.BRIDGE_PAIRING_ATTEMPTS", 1),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    client.async_install_apk.assert_awaited_once_with(b"PK\x03\x04 an apk")
    # Once: not again at the next start
    assert "install_tv_app" not in entry.data


@pytest.mark.parametrize(
    ("published", "error"),
    [(None, "no SHA-256"), ("0" * 64, "doesn't match")],
)
async def test_an_apk_that_isnt_as_published_isnt_installed(
    hass: HomeAssistant,
    client: AsyncMock,
    web: AiohttpClientMocker,
    published: str | None,
    error: str,
) -> None:
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.googletv.bridge import BRIDGE_APK_URL

    await _set_up(hass, client)
    web.get(BRIDGE_APK_URL, content=b"PK\x03\x04 an apk")
    if published:
        web.get(f"{BRIDGE_APK_URL}.sha256", text=published)
    else:
        web.get(f"{BRIDGE_APK_URL}.sha256", status=404)
    with pytest.raises(HomeAssistantError, match=error):
        await hass.services.async_call(
            DOMAIN,
            "install_tv_bridge",
            {"entity_id": "media_player.lott_s_tv"},
            blocking=True,
        )
    client.async_install_apk.assert_not_awaited()


async def test_a_forgotten_pairing_pairs_again(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from homeassistant.exceptions import HomeAssistantError

    entry = await _paired(hass, client, web)
    web.clear_requests()
    web.post(f"{BRIDGE}/api/notify", status=401, json={"error": "Not paired"})
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            "notify",
            {"entity_id": "media_player.lott_s_tv", "message": "Hi"},
            blocking=True,
        )
    assert entry.runtime_data.bridge.token is None


# Through the TV app alone (no ADB)

APP_STATE = {
    "screen_on": True,
    "foreground_app": "com.netflix.ninja",
    "uptime_ms": 1294401030,
    "volume": {"level": 6, "max": 15, "muted": False},
    "sessions": [
        {
            "package": "com.netflix.ninja",
            "state": 3,
            "position_ms": 5000,
            "updated_ms": 1294400000,
            "speed": 1.0,
            "title": "Rick and Morty",
            "subtitle": "Adult Swim",
            "description": None,
        }
    ],
    "overlay_permission": True,
    "usage_access": True,
    "notification_access": True,
    "network_debugging": False,
    "instance": "run-1",
    "popups": [],
}


async def _app_only(hass: HomeAssistant, web: AiohttpClientMocker) -> MockConfigEntry:
    """A TV added through its app, ADB never turned on."""
    _bridge_web(web)
    web.get(f"{BRIDGE}/api/state", json=APP_STATE)
    web.get(
        f"{BRIDGE}/api/inputs",
        json={"inputs": [{"id": "com.tcl.tvinput/.Hdmi/HW15", "name": "Xbox"}]},
    )
    web.get(
        f"{BRIDGE}/api/apps",
        json={
            "apps": [
                {
                    "package": "com.netflix.ninja",
                    "activity": "com.netflix.ninja.MainActivity",
                    "name": "Netflix",
                }
            ]
        },
    )
    web.get(
        f"{BRIDGE}/api/diagnostics",
        json={"connection": "wifi", "wifi_signal": -52, "storage_used": 40},
    )
    for path in ("/api/key", "/api/volume", "/api/launch", "/api/input"):
        web.post(f"{BRIDGE}{path}", json={"ok": True})
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="a1b2c3d4",
        title="Lott's TV",
        data={
            CONF_HOST: "10.0.0.5",
            "connection": "app",
            "bridge_token": "T0KEN",
            "props": {"manufacturer": "TCL", "model": "Smart TV Pro"},
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_a_tv_through_its_app_alone(
    hass: HomeAssistant, web: AiohttpClientMocker
) -> None:
    from homeassistant.components.media_player import MediaPlayerEntityFeature
    from homeassistant.exceptions import HomeAssistantError

    await _app_only(hass, web)
    player = hass.states.get("media_player.lott_s_tv")
    assert player.state == "playing"
    assert player.attributes["media_title"] == "Rick and Morty"
    assert player.attributes["volume_level"] == pytest.approx(0.4)
    assert player.attributes["source_list"][-1] == "Xbox"
    # An app can't turn the TV off, nor wake it from standby
    features = player.attributes["supported_features"]
    assert not features & MediaPlayerEntityFeature.TURN_OFF
    assert hass.states.get("sensor.lott_s_tv_activity").state == "playing"
    assert hass.states.get("sensor.lott_s_tv_wi_fi_signal").state == "-52"
    # Only the keys an app can press
    assert hass.states.get("button.lott_s_tv_remote_play_pause") is not None
    assert hass.states.get("button.lott_s_tv_remote_home") is None

    await hass.services.async_call(
        "media_player",
        "media_pause",
        {"entity_id": "media_player.lott_s_tv"},
        blocking=True,
    )
    assert _bridge_calls(web, "/api/key")[-1][2] == {"key": "MEDIA_PAUSE"}
    await hass.services.async_call(
        "media_player",
        "volume_set",
        {"entity_id": "media_player.lott_s_tv", "volume_level": 0.5},
        blocking=True,
    )
    assert _bridge_calls(web, "/api/volume")[-1][2] == {"level": 0.5}
    await hass.services.async_call(
        "media_player",
        "select_source",
        {"entity_id": "media_player.lott_s_tv", "source": "Xbox"},
        blocking=True,
    )
    assert _bridge_calls(web, "/api/input")[-1][2] == {
        "id": "com.tcl.tvinput/.Hdmi/HW15"
    }
    # What only ADB does says so
    with pytest.raises(HomeAssistantError, match="needs ADB"):
        await hass.services.async_call(
            "remote",
            "send_command",
            {"entity_id": "remote.lott_s_tv", "command": "DPAD_UP"},
            blocking=True,
        )
    # Home Assistant told the app who it is, and that it's without ADB
    report = _bridge_calls(web, "/api/client")[-1][2]
    assert report["adb"] is False


async def test_the_tv_apps_version(
    hass: HomeAssistant, web: AiohttpClientMocker
) -> None:
    entry = await _app_only(hass, web)
    await hass.async_block_till_done()
    state = hass.states.get("sensor.lott_s_tv_tv_app")
    assert state.state == VERSION
    assert state.attributes["build"] == "abc1234"
    # A newer one says hello
    entry.runtime_data._async_handle_event(
        {
            "type": "hello",
            "instance": "run-2",
            "app_version": "99.0.0",
            "build": "def5678",
        }
    )
    await hass.async_block_till_done()
    state = hass.states.get("sensor.lott_s_tv_tv_app")
    assert (state.state, state.attributes["build"]) == ("99.0.0", "def5678")


async def test_a_tv_over_adb_without_the_app_offers_to_install_it(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from homeassistant.helpers import issue_registry as ir

    from custom_components.googletv.bridge import BRIDGE_APK_URL

    entry = await _set_up(hass, client)
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"install_tv_app_{entry.entry_id}"
    )
    assert issue is not None and issue.is_fixable
    # Fixed: installed over ADB
    _bridge_web(web)
    web.get(BRIDGE_APK_URL, content=b"PK\x03\x04 an apk")
    web.get(
        f"{BRIDGE_APK_URL}.sha256",
        text=hashlib.sha256(b"PK\x03\x04 an apk").hexdigest(),
    )
    client.async_read_file.return_value = "p1 123456\n"
    client.async_get_apps.return_value = [*APPS, BRIDGE_APP]
    from custom_components.googletv.repairs import async_create_fix_flow

    with patch("custom_components.googletv.coordinator.BRIDGE_PAIRING_ATTEMPTS", 1):
        flow = await async_create_fix_flow(hass, issue.issue_id, issue.data)
        flow.hass = hass
        result = await flow.async_step_init()
        assert result["step_id"] == "confirm"
        result = await flow.async_step_confirm({})
    assert result["type"] == "create_entry"
    client.async_install_apk.assert_awaited_once()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, f"install_tv_app_{entry.entry_id}")
        is None
    )


async def test_the_tv_app_from_google_play_isnt_installed_over(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from homeassistant.exceptions import HomeAssistantError

    await _paired(hass, client, web)
    client.async_shell.return_value = (
        "package:com.raineworks.tvbridge  installer=com.android.vending\n"
    )
    with pytest.raises(HomeAssistantError, match="from Google Play"):
        await hass.services.async_call(
            DOMAIN,
            "install_tv_bridge",
            {"entity_id": "media_player.lott_s_tv"},
            blocking=True,
        )
    client.async_install_apk.assert_not_awaited()


# Apps left out of Home Assistant, and the TV app kept up to date


async def test_an_app_left_out_on_the_tv(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    """Its switch in the TV app: out of the app list, its button disabled."""
    from homeassistant.helpers import entity_registry as er

    await _paired(hass, client, web)
    tv = hass.states.get("media_player.lott_s_tv")
    assert "YouTube TV" not in tv.attributes["source_list"]
    assert "Netflix" in tv.attributes["source_list"]
    assert OTHER_APP not in [a["package"] for a in tv.attributes["apps"]]
    button = er.async_get(hass).async_get("button.lott_s_tv_app_youtube_tv")
    assert button.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_a_switch_flipped_on_the_tv(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    """The TV app says at once: the buttons and the app list follow."""
    from homeassistant.helpers import entity_registry as er

    entry = await _paired(hass, client, web)
    registry = er.async_get(hass)
    entry.runtime_data._async_handle_event(
        {"type": "rules", **RULES, "hidden_apps": ["com.netflix.ninja"]}
    )
    await hass.async_block_till_done()
    assert registry.async_get("button.lott_s_tv_app_youtube_tv").disabled_by is None
    assert registry.async_get("button.lott_s_tv_app_netflix").disabled
    sources = hass.states.get("media_player.lott_s_tv").attributes["source_list"]
    assert "YouTube TV" in sources and "Netflix" not in sources


async def test_an_app_button_disabled_here_hides_it_on_the_tv(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from homeassistant.helpers import entity_registry as er

    await _paired(hass, client, web)
    er.async_get(hass).async_update_entity(
        "button.lott_s_tv_app_netflix", disabled_by=er.RegistryEntryDisabler.USER
    )
    await hass.async_block_till_done()
    assert _bridge_calls(web, "/api/rules")[-1][2] == {
        "hidden_apps": sorted(["com.netflix.ninja", OTHER_APP])
    }


async def test_the_apps_in_the_options(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    """The TV app's switches, on the integration's Configure: kept on the TV."""
    entry = await _paired(hass, client, web)
    data = entry.runtime_data.data
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "menu"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "apps"}
    )
    assert result["step_id"] == "apps"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "apps_shown": ["com.netflix.ninja"],
            "popups_apps": [a.package for a in data.apps if a.package != OTHER_APP],
            "popups_inputs": [],
        },
    )
    assert result["type"] == "create_entry"
    assert entry.options == {}
    sent = _bridge_calls(web, "/api/rules")[-1][2]
    assert sent["hidden_apps"] == sorted(
        a.package for a in data.apps if a.package != "com.netflix.ninja"
    )
    assert sent["blocked_apps"] == [OTHER_APP]
    assert sent["blocked_inputs"] == sorted(i.id for i in data.state.inputs)


def _old_app(web: AiohttpClientMocker, installer: str | None = None) -> None:
    """The TV app at 2.3.0 (registered first, so it's what's answered)."""
    web.get(
        f"{BRIDGE}/api/info",
        json={
            "api": 1,
            "app_version": "2.3.0",
            "build": "abc1234",
            "paired": True,
            "features": ["events", "confirm_pairing", "device"],
            "installer": installer,
        },
    )


async def test_an_old_tv_app_is_updated_over_adb(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    from custom_components.googletv.bridge import APK_NAME, BRIDGE_RELEASES_URL

    url = f"{BRIDGE_RELEASES_URL}/v{VERSION}/{APK_NAME}"
    apk = b"PK\x03\x04 the new app" * 1000
    web.get(url, content=apk)
    web.get(f"{url}.sha256", text=hashlib.sha256(apk).hexdigest())
    _old_app(web)
    client.async_shell.return_value = "package:com.raineworks.tvbridge\n"
    await _paired(hass, client, web)
    await hass.async_block_till_done()
    # The integration's own version, once
    client.async_install_apk.assert_awaited_once_with(apk)


async def test_an_old_tv_app_from_google_play_is_plays_to_update(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    _old_app(web, installer="com.android.vending")
    await _paired(hass, client, web)
    await hass.async_block_till_done()
    client.async_install_apk.assert_not_awaited()


async def test_an_old_tv_app_without_adb_is_a_repair(
    hass: HomeAssistant, web: AiohttpClientMocker
) -> None:
    from homeassistant.helpers import issue_registry as ir

    _old_app(web)
    entry = await _app_only(hass, web)
    await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"update_tv_app_{entry.entry_id}"
    )
    assert issue is not None
    assert issue.translation_placeholders["version"] == "2.3.0"


async def test_an_app_uninstalled_on_the_tv_goes_at_once(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    """The TV app says so: the list is read again, the button removed."""
    from homeassistant.helpers import entity_registry as er

    entry = await _paired(hass, client, web)
    registry = er.async_get(hass)
    assert registry.async_get("button.lott_s_tv_app_netflix") is not None
    client.async_get_apps.return_value = [
        a for a in [*APPS, BRIDGE_APP] if a.package != "com.netflix.ninja"
    ]
    entry.runtime_data._async_handle_event(
        {"type": "apps", "change": "uninstalled", "package": "com.netflix.ninja"}
    )
    await hass.async_block_till_done()
    assert registry.async_get("button.lott_s_tv_app_netflix") is None
    sources = hass.states.get("media_player.lott_s_tv").attributes["source_list"]
    assert "Netflix" not in sources
    # Installed again: back
    client.async_get_apps.return_value = [*APPS, BRIDGE_APP]
    entry.runtime_data._async_handle_event(
        {"type": "apps", "change": "installed", "package": "com.netflix.ninja"}
    )
    # Refreshes asked for this close together are spaced out (by 10 s)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await hass.async_block_till_done()
    assert hass.states.get("button.lott_s_tv_app_netflix") is not None


async def test_an_input_on_screen_has_its_artwork(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker, hass_client
) -> None:
    """On the Xbox: its name as the title, and its icon on Xbox green."""
    await _set_up(hass, client)
    tv = hass.states.get("media_player.lott_s_tv")
    assert tv.attributes["media_title"] == "Xbox"
    picture = tv.attributes["entity_picture"]
    assert picture.startswith("/api/media_player_proxy/media_player.lott_s_tv")
    response = await (await hass_client()).get(picture)
    assert response.status == 200
    assert response.headers["Content-Type"].startswith("image/svg+xml")
    svg = await response.text()
    assert "#107C10" in svg and svg.startswith("<svg")


def _signed_by(url: str) -> dict:
    """The claims of a URL's authSig (not checked: Home Assistant does that)."""
    import base64

    from yarl import URL

    claims = URL(url).query["authSig"].split(".")[1]
    return json.loads(base64.urlsafe_b64decode(claims + "=" * (-len(claims) % 4)))


async def test_home_assistant_urls_are_signed_for_the_tv(
    hass: HomeAssistant, client: AsyncMock, web: AiohttpClientMocker
) -> None:
    """Its own paths signed (as the content user); others left as they are."""
    from homeassistant.components.http.auth import STORAGE_KEY

    hass.config.internal_url = "http://192.168.1.2:8123"
    entry = await _paired(hass, client, web)

    async def sent(**fields: str) -> dict:
        await hass.services.async_call(
            DOMAIN,
            "notify",
            {"entity_id": "media_player.lott_s_tv", "title": "Doorbell", **fields},
            blocking=True,
            return_response=True,
        )
        return _bridge_calls(web, "/api/notify")[-1][2]

    call = await sent(
        image="/media/local/doorbell_snapshot.jpg",
        video="/api/unifiprotect/video/e1/ev1",
        icon="https://example.com/bell.png",
    )
    image = _signed_by(call["image_url"])
    assert image["path"] == "/media/local/doorbell_snapshot.jpg"
    assert image["iss"] == hass.data[STORAGE_KEY]
    assert image["exp"] - image["iat"] == 15 * 60
    assert _signed_by(call["video_url"])["path"] == "/api/unifiprotect/video/e1/ev1"
    assert call["icon"] == "https://example.com/bell.png"
    # The camera proxy carries its own token
    proxy = "http://192.168.1.2:8123/api/camera_proxy/camera.door?token=abc"
    assert (await sent(image=proxy))["image_url"] == proxy
    # A live one is kept as given, and signed afresh each time it's sent
    await sent(image="/media/local/doorbell_snapshot.jpg", duration="0", tag="door")
    kept = entry.runtime_data._live["door"]["payload"]["image_url"]
    assert kept == "http://192.168.1.2:8123/media/local/doorbell_snapshot.jpg"

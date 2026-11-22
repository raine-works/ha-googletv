"""The TV as a media player: power, volume, playback, apps, inputs, what's on."""

from __future__ import annotations

from collections.abc import Coroutine
from datetime import datetime
import logging
from typing import Any
from urllib.parse import parse_qs, urlsplit

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    ATTR_MEDIA_ANNOUNCE,
    ATTR_MEDIA_EXTRA,
    DOMAIN as MEDIA_PLAYER_DOMAIN,
    BrowseMedia,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    async_process_play_media_url,
)
from homeassistant.const import ATTR_ENTITY_ID, ENTITY_MATCH_ALL, STATE_UNAVAILABLE
from homeassistant.core import (
    HomeAssistant,
    ServiceResponse,
    SupportsResponse,
    async_get_hass,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import (
    config_validation as cv,
    entity_platform,
    entity_registry as er,
)
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .artwork import input_artwork
from .bridge import BRIDGE_APK_URL, BRIDGE_DEV_APK_URL, BRIDGE_PACKAGE
from .const import DOMAIN
from .coordinator import GoogleTvConfigEntry, GoogleTvCoordinator, translate_errors
from .entity import GoogleTvEntity
from .parsers import MUSIC_APPS, PLAYBACK_PAUSED, App, TvInput, app_name

_LOGGER = logging.getLogger(__name__)

# play_media's types beyond Home Assistant's own: an app by package, an input by id
MEDIA_TYPE_APP = "app"
MEDIA_TYPE_INPUT = "input"

# Media the TV app plays, by Home Assistant's media types
AUDIO_TYPES = {MediaType.MUSIC, MediaType.PODCAST, MediaType.TRACK, "audio"}
VIDEO_TYPES = {
    MediaType.VIDEO,
    MediaType.MOVIE,
    MediaType.EPISODE,
    MediaType.TVSHOW,
    MediaType.CHANNEL,
    "video",
    "application/x-mpegurl",
    "application/vnd.apple.mpegurl",
}
TTS_SOURCE = "media-source://tts/"


def _kind(media_type: str) -> str | None:
    """Audio, video or an image, for the TV app's player; None if it's none."""
    media_type = media_type.lower()
    if media_type.startswith("audio/") or media_type in AUDIO_TYPES:
        return "audio"
    if media_type.startswith("video/") or media_type in VIDEO_TYPES:
        return "video"
    if media_type.startswith("image/") or media_type == MediaType.IMAGE:
        return "image"
    return None


def _only_our_tvs(data: dict[str, Any]) -> dict[str, Any]:
    """Refuse an entity named in an action's target that isn't one of our TVs.

    Home Assistant runs an entity service only on the integration's own
    entities and skips any other it's given without a word, so googletv.notify
    sent to another integration's media player (Music Assistant's for the same
    TV, say) did nothing and still succeeded. Targets by area, device or label
    resolve to our entities alone, and stay as they are.
    """
    entity_ids = data.get(ATTR_ENTITY_ID)
    if not entity_ids or entity_ids == ENTITY_MATCH_ALL:
        return data
    registry = er.async_get(async_get_hass())
    ours = sorted(
        entry.entity_id
        for entry in registry.entities.values()
        if entry.platform == DOMAIN and entry.domain == MEDIA_PLAYER_DOMAIN
    )
    others = [entity_id for entity_id in entity_ids if entity_id not in ours]
    if others:
        raise vol.Invalid(
            f"{', '.join(others)} isn't a Raineworks TV: send it to one of"
            f" its TVs ({', '.join(ours) or 'none set up'})"
        )
    return data


def _tv_action(schema: dict[Any, Any]) -> vol.All:
    """An action's schema on our TVs, refusing anything else named."""
    return vol.All(cv.make_entity_service_schema(schema), _only_our_tvs)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoogleTvConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the TV's media player, and the TV's actions on it."""
    async_add_entities([GoogleTvMediaPlayer(entry.runtime_data)])
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "notify",
        _tv_action(NOTIFY_SCHEMA),
        "async_tv_notify",
        supports_response=SupportsResponse.OPTIONAL,
    )
    platform.async_register_entity_service(
        "dismiss_notifications",
        _tv_action({vol.Optional("tag"): cv.string}),
        "async_dismiss_notifications",
    )
    platform.async_register_entity_service(
        "set_notification_rules",
        _tv_action(
            {
                vol.Optional("blocked_apps"): vol.All(cv.ensure_list, [cv.string]),
                vol.Optional("blocked_inputs"): vol.All(cv.ensure_list, [cv.string]),
                vol.Optional("when_blocked"): vol.In(["panel", "drop"]),
            }
        ),
        "async_set_notification_rules",
        supports_response=SupportsResponse.OPTIONAL,
    )
    platform.async_register_entity_service(
        "show_dashboard",
        _tv_action(
            {
                vol.Optional("dashboard", default="lovelace"): cv.string,
                vol.Optional("view"): cv.string,
            }
        ),
        "async_show_dashboard",
    )
    platform.async_register_entity_service(
        "install_tv_bridge",
        _tv_action(
            {
                vol.Optional("development", default=False): cv.boolean,
                vol.Optional("url"): vol.Url(),
            }
        ),
        "async_install_tv_bridge",
    )


POSITIONS = [
    "top_left",
    "top",
    "top_right",
    "center",
    "bottom_left",
    "bottom",
    "bottom_right",
]
NOTIFY_SCHEMA = {
    vol.Optional("message"): cv.string,
    vol.Optional("title"): cv.string,
    vol.Optional("icon"): cv.string,
    vol.Optional("image"): cv.string,
    vol.Optional("video"): cv.string,
    vol.Optional("camera_entity"): cv.entity_domain("camera"),
    vol.Optional("camera_view", default="live"): vol.In(["live", "hls", "snapshot"]),
    vol.Optional("mode"): vol.In(["popup", "panel", "both"]),
    vol.Optional("position"): vol.In(POSITIONS),
    # 0: until it's dismissed (a live notification)
    vol.Optional("duration"): vol.All(vol.Coerce(int), vol.Range(min=0, max=600)),
    vol.Optional("progress"): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
    vol.Optional("until_entity"): cv.entity_id,
    # Buttons: the card takes the remote's focus; a press fires googletv_event
    vol.Optional("actions"): vol.All(
        cv.ensure_list,
        [
            vol.Schema(
                {
                    vol.Required("action"): vol.Match(r"^[A-Za-z0-9_.:-]{1,64}$"),
                    vol.Required("title"): vol.All(
                        cv.string, vol.Length(min=1, max=40)
                    ),
                }
            )
        ],
        vol.Length(max=3),
    ),
    vol.Optional("until_state"): cv.string,
    vol.Optional("size"): vol.In(["compact", "small", "medium", "large"]),
    vol.Optional("color"): cv.string,
    vol.Optional("mute"): cv.boolean,
    vol.Optional("tag"): cv.string,
    vol.Optional("ignore_rules"): cv.boolean,
    vol.Optional("when_blocked"): vol.In(["panel", "drop"]),
}


# media_image_url for an input's artwork (not fetched: drawn)
INPUT_ARTWORK = "googletv-input:"


class GoogleTvMediaPlayer(GoogleTvEntity, MediaPlayerEntity):
    """A Google TV."""

    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.TV
    # Off, not unavailable, while the TV is off its network
    _available_offline = True
    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
        | MediaPlayerEntityFeature.SELECT_SOURCE
        | MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.BROWSE_MEDIA
        | MediaPlayerEntityFeature.MEDIA_ANNOUNCE
    )

    def __init__(self, coordinator: GoogleTvCoordinator) -> None:
        """Initialize the media player."""
        super().__init__(coordinator, "media_player")
        if coordinator.app_only:
            # An app can't turn the TV off, nor wake it from standby
            self._attr_supported_features &= ~(
                MediaPlayerEntityFeature.TURN_ON | MediaPlayerEntityFeature.TURN_OFF
            )
        self._position: float | None = None
        self._position_updated_at: datetime | None = None
        self._position_playing = False
        self._update_position()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Take the new poll."""
        self._update_position()
        super()._handle_coordinator_update()

    def _update_position(self) -> None:
        """Keep the position and when it was read, unless it moved unexpectedly.

        Home Assistant extrapolates a playing position from when it was dated,
        so it's only dated again when the reported one stops matching that (a
        seek, a pause, a new title): no backward jumps, and no new state every
        poll while it plays as expected.
        """
        state = self._state
        playing = state.now_playing if state.awake else None
        position = playing.position_at(state.uptime_ms) if playing else None
        now = dt_util.utcnow()
        is_playing = bool(playing and playing.playing)
        if position is None:
            self._position = self._position_updated_at = None
            return
        if self._position is not None and self._position_updated_at is not None:
            expected = self._position
            if self._position_playing:
                expected += (now - self._position_updated_at).total_seconds()
            if is_playing == self._position_playing and abs(position - expected) < 2:
                return
        self._position, self._position_updated_at = position, now
        self._position_playing = is_playing

    # What the TV shows

    @property
    def state(self) -> MediaPlayerState:
        """Off while its screen is off; playing or paused while an app plays."""
        state = self._state
        if not state.awake:
            return MediaPlayerState.OFF
        playing = state.now_playing
        if playing and playing.playing:
            return MediaPlayerState.PLAYING
        if state.screensaver:
            return MediaPlayerState.IDLE
        if playing and playing.state == PLAYBACK_PAUSED:
            return MediaPlayerState.PAUSED
        return MediaPlayerState.ON

    @property
    def app_id(self) -> str | None:
        """The app in front (its package)."""
        return self._state.app if self._state.awake else None

    @property
    def app_name(self) -> str | None:
        """The app in front, by name, or the input it shows."""
        if not self._state.awake:
            return None
        if self._state.input:
            return self._state.input.label
        return self._app_name(self._state.app)

    def _app_name(self, package: str | None) -> str | None:
        app = self._app(package)
        return app.name if app else app_name(package)

    def _app(self, package: str | None) -> App | None:
        return next(
            (a for a in self.coordinator.data.apps if a.package == package), None
        )

    @property
    def icon(self) -> str | None:
        """The input's icon while one is on screen (an Xbox's…)."""
        state = self._state
        return state.input.icon if state.awake and state.input else None

    @property
    def source_list(self) -> list[str]:
        """The launcher's apps (those not left out), then the HDMI inputs."""
        hidden = self.coordinator.data.hidden_apps
        return [
            a.name for a in self.coordinator.data.apps if a.package not in hidden
        ] + [
            i.label
            for i in self._state.inputs
            if i.id not in self.coordinator.data.hidden_inputs
        ]

    @property
    def source(self) -> str | None:
        """The input on screen, else the app in front."""
        return self.app_name

    @property
    def volume_level(self) -> float | None:
        """The media volume, 0 to 1."""
        return self._state.volume if self._state.awake else None

    @property
    def is_volume_muted(self) -> bool | None:
        """Whether the media volume is muted."""
        return self._state.muted if self._state.awake else None

    @property
    def media_title(self) -> str | None:
        """The title of what's playing, as its app reports it; else the input on."""
        if not self._state.awake:
            return None
        if self._state.input:
            return self._state.input.label
        playing = self._state.now_playing
        return playing.title if playing else None

    @property
    def media_artist(self) -> str | None:
        """The show, channel or artist; on an input, what its device calls itself."""
        if not self._state.awake:
            return None
        if (tv_input := self._state.input) is not None:
            return tv_input.device if tv_input.device != tv_input.label else None
        playing = self._state.now_playing
        return playing.subtitle if playing else None

    @property
    def media_content_type(self) -> MediaType | None:
        """Music for a music app, else video."""
        playing = self._state.now_playing if self._state.awake else None
        if not playing:
            return None
        return MediaType.MUSIC if playing.package in MUSIC_APPS else MediaType.VIDEO

    @property
    def media_image_url(self) -> str | None:
        """What's playing's cover or poster, else its app's icon.

        On an input, its artwork (``async_get_media_image`` draws it): this
        names it, so the picture changes with the input.
        """
        state = self._state
        if not state.awake:
            return None
        if state.input:
            return f"{INPUT_ARTWORK}{state.input.kind.key}/{state.input.icon}"
        if self.coordinator.data.artwork:
            return self.coordinator.data.artwork
        playing = state.now_playing
        app = self._app(playing.package if playing else state.app)
        return app.icon if app else None

    async def async_get_media_image(self) -> tuple[bytes | None, str | None]:
        """The input's artwork, drawn here; anything else, fetched."""
        url = self.media_image_url
        if url and url.startswith(INPUT_ARTWORK):
            kind, icon = url.removeprefix(INPUT_ARTWORK).split("/", 1)
            return input_artwork(kind, icon), "image/svg+xml"
        return await super().async_get_media_image()

    @property
    def media_position(self) -> int | None:
        """Seconds into what's playing, when it was last dated."""
        return int(self._position) if self._position is not None else None

    @property
    def media_position_updated_at(self) -> datetime | None:
        """When the position was dated."""
        return self._position_updated_at

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The apps and inputs, for dashboards that list them."""
        state = self._state
        return {
            "apps": [
                {"package": a.package, "name": a.name, "icon": a.icon}
                for a in self.coordinator.data.apps
                if a.package not in self.coordinator.data.hidden_apps
            ],
            "inputs": [
                {
                    "id": i.id,
                    "port": i.port,
                    "name": i.label,
                    "icon": i.icon,
                    "kind": i.kind.key,
                    "device": i.device,
                }
                for i in state.inputs
                if i.id not in self.coordinator.data.hidden_inputs
            ],
            "input": state.input.id if state.awake and state.input else None,
            "tv_bridge": "paired"
            if self.coordinator.data.bridge_paired
            else "installed"
            if self.coordinator.data.bridge_installed
            else "not_installed",
            "media_app": state.now_playing.package
            if state.awake and state.now_playing
            else None,
        }

    # Notifications (the TV app)

    def _home_assistant_url(self, path: str) -> str:
        """A Home Assistant path as a URL the TV can load."""
        if not path.startswith("/"):
            return path
        try:
            base = get_url(self.hass, allow_external=False, prefer_external=False)
        except NoURLAvailableError:
            base = get_url(self.hass)
        return base.rstrip("/") + path

    async def _camera_urls(self, entity_id: str, view: str) -> dict[str, Any]:
        """A camera for the TV: live (WebRTC, HLS behind it), HLS, or a snapshot.

        Its snapshot is an ``image_url`` (the poster while it starts): the
        caller's image wins over it. An unavailable camera gives nothing.
        """
        from homeassistant.components.camera import (
            StreamType,
            async_request_stream,
            get_camera_from_entity_id,
        )

        state = self.hass.states.get(entity_id)
        if state is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_camera",
                translation_placeholders={"entity_id": entity_id},
            )
        token = state.attributes.get("access_token")
        if state.state == STATE_UNAVAILABLE or not token:
            # Its snapshot would be a broken image: the rest of the card shows
            _LOGGER.warning(
                "camera_entity %s is unavailable: its picture isn't shown", entity_id
            )
            return {}
        urls: dict[str, Any] = {
            "image_url": self._home_assistant_url(
                f"/api/camera_proxy/{entity_id}?token={token}"
            )
        }
        if view == "snapshot":
            return urls
        try:
            camera = get_camera_from_entity_id(self.hass, entity_id)
        except HomeAssistantError:
            return urls
        types = camera.camera_capabilities.frontend_stream_types
        if view == "live" and StreamType.WEB_RTC in types:
            urls["webrtc"] = {
                "entity_id": entity_id,
                "ws_url": self._websocket_url(),
                "ice_servers": camera.async_get_webrtc_client_configuration()
                .configuration.to_dict()
                .get("iceServers", []),
            }
        if StreamType.HLS in types:
            # The stream (or, with WebRTC, what it falls back to)
            try:
                stream = await async_request_stream(self.hass, entity_id, fmt="hls")
            except HomeAssistantError:
                # No stream (a still-only camera): its snapshot
                return urls
            urls["video_url"] = self._home_assistant_url(stream)
        return urls

    def _websocket_url(self) -> str:
        """Home Assistant's websocket, as the TV reaches it."""
        base = self._home_assistant_url("/api/websocket")
        return "ws" + base.removeprefix("http")

    async def async_tv_notify(self, **kwargs: Any) -> ServiceResponse:
        """Show a notification on the TV (googletv.notify)."""
        payload: dict[str, Any] = {
            key: kwargs[key]
            for key in (
                "message",
                "title",
                "mode",
                "position",
                "duration",
                "size",
                "color",
                "mute",
                "tag",
                "ignore_rules",
                "when_blocked",
                "actions",
            )
            if key in kwargs
        }
        if icon := kwargs.get("icon"):
            # mdi:<name>, or an image (a URL or a Home Assistant path)
            payload["icon"] = (
                icon if icon.startswith("mdi:") else self._home_assistant_url(icon)
            )
        if image := kwargs.get("image"):
            payload["image_url"] = self._home_assistant_url(image)
        if video := kwargs.get("video"):
            payload["video_url"] = self._home_assistant_url(video)
        if "progress" in kwargs:
            payload["progress"] = round(kwargs["progress"])
        if camera := kwargs.get("camera_entity"):
            urls = await self._camera_urls(camera, kwargs["camera_view"])
            if "image_url" in payload:
                # The caller's image (a doorbell's snapshot) over the camera's
                urls.pop("image_url", None)
            payload.update(urls)
        if not any(
            k in payload for k in ("message", "title", "image_url", "video_url")
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="nothing_to_show"
            )
        until = None
        if entity_id := kwargs.get("until_entity"):
            until = {"entity_id": entity_id, "state": kwargs.get("until_state")}
        return await self.coordinator.async_notify(payload, until)

    async def async_dismiss_notifications(self, tag: str | None = None) -> None:
        """Take notifications down (googletv.dismiss_notifications)."""
        await self.coordinator.async_dismiss(tag)

    async def async_set_notification_rules(self, **kwargs: Any) -> ServiceResponse:
        """Pop-ups' rules: apps and inputs (by name or id) they don't show over."""
        changes: dict[str, Any] = {}
        if "blocked_apps" in kwargs:
            by_name = {a.name.casefold(): a.package for a in self.coordinator.data.apps}
            changes["blocked_apps"] = [
                by_name.get(app.casefold(), app) for app in kwargs["blocked_apps"]
            ]
        if "blocked_inputs" in kwargs:
            by_name = {i.label.casefold(): i.id for i in self._state.inputs}
            changes["blocked_inputs"] = [
                by_name.get(name.casefold(), name) for name in kwargs["blocked_inputs"]
            ]
        if "when_blocked" in kwargs:
            changes["when_blocked"] = kwargs["when_blocked"]
        return await self.coordinator.async_bridge_rules(changes)

    async def async_install_tv_bridge(
        self, development: bool = False, url: str | None = None
    ) -> None:
        """Install or update the TV app over ADB (install_tv_bridge)."""
        await self.coordinator.async_install_bridge(
            url or (BRIDGE_DEV_APK_URL if development else BRIDGE_APK_URL)
        )

    # What it does

    async def _run(self, coro: Coroutine[Any, Any, None]) -> None:
        with translate_errors():
            await coro
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        """Wake the TV."""
        await self.coordinator.async_turn_on()

    async def async_turn_off(self) -> None:
        """Put the TV to sleep."""
        await self._run(self.coordinator.client.async_key("SLEEP"))

    async def async_volume_up(self) -> None:
        """Volume up a step."""
        await self._run(self.coordinator.client.async_key("VOLUME_UP"))

    async def async_volume_down(self) -> None:
        """Volume down a step."""
        await self._run(self.coordinator.client.async_key("VOLUME_DOWN"))

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume."""
        await self._run(
            self.coordinator.client.async_set_volume(
                volume, self._state.volume_max or 100
            )
        )

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute (the TV's mute key toggles, so only when it changes)."""
        if self._state.muted is not None and self._state.muted == mute:
            return
        await self._run(self.coordinator.client.async_key("VOLUME_MUTE"))

    async def async_media_play(self) -> None:
        """Play."""
        await self._run(self.coordinator.client.async_key("MEDIA_PLAY"))

    async def async_media_pause(self) -> None:
        """Pause."""
        await self._run(self.coordinator.client.async_key("MEDIA_PAUSE"))

    async def async_media_stop(self) -> None:
        """Stop; Home Assistant's own media and dashboards close."""
        if self._state.app == BRIDGE_PACKAGE:
            await self.coordinator.async_stop_media()
            await self.coordinator.async_request_refresh()
            return
        await self._run(self.coordinator.client.async_key("MEDIA_STOP"))

    async def async_media_next_track(self) -> None:
        """Next."""
        await self._run(self.coordinator.client.async_key("MEDIA_NEXT"))

    async def async_media_previous_track(self) -> None:
        """Previous."""
        await self._run(self.coordinator.client.async_key("MEDIA_PREVIOUS"))

    async def async_select_source(self, source: str) -> None:
        """Open an app or switch to an input, by name."""
        tv_input = self._input(source)
        if tv_input:
            await self.coordinator.async_select_input(tv_input.id)
            return
        app = next((a for a in self.coordinator.data.apps if a.name == source), None)
        if app is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_source",
                translation_placeholders={"source": source},
            )
        await self.coordinator.async_open_app(app)

    def _input(self, name_or_id: str) -> TvInput | None:
        return next(
            (i for i in self._state.inputs if name_or_id in (i.label, i.id)), None
        )

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any
    ) -> None:
        """Play media, open an app, an input or a link.

        Home Assistant's media (its media browser, text-to-speech, a camera,
        an audio or video URL) plays through the TV app: full screen, or
        with ``announce`` (text-to-speech's default) spoken over what's on,
        which ducks. ``app`` opens an app by package, ``input`` an input,
        ``url`` a link the TV opens (a YouTube video in YouTube).
        """
        client = self.coordinator.client
        announce = kwargs.get(ATTR_MEDIA_ANNOUNCE)
        extra: dict[str, Any] = kwargs.get(ATTR_MEDIA_EXTRA) or {}
        message = None
        if media_source.is_media_source_id(media_id):
            if media_id.startswith(TTS_SOURCE):
                message = parse_qs(urlsplit(media_id).query).get("message", [None])[0]
                if announce is None:
                    announce = True
            item = await media_source.async_resolve_media(
                self.hass, media_id, self.entity_id
            )
            media_type, media_id = item.mime_type, item.url
        if media_type == MEDIA_TYPE_APP:
            app = self._app(media_id) or App(media_id, "", media_id)
            await self.coordinator.async_open_app(app)
        elif media_type == MEDIA_TYPE_INPUT:
            tv_input = self._input(media_id)
            await self.coordinator.async_select_input(
                tv_input.id if tv_input else media_id
            )
        elif media_type in (MediaType.URL, "url") and not announce:
            await self._run(client.async_open_url(media_id))
        elif kind := "audio" if announce else _kind(media_type):
            payload: dict[str, Any] = {
                "url": async_process_play_media_url(self.hass, media_id),
                "kind": kind,
                "announce": bool(announce),
            }
            if "/" in media_type:
                payload["mime"] = media_type
            metadata = extra.get("metadata") or {}
            for key, value in (
                ("title", extra.get("title") or metadata.get("title")),
                ("artist", metadata.get("artist")),
                ("message", message),
            ):
                if value:
                    payload[key] = str(value)
            if thumb := extra.get("thumb") or metadata.get("thumb"):
                payload["image_url"] = self._home_assistant_url(str(thumb))
            await self.coordinator.async_play(payload)
            await self.coordinator.async_request_refresh()
        else:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_media_type",
                translation_placeholders={"media_type": str(media_type)},
            )

    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Home Assistant's media the TV can play: audio, video and images."""
        return await media_source.async_browse_media(
            self.hass,
            media_content_id,
            content_filter=lambda item: item.media_content_type.startswith(
                ("audio/", "video/", "image/")
            ),
        )

    async def async_show_dashboard(
        self, dashboard: str = "lovelace", view: str | None = None
    ) -> None:
        """Show a dashboard full screen (googletv.show_dashboard)."""
        path = "/" + dashboard.strip("/")
        if view:
            path += "/" + view.strip("/")
        await self.coordinator.async_show_dashboard(self._home_assistant_url(path))
        await self.coordinator.async_request_refresh()

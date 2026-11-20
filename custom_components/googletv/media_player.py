"""The TV as a media player: power, volume, playback, apps, inputs, what's on."""

from __future__ import annotations

from collections.abc import Coroutine
from datetime import datetime
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import GoogleTvConfigEntry, GoogleTvCoordinator, translate_errors
from .entity import GoogleTvEntity
from .parsers import MUSIC_APPS, PLAYBACK_PAUSED, App, TvInput, app_name

# play_media's types beyond Home Assistant's own: an app by package, an input by id
MEDIA_TYPE_APP = "app"
MEDIA_TYPE_INPUT = "input"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoogleTvConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the TV's media player."""
    async_add_entities([GoogleTvMediaPlayer(entry.runtime_data)])


class GoogleTvMediaPlayer(GoogleTvEntity, MediaPlayerEntity):
    """A Google TV."""

    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.TV
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
    )

    def __init__(self, coordinator: GoogleTvCoordinator) -> None:
        """Initialize the media player."""
        super().__init__(coordinator, "media_player")
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
        """The launcher's apps, then the HDMI inputs."""
        return [a.name for a in self.coordinator.data.apps] + [
            i.label for i in self._state.inputs
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
        """The title of what's playing, as its app reports it."""
        playing = self._state.now_playing if self._state.awake else None
        return playing.title if playing else None

    @property
    def media_artist(self) -> str | None:
        """The show, channel or artist."""
        playing = self._state.now_playing if self._state.awake else None
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
        """What's playing's cover or poster, else its app's icon."""
        state = self._state
        if not state.awake or state.input:
            return None
        if self.coordinator.data.artwork:
            return self.coordinator.data.artwork
        playing = state.now_playing
        app = self._app(playing.package if playing else state.app)
        return app.icon if app else None

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
            ],
            "input": state.input.id if state.awake and state.input else None,
            "media_app": state.now_playing.package
            if state.awake and state.now_playing
            else None,
        }

    # What it does

    async def _run(self, coro: Coroutine[Any, Any, None]) -> None:
        with translate_errors():
            await coro
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        """Wake the TV."""
        await self._run(self.coordinator.client.async_key("WAKEUP"))

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
        """Stop."""
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
        """Open an app (``app``: a package), an input (``input``) or a ``url``."""
        client = self.coordinator.client
        if media_type == MEDIA_TYPE_APP:
            app = self._app(media_id) or App(media_id, "", media_id)
            await self.coordinator.async_open_app(app)
        elif media_type == MEDIA_TYPE_INPUT:
            tv_input = self._input(media_id)
            await self.coordinator.async_select_input(
                tv_input.id if tv_input else media_id
            )
        elif media_type in (MediaType.URL, "url"):
            await self._run(client.async_open_url(media_id))
        else:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_media_type",
                translation_placeholders={"media_type": str(media_type)},
            )

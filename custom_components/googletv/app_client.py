"""A TV through its app alone (no ADB): the same calls as ``GoogleTvClient``.

The TV app (Google TV by Raineworks) reads the TV and does what an app may:
media and volume keys, opening apps, links and inputs, the volume. What
only ADB can do (the D-pad, Home, turning the TV off, which input is on
screen) raises ``GoogleTvError`` saying so; ADB can be added to the TV later.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from .adb import GoogleTvAuthError, GoogleTvError
from .bridge import BridgeAuthError, BridgeClient, BridgeError
from .parsers import App, Diagnostics, MediaSession, TvInput, TvState

# Keys the app can press; the rest need ADB
APP_KEYS = {
    "MEDIA_PLAY_PAUSE",
    "MEDIA_PLAY",
    "MEDIA_PAUSE",
    "MEDIA_STOP",
    "MEDIA_NEXT",
    "MEDIA_PREVIOUS",
    "MEDIA_REWIND",
    "MEDIA_FAST_FORWARD",
    "VOLUME_UP",
    "VOLUME_DOWN",
    "VOLUME_MUTE",
}


class NeedsAdbError(GoogleTvError):
    """Only ADB (network debugging) can do it."""


class AppClient:
    """A TV through its app's API."""

    def __init__(self, bridge: BridgeClient) -> None:
        """Set up the client on the app's API (paired: it has a token)."""
        self.bridge = bridge
        self.host = bridge.host
        self._inputs: list[TvInput] = []

    @property
    def connected(self) -> bool:
        """Always: each call is its own request."""
        return True

    async def _call[T](self, call: Awaitable[T]) -> T:
        try:
            return await call
        except BridgeAuthError as err:
            raise GoogleTvAuthError(str(err)) from err
        except BridgeError as err:
            raise GoogleTvError(str(err)) from err

    async def _post(self, path: str, body: dict[str, Any]) -> None:
        await self._call(self.bridge.async_request("POST", path, body))

    async def async_connect(self, auth_timeout_s: float = 0.5) -> None:
        """The app answers, and knows the token."""
        await self._call(self.bridge.async_state())

    async def async_close(self) -> None:
        """Nothing held open."""

    async def async_get_props(self) -> dict[str, str]:
        """Maker, model and Android version (no serial or MACs for an app)."""
        info = await self._call(self.bridge.async_info())
        return {
            key: str(info[source])
            for key, source in (
                ("manufacturer", "manufacturer"),
                ("model", "model"),
                ("android", "android"),
            )
            if info.get(source)
        }

    async def async_get_state(self) -> TvState:
        """The screen, the app in front, the volume and what's playing."""
        data = await self._call(self.bridge.async_state())
        if not self._inputs:
            await self._read_inputs()
        volume = data.get("volume") or {}
        top = volume.get("max") or None
        sessions = [
            MediaSession(
                package=s["package"],
                active=True,
                state=int(s.get("state") or 0),
                position_ms=s.get("position_ms"),
                updated_ms=s.get("updated_ms"),
                speed=float(s.get("speed") or 1.0),
                title=s.get("title"),
                subtitle=s.get("subtitle"),
                description=s.get("description"),
            )
            for s in data.get("sessions") or []
            if s.get("package")
        ]
        return TvState(
            awake=bool(data.get("screen_on")),
            app=data.get("foreground_app"),
            volume=min(1.0, volume["level"] / top)
            if top and volume.get("level") is not None
            else None,
            muted=volume.get("muted"),
            volume_max=top,
            uptime_ms=int(data.get("uptime_ms") or 0),
            sessions=sessions,
            inputs=self._inputs,
        )

    async def async_get_quick_state(self, previous: TvState) -> TvState:
        """As full as the full read: the app answers in one request."""
        return await self.async_get_state()

    async def _read_inputs(self) -> None:
        reply = await self._call(self.bridge.async_request("GET", "/api/inputs"))
        self._inputs = [
            TvInput(id=i["id"], port=n, label=i.get("name") or f"HDMI {n}")
            for n, i in enumerate(reply.get("inputs") or [], start=1)
        ]

    async def async_get_apps(self) -> list[App]:
        """The launcher's apps."""
        await self._read_inputs()
        reply = await self._call(self.bridge.async_request("GET", "/api/apps"))
        return [
            App(a["package"], a.get("activity") or "", a.get("name") or a["package"])
            for a in reply.get("apps") or []
        ]

    async def async_get_diagnostics(self) -> Diagnostics:
        """The network, storage and memory."""
        d = await self._call(self.bridge.async_request("GET", "/api/diagnostics"))
        return Diagnostics(
            connection=d.get("connection"),
            ip_address=self.host,
            wifi_signal=d.get("wifi_signal"),
            storage_used=d.get("storage_used"),
            storage_free_mb=d.get("storage_free_mb"),
            memory_free_mb=d.get("memory_free_mb"),
            memory_total_mb=d.get("memory_total_mb"),
        )

    async def async_key(self, key: str) -> None:
        """A media or volume key; waking is left to the TV; the rest needs ADB."""
        key = key.upper().removeprefix("KEYCODE_")
        if key == "WAKEUP":
            # An app can't wake the screen: opening an app or input may
            return
        if key not in APP_KEYS:
            raise NeedsAdbError(f"{key} needs ADB (network debugging)")
        await self._post("/api/key", {"key": key})

    async def async_launch_app(self, package: str, activity: str | None = None) -> None:
        """Open an app by its launcher entry."""
        await self._post("/api/launch", {"package": package})

    async def async_open_url(self, url: str) -> None:
        """Open a link in the app that takes it."""
        await self._post("/api/open_url", {"url": url})

    async def async_select_input(self, input_id: str) -> None:
        """Switch to an input, through the TV's own input app."""
        await self._post("/api/input", {"id": input_id})

    async def async_set_volume(self, level: float, steps: int = 100) -> None:
        """The media volume, 0 to 1."""
        await self._post("/api/volume", {"level": level})

    async def async_shell(self, command: str, *args: Any, **kwargs: Any) -> str:
        """Only over ADB."""
        raise NeedsAdbError("A shell needs ADB (network debugging)")

    async def async_install_apk(self, apk: bytes) -> bool:
        """Only over ADB."""
        raise NeedsAdbError("Installing needs ADB (network debugging)")

    async def async_read_file(self, path: str) -> str:
        """Only over ADB."""
        raise NeedsAdbError("Reading files needs ADB (network debugging)")

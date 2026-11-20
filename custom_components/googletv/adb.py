"""A Google TV over ADB (network debugging).

One TCP connection per TV, opened once and reused; every read is one shell
command (``parsers.POLL_COMMAND``). Commands are serialized: ADB's shell
streams share the connection, and the TVs answer one at a time anyway.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re

from adb_shell.adb_device_async import AdbDeviceTcpAsync
from adb_shell.auth.keygen import keygen
from adb_shell.auth.sign_pythonrsa import PythonRSASigner
from adb_shell.exceptions import (
    AdbConnectionError,
    AdbTimeoutError,
    DeviceAuthError,
    InvalidChecksumError,
    InvalidCommandError,
    InvalidResponseError,
    TcpTimeoutException,
)

from .const import AUTH_TIMEOUT_S, COMMAND_TIMEOUT_S, CONNECT_TIMEOUT_S, KEYCODES
from .parsers import (
    APPS_COMMAND,
    POLL_COMMAND,
    PROPS_COMMAND,
    App,
    TvState,
    parse_apps,
    parse_props,
    parse_state,
)

_LOGGER = logging.getLogger(__name__)

_CONNECTION_ERRORS = (
    AdbConnectionError,
    AdbTimeoutError,
    InvalidChecksumError,
    InvalidCommandError,
    InvalidResponseError,
    TcpTimeoutException,
    ConnectionError,
    OSError,
    asyncio.TimeoutError,
)

# What a shell command may carry from Home Assistant: package and activity
# names, input ids and URLs are checked against these before they're sent.
_PACKAGE = re.compile(r"^[A-Za-z][\w]*(\.[A-Za-z_][\w]*)+$")
_ACTIVITY = re.compile(r"^[A-Za-z_][\w.$]*$")
_INPUT_ID = re.compile(r"^[\w.]+/[\w.$]+/\w+$")
_URL = re.compile(r"^[a-z][a-z0-9+.-]*://[^\s'\"\\`$;|&<>]*$", re.I)


class GoogleTvError(Exception):
    """The TV couldn't be reached, or refused."""


class GoogleTvAuthError(GoogleTvError):
    """The TV didn't trust Home Assistant's key: its prompt wasn't accepted."""


def load_signer(key_path: str) -> PythonRSASigner:
    """Home Assistant's ADB key, made the first time (blocking: run in an executor)."""
    if not os.path.isfile(key_path):
        keygen(key_path)
    with (
        open(key_path, encoding="utf-8") as priv,
        open(f"{key_path}.pub", encoding="utf-8") as pub,
    ):
        return PythonRSASigner(pub.read(), priv.read())


class GoogleTvClient:
    """One TV's ADB connection and the commands the integration sends it."""

    def __init__(self, host: str, port: int, signer: PythonRSASigner) -> None:
        """Set up the client (it connects on first use)."""
        self.host = host
        self.port = port
        self._signer = signer
        self._device = AdbDeviceTcpAsync(host, port, default_transport_timeout_s=9.0)
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        """The connection is open."""
        return self._device.available

    async def async_connect(self, auth_timeout_s: float = 0.5) -> None:
        """Open the connection, waiting ``auth_timeout_s`` for the TV's prompt."""
        try:
            await self._device.connect(
                rsa_keys=[self._signer],
                transport_timeout_s=CONNECT_TIMEOUT_S,
                auth_timeout_s=auth_timeout_s,
            )
        except DeviceAuthError as err:
            raise GoogleTvAuthError(str(err)) from err
        except _CONNECTION_ERRORS as err:
            raise GoogleTvError(
                f"Can't connect to {self.host}:{self.port}: {err}"
            ) from err
        if not self._device.available:
            raise GoogleTvAuthError("The TV didn't accept Home Assistant's key")

    async def async_pair(self) -> dict[str, str]:
        """Connect, waiting for the prompt to be accepted, and read who the TV is."""
        await self.async_connect(auth_timeout_s=AUTH_TIMEOUT_S)
        return parse_props(await self.async_shell(PROPS_COMMAND))

    async def async_close(self) -> None:
        """Close the connection."""
        with contextlib.suppress(*_CONNECTION_ERRORS):
            await self._device.close()

    async def async_shell(
        self, command: str, timeout_s: float = COMMAND_TIMEOUT_S
    ) -> str:
        """Run a shell command, reconnecting first if the connection dropped."""
        async with self._lock:
            if not self._device.available:
                await self.async_connect()
            try:
                result = await self._device.shell(
                    command, read_timeout_s=timeout_s, timeout_s=timeout_s
                )
            except _CONNECTION_ERRORS as err:
                await self.async_close()
                raise GoogleTvError(f"{self.host}: {err}") from err
        return result if isinstance(result, str) else ""

    async def async_get_state(self) -> TvState:
        """Read the TV: power, app, volume, what's playing, inputs."""
        return parse_state(await self.async_shell(POLL_COMMAND))

    async def async_get_apps(self) -> list[App]:
        """The launcher's apps."""
        return parse_apps(await self.async_shell(APPS_COMMAND))

    async def async_get_props(self) -> dict[str, str]:
        """Maker, model, Android version and serial."""
        return parse_props(await self.async_shell(PROPS_COMMAND))

    async def async_key(self, key: str) -> None:
        """Press a key (a ``KEYCODES`` name, or an Android key code number)."""
        code = KEYCODES.get(key.upper().removeprefix("KEYCODE_"))
        if code is None:
            if not key.isdigit():
                raise GoogleTvError(f"Unknown key: {key}")
            code = int(key)
        await self.async_shell(f"input keyevent {code}")

    async def async_launch_app(self, package: str, activity: str | None = None) -> None:
        """Open an app by its launch screen (no Play Store link, so every app opens)."""
        if not _PACKAGE.match(package) or (activity and not _ACTIVITY.match(activity)):
            raise GoogleTvError(f"Not an app: {package}")
        if activity:
            await self.async_shell(f"am start -n {package}/{activity}")
        else:
            await self.async_shell(
                f"monkey -p {package} -c android.intent.category.LEANBACK_LAUNCHER 1"
            )

    async def async_open_url(self, url: str) -> None:
        """Open a link (a deep link, or a web address an app takes)."""
        if not _URL.match(url):
            raise GoogleTvError(f"Not a link: {url}")
        await self.async_shell(f"am start -a android.intent.action.VIEW -d '{url}'")

    async def async_select_input(self, input_id: str) -> None:
        """Switch to an HDMI input (Android's passthrough link to it)."""
        if not _INPUT_ID.match(input_id):
            raise GoogleTvError(f"Not an input: {input_id}")
        encoded = input_id.replace("/", "%2F")
        await self.async_shell(
            "am start -a android.intent.action.VIEW "
            f"-d content://android.media.tv/passthrough/{encoded}"
        )

    async def async_set_volume(self, level: float) -> None:
        """Set the media volume (0 to 1) on the TV's 0–100 scale."""
        value = max(0, min(100, round(level * 100)))
        await self.async_shell(f"cmd media_session volume --stream 3 --set {value}")

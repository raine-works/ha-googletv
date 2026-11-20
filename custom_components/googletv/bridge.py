"""Raineworks TV Bridge: the TV app's local API (see protocol/README.md).

The app shows Home Assistant's notifications on the TV: pop-ups over whatever
is on screen (apps and HDMI inputs) with text, an image or a video, or in the
notification panel. The integration installs it over ADB, pairs with it over
ADB (no code to type), and sends it notifications.
"""

from __future__ import annotations

from typing import Any

import aiohttp

BRIDGE_PACKAGE = "com.raineworks.tvbridge"
BRIDGE_PORT = 8721
BRIDGE_SERVICE_TYPE = "_rwtvbridge._tcp.local."
# The APK attached to the latest release, and master's build for testing
BRIDGE_APK_URL = (
    "https://github.com/raine-works/ha-googletv/releases/latest/download/"
    "raineworks-tv-bridge.apk"
)
BRIDGE_DEV_APK_URL = (
    "https://github.com/raine-works/ha-googletv/releases/download/tv-bridge-dev/"
    "raineworks-tv-bridge.apk"
)
# Where the app writes a pairing code for ADB (`via: adb`)
BRIDGE_PAIRING_FILE = f"/sdcard/Android/data/{BRIDGE_PACKAGE}/files/pairing_code"

TIMEOUT = aiohttp.ClientTimeout(total=10)


class BridgeError(Exception):
    """The app couldn't be reached, or refused."""


class BridgeAuthError(BridgeError):
    """The app doesn't know the token (it was reinstalled, or forgot pairings)."""


class BridgeClient:
    """The TV app's API on one TV."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        token: str | None = None,
        port: int = BRIDGE_PORT,
    ) -> None:
        """Set up the client."""
        self._session = session
        self.host = host
        self.port = port
        self.token = token

    async def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        url = f"http://{self.host}:{self.port}{path}"
        try:
            async with self._session.request(
                method, url, json=body, headers=headers, timeout=TIMEOUT
            ) as response:
                reply = await response.json(content_type=None)
                if response.status == 401:
                    raise BridgeAuthError(reply.get("error", "Not paired"))
                if response.status >= 400:
                    raise BridgeError(reply.get("error", f"HTTP {response.status}"))
                return reply
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise BridgeError(f"Can't reach TV Bridge on {self.host}: {err}") from err

    async def async_info(self) -> dict[str, Any]:
        """Who the app is (no token needed)."""
        return await self._request("GET", "/api/info")

    async def async_pair_start(self, via: str) -> str:
        """Start pairing; the code goes on screen (``screen``) or to ADB (``adb``)."""
        reply = await self._request("POST", "/api/pair/start", {"via": via})
        return str(reply["pairing_id"])

    async def async_pair_finish(self, pairing_id: str, code: str) -> str:
        """The token for a right code."""
        reply = await self._request(
            "POST", "/api/pair/finish", {"pairing_id": pairing_id, "code": code}
        )
        self.token = str(reply["token"])
        return self.token

    async def async_state(self) -> dict[str, Any]:
        """The screen, the app in front, the app's permissions."""
        return await self._request("GET", "/api/state")

    async def async_notify(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Show a notification; whether it popped up, went to the panel, and why."""
        return await self._request("POST", "/api/notify", payload)

    async def async_dismiss(self, tag: str | None = None) -> None:
        """Take a pop-up (or all of them) down."""
        await self._request("POST", "/api/dismiss", {"tag": tag} if tag else {})

    async def async_rules(
        self, changes: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """The notification rules, changed first when ``changes`` are given."""
        if changes:
            return await self._request("POST", "/api/rules", changes)
        return await self._request("GET", "/api/rules")


def parse_pairing_file(text: str) -> tuple[str, str] | None:
    """``<pairing_id> <code>`` from the app's pairing file, if it's there."""
    parts = text.split()
    if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 6:
        return parts[0], parts[1]
    return None

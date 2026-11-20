"""Data update coordinator for a Google TV."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
import contextlib
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
import logging
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .adb import GoogleTvAuthError, GoogleTvClient, GoogleTvError
from .bridge import (
    BRIDGE_PACKAGE,
    BRIDGE_PAIRING_FILE,
    BridgeAuthError,
    BridgeClient,
    BridgeError,
    parse_pairing_file,
)
from .const import (
    APPS_INTERVAL,
    CONF_BRIDGE_TOKEN,
    DOMAIN,
    FULL_INTERVAL,
    SCAN_INTERVAL,
)
from .online import Lookups
from .parsers import HOME_APPS, INPUT_APPS, MUSIC_APPS, App, Diagnostics, TvState
from .wol import async_wake

_LOGGER = logging.getLogger(__name__)

# TV Bridge: the APK's download, and pairing with it once it's installed
BRIDGE_APK_MAX_BYTES = 100 * 1024 * 1024
BRIDGE_DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=180)
BRIDGE_PAIRING_ATTEMPTS = 6
BRIDGE_PAIRING_RETRY_S = 2
BRIDGE_PAIRING_BACKOFF = timedelta(minutes=5)
BRIDGE_SETUP_COMMANDS = (
    f"appops set {BRIDGE_PACKAGE} SYSTEM_ALERT_WINDOW allow",
    f"appops set {BRIDGE_PACKAGE} GET_USAGE_STATS allow",
    f"cmd deviceidle whitelist +{BRIDGE_PACKAGE}",
    f"am broadcast -a {BRIDGE_PACKAGE}.START -n {BRIDGE_PACKAGE}/.StartReceiver",
)

# How far the TV's start time may wander between reads before it's a restart
BOOT_DRIFT = timedelta(minutes=2)
# How soon a failed artwork lookup is tried again while the title plays
ARTWORK_RETRY = timedelta(minutes=1)
# How long the first update waits for apps' listings (later ones don't wait)
FIRST_LISTINGS_TIMEOUT_S = 20

type GoogleTvConfigEntry = ConfigEntry[GoogleTvCoordinator]


@dataclass
class GoogleTvData:
    """What the entities show: the latest poll, the apps, the artwork."""

    state: TvState
    apps: list[App] = field(default_factory=list)
    # A cover or poster for what's playing, when one was found online
    artwork: str | None = None
    # Network, storage and memory, read with the apps
    diagnostics: Diagnostics = field(default_factory=Diagnostics)
    # When the TV started (kept steady between reads)
    last_boot: datetime | None = None
    # The TV answered: off its network (in standby, unplugged) it's shown off
    reachable: bool = True
    # Raineworks TV Bridge (notifications): installed, and paired with
    bridge_installed: bool = False
    bridge_paired: bool = False


@contextmanager
def translate_errors() -> Iterator[None]:
    """Re-raise client errors from user actions as HomeAssistantError."""
    try:
        yield
    except GoogleTvError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_failed",
            translation_placeholders={"error": str(err)},
        ) from err


class GoogleTvCoordinator(DataUpdateCoordinator[GoogleTvData]):
    """Reads one TV every few seconds over its ADB connection."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: GoogleTvConfigEntry,
        client: GoogleTvClient,
        props: dict[str, str],
        lookups: Lookups | None,
    ) -> None:
        """Initialize the coordinator (``lookups`` None: nothing online)."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
            config_entry=entry,
        )
        self.client = client
        self.props = props
        self.lookups = lookups
        # The options it was set up with (a change to them reloads it)
        self.options = dict(entry.options)
        self.bridge = BridgeClient(
            async_get_clientsession(hass),
            entry.data[CONF_HOST],
            entry.data.get(CONF_BRIDGE_TOKEN),
        )
        self._bridge_pairing = False
        self._bridge_retry_at: datetime | None = None
        self._launcher_apps: list[App] = []
        self._apps_read_at: datetime | None = None
        self._full_read_at: datetime | None = None
        self._last_boot: datetime | None = None
        self._diagnostics = Diagnostics()
        self._artwork_for: tuple[str, str, str | None] | None = None
        self._artwork_tried_at: datetime | None = None

    async def _async_update_data(self) -> GoogleTvData:
        """Read the TV (fully every few seconds, quickly between), and its apps."""
        try:
            now = dt_util.utcnow()
            state = await self._async_read_state(now)
            if self._apps_read_at is None or now - self._apps_read_at >= APPS_INTERVAL:
                first = self._apps_read_at is None
                self._launcher_apps = await self.client.async_get_apps()
                self._diagnostics = await self.client.async_get_diagnostics()
                self._apps_read_at = now
                if first:
                    # Named before their buttons are made, which fixes their ids
                    await self._async_first_listings()
                else:
                    self._look_up_listings()
        except GoogleTvAuthError as err:
            # The TV forgot Home Assistant's key: ask for it again (reauth)
            raise ConfigEntryAuthFailed(str(err)) from err
        except GoogleTvError as err:
            return self._offline(err)
        if self.data is not None and not self.data.reachable:
            _LOGGER.info("%s is back on the network", self.client.host)
        state = self._without_stale_input(state)
        if state.uptime_ms:
            boot = now - timedelta(milliseconds=state.uptime_ms)
            # Read every second, it wobbles by a little; a restart moves it
            if self._last_boot is None or abs(boot - self._last_boot) > BOOT_DRIFT:
                self._last_boot = boot.replace(second=0, microsecond=0)
        installed = self.bridge_installed
        if installed and not self.bridge.token:
            self._pair_bridge_soon(now)
        return GoogleTvData(
            state=state,
            apps=self._named_apps(),
            artwork=self._artwork(state),
            diagnostics=self._diagnostics,
            last_boot=self._last_boot,
            bridge_installed=installed,
            bridge_paired=installed and bool(self.bridge.token),
        )

    # Raineworks TV Bridge: installing, pairing, notifications

    @property
    def bridge_installed(self) -> bool:
        """The app is in the TV's launcher."""
        return any(a.package == BRIDGE_PACKAGE for a in self._launcher_apps)

    def _pair_bridge_soon(self, now: datetime) -> None:
        if self._bridge_pairing or (
            self._bridge_retry_at is not None and now < self._bridge_retry_at
        ):
            return
        self._bridge_pairing = True
        self.config_entry.async_create_background_task(
            self.hass, self._async_pair_bridge(), f"{DOMAIN} TV Bridge pairing"
        )

    async def _async_pair_bridge(self, attempts: int = 1) -> bool:
        """Pair with the app over ADB: it writes a code only ADB can read."""
        self._bridge_pairing = True
        try:
            for attempt in range(attempts):
                if attempt:
                    await asyncio.sleep(BRIDGE_PAIRING_RETRY_S)
                try:
                    pairing_id = await self.bridge.async_pair_start("adb")
                    parsed = parse_pairing_file(
                        await self.client.async_read_file(BRIDGE_PAIRING_FILE)
                    )
                    if parsed is None or parsed[0] != pairing_id:
                        raise BridgeError("The app wrote no pairing code")
                    token = await self.bridge.async_pair_finish(*parsed)
                except (BridgeError, GoogleTvError) as err:
                    _LOGGER.debug("Can't pair with TV Bridge yet: %s", err)
                    continue
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={**self.config_entry.data, CONF_BRIDGE_TOKEN: token},
                )
                _LOGGER.info("Paired with TV Bridge on %s", self.client.host)
                if self.data is not None:
                    self.data = replace(self.data, bridge_paired=True)
                    self.async_update_listeners()
                return True
            self._bridge_retry_at = dt_util.utcnow() + BRIDGE_PAIRING_BACKOFF
            return False
        finally:
            self._bridge_pairing = False

    async def async_install_bridge(self, url: str) -> None:
        """Install (or update) TV Bridge from its APK, allow it, and pair."""
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(url, timeout=BRIDGE_DOWNLOAD_TIMEOUT) as response:
                response.raise_for_status()
                apk = await response.content.read(BRIDGE_APK_MAX_BYTES + 1)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="bridge_download_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        if len(apk) > BRIDGE_APK_MAX_BYTES or not apk.startswith(b"PK"):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="bridge_download_failed",
                translation_placeholders={"error": "not an APK"},
            )
        with translate_errors():
            await self.client.async_install_apk(apk)
            # Pop-ups over other apps and its rules' app detection, which TVs
            # often have no settings screen for; kept running; started
            for command in BRIDGE_SETUP_COMMANDS:
                await self.client.async_shell(command)
        self._apps_read_at = None
        self._bridge_retry_at = None
        if not self.bridge.token:
            await self._async_pair_bridge(attempts=BRIDGE_PAIRING_ATTEMPTS)
        await self.async_request_refresh()

    async def async_notify(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Show a notification on the TV, telling the app what's on screen."""
        if not self.bridge.token:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="bridge_not_paired"
            )
        state = self.data.state if self.data else None
        if state and state.awake:
            context = {"app": state.app}
            if state.input:
                context["input"] = state.input.id
            payload = {"context": context, **payload}
        try:
            return await self.bridge.async_notify(payload)
        except BridgeAuthError as err:
            # The app forgot the pairing (reinstalled, data cleared): pair again
            self.bridge.token = None
            self._bridge_retry_at = None
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="bridge_not_paired"
            ) from err
        except BridgeError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def async_bridge_rules(self, changes: dict[str, Any]) -> dict[str, Any]:
        """Change the app's notification rules."""
        if not self.bridge.token:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="bridge_not_paired"
            )
        try:
            return await self.bridge.async_rules(changes)
        except BridgeError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    def _offline(self, err: Exception) -> GoogleTvData:
        """The TV off its network: shown off, its inputs and apps kept.

        Many TVs drop their network in standby (a Sony without Remote start),
        so an unreachable TV is an off one: the media player and Activity say
        off (and Turn on sends Wake-on-LAN), the rest go unavailable.
        """
        previous = self.data
        if previous is None or previous.reachable:
            _LOGGER.info("%s is off its network: %s", self.client.host, err)
        # Read fully when it's back
        self._full_read_at = None
        return GoogleTvData(
            state=TvState(inputs=previous.state.inputs if previous else []),
            apps=self._named_apps(),
            diagnostics=self._diagnostics,
            last_boot=self._last_boot,
            reachable=False,
        )

    async def _async_read_state(self, now: datetime) -> TvState:
        """A full read when it's due, else a quick one over the last.

        The quick read (the screen and media sessions) shows a pause within a
        second; a screen turning on or off brings the full read forward, so
        the app and input catch up at once.
        """
        if (
            self.data is not None
            and self._full_read_at is not None
            and now - self._full_read_at < FULL_INTERVAL
        ):
            previous = self.data.state
            state = await self.client.async_get_quick_state(previous)
            if state.awake == previous.awake:
                return state
        state = await self.client.async_get_state()
        self._full_read_at = now
        return state

    async def async_request_refresh(self) -> None:
        """Read the TV fully soon (after a command: a new app, an input)."""
        self._full_read_at = None
        await super().async_request_refresh()

    def _without_stale_input(self, state: TvState) -> TvState:
        """No input on screen while a launcher app or the home screen is.

        The TV's input session can outlive leaving the input; an app the
        launcher lists in front (Disney+, Netflix…) means the input is gone,
        unless it's the TV's own input app.
        """
        if not state.input or not state.app or state.app in INPUT_APPS:
            return state
        if state.app in HOME_APPS or any(
            a.package == state.app for a in self._launcher_apps
        ):
            return replace(state, input=None)
        return state

    # The apps, named and pictured from their Play Store listings

    def _named_apps(self) -> list[App]:
        apps = []
        for app in self._launcher_apps:
            listing = self.lookups.listing(app.package) if self.lookups else None
            if listing:
                # A name the integration knows wins; the package is no name
                name = app.name if app.name != app.package else listing.name
                app = replace(app, name=name or app.name, icon=listing.icon)
            apps.append(app)
        return sorted(apps, key=lambda a: a.name.casefold())

    def _wanted_listings(self) -> list[str]:
        if not self.lookups:
            return []
        return [
            a.package
            for a in self._launcher_apps
            if self.lookups.needs_listing(a.package)
        ]

    async def _async_first_listings(self) -> None:
        """Read missing listings before the first update (cached after that)."""
        if wanted := self._wanted_listings():
            assert self.lookups
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(FIRST_LISTINGS_TIMEOUT_S):
                    await self.lookups.async_fetch_listings(wanted)

    def _look_up_listings(self) -> None:
        if wanted := self._wanted_listings():
            self.config_entry.async_create_background_task(
                self.hass, self._async_listings(wanted), f"{DOMAIN} app listings"
            )

    async def _async_listings(self, packages: list[str]) -> None:
        assert self.lookups
        if await self.lookups.async_fetch_listings(packages) and self.data:
            self.data = replace(self.data, apps=self._named_apps())
            self.async_update_listeners()

    # Artwork for what's playing

    def _artwork(self, state: TvState) -> str | None:
        """The artwork found for what's playing; a new title starts a lookup."""
        playing = state.now_playing if state.awake else None
        if not self.lookups or not playing or not playing.title:
            self._artwork_for = None
            return None
        key = (playing.package, playing.title, playing.subtitle)
        found = self.lookups.artwork(*key)
        # A new title, or one whose lookup failed (a refusal, no network)
        # a while ago: look it up
        retry = (
            key == self._artwork_for
            and not self.lookups.has_artwork(*key)
            and self._artwork_tried_at is not None
            and dt_util.utcnow() - self._artwork_tried_at >= ARTWORK_RETRY
        )
        if found is None and (key != self._artwork_for or retry):
            self._artwork_for = key
            self._artwork_tried_at = dt_util.utcnow()
            self.config_entry.async_create_background_task(
                self.hass,
                self._async_find_artwork(key, playing.package in MUSIC_APPS),
                f"{DOMAIN} artwork",
            )
        return found

    async def _async_find_artwork(
        self, key: tuple[str, str, str | None], music: bool
    ) -> None:
        assert self.lookups
        art = await self.lookups.async_artwork(*key, music=music)
        # Still playing the same thing: show it now, not at the next poll
        if art and self.data and key == self._artwork_for:
            self.data = replace(self.data, artwork=art)
            self.async_update_listeners()

    # Commands the entities share

    @property
    def wake_macs(self) -> list[str]:
        """The TV's MACs, for Wake-on-LAN."""
        return [
            mac for key in ("mac_ethernet", "mac_wifi") if (mac := self.props.get(key))
        ]

    async def async_turn_on(self) -> None:
        """Wake the TV: Wake-on-LAN if it's off its network, else its wake key."""
        if self.data is not None and not self.data.reachable:
            if not self.wake_macs:
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="unreachable"
                )
            await async_wake(self.hass, self.wake_macs)
        else:
            with translate_errors():
                await self.client.async_key("WAKEUP")
        await self.async_request_refresh()

    async def async_open_app(self, app: App) -> None:
        """Wake the TV if it's asleep, then open the app."""
        with translate_errors():
            if self.data and not self.data.state.awake:
                await self.client.async_key("WAKEUP")
            await self.client.async_launch_app(app.package, app.activity)
        await self.async_request_refresh()

    async def async_select_input(self, input_id: str) -> None:
        """Wake the TV if it's asleep, then switch to an HDMI input."""
        with translate_errors():
            if self.data and not self.data.state.awake:
                await self.client.async_key("WAKEUP")
            await self.client.async_select_input(input_id)
        await self.async_request_refresh()

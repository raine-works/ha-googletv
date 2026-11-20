"""Data update coordinator for a Google TV."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Iterator
import contextlib
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
import hashlib
import logging
from typing import Any
from uuid import uuid4

import aiohttp
from homeassistant.auth.const import GROUP_ID_READ_ONLY, GROUP_ID_USER
from homeassistant.auth.models import TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN
from homeassistant.components.http.auth import async_sign_path
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util
from yarl import URL

from .adb import GoogleTvAuthError, GoogleTvClient, GoogleTvError
from .app_client import AppClient, NeedsAdbError
from .bridge import (
    APK_NAME,
    BRIDGE_APK_URL,
    BRIDGE_DEV_APK_URL,
    BRIDGE_PACKAGE,
    BRIDGE_PAIRING_FILE,
    BRIDGE_RELEASES_URL,
    BridgeAuthError,
    BridgeClient,
    BridgeError,
    parse_pairing_file,
)
from .const import (
    APPS_INTERVAL,
    CONF_BRIDGE_TOKEN,
    CONF_DASHBOARD_CONTROLS,
    CONF_DASHBOARD_TOKEN,
    CONF_DASHBOARD_USER,
    DOMAIN,
    FULL_INTERVAL,
    SCAN_INTERVAL,
)
from .online import Lookups
from .parsers import HOME_APPS, INPUT_APPS, MUSIC_APPS, App, Diagnostics, TvState
from .wol import async_wake

_LOGGER = logging.getLogger(__name__)

# The TV app: the APK's download, and pairing with it once it's installed
BRIDGE_APK_MAX_BYTES = 100 * 1024 * 1024
BRIDGE_DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=180)
BRIDGE_PAIRING_ATTEMPTS = 6
BRIDGE_PAIRING_RETRY_S = 2
BRIDGE_PAIRING_BACKOFF = timedelta(minutes=5)
BRIDGE_SETUP_COMMANDS = (
    f"appops set {BRIDGE_PACKAGE} SYSTEM_ALERT_WINDOW allow",
    f"appops set {BRIDGE_PACKAGE} GET_USAGE_STATS allow",
    # Notification access: what other apps play, for the app on its own
    f"cmd notification allow_listener {BRIDGE_PACKAGE}/{BRIDGE_PACKAGE}.MediaListener",
    f"cmd deviceidle whitelist +{BRIDGE_PACKAGE}",
    f"am broadcast -a {BRIDGE_PACKAGE}.START -n {BRIDGE_PACKAGE}/.StartReceiver",
)

# Who installed the TV app, when it was Google Play (Play updates it)
PLAY_STORE = "com.android.vending"

# The TV app's event stream: tried again this soon after it ends, then less often
EVENTS_RETRY_S = 5
EVENTS_MAX_RETRY_S = 300
# Fired on Home Assistant's bus for each event from the TV
EVENT_TYPE = f"{DOMAIN}_event"

# Home Assistant URLs sent to the TV are signed for this long: it loads each
# file once (a clip, downloaded whole before it plays)
SIGNED_URL_LIFETIME = timedelta(minutes=15)
SIGNED_QUERY = "authSig"
# Paths that carry their own access token (a camera's live stream)
SELF_SIGNED_PATHS = ("/api/hls/",)

# How long the TV's dashboard token lasts (it's made again if revoked)
DASHBOARD_TOKEN_LIFETIME = timedelta(days=3650)

# Live notifications (duration 0): kept across restarts, and shown again
# when the app has restarted (checked this often while there are any)
LIVE_STORAGE_VERSION = 1
LIVE_CHECK_INTERVAL = timedelta(seconds=30)

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
    # The TV app (notifications): installed, and paired with
    bridge_installed: bool = False
    bridge_paired: bool = False
    # Its version and build (the commit), as it reports them
    bridge_version: str | None = None
    bridge_build: str | None = None
    # Apps Home Assistant leaves out: the TV app's switches, else the app
    # buttons disabled here
    hidden_apps: frozenset[str] = frozenset()


@contextmanager
def translate_errors() -> Iterator[None]:
    """Re-raise client errors from user actions as HomeAssistantError."""
    try:
        yield
    except NeedsAdbError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="needs_adb",
            translation_placeholders={"error": str(err)},
        ) from err
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
        client: GoogleTvClient | AppClient,
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
        # Through the TV app alone (no ADB): the app is the connection
        self.app_only = isinstance(client, AppClient)
        self.bridge = (
            client.bridge
            if isinstance(client, AppClient)
            else BridgeClient(
                async_get_clientsession(hass),
                entry.data[CONF_HOST],
                entry.data.get(CONF_BRIDGE_TOKEN),
            )
        )
        # The TV app's version and build, as it reports them
        self.bridge_info: dict[str, Any] = {}
        # Installing the app now (asked when the TV was added)
        self.installing = False
        self._granted = False
        self._bridge_pairing = False
        self._bridge_retry_at: datetime | None = None
        self._launcher_apps: list[App] = []
        self._apps_read_at: datetime | None = None
        self._full_read_at: datetime | None = None
        self._last_boot: datetime | None = None
        self._diagnostics = Diagnostics()
        self._artwork_for: tuple[str, str, str | None] | None = None
        self._artwork_tried_at: datetime | None = None
        # Live notifications by tag: {"payload": …, "until": … | None}
        self._live: dict[str, dict[str, Any]] = {}
        self._live_unsubs: dict[str, CALLBACK_TYPE] = {}
        self._live_store: Store[dict[str, Any]] = Store(
            hass, LIVE_STORAGE_VERSION, f"{DOMAIN}.live.{entry.entry_id}"
        )
        # Tags to take down once the app answers again
        self._dismiss_pending: set[str] = set()
        # The app's run that shows them (it changes when the app restarts)
        self._bridge_instance: str | None = None
        self._live_checked_at: datetime | None = None
        self._live_checking = False
        # One TV user and token, however many dashboards are asked for at once
        self._dashboard_lock = asyncio.Lock()
        # The event entity, told of notification events
        self._event_listeners: list[Callable[[dict[str, Any]], None]] = []
        # The app's rules (hidden apps, pop-ups' rules) as it last said; None
        # until read, or for an app from before 2.4 (its buttons say then)
        self.app_rules: dict[str, Any] | None = None
        # Changes made here the app hasn't taken yet (it was unreachable)
        self._rules_pending: dict[str, list[str]] = {}
        # The integration version an update of the app was last tried for
        self._update_tried: str | None = None
        # Who installed the app (Google Play updates its own)
        self._bridge_installer: str | None = None

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
                self._after_apps_read()
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
        if installed and not self.bridge.token and not self.app_only:
            self._pair_bridge_soon(now)
        if installed and self.bridge.token:
            self._check_live_soon(now)
        return GoogleTvData(
            state=state,
            apps=self._named_apps(),
            artwork=self._artwork(state),
            diagnostics=self._diagnostics,
            last_boot=self._last_boot,
            bridge_installed=installed,
            bridge_paired=installed and bool(self.bridge.token),
            bridge_version=self.bridge_info.get("version"),
            bridge_build=self.bridge_info.get("build"),
            hidden_apps=frozenset(self.hidden_apps),
        )

    # The TV app: installing, pairing, notifications

    @property
    def bridge_installed(self) -> bool:
        """The app is in the TV's launcher (through it alone: of course)."""
        return self.app_only or any(
            a.package == BRIDGE_PACKAGE for a in self._launcher_apps
        )

    @callback
    def _after_apps_read(self) -> None:
        """With the app list read: the app's version; over ADB, a missing app."""
        if self.bridge.token and self.bridge_installed:
            self.config_entry.async_create_background_task(
                self.hass, self._async_read_bridge(), f"{DOMAIN} TV app info"
            )
        if self.app_only:
            return
        if self.bridge_installed and not self._granted:
            # Its permissions, which TVs often hide (an app-only TV given ADB)
            self._granted = True
            self.config_entry.async_create_background_task(
                self.hass, self._async_grant(), f"{DOMAIN} TV app permissions"
            )
        issue = f"install_tv_app_{self.config_entry.entry_id}"
        if self.bridge_installed or self.installing:
            ir.async_delete_issue(self.hass, DOMAIN, issue)
        else:
            # Over ADB without the app: a repair offers to install it
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue,
                is_fixable=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key="install_tv_app",
                translation_placeholders={"name": self.config_entry.title},
                data={"entry_id": self.config_entry.entry_id},
            )

    async def _async_grant(self) -> None:
        for command in BRIDGE_SETUP_COMMANDS[:-1]:
            try:
                await self.client.async_shell(command)
            except GoogleTvError as err:
                _LOGGER.debug("Can't grant the TV app %s: %s", command, err)
                return

    async def _async_read_bridge(self) -> None:
        """The app's version (an old one is updated) and its rules."""
        try:
            info = await self.bridge.async_info()
        except BridgeError as err:
            _LOGGER.debug("Can't read the TV app's version: %s", err)
            return
        self._set_bridge_info(info.get("app_version"), info.get("build"))
        self._bridge_installer = info.get("installer")
        await self._async_after_bridge_info(info)

    async def _async_after_bridge_info(self, info: dict[str, Any]) -> None:
        """Its rules (an app that has them), and an update if it's old."""
        if "hidden_apps" in (info.get("features") or []):
            await self._async_sync_rules()
        await self._async_update_bridge_if_old(info)

    async def _async_update_bridge_if_old(self, info: dict[str, Any]) -> None:
        """An app older than the integration: updated over ADB, once per version.

        One from Google Play is Play's to update; through the app alone (no
        ADB), a repair says to update it.
        """
        ours = str((await async_get_integration(self.hass, DOMAIN)).version or "")
        issue = f"update_tv_app_{self.config_entry.entry_id}"
        theirs = info.get("app_version") or self.bridge_info.get("version")
        installer = info.get("installer", self._bridge_installer)
        if not _older(theirs, ours) or installer == PLAY_STORE:
            ir.async_delete_issue(self.hass, DOMAIN, issue)
            return
        if self.app_only:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="update_tv_app",
                translation_placeholders={
                    "name": self.config_entry.title,
                    "version": str(theirs),
                    "latest": ours,
                },
            )
            return
        if self._update_tried == ours:
            return
        self._update_tried = ours
        _LOGGER.info(
            "Updating the TV app on %s from %s to %s", self.client.host, theirs, ours
        )
        try:
            await self.async_install_bridge(f"{BRIDGE_RELEASES_URL}/v{ours}/{APK_NAME}")
        except HomeAssistantError as err:
            _LOGGER.warning(
                "Couldn't update the TV app on %s to %s: %s",
                self.client.host,
                ours,
                err,
            )

    # Apps' rules: which Home Assistant leaves out, which pop-ups don't show over

    @property
    def hidden_apps(self) -> set[str]:
        """Apps left out: the TV app's switches, else the buttons disabled here."""
        if self.app_rules is not None:
            return set(self.app_rules.get("hidden_apps") or [])
        return {package for package, e in self._app_buttons().items() if e.disabled}

    def _app_buttons(self) -> dict[str, er.RegistryEntry]:
        """The app buttons in the entity registry, by package."""
        prefix = self.app_button_prefix
        return {
            e.unique_id.removeprefix(prefix): e
            for e in er.async_entries_for_config_entry(
                er.async_get(self.hass), self.config_entry.entry_id
            )
            if e.domain == "button" and e.unique_id.startswith(prefix)
        }

    @property
    def app_button_prefix(self) -> str:
        """The start of an app button's unique id (the package follows)."""
        return f"{self.config_entry.unique_id or self.config_entry.entry_id}_app_"

    async def _async_sync_rules(self) -> None:
        """The app's rules, once it has the changes it missed."""
        try:
            rules = await self.bridge.async_rules(self._rules_pending or None)
        except BridgeError as err:
            _LOGGER.debug("Can't read the TV app's rules: %s", err)
            return
        self._rules_pending = {}
        self._apply_rules(rules)

    @callback
    def _apply_rules(self, rules: dict[str, Any]) -> None:
        """The app's rules as it says them: the app buttons follow."""
        if self._rules_pending:
            # It's back: it takes what it missed first, then says again
            self.config_entry.async_create_background_task(
                self.hass, self._async_sync_rules(), f"{DOMAIN} TV app rules"
            )
            return
        rules = {k: v for k, v in rules.items() if k != "type" and k != "time"}
        if rules == self.app_rules:
            return
        self.app_rules = rules
        self._rules_changed()

    @callback
    def _rules_changed(self) -> None:
        hidden = self.hidden_apps
        registry = er.async_get(self.hass)
        for package, entry in self._app_buttons().items():
            if package in hidden and not entry.disabled:
                registry.async_update_entity(
                    entry.entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION
                )
            elif package not in hidden and entry.disabled_by in (
                er.RegistryEntryDisabler.INTEGRATION,
                er.RegistryEntryDisabler.USER,
            ):
                registry.async_update_entity(entry.entity_id, disabled_by=None)
        if self.data is not None:
            self.data = replace(self.data, hidden_apps=frozenset(hidden))
            self.async_update_listeners()

    async def async_set_app_rules(self, changes: dict[str, list[str]]) -> None:
        """Change which apps are left out, or which pop-ups don't show over.

        The TV app keeps them (one that's unreachable gets them when it's
        back); without it, apps are left out by disabling their buttons.
        """
        changes = {k: sorted(set(v)) for k, v in changes.items()}
        if self.app_rules is None:
            if "hidden_apps" in changes:
                self._hide_by_buttons(set(changes["hidden_apps"]))
            if self.bridge.token and (
                rest := {k: v for k, v in changes.items() if k != "hidden_apps"}
            ):
                await self.async_bridge_rules(rest)
            return
        self.app_rules = {**self.app_rules, **changes}
        self._rules_pending = {**self._rules_pending, **changes}
        self._rules_changed()
        await self._async_sync_rules()

    @callback
    def _hide_by_buttons(self, hidden: set[str]) -> None:
        """Without the TV app's rules: the hidden apps' buttons disabled."""
        registry = er.async_get(self.hass)
        for package, entry in self._app_buttons().items():
            if package in hidden and not entry.disabled:
                registry.async_update_entity(
                    entry.entity_id, disabled_by=er.RegistryEntryDisabler.USER
                )
            elif package not in hidden and entry.disabled_by is not None:
                registry.async_update_entity(entry.entity_id, disabled_by=None)
        if self.data is not None:
            self.data = replace(self.data, hidden_apps=frozenset(hidden))
            self.async_update_listeners()

    @callback
    def async_watch_app_buttons(self) -> CALLBACK_TYPE:
        """An app button disabled or enabled here hides or shows it in the TV app."""

        @callback
        def updated(event: Event[er.EventEntityRegistryUpdatedData]) -> None:
            data = event.data
            if data["action"] != "update" or "disabled_by" not in data["changes"]:
                return
            entry = er.async_get(self.hass).async_get(data["entity_id"])
            prefix = self.app_button_prefix
            if (
                entry is None
                or entry.config_entry_id != self.config_entry.entry_id
                or entry.domain != "button"
                or not entry.unique_id.startswith(prefix)
                or self.app_rules is None
            ):
                return
            package = entry.unique_id.removeprefix(prefix)
            hidden = self.hidden_apps
            if entry.disabled == (package in hidden):
                # As the app says already (its own change, mirrored)
                return
            self.config_entry.async_create_background_task(
                self.hass,
                self.async_set_app_rules({"hidden_apps": list(hidden ^ {package})}),
                f"{DOMAIN} TV app rules",
            )

        return self.hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, updated)

    @callback
    def _set_bridge_info(self, version: str | None, build: str | None) -> None:
        info = {"version": version, "build": build}
        if version and info != self.bridge_info:
            self.bridge_info = info
            if self.data is not None:
                self.data = replace(
                    self.data, bridge_version=version, bridge_build=build
                )
            self.async_update_listeners()

    @callback
    def async_report_soon(self) -> None:
        """Tell the TV app this integration's version, and whether ADB's in use."""
        self.config_entry.async_create_background_task(
            self.hass, self._async_report(), f"{DOMAIN} report to the TV app"
        )

    async def _async_report(self) -> None:
        if not self.bridge.token:
            return
        version = str((await async_get_integration(self.hass, DOMAIN)).version or "")
        try:
            await self.bridge.async_report(version, adb=not self.app_only)
        except BridgeError as err:
            _LOGGER.debug("Can't report to the TV app: %s", err)

    def _pair_bridge_soon(self, now: datetime) -> None:
        if self._bridge_pairing or (
            self._bridge_retry_at is not None and now < self._bridge_retry_at
        ):
            return
        self._bridge_pairing = True
        self.config_entry.async_create_background_task(
            self.hass,
            self._async_pair_bridge(),
            f"{DOMAIN} TV app pairing",
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
                    _LOGGER.debug("Can't pair with the TV app yet: %s", err)
                    continue
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={**self.config_entry.data, CONF_BRIDGE_TOKEN: token},
                )
                _LOGGER.info("Paired with the TV app on %s", self.client.host)
                self.async_report_soon()
                if self.data is not None:
                    self.data = replace(self.data, bridge_paired=True)
                    self.async_update_listeners()
                return True
            self._bridge_retry_at = dt_util.utcnow() + BRIDGE_PAIRING_BACKOFF
            return False
        finally:
            self._bridge_pairing = False

    async def async_install_bridge(self, url: str) -> None:
        """Install (or update) the TV app, allow it, and pair.

        Not over one from Google Play: it's signed differently (Play updates it).
        """
        if await self._async_bridge_from_play():
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="bridge_from_play"
            )
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(url, timeout=BRIDGE_DOWNLOAD_TIMEOUT) as response:
                response.raise_for_status()
                # All of it (read(n) returns what has arrived so far, not n)
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.content.iter_chunked(64 * 1024):
                    size += len(chunk)
                    if size > BRIDGE_APK_MAX_BYTES:
                        break
                    chunks.append(chunk)
                apk = b"".join(chunks)
                length = response.headers.get("Content-Length", "")
                expected = int(length) if length.isdigit() else None
                if expected is not None and size != expected:
                    raise aiohttp.ClientPayloadError(f"got {size} of {expected} bytes")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="bridge_download_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        if size > BRIDGE_APK_MAX_BYTES or not apk.startswith(b"PK"):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="bridge_download_failed",
                translation_placeholders={"error": "not an APK"},
            )
        await self._async_check_apk(session, url, apk)
        with translate_errors():
            await self.client.async_install_apk(apk)
            # Pop-ups over other apps and its rules' app detection, which TVs
            # often have no settings screen for; kept running; started
            for command in BRIDGE_SETUP_COMMANDS:
                await self.client.async_shell(command)
        self._apps_read_at = None
        self._bridge_retry_at = None
        self.installing = False
        if not self.bridge.token:
            await self._async_pair_bridge(attempts=BRIDGE_PAIRING_ATTEMPTS)
        await self.async_request_refresh()

    async def _async_bridge_from_play(self) -> bool:
        """The installed TV app came from Google Play."""
        if not self.bridge_installed or self.app_only:
            return self.app_only
        try:
            listing = await self.client.async_shell(
                f"pm list packages -i {BRIDGE_PACKAGE}"
            )
        except GoogleTvError:
            return False
        return any(
            line.split()[0] == f"package:{BRIDGE_PACKAGE}"
            and "installer=com.android.vending" in line
            for line in listing.splitlines()
            if line.strip()
        )

    async def _async_check_apk(
        self, session: aiohttp.ClientSession, url: str, apk: bytes
    ) -> None:
        """The APK as published: its SHA-256 (``<url>.sha256``) must match.

        Required for the project's own releases; an APK from another address
        is checked when it has one, else installed as asked.
        """
        try:
            async with session.get(
                f"{url}.sha256", timeout=BRIDGE_DOWNLOAD_TIMEOUT
            ) as response:
                published = (
                    (await response.text()).split()[0].lower()
                    if response.status == 200
                    else None
                )
        except (aiohttp.ClientError, TimeoutError, IndexError):
            published = None
        if published is None:
            if url in (BRIDGE_APK_URL, BRIDGE_DEV_APK_URL) or url.startswith(
                BRIDGE_RELEASES_URL
            ):
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="bridge_download_failed",
                    translation_placeholders={"error": "no SHA-256 to check it"},
                )
            _LOGGER.warning("Installing %s unchecked: it has no SHA-256", url)
            return
        if hashlib.sha256(apk).hexdigest() != published:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="bridge_download_failed",
                translation_placeholders={"error": "its SHA-256 doesn't match"},
            )

    # The TV app's events

    @callback
    def async_start_events(self) -> None:
        """Listen to the TV app's events while the TV is set up."""
        self.config_entry.async_create_background_task(
            self.hass, self._async_events(), f"{DOMAIN} TV app events"
        )

    @callback
    def async_add_event_listener(
        self, listener: Callable[[dict[str, Any]], None]
    ) -> CALLBACK_TYPE:
        """Call ``listener`` with each notification event; returns its removal."""
        self._event_listeners.append(listener)
        return lambda: self._event_listeners.remove(listener)

    async def _async_events(self) -> None:
        """The event stream, kept open: connected again when it ends."""
        retry = EVENTS_RETRY_S
        while True:
            if self.bridge.token and (self.data is None or self.data.reachable):
                try:
                    async for event in self.bridge.async_events():
                        retry = EVENTS_RETRY_S
                        self._async_handle_event(event)
                except BridgeAuthError:
                    self._forget_pairing()
                except BridgeError as err:
                    # An app from before 2.2 has no stream: tried now and then
                    _LOGGER.debug("TV app events: %s", err)
            await asyncio.sleep(retry)
            retry = min(retry * 2, EVENTS_MAX_RETRY_S)

    @callback
    def _async_handle_event(self, event: dict[str, Any]) -> None:
        """An event from the TV: on Home Assistant's bus (googletv_event)."""
        kind = event.get("type")
        if kind == "ping":
            return
        if kind == "rules":
            self._apply_rules(event)
            return
        if kind == "hello":
            self._set_bridge_info(event.get("app_version"), event.get("build"))
            # Connected again: anything changed meanwhile (rules, a new version)
            self.config_entry.async_create_background_task(
                self.hass, self._async_after_bridge_info(event), f"{DOMAIN} TV app"
            )
            # A new run of the app: its live notifications are checked at once
            instance = event.get("instance")
            if self._bridge_instance is None:
                self._bridge_instance = instance
            elif instance != self._bridge_instance:
                self._live_checked_at = None
            return
        if kind in ("notification_action", "notification_dismissed"):
            # Down on the TV: a live one isn't shown again
            if (tag := event.get("tag")) in self._live:
                self._forget_live(tag)
                self._save_live()
            for listener in list(self._event_listeners):
                listener(event)
        elif kind in ("player", "dashboard", "state"):
            self.hass.async_create_task(self.async_request_refresh())
        elif kind == "apps":
            # Installed or uninstalled: the app list is read again now
            self._apps_read_at = None
            self.hass.async_create_task(self.async_request_refresh())
        data = {k: v for k, v in event.items() if k != "time"}
        if device := dr.async_get(self.hass).async_get_device(
            identifiers={
                (DOMAIN, self.config_entry.unique_id or self.config_entry.entry_id)
            }
        ):
            data["device_id"] = device.id
        self.hass.bus.async_fire(EVENT_TYPE, data)

    async def async_install_bridge_quietly(self) -> None:
        """Install the app when the TV is added; a failure is only logged."""
        try:
            await self.async_install_bridge(BRIDGE_APK_URL)
        except HomeAssistantError as err:
            self.installing = False
            self._after_apps_read()
            _LOGGER.warning(
                "Couldn't install the TV app on %s (install it with the "
                "googletv.install_tv_bridge action): %s",
                self.client.host,
                err,
            )

    async def async_notify(
        self, payload: dict[str, Any], until: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Show a notification on the TV; with duration 0, a live one.

        A live notification stays until it's dismissed, or (``until``: an
        ``entity_id`` and maybe a ``state``) until that entity reaches the
        state, or changes from the one it has now. The integration keeps it:
        it's shown again if the app restarts, and survives a restart of Home
        Assistant. The reply has the notification's tag.
        """
        tag: str | None = payload.get("tag")
        if until is not None:
            entity_id = until["entity_id"]
            state = self.hass.states.get(entity_id)
            if state is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="unknown_entity",
                    translation_placeholders={"entity_id": entity_id},
                )
            until = {"entity_id": entity_id, "state": until.get("state")}
            until["from"] = state.state
            tag = tag or f"until:{entity_id}"
            if _until_met(until, state):
                # Over before it began (the door's already closed)
                if tag in self._live:
                    await self.async_dismiss(tag)
                return {
                    "popup": False,
                    "panel": False,
                    "reason": "until_met",
                    "tag": tag,
                }
            # Up until the entity changes, whatever the duration
            payload = {**payload, "duration": 0}
        if payload.get("duration") == 0:
            tag = tag or f"live-{uuid4().hex[:12]}"
        if payload.get("actions"):
            # Its buttons' events name it
            tag = tag or f"actions-{uuid4().hex[:12]}"
        if tag:
            payload = {**payload, "tag": tag}
        reply = await self._async_send(payload)
        if tag:
            self._forget_live(tag)
            if payload.get("duration") == 0:
                self._live[tag] = {"payload": payload, "until": until}
                self._watch_live(tag, until)
            self._save_live()
        reply.pop("instance", None)
        return {**reply, "tag": tag}

    async def _async_send(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a notification, telling the app what's on screen."""
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
            reply = await self.bridge.async_notify(self._signed(payload))
        except BridgeAuthError as err:
            self._forget_pairing()
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="bridge_not_paired"
            ) from err
        except BridgeError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        # The app's run, learned once: after that it changes only when the
        # live notifications have been shown again (_async_check_live)
        if self._bridge_instance is None:
            self._bridge_instance = reply.get("instance")
        return reply

    def _signed(self, payload: dict[str, Any]) -> dict[str, Any]:
        """The payload with its Home Assistant URLs signed, for the TV to load.

        The TV fetches images, clips and icons with no sign-in, so a path
        that needs one (/media/local/…, a UniFi Protect clip) is signed, for
        a while, as Home Assistant's read-only content user. Only the copy
        sent is: a live notification keeps its URLs as given, and is signed
        afresh each time it's shown again.
        """
        bases = set()
        for external in (False, True):
            with contextlib.suppress(NoURLAvailableError):
                bases.add(
                    get_url(
                        self.hass,
                        allow_internal=not external,
                        allow_external=external,
                    ).rstrip("/")
                )
        signed = dict(payload)
        for key in ("image_url", "video_url", "icon"):
            url = payload.get(key)
            if not isinstance(url, str):
                continue
            base = next((b for b in bases if url.startswith(f"{b}/")), None)
            if base is None:
                continue
            path = url.removeprefix(base)
            query = URL(path).query
            if (
                SIGNED_QUERY in query
                or "token" in query
                or path.startswith(SELF_SIGNED_PATHS)
            ):
                # Signed already: by a token (the camera proxy), or in its path
                continue
            signed[key] = base + async_sign_path(
                self.hass, path, SIGNED_URL_LIFETIME, use_content_user=True
            )
        return signed

    async def async_dismiss(self, tag: str | None = None) -> None:
        """Take a notification (by tag), or all of them, off the TV."""
        if not self.bridge.token:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="bridge_not_paired"
            )
        tags = [tag] if tag else list(self._live)
        for live in tags:
            self._forget_live(live)
        self._save_live()
        try:
            await self.bridge.async_dismiss(tag)
        except BridgeError as err:
            # Taken down once the app answers again
            self._dismiss_pending.update(tags)
            self._save_live()
            if isinstance(err, BridgeAuthError):
                self._forget_pairing()
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="bridge_not_paired"
                ) from err
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def async_load_live(self) -> None:
        """The live notifications from before a restart, watched again.

        One whose ``until`` came true meanwhile is taken down; one whose entity
        isn't there yet (its integration still starting) is just watched.
        """
        stored = await self._live_store.async_load() or {}
        self._bridge_instance = stored.get("instance")
        self._live = stored.get("live", {})
        self._dismiss_pending = set(stored.get("dismiss", []))
        for tag, live in list(self._live.items()):
            until = live.get("until")
            state = self.hass.states.get(until["entity_id"]) if until else None
            if until and state is not None and _until_met(until, state):
                self._forget_live(tag)
                self._dismiss_pending.add(tag)
            else:
                self._watch_live(tag, until)

    async def async_stop_live(self) -> None:
        """Stop watching (unloading), saved at once; the TV keeps showing them."""
        for unsub in self._live_unsubs.values():
            unsub()
        self._live_unsubs.clear()
        # In place of the delayed save, so setting up again reads it
        await self._live_store.async_save(self._live_data())

    def _watch_live(self, tag: str, until: dict[str, Any] | None) -> None:
        if not until:
            return

        @callback
        def changed(event: Event[EventStateChangedData]) -> None:
            if _until_met(until, event.data["new_state"]):
                self._forget_live(tag)
                self._dismiss_pending.add(tag)
                self._save_live()
                self.config_entry.async_create_background_task(
                    self.hass,
                    self._async_dismiss_pending(),
                    f"{DOMAIN} live notification {tag} done",
                )

        self._live_unsubs[tag] = async_track_state_change_event(
            self.hass, [until["entity_id"]], changed
        )

    def _forget_live(self, tag: str) -> None:
        self._live.pop(tag, None)
        self._dismiss_pending.discard(tag)
        if unsub := self._live_unsubs.pop(tag, None):
            unsub()

    def _live_data(self) -> dict[str, Any]:
        return {
            "instance": self._bridge_instance,
            "live": self._live,
            "dismiss": sorted(self._dismiss_pending),
        }

    def _save_live(self) -> None:
        self._live_store.async_delay_save(self._live_data, 1)

    async def _async_dismiss_pending(self) -> None:
        """Take down what's done; what fails stays pending, tried again later."""
        for tag in list(self._dismiss_pending):
            try:
                await self.bridge.async_dismiss(tag)
            except BridgeError as err:
                if isinstance(err, BridgeAuthError):
                    self._forget_pairing()
                _LOGGER.debug("Can't take %s down yet: %s", tag, err)
                return
            self._dismiss_pending.discard(tag)
        self._save_live()

    def _check_live_soon(self, now: datetime) -> None:
        if (
            not (self._live or self._dismiss_pending)
            or self._live_checking
            or (
                self._live_checked_at is not None
                and now - self._live_checked_at < LIVE_CHECK_INTERVAL
            )
        ):
            return
        self._live_checking = True
        self._live_checked_at = now
        self.config_entry.async_create_background_task(
            self.hass, self._async_check_live(), f"{DOMAIN} live notifications"
        )

    async def _async_check_live(self) -> None:
        """Dismiss what's pending; show the live ones again if the app restarted."""
        try:
            if self._dismiss_pending:
                await self._async_dismiss_pending()
            if not self._live:
                return
            try:
                instance = (await self.bridge.async_state()).get("instance")
            except BridgeError as err:
                if isinstance(err, BridgeAuthError):
                    self._forget_pairing()
                _LOGGER.debug("Can't check the live notifications: %s", err)
                return
            if not instance or instance == self._bridge_instance:
                return
            if self._bridge_instance is None:
                # The first run seen: nothing was shown on another
                self._bridge_instance = instance
                self._save_live()
                return
            _LOGGER.debug("The TV app restarted: showing live notifications")
            for tag, live in list(self._live.items()):
                try:
                    await self._async_send(live["payload"])
                except HomeAssistantError as err:
                    _LOGGER.debug("Can't show %s again: %s", tag, err)
                    return
            self._bridge_instance = instance
            self._save_live()
        finally:
            self._live_checking = False

    async def async_play(self, payload: dict[str, Any]) -> None:
        """Play media through the app: full screen, or announced over what's on."""
        await self._async_bridge_call(self.bridge.async_play(payload))

    async def async_stop_media(self) -> None:
        """Close the app's player and dashboard."""
        await self._async_bridge_call(self.bridge.async_stop())

    async def async_show_dashboard(self, url: str) -> None:
        """Show a dashboard on the TV, signed in as the TV's own user."""
        token = await self._async_dashboard_token()
        await self._async_bridge_call(self.bridge.async_dashboard(url, token))

    async def _async_dashboard_token(self) -> str:
        """An access token for the TV's own user, made (once) when first needed.

        The user is local only and named after the TV: it's in Settings →
        People → Users, where it can be removed. It's read-only (dashboards
        show, but don't control) unless the TV's options let them control.
        Its long-lived token is made again if it's revoked.
        """
        async with self._dashboard_lock:
            return await self._async_dashboard_token_locked()

    async def _async_dashboard_token_locked(self) -> str:
        auth = self.hass.auth
        data = self.config_entry.data
        user = None
        if user_id := data.get(CONF_DASHBOARD_USER):
            user = await auth.async_get_user(user_id)
        group = (
            GROUP_ID_USER
            if self.config_entry.options.get(CONF_DASHBOARD_CONTROLS, False)
            else GROUP_ID_READ_ONLY
        )
        if user is None:
            # Home Assistant's first user is its owner: never the TV's
            if await auth.async_get_owner() is None:
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="no_owner"
                )
            user = await auth.async_create_user(
                f"{self.config_entry.title} (TV)",
                group_ids=[group],
                local_only=True,
            )
        elif [g.id for g in user.groups] != [group]:
            await auth.async_update_user(user, group_ids=[group])
        refresh = None
        if token_id := data.get(CONF_DASHBOARD_TOKEN):
            refresh = auth.async_get_refresh_token(token_id)
        if refresh is None or refresh.user.id != user.id:
            refresh = await auth.async_create_refresh_token(
                user,
                client_name=f"Raineworks TV: {self.config_entry.title}",
                token_type=TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN,
                access_token_expiration=DASHBOARD_TOKEN_LIFETIME,
            )
        if (data.get(CONF_DASHBOARD_USER), data.get(CONF_DASHBOARD_TOKEN)) != (
            user.id,
            refresh.id,
        ):
            # The entry as it is now: a pairing may have saved its token meanwhile
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    **self.config_entry.data,
                    CONF_DASHBOARD_USER: user.id,
                    CONF_DASHBOARD_TOKEN: refresh.id,
                },
            )
        return auth.async_create_access_token(refresh)

    async def _async_bridge_call[T](self, call: Coroutine[Any, Any, T]) -> T:
        """A call to the app, its errors as Home Assistant's."""
        if not self.bridge.token:
            call.close()
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="bridge_not_paired"
            )
        try:
            return await call
        except BridgeAuthError as err:
            self._forget_pairing()
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="bridge_not_paired"
            ) from err
        except BridgeError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    def _forget_pairing(self) -> None:
        """The app forgot the pairing (reinstalled, data cleared): pair again soon."""
        self.bridge.token = None
        self._bridge_retry_at = None

    async def async_bridge_rules(self, changes: dict[str, Any]) -> dict[str, Any]:
        """Change the app's notification rules."""
        return await self._async_bridge_call(self.bridge.async_rules(changes))

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
            hidden_apps=frozenset(self.hidden_apps),
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
        if self.app_only and self.data is not None and not self.data.reachable:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="needs_adb",
                translation_placeholders={"error": "Turning the TV on"},
            )
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


def _until_met(until: dict[str, Any], state: State | None) -> bool:
    """A live notification's end: its entity at the state, or changed."""
    if state is None:
        # Removed: its integration reloading, most likely; not an end
        return False
    if until.get("state") is not None:
        return state.state == until["state"]
    # Any change but a blip (unavailable, unknown) ends it
    return state.state not in (until["from"], STATE_UNAVAILABLE, STATE_UNKNOWN)


def _older(version: str | None, than: str) -> bool:
    """Whether a version (``2.3.0``) is older than another; unknown ones aren't."""

    def parts(v: str) -> tuple[int, ...] | None:
        try:
            return tuple(int(p) for p in v.split("."))
        except ValueError:
            return None

    mine, other = parts(version or ""), parts(than)
    return mine is not None and other is not None and mine < other

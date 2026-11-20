"""Data update coordinator for a Google TV."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
import contextlib
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .adb import GoogleTvClient, GoogleTvError
from .const import APPS_INTERVAL, DOMAIN, SCAN_INTERVAL
from .online import Lookups
from .parsers import MUSIC_APPS, App, TvState

_LOGGER = logging.getLogger(__name__)

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
        self._launcher_apps: list[App] = []
        self._apps_read_at: datetime | None = None
        self._artwork_for: tuple[str, str, str | None] | None = None

    async def _async_update_data(self) -> GoogleTvData:
        """Read the TV, and its apps when they're due."""
        try:
            state = await self.client.async_get_state()
            now = dt_util.utcnow()
            if self._apps_read_at is None or now - self._apps_read_at >= APPS_INTERVAL:
                first = self._apps_read_at is None
                self._launcher_apps = await self.client.async_get_apps()
                self._apps_read_at = now
                if first:
                    # Named before their buttons are made, which fixes their ids
                    await self._async_first_listings()
                else:
                    self._look_up_listings()
        except GoogleTvError as err:
            raise UpdateFailed(f"Can't read the TV: {err}") from err
        return GoogleTvData(
            state=state, apps=self._named_apps(), artwork=self._artwork(state)
        )

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
        if found is None and key != self._artwork_for:
            self._artwork_for = key
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

"""Online lookups, shared by every TV: apps' Play Store listings and artwork.

App listings are kept in Home Assistant's storage (``.storage/googletv.apps``)
and read again after ``LISTING_MAX_AGE``, so each app's page is fetched about
once a month however many TVs have it. Artwork is kept in memory by title.
A lookup that fails (no network, a refusal) is tried again later; it never
fails a TV's poll.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import timedelta
import logging
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .lookups import (
    NO_ARTWORK_APPS,
    WIKIPEDIA_API,
    StoreListing,
    film_search_params,
    movie_search_url,
    parse_store_page,
    pick_film_poster,
    pick_movie_poster,
    pick_show_image,
    pick_song_artwork,
    show_search_url,
    song_search_url,
    store_url,
)

_LOGGER = logging.getLogger(__name__)

LISTING_MAX_AGE = timedelta(days=30)
# A failed listing fetch waits this long before it's tried again
LISTING_RETRY = timedelta(hours=6)
ARTWORK_CACHE_SIZE = 256
TIMEOUT = aiohttp.ClientTimeout(total=10)
# Wikipedia asks API clients to name themselves and a way to reach them
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; HomeAssistant-googletv;"
        " +https://github.com/raine-works/ha-googletv)"
    )
}
_LOOKUPS_KEY = "lookups"


def get_lookups(hass: HomeAssistant) -> Lookups:
    """The one ``Lookups`` for every TV."""
    data = hass.data.setdefault(DOMAIN, {})
    if _LOOKUPS_KEY not in data:
        data[_LOOKUPS_KEY] = Lookups(hass)
    return data[_LOOKUPS_KEY]


class Lookups:
    """Apps' names and icons, and artwork for what's playing."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Set up (``async_load`` reads the stored listings)."""
        self._hass = hass
        self._store: Store[dict[str, dict[str, Any]]] = Store(hass, 1, f"{DOMAIN}.apps")
        self._listings: dict[str, dict[str, Any]] = {}
        self._failed: dict[str, Any] = {}
        self._loaded = False
        self._load_lock = asyncio.Lock()
        self._fetching: set[str] = set()
        self._limit = asyncio.Semaphore(4)
        self._artwork: OrderedDict[tuple[str, str, str], str | None] = OrderedDict()

    async def async_load(self) -> None:
        """Read the stored listings, once."""
        async with self._load_lock:
            if not self._loaded:
                self._listings = await self._store.async_load() or {}
                self._loaded = True

    def listing(self, package: str) -> StoreListing | None:
        """An app's stored listing, if it has one."""
        stored = self._listings.get(package)
        if not stored:
            return None
        return StoreListing(stored.get("name"), stored.get("icon"))

    def needs_listing(self, package: str) -> bool:
        """Never read, or read long enough ago, and not failing just now."""
        now = dt_util.utcnow()
        failed = self._failed.get(package)
        if failed and now - failed < LISTING_RETRY:
            return False
        stored = self._listings.get(package)
        if not stored:
            return True
        read_at = dt_util.parse_datetime(stored.get("read_at", ""))
        return read_at is None or now - read_at > LISTING_MAX_AGE

    async def async_fetch_listings(self, packages: list[str]) -> bool:
        """Read these apps' listings; whether any changed."""
        wanted = [p for p in packages if p not in self._fetching]
        self._fetching.update(wanted)
        try:
            results = await asyncio.gather(*(self._fetch_listing(p) for p in wanted))
        finally:
            self._fetching.difference_update(wanted)
        if any(results):
            self._store.async_delay_save(lambda: self._listings, 10)
        return any(results)

    async def _fetch_listing(self, package: str) -> bool:
        session = async_get_clientsession(self._hass)
        async with self._limit:
            try:
                async with session.get(
                    store_url(package), headers=HEADERS, timeout=TIMEOUT
                ) as response:
                    if response.status == 404:
                        # Not on the Play Store (a TV maker's own app)
                        listing = StoreListing(None, None)
                    else:
                        response.raise_for_status()
                        listing = parse_store_page(await response.text())
            except (aiohttp.ClientError, TimeoutError) as err:
                _LOGGER.debug("Can't read %s's Play Store listing: %s", package, err)
                self._failed[package] = dt_util.utcnow()
                return False
        self._failed.pop(package, None)
        old = self._listings.get(package) or {}
        self._listings[package] = {
            "name": listing.name,
            "icon": listing.icon,
            "read_at": dt_util.utcnow().isoformat(),
        }
        return (old.get("name"), old.get("icon")) != (listing.name, listing.icon)

    def artwork(self, package: str, title: str, subtitle: str | None) -> str | None:
        """Artwork already found for this, without looking it up."""
        return self._artwork.get((package, title, subtitle or ""))

    async def async_artwork(
        self, package: str, title: str, subtitle: str | None, music: bool
    ) -> str | None:
        """A song's cover, or a show's or film's poster, once per title.

        A title without a subtitle is likely a film (Disney+ reports "Cars"
        alone), so films are tried first; with one (YouTube TV's channel, an
        episode), shows are.
        """
        key = (package, title, subtitle or "")
        if key in self._artwork:
            self._artwork.move_to_end(key)
            return self._artwork[key]
        if package in NO_ARTWORK_APPS:
            return None
        try:
            if music:
                reply = await self._get_json(song_search_url(title, subtitle))
                art = pick_song_artwork(reply, title, subtitle) if reply else None
            else:
                lookups = [self._show_poster, self._film_poster]
                if not subtitle:
                    lookups.reverse()
                art = None
                for lookup in lookups:
                    if art := await lookup(title):
                        break
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            # Not kept: tried again when this plays next
            _LOGGER.debug("Can't look up artwork for %s: %s", title, err)
            return None
        self._artwork[key] = art
        while len(self._artwork) > ARTWORK_CACHE_SIZE:
            self._artwork.popitem(last=False)
        return art

    def has_artwork(self, package: str, title: str, subtitle: str | None) -> bool:
        """Whether this was looked up (found or not), so a failure shows."""
        return (package, title, subtitle or "") in self._artwork

    async def _show_poster(self, title: str) -> str | None:
        reply = await self._get_json(show_search_url(title))
        return pick_show_image(reply, title) if reply else None

    async def _film_poster(self, title: str) -> str | None:
        """Google Play's poster, full size; else Wikipedia's small one."""
        session = async_get_clientsession(self._hass)
        async with session.get(
            # Home Assistant's own country picks the store (Settings → System)
            movie_search_url(title, self._hass.config.country),
            headers=HEADERS,
            timeout=TIMEOUT,
        ) as response:
            response.raise_for_status()
            if poster := pick_movie_poster(await response.text(), title):
                return poster
        reply = await self._get_json(WIKIPEDIA_API, film_search_params(title))
        return pick_film_poster(reply, title) if reply else None

    async def _get_json(self, url: str, params: dict[str, str] | None = None) -> Any:
        session = async_get_clientsession(self._hass)
        async with session.get(
            url, params=params, headers=HEADERS, timeout=TIMEOUT
        ) as response:
            response.raise_for_status()
            # iTunes answers text/javascript
            return await response.json(content_type=None)

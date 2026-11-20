"""What the integration looks up online, as pure functions on the replies.

* An app's name and icon: its Google Play listing (``og:title`` and
  ``og:image``), since the TV itself only gives a package and a resource id.
* Artwork for what's playing: a song's cover from the iTunes Search API, a
  show's poster from TVmaze, a film's poster from Wikipedia (its articles
  with a film infobox). None needs a key. A match must have the same name
  (and, for a song, the same artist), so a stray result never shows.

Imports nothing from Home Assistant, so the tests load it on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
import html
import re
from typing import Any
from urllib.parse import quote

ICON_SIZE = 256
ARTWORK_SIZE = 600

# Apps whose titles aren't shows or songs (YouTube's are video titles)
NO_ARTWORK_APPS = frozenset({"com.google.android.youtube.tv"})


@dataclass(frozen=True)
class StoreListing:
    """An app's Play Store name and icon."""

    name: str | None
    icon: str | None


def store_url(package: str) -> str:
    """An app's Play Store page, in English."""
    return f"https://play.google.com/store/apps/details?id={quote(package)}&hl=en"


def _meta(page: str, prop: str) -> str | None:
    match = re.search(
        rf'<meta\s+property="og:{prop}"\s+content="([^"]*)"', page, re.IGNORECASE
    )
    return html.unescape(match.group(1)).strip() if match else None


def parse_store_page(page: str) -> StoreListing:
    """The name ("YouTube TV", not its tagline) and icon from a listing page."""
    name = _meta(page, "title")
    if name:
        name = re.sub(r"\s+-\s+Apps on Google Play$", "", name)
        # "YouTube TV: Live TV & more", "Plex - Stream Movies & TV": the name
        name = re.split(r":\s|\s[-–|]\s", name, maxsplit=1)[0].strip() or None
    icon = _meta(page, "image")
    if icon and "googleusercontent.com" in icon:
        # Google's image server sizes by suffix: "=s0-br30" is the original
        icon = re.sub(r"=[^/=]*$", "", icon) + f"=s{ICON_SIZE}"
    return StoreListing(name, icon or None)


def _norm(text: str | None) -> str:
    return re.sub(r"[^0-9a-z]+", "", (text or "").casefold())


def song_search_url(title: str, artist: str | None) -> str:
    """The iTunes Search API's song search for a title and artist."""
    term = quote(f"{artist or ''} {title}".strip())
    return f"https://itunes.apple.com/search?term={term}&entity=song&limit=10"


def pick_song_artwork(
    reply: dict[str, Any], title: str, artist: str | None
) -> str | None:
    """The cover of the song with this title (and artist, when given)."""
    want_title, want_artist = _norm(title), _norm(artist)
    for result in reply.get("results") or []:
        if _norm(result.get("trackName")) != want_title:
            continue
        found = _norm(result.get("artistName"))
        if want_artist and want_artist not in found and found not in want_artist:
            continue
        art = result.get("artworkUrl100")
        if isinstance(art, str) and art:
            size = f"{ARTWORK_SIZE}x{ARTWORK_SIZE}bb"
            return re.sub(r"\d+x\d+bb", size, art)
    return None


def show_search_url(name: str) -> str:
    """TVmaze's show search."""
    return f"https://api.tvmaze.com/search/shows?q={quote(name)}"


def pick_show_image(reply: list[dict[str, Any]], name: str) -> str | None:
    """The poster of the show with exactly this name (the best-scored one)."""
    want = _norm(name)
    for result in reply if isinstance(reply, list) else []:
        show = result.get("show") or {}
        if _norm(show.get("name")) != want:
            continue
        image = show.get("image") or {}
        art = image.get("original") or image.get("medium")
        if isinstance(art, str) and art:
            return art
    return None


WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
_IMAGE = re.compile(r"\.(jpe?g|png|webp|gif)$", re.IGNORECASE)


def film_search_params(title: str) -> dict[str, str]:
    """Wikipedia's search for films with this title, with their posters."""
    return {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "generator": "search",
        "gsrsearch": f'intitle:"{title}" hastemplate:"Infobox film"',
        "gsrlimit": "10",
        "prop": "pageimages",
        "piprop": "original",
        # Posters are non-free images; the default leaves them out
        "pilicense": "any",
    }


def pick_film_poster(reply: dict[str, Any], title: str) -> str | None:
    """The poster of the most relevant film with exactly this title.

    "Cars (film)" is Cars, "Moana (2016 film)" Moana; "Cars 2" isn't Cars.
    """
    want = _norm(title)
    pages = (reply.get("query") or {}).get("pages") or []
    for page in sorted(pages, key=lambda p: p.get("index", 0)):
        name = re.sub(r"\s*\([^)]*\)$", "", page.get("title") or "")
        if _norm(name) != want:
            continue
        source = ((page.get("original") or {}).get("source") or "").split("?")[0]
        if _IMAGE.search(source):
            return source
    return None

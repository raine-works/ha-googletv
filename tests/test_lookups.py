"""The online lookups' parsing, on replies saved from the real services."""

from __future__ import annotations

import json
import pathlib

from googletv_lookups import (
    StoreListing,
    parse_store_page,
    pick_show_image,
    pick_song_artwork,
    show_search_url,
    song_search_url,
    store_url,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def test_store_listings() -> None:
    netflix = parse_store_page((FIXTURES / "store_netflix.html").read_text())
    assert netflix == StoreListing(
        "Netflix",
        "https://play-lh.googleusercontent.com/ndMigyoaH5k4aZ5GyIHj5ZNXEJQ_YTkcCByrX"
        "-m-IZE1xGJYfQZ9Hr3u1rFDK3EByo4VcDtBohg0Aqp3d3SW0Jo=s256",
    )
    # "YouTube TV: Live TV &amp; more - Apps on Google Play": just the name
    youtube = parse_store_page((FIXTURES / "store_youtube_tv.html").read_text())
    assert youtube.name == "YouTube TV"
    assert youtube.icon and youtube.icon.endswith("=s256")
    assert parse_store_page("<html></html>") == StoreListing(None, None)
    assert (
        parse_store_page(
            '<meta property="og:title" content="Plex - Stream Movies &amp; TV'
            ' - Apps on Google Play">'
        ).name
        == "Plex"
    )


def test_a_songs_cover() -> None:
    reply = json.loads((FIXTURES / "itunes_broom.json").read_text())
    # iTunes credits "J Scott Rakozy & Hogwarts Legacy"; Spotify the first
    art = pick_song_artwork(reply, "Everybody Grab a Broom", "J Scott Rakozy")
    assert art == (
        "https://is1-ssl.mzstatic.com/image/thumb/Music113/v4/77/c0/d3/"
        "77c0d36b-2a78-8122-90a4-03315f2e1ca4/794043213519.jpg/600x600bb.jpg"
    )
    # Another artist's song of the same name, or another title: nothing
    assert pick_song_artwork(reply, "Everybody Grab a Broom", "Someone Else") is None
    assert pick_song_artwork(reply, "Another Song", "J Scott Rakozy") is None
    assert pick_song_artwork({}, "Anything", None) is None


def test_a_shows_poster() -> None:
    reply = json.loads((FIXTURES / "tvmaze_rick_and_morty.json").read_text())
    assert pick_show_image(reply, "Rick and Morty") == (
        "https://static.tvmaze.com/uploads/images/original_untouched/626/1566363.jpg"
    )
    # Only that name: "Rick and Morty Specials" has no poster, and isn't it
    assert pick_show_image(reply, "Rick and Morty Specials") is None
    assert pick_show_image(reply, "Adult Swim") is None
    assert pick_show_image({"not": "a list"}, "Rick and Morty") is None  # type: ignore[arg-type]


def test_urls() -> None:
    assert store_url("com.netflix.ninja") == (
        "https://play.google.com/store/apps/details?id=com.netflix.ninja&hl=en"
    )
    assert show_search_url("Rick and Morty") == (
        "https://api.tvmaze.com/search/shows?q=Rick%20and%20Morty"
    )
    assert song_search_url("3 Nights", "Dominic Fike") == (
        "https://itunes.apple.com/search?term=Dominic%20Fike%203%20Nights"
        "&entity=song&limit=10"
    )

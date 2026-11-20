# Google TV for Home Assistant

An **unofficial** [Home Assistant](https://www.home-assistant.io/) integration for
Google TV and Android TV, from [raine-works](https://github.com/raine-works): power,
apps, HDMI inputs, volume, what's playing and a remote, all over one local
connection (ADB network debugging). No Android TV Remote, Google Cast or ADB
integrations to combine, and no helpers to make.

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![License](https://img.shields.io/badge/License-MIT-lightgrey.svg?style=for-the-badge)](LICENSE)

[![Test](https://github.com/raine-works/ha-googletv/actions/workflows/test.yaml/badge.svg)](https://github.com/raine-works/ha-googletv/actions/workflows/test.yaml)
[![Validate](https://github.com/raine-works/ha-googletv/actions/workflows/validate.yaml/badge.svg)](https://github.com/raine-works/ha-googletv/actions/workflows/validate.yaml)

<a href="https://buymeacoffee.com/raineworks"><img src="https://img.shields.io/badge/Buy%20Me%20a%20Coffee-FFDD00?style=for-the-badge&logo=buymeacoffee&logoColor=black" alt="Buy Me a Coffee" /></a>

> This project is not affiliated with, authorized, or endorsed by Google. Google
> TV and Android TV are trademarks of Google LLC.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=raine-works&repository=ha-googletv&category=integration)

## What you get

Each TV is one device with:

**Media player** (`media_player.<tv>`, device class TV)

| | |
| :--- | :--- |
| State | `off` (asleep), `playing` / `paused` (what the front app reports), else `on` |
| Sources | Every app in the TV's launcher, then its HDMI inputs, by the names given to them on the TV ("Xbox"; "HDMI 2" when unnamed). `source` is the input on screen, else the app in front. A device on HDMI-CEC's own input counts as its port's input. |
| Now playing | Title, artist or show, position, from the TV's media sessions (Netflix, YouTube TV, Spotify, Plex…), with no Cast needed |
| Artwork | A song's cover (iTunes) or a show's poster (TVmaze), else the app's icon |
| Volume | The TV's media volume as a level (set, step, mute) |
| Controls | Turn on / off, play, pause, stop, next, previous, select source |
| `play_media` | `media_content_type: app` with a package (`com.netflix.ninja`), `input` with an input id, or `url` with a link the TV opens |
| Attributes | `app_id`, `app_name`, `apps` (package, name and icon), `inputs` (id, port, name), `input`, `media_app` |

**Input** (`select.<tv>_input`): the HDMI inputs by their names on the TV,
showing the one on screen; pick one to switch to it (the TV wakes first).

**A button per app** (`button.<tv>_netflix`, …): named and pictured from the
app's Google Play listing; press to open it (the TV wakes first). An app
installed later gets its button on its own; an uninstalled one goes
unavailable.

**Remote** (`remote.<tv>`): `remote.send_command` with any key: `HOME`, `BACK`,
`DPAD_UP` / `DOWN` / `LEFT` / `RIGHT` / `CENTER`, `VOLUME_UP`, `MEDIA_PLAY_PAUSE`,
`SETTINGS`, … or an Android key code number. `num_repeats` and `delay_secs` work.

Apps open by their launch screen (`am start`), not by a Play Store link, so
apps that Android TV Remote can no longer launch (YouTube TV, Apple TV, HBO Max,
Hulu since the Play Store's 2026 update) open here.

The TV is read every 5 seconds with a single shell command; its app list every
10 minutes.

### Online lookups

The TV gives only an app's package, and only the title and artist of what's
playing, so the integration looks the rest up:

* **App names and icons** from each app's Google Play listing, kept in
  `.storage/googletv.apps` and read again monthly. An app that isn't on Google
  Play (a TV maker's own) keeps its package as its name.
* **Artwork**: a song's cover from the iTunes Search API, matched by title and
  artist; a show's poster from TVmaze, matched by its exact name (YouTube TV
  reports the show). Movies and YouTube videos show the app's icon.

None of them needs an account or a key. To keep everything on your network,
turn off **Look up app icons and artwork online** in the TV's options
(Settings → Devices & services → Google TV → Configure).

## Setting up a TV

1. **Turn on developer options.** Settings → System → About → tap **Android TV
   OS build** seven times.
2. **Turn on debugging.** Settings → System → Developer options: **USB
   debugging** on, and **Network debugging** (or Wireless debugging) where it's
   a separate switch. Some TVs (TCL) only offer it while the TV has a wired or
   Wi-Fi connection, and some (Sony) call it **ADB debugging**.
3. **Optionally give the TV a fixed address** in your router (a DHCP
   reservation). A discovered TV that moves is followed anyway.
4. **Add the TV.** Home Assistant finds Google TVs on your network by
   themselves: one with network debugging on shows up under Settings →
   Devices & services → **Discovered**. Choose **Add**, then **Submit**. (Or
   add it by hand: Add integration → **Google TV**, with the TV's address and
   port 5555.)
5. **Accept the prompt on the TV.** "Allow USB debugging?" appears with Home
   Assistant's key: tick **Always allow from this computer** and choose
   **Allow**. The setup waits up to a minute for it.

If the TV forgets the key (debugging turned off and on, a factory reset), Home
Assistant asks you to reconnect it: open the repair, be at the TV, and accept
the prompt again.

Home Assistant keeps one key for every TV, in `.storage/googletv_adbkey`.

### Discovery

Every Google TV announces itself over mDNS (`_androidtvremote2._tcp`, the
service its phone remote uses) with its name and Bluetooth address. Home
Assistant offers a TV only when its ADB port (5555) answers, so turning on
network debugging is what makes it appear. Each TV is known by its Bluetooth
address (read over ADB too, else its serial number), so a TV already added is
never offered again, and if it gets a new IP address its entry follows it.

## Notes

* Only one ADB client can hold a TV's connection comfortably. Remove the TV
  from Home Assistant's own **Android Debug Bridge** integration (or anything
  else using ADB on it) before adding it here.
* Inputs are read from Android's TV input service. Seen on TCL (Google TV) and
  Sony (Android TV) sets; a TV whose maker doesn't use it shows no inputs.
* Apps are named from a table of well-known apps, else by their package.
  Reading names and icons from the apps themselves is planned.

## Development

```bash
pip install -r requirements-test.txt     # parser tests and ruff
pytest -q
pip install -r requirements-test-ha.txt  # with Home Assistant: config flow and setup
pytest -q
```

The parsers (`custom_components/googletv/parsers.py`) are tested on output
captured from real TVs (`tests/test_parsers.py`).

## ☕ Support

If you find this project helpful, consider buying me a coffee to support continued
maintenance and development:

<a href="https://buymeacoffee.com/raineworks"><img src="https://img.shields.io/badge/Buy%20Me%20a%20Coffee-FFDD00?style=for-the-badge&logo=buymeacoffee&logoColor=black" alt="Buy Me a Coffee" /></a>

## License

MIT

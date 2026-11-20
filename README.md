# Google TV for Home Assistant

One integration for a Google TV or Android TV: power, apps, HDMI inputs, volume,
what's playing and a remote, all over one local connection (ADB network
debugging). No Android TV Remote, Google Cast or ADB integrations to combine,
and no helpers to make.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=raine-works&repository=ha-googletv&category=integration)

## What you get

Each TV is one device with two entities:

**Media player** (`media_player.<tv>`, device class TV)

| | |
| :--- | :--- |
| State | `off` (asleep), `playing` / `paused` (what the front app reports), else `on` |
| Sources | Every app in the TV's launcher, then its HDMI inputs, by the names given to them on the TV ("Xbox"; "HDMI 2" when unnamed). `source` is the input on screen, else the app in front. A device on HDMI-CEC's own input counts as its port's input. |
| Now playing | Title, artist or show, position, from the TV's media sessions (Netflix, YouTube, Spotify, Plex…), with no Cast needed |
| Volume | The TV's media volume as a level (set, step, mute) |
| Controls | Turn on / off, play, pause, stop, next, previous, select source |
| `play_media` | `media_content_type: app` with a package (`com.netflix.ninja`), `input` with an input id, or `url` with a link the TV opens |
| Attributes | `app_id`, `app_name`, `apps` (package and name), `inputs` (id, port, name), `input`, `media_app` |

**Remote** (`remote.<tv>`): `remote.send_command` with any key: `HOME`, `BACK`,
`DPAD_UP` / `DOWN` / `LEFT` / `RIGHT` / `CENTER`, `VOLUME_UP`, `MEDIA_PLAY_PAUSE`,
`SETTINGS`, … or an Android key code number. `num_repeats` and `delay_secs` work.

Apps open by their launch screen (`am start`), not by a Play Store link, so
apps that Android TV Remote can no longer launch (YouTube TV, Apple TV, HBO Max,
Hulu since the Play Store's 2026 update) open here.

The TV is read every 5 seconds with a single shell command; its app list every
10 minutes.

## Setting up a TV

1. **Turn on developer options.** Settings → System → About → tap **Android TV
   OS build** seven times.
2. **Turn on debugging.** Settings → System → Developer options: **USB
   debugging** on, and **Network debugging** (or Wireless debugging) where it's
   a separate switch. Some TVs (TCL) only offer it while the TV has a wired or
   Wi-Fi connection, and some (Sony) call it **ADB debugging**.
3. **Give the TV a fixed address** in your router (a DHCP reservation).
4. **Add the integration** in Home Assistant: Settings → Devices & services →
   Add integration → **Google TV**, with the TV's address (port 5555).
5. **Accept the prompt on the TV.** "Allow USB debugging?" appears with Home
   Assistant's key: tick **Always allow from this computer** and choose
   **Allow**. The setup waits up to a minute for it.

If the TV forgets the key (debugging turned off and on, a factory reset), Home
Assistant asks you to reconnect it: open the repair, be at the TV, and accept
the prompt again.

Home Assistant keeps one key for every TV, in `.storage/googletv_adbkey`.

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

## License

MIT

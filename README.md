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

Each TV is a device with:

**Media player** (`media_player.<tv>`, device class TV)

| | |
| :--- | :--- |
| State | `off` (asleep), `playing` / `paused` (what the front app reports), else `on` |
| Sources | Every app in the TV's launcher, then its HDMI inputs, by the names given to them on the TV ("Xbox"; "HDMI 2" when unnamed). `source` is the input on screen, else the app in front. A device on HDMI-CEC's own input counts as its port's input. |
| Now playing | Title, artist or show, position, from the TV's media sessions (Netflix, YouTube TV, Spotify, Plex…), with no Cast needed |
| Artwork | A song's cover (iTunes), a show's poster (TVmaze) or a film's poster (Google Play, else Wikipedia), else the app's icon |
| Volume | The TV's media volume as a level (set, step, mute) |
| Controls | Turn on / off, play, pause, stop, next, previous, select source |
| `play_media` | `media_content_type: app` with a package (`com.netflix.ninja`), `input` with an input id, or `url` with a link the TV opens |
| Attributes | `app_id`, `app_name`, `apps` (package, name and icon), `inputs` (id, port, name), `input`, `media_app` |

**Input** (`select.<tv>_input`): the HDMI inputs by their names on the TV,
showing the one on screen; pick one to switch to it (the TV wakes first).

Each input gets an icon for what's on it, from its name on the TV ("Xbox",
"PS5", "Switch", "Apple TV", "Cable box"…), else from the name its device
gives itself over HDMI-CEC; anything else is an HDMI port. The Input select
and the media player take the icon of the input on screen, and both list
every input's `icon`, `kind` and CEC `device` in their attributes.

| Kind | Matches | Icon |
| :--- | :--- | :--- |
| `xbox` | Xbox | `mdi:microsoft-xbox` |
| `playstation` | PlayStation, PS4, PS5 | `mdi:sony-playstation` |
| `nintendo_switch` | Nintendo, Switch, Switch 2 | `mdi:nintendo-switch` |
| `nintendo_wii` | Wii, Wii U | `mdi:nintendo-wii` |
| `steam` | Steam, Steam Deck | `mdi:steam` |
| `apple_tv` | Apple TV | `mdi:apple` |
| `laptop` | Laptop, MacBook | `mdi:laptop` |
| `computer` | PC, Computer, Mac | `mdi:desktop-tower-monitor` |
| `streamer` | Chromecast, Fire TV, Roku, Shield | `mdi:television-box` |
| `cable` | Cable, Satellite, TiVo, Box | `mdi:set-top-box` |
| `disc` | Blu-ray, DVD | `mdi:disc-player` |
| `audio` | Soundbar, Receiver, Sonos | `mdi:soundbar` |
| `camera` | Camera, GoPro | `mdi:camera` |
| `console` | Game, Console, Retro | `mdi:controller` |
| `hdmi` | anything else | `mdi:video-input-hdmi` |

**Activity** (`sensor.<tv>_activity`): what the TV is doing, the sensor to
trigger automations on:

| State | When |
| :--- | :--- |
| `off` | The screen is off |
| `screensaver` | The screensaver is on (music playing under it counts as `playing`) |
| `home` | The home screen |
| `app` | An app is open, nothing playing |
| `playing` | Something's playing |
| `paused` | It's paused |
| `input` | An HDMI input is on screen (its name in the `input` attribute) |

Dim the lights when the TV plays, bring them up when it pauses:

```yaml
triggers:
  - trigger: state
    entity_id: sensor.living_room_tv_activity
    to: playing
    id: playing
  - trigger: state
    entity_id: sensor.living_room_tv_activity
    from: playing
    to: paused
    id: paused
actions:
  - choose:
      - conditions: "{{ trigger.id == 'playing' }}"
        sequence:
          - action: light.turn_on
            target: { area_id: living_room }
            data: { brightness_pct: 10, transition: 2 }
      - conditions: "{{ trigger.id == 'paused' }}"
        sequence:
          - action: light.turn_on
            target: { area_id: living_room }
            data: { brightness_pct: 60, transition: 2 }
```

**Current app** (`sensor.<tv>_current_app`): the app in front by name, its
package in the `package` attribute.

**Diagnostics** (read every 10 minutes): Connection (Ethernet or Wi-Fi),
Wi-Fi signal (on Wi-Fi), Storage used and Storage free, Last restart; IP
address and Memory free are there disabled. The device's **Download
diagnostics** gives the TV's latest reading with its address and identifiers
redacted, for bug reports.

**Remote keys** (`button.<tv>_home`, …): Home, Back, Up, Down, Left, Right,
OK, Play/pause, Volume up, Volume down, Mute and Settings, a button each.

**Apps**: a device of its own, "<TV> Apps", linked under the TV, so the TV's
page keeps its controls apart from the app list. A button per app
(`button.<tv>_apps_netflix`, …), named and pictured from its Google Play
listing; press to open it (the TV wakes first). An app installed later gets
its button on its own; an uninstalled one goes unavailable. Hide or disable
the ones you don't want (the button's ⚙️ → Visible / Enabled).

**Remote** (`remote.<tv>`), for automations and dashboards:
`remote.send_command` with any key: `HOME`, `BACK`,
`DPAD_UP` / `DOWN` / `LEFT` / `RIGHT` / `CENTER`, `VOLUME_UP`, `MEDIA_PLAY_PAUSE`,
`SETTINGS`, … or an Android key code number. `num_repeats` and `delay_secs` work.

Apps open by their launch screen (`am start`), not by a Play Store link, so
apps that Android TV Remote can no longer launch (YouTube TV, Apple TV, HBO Max,
Hulu since the Play Store's 2026 update) open here.

The TV is read every second: its screen and what's playing (about 100 ms
of work on the TV), so playing, paused and the screen turning off show within
a second; every 5 seconds the full read adds the app, volume and inputs (and
at once when the screen turns on or off, or after a command). Its app list and
diagnostics every 10 minutes.

### Notifications: Raineworks TV Bridge

**Raineworks TV Bridge** is this project's TV app (`android/`): Home
Assistant's notifications on the TV, as pop-ups over whatever's on screen,
apps and HDMI inputs alike, or in the TV's notification panel.

* **Install it from Home Assistant**: the **Install Raineworks TV Bridge** action
  (`googletv.install_tv_bridge`) on the TV's media player downloads the app
  from the latest release, installs it over ADB, allows its pop-ups (which
  many TVs have no settings screen for) and pairs with it, no code to type.
* **A notify entity** (`notify.<tv>_notifications`): a message pops up in the
  top right.
* **The `googletv.notify` action** for the rest:

| Field | |
| :--- | :--- |
| `message`, `title` | The text |
| `image` | An image URL, or a Home Assistant path (`/local/doorbell.jpg`) |
| `camera_entity` | A camera's live stream (`camera_view: live`, the default) or snapshot: who's at the door |
| `video` | A video or live stream URL (HLS, RTSP, MP4) |
| `mode` | `popup` (over what's on screen), `panel` (the notification panel), `both` |
| `position` | `top_left`, `top`, `top_right`, `center`, `bottom_left`, `bottom`, `bottom_right`; the TV's own setting when not given |
| `duration` | Seconds on screen (8, or 20 with a video) |
| `size` | `compact` (a one-line pill), `small`, `medium`, `large`; the TV's own setting when not given |
| `color` | The pop-up's border (`#03A9F4`) |
| `mute` | A video's sound (off by default) |
| `tag` | A pop-up with the same tag replaces it; `googletv.dismiss_notifications` takes it down |
| `ignore_rules` | Pop up even where the rules say not to |

```yaml
action: googletv.notify
target:
  entity_id: media_player.living_room_tv
data:
  title: Front door
  message: Someone's at the door
  camera_entity: camera.front_door
  position: bottom_right
  duration: 30
```

**Rules**: pop-ups don't show over the apps and inputs you pick, on the TV
(the app's screen) or with `googletv.set_notification_rules` (apps and
inputs by name: `Netflix`, `Xbox`). Those notifications go to the panel
instead, or nowhere (`when_blocked: drop`). Over ADB the integration tells
the app which input is on screen, so input rules work; pop-ups show over
HDMI inputs otherwise.

The app's API is in `protocol/README.md`. On the Play Store later; until
then it's installed from Home Assistant as above (sideloaded builds are
signed with a development key kept in the repo).

### Online lookups

The TV gives only an app's package, and only the title and artist of what's
playing, so the integration looks the rest up:

* **App names and icons** from each app's Google Play listing, kept in
  `.storage/googletv.apps` and read again monthly. An app that isn't on Google
  Play (a TV maker's own) keeps its package as its name.
* **Artwork**: a song's cover from the iTunes Search API, matched by title and
  artist; a show's poster from TVmaze; a film's poster from Google Play's
  movie search (full size, in the store of the country set in Home
  Assistant), else from Wikipedia (small copies), each matched by its exact
  name. A title an app reports alone (Disney+'s "Cars") is tried as a film
  first; one with a subtitle (YouTube TV's show and channel) as a show
  first. YouTube videos show the app's icon. A lookup that fails is tried
  again a minute later.

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
the prompt again. Until then the integration doesn't connect, so the TV
doesn't keep showing its prompt.

A TV with a new address or port: the integration's **Reconfigure**. (A TV it
found on the network follows a new address by itself.)

Home Assistant keeps one key for every TV, in `.storage/googletv_adbkey`.

### Discovery

Every Google TV announces itself over mDNS (`_androidtvremote2._tcp`, the
service its phone remote uses) with its name and Bluetooth address. Home
Assistant offers a TV only when its ADB port (5555) answers, so turning on
network debugging is what makes it appear. Each TV is known by its Bluetooth
address (read over ADB too, else its serial number), so a TV already added is
never offered again, and if it gets a new IP address its entry follows it.

### When the TV is off

Keep the TV reachable in standby, so it can be woken and its state read:

* **Sony**: Settings → Network & Internet → **Remote start** on (some models:
  Settings → System → Power and energy → **Network standby**).
* **TCL, Hisense and others**: often reachable in standby already; if not,
  look for **Network standby**, **Wake on LAN** or **Quick start**.

A TV that drops off its network anyway is shown **off**, not unavailable: the
media player, Activity and remote stay available (the rest wait until it's
back), and **Turn on** sends Wake-on-LAN to its MACs (Ethernet and Wi-Fi,
read when it was added). Whether that wakes it is up to the TV; with Remote
start or network standby on, the integration wakes it with its own key.
Home Assistant starting while a known TV is off sets it up as off too.

## Notes

* Requires Home Assistant 2025.2 or newer.
* Only one ADB client can hold a TV's connection comfortably. Remove the TV
  from Home Assistant's own **Android Debug Bridge** integration (or anything
  else using ADB on it) before adding it here.
* Inputs are read from Android's TV input service. Seen on TCL (Google TV) and
  Sony (Android TV) sets; a TV whose maker doesn't use it shows no inputs.
* Apps are named from a table of well-known apps, else from their Google Play
  listing (with online lookups on), else by their package.

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

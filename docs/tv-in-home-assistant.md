# The TV in Home Assistant

Each TV is a device with these entities.

## Media player

`media_player.<tv>`, device class TV.

| | |
| :--- | :--- |
| State | `off` (asleep), `playing` / `paused` (what the front app reports), else `on` |
| Sources | Every app in the TV's launcher, then its HDMI inputs, by their names on the TV ("Xbox"; "HDMI 2" when unnamed). `source` is the input on screen, else the app in front. A device on HDMI-CEC's own input counts as its port's input |
| Now playing | Title, artist or show and position, from the TV's media sessions, with no Cast needed |
| Artwork | A song's cover (iTunes), a show's poster (TVmaze) or a film's poster (Google Play, else Wikipedia), else the app's icon. On an HDMI input: its icon on its colour (an Xbox's logo on Xbox green), with the input's name as the title |
| Volume | The TV's media volume as a level: set, step, mute |
| Controls | Turn on / off, play, pause, stop, next, previous, select source |
| Media | Browse and play Home Assistant's media, announcements, and apps, inputs and links: see [Media and dashboards](media-and-dashboards.md) |
| Attributes | `app_id`, `app_name`, `apps` (package, name and icon), `inputs` (id, port, name, icon, kind, CEC device), `input`, `media_app`, `tv_bridge` (the TV app: `paired`, `installed` or `not_installed`) |

## Activity

`sensor.<tv>_activity`: what the TV is doing, the sensor to trigger
automations on.

| State | When |
| :--- | :--- |
| `off` | The screen is off |
| `screensaver` | The screensaver is on (music playing under it counts as `playing`) |
| `home` | The home screen |
| `app` | An app is open, nothing playing |
| `playing` | Something's playing |
| `paused` | It's paused |
| `input` | An HDMI input is on screen (its name in the `input` attribute) |

## Input

`select.<tv>_input`: the HDMI inputs by their names on the TV, showing the
one on screen. Pick one to switch to it (the TV wakes first).

Each input gets an icon for what's on it, from its name on the TV, else
from the name its device gives itself over HDMI-CEC:

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

## Apps, remote and the rest

* **Current app** (`sensor.<tv>_current_app`): the app in front by name,
  its package in the `package` attribute.
* **Apps**: a button per app on the TV's device ("App · Netflix",
  `button.<tv>_app_netflix`, …), named and pictured from its Google Play
  listing. Press to open it (the
  TV wakes first). Apps installed later get their buttons on their own, and
  an uninstalled app's button goes: at once with the TV app (it says so),
  else within 10 minutes. Apps
  open by their launch screen, so the ones Android TV Remote can no longer
  launch (YouTube TV, Apple TV, HBO Max, Hulu) open here. (Before 2.4 they
  were a device of their own, "<TV> Apps"; it's folded into the TV, and
  the buttons keep their entity ids. The "App ·" and "Remote ·" names
  from 2.4.1 keep each kind together on the device's page.)
* **Choosing apps**: leave an app out of Home Assistant (the Source list,
  the `apps` attribute, its button) with its **Home Assistant** switch in
  the TV app's Apps section, on the integration's **Configure → Apps and
  inputs**, or
  by disabling its button. All three stay in step: disabling a button flips
  the switch on the TV, and the other way round. HDMI inputs have the same
  switch (the TV app's Apps section, or **Configure → Apps and inputs**):
  an input left out goes from the Source list and the Input picker.
* **Remote keys** ("Remote · Home", `button.<tv>_remote_home`, …): Home, Back, Up, Down, Left,
  Right, OK, Play/pause, Volume up, Volume down, Mute and Settings.
* **Remote** (`remote.<tv>`): `remote.send_command` with any key (`HOME`,
  `BACK`, `DPAD_UP` / `DOWN` / `LEFT` / `RIGHT` / `CENTER`, `VOLUME_UP`,
  `MEDIA_PLAY_PAUSE`, `SETTINGS`…) or an Android key code; `num_repeats`
  and `delay_secs` work.
* **Notifications** (`notify.<tv>_notifications`): see [Notifications](notifications.md).
* **Pop-ups** (`switch.<tv>_pop_ups`): whether notifications pop up on the
  TV at all, the TV app's own switch (2.7 and later). See
  [Notifications → Rules](notifications.md#rules).
* **TV app** (`sensor.<tv>_tv_app`): the TV app's version, its build (the
  commit it was built from) in the `build` attribute.
* **Diagnostics**: Connection (Ethernet or Wi-Fi), Wi-Fi signal, Storage
  used and free, Last restart; IP address and Memory free are there,
  disabled. **Download diagnostics** on the device gives the TV's latest
  reading, its address and identifiers redacted, for bug reports.

The TV is read every second: its screen and what's playing (about 100 ms of
work on the TV), so playing, paused and the screen turning off show within a
second. Every 5 seconds the full read adds the app, volume and inputs (and at
once after a command). The app list and diagnostics every 10 minutes.

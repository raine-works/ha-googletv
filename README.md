<p align="center">
  <img src="android/play/icon-512.png" alt="Raineworks TV" width="128">
</p>

# Raineworks TV

An **unofficial** [Home Assistant](https://www.home-assistant.io/) integration for
Google TV and Android TV, from [Raineworks](https://github.com/raine-works), with a
TV app of its own. One local connection does what used to take the Android TV
Remote, Google Cast and ADB integrations together, and a few things none of them can.

[![Home Assistant Marketplace](https://img.shields.io/badge/Home_Assistant-Marketplace-41BDF5.svg?style=for-the-badge)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=raine-works&repository=ha-googletv&category=integration)
[![License](https://img.shields.io/badge/License-MIT-lightgrey.svg?style=for-the-badge)](LICENSE)

[![Test](https://github.com/raine-works/ha-googletv/actions/workflows/test.yaml/badge.svg)](https://github.com/raine-works/ha-googletv/actions/workflows/test.yaml)
[![Validate](https://github.com/raine-works/ha-googletv/actions/workflows/validate.yaml/badge.svg)](https://github.com/raine-works/ha-googletv/actions/workflows/validate.yaml)

<a href="https://buymeacoffee.com/raineworks"><img src="https://img.shields.io/badge/Buy%20Me%20a%20Coffee-FFDD00?style=for-the-badge&logo=buymeacoffee&logoColor=black" alt="Buy Me a Coffee" /></a>

> This project is not affiliated with, authorized, or endorsed by Google. Google
> TV and Android TV are trademarks of Google LLC; the integration's icon in Home
> Assistant is Google TV's, to say what it's for. The TV app is Raineworks TV's own.

## What it does

* **Control the TV**: power (with Wake-on-LAN), volume, every app and HDMI
  input by its name on the TV, a remote, and what's playing in any app
  (Netflix, YouTube TV, Spotify, Plex…) with its artwork. Within a second.
* **Know what it's doing**: an Activity sensor (`off`, `home`, `app`,
  `playing`, `paused`, `input`, `screensaver`) to drive your automations.
* **Notifications on the TV**, over whatever's on, HDMI inputs included:
  text, an image, a clip (a UniFi Protect doorbell's), a **live camera
  over WebRTC in about a second** (an H.264 one; others over HLS), a
  progress bar, **buttons you answer with the remote**. **Live
  notifications** stay up while something's true (the front door is
  open) and update in place.
* **Events from the TV**: a button pressed, a notification dismissed (or
  something on it that didn't load), media played or closed, an app
  installed, as they happen, to trigger automations on.
* **Choose on the TV** which apps and inputs Home Assistant shows, and
  which ones notifications pop up over; or from Home Assistant: they stay
  in step.
* **A media target, in place of Google Cast**: Home Assistant's media
  browser, text-to-speech and cameras play on the TV. Announcements are
  spoken *over* your show, which ducks, instead of stopping it.
* **Dashboards on the TV**: any Home Assistant dashboard, full screen,
  signed in by itself.
* **Simple setup, either way**: install the TV app and choose **Allow** on
  the TV, with no developer mode; or turn on network debugging and Home
  Assistant installs the app itself. Nothing to type, and nothing to look
  after: over ADB, the TV app is kept at the integration's version.

Everything stays on your network, except optional lookups of app icons and
artwork ([Privacy and security](docs/privacy-and-security.md)).


## Setup

[![Open your Home Assistant instance and open this repository in the Home Assistant Marketplace.](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=raine-works&repository=ha-googletv&category=integration)

1. Open **Raineworks TV** in the Home Assistant Marketplace with the button
   above, or go to Settings → Marketplace. If it isn't listed, add
   `https://github.com/raine-works/ha-googletv` as a custom repository,
   type **Integration**. Download it and restart Home Assistant.
2. Connect the TV one of two ways: install the **TV app** on the TV and
   choose **Allow** (no developer mode), or turn on network debugging and
   let Home Assistant install the app over **ADB** (everything, including the
   remote's keys and turning the TV off).
3. The TV appears under Settings → Devices & services → **Discovered**.
   Choose **Add**.

[Setup](docs/setup.md) has every step, and what each way gives. Requires
Home Assistant 2025.2 or newer.

## Documentation

| Guide | What it covers |
| :--- | :--- |
| [Setup](docs/setup.md) | Installing, the TV app or ADB, and what each way gives |
| [The TV in Home Assistant](docs/tv-in-home-assistant.md) | The media player, Activity, inputs, apps, remote and diagnostics |
| [Notifications](docs/notifications.md) | Pop-ups, live cameras, buttons, live notifications, stacking and rules |
| [Events from the TV](docs/events.md) | `googletv_event` and the notification events entity |
| [Media and dashboards](docs/media-and-dashboards.md) | The TV as a media target, announcements, dashboards on the TV |
| [Recipes](docs/recipes.md) | Automations to start from |
| [Actions](docs/reference/actions.md) | Every action and its fields |
| [Privacy and security](docs/privacy-and-security.md) | What stays local, lookups, keys and tokens |
| [Privacy policy](docs/privacy-policy.md) | The TV app's and the integration's privacy policy |
| [Troubleshooting](docs/troubleshooting.md) | Common problems and their fixes |
| [Development](docs/development.md) | Tests and the TV app |

The same pages are indexed in [docs/README.md](docs/README.md).

## Support

If you find this project helpful, consider buying me a coffee to support
continued maintenance and development:

<a href="https://buymeacoffee.com/raineworks"><img src="https://img.shields.io/badge/Buy%20Me%20a%20Coffee-FFDD00?style=for-the-badge&logo=buymeacoffee&logoColor=black" alt="Buy Me a Coffee" /></a>

## License

MIT

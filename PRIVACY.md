# Privacy policy: Raineworks TV

_Last updated: 20 November 2026_

This policy covers the **Raineworks TV** TV app (package
`com.raineworks.tvbridge`) and the **Raineworks TV** Home Assistant
integration, both made by Raineworks (Raine Petersen).

## In short

The app connects your TV to **your own Home Assistant**, on your own
network. Nothing it sees on your TV goes to Raineworks or to anyone else: we
run no servers, and the app contains no analytics, advertising or tracking.

## What the app handles, and where it goes

The app works only for the Home Assistant you pair it with (you choose
**Allow** on the TV, or Home Assistant pairs with it over ADB, which you turn
on). It sends that Home Assistant, over your local network:

* **What the TV is doing**: whether its screen is on, its volume, which app
  is in front (with **Usage access** allowed), and what's playing in other
  apps, its title, artist and position (with **Notification access**
  allowed; the app reads media sessions only, never your notifications).
* **What happens on the TV**: buttons pressed on notifications Home
  Assistant shows, notifications dismissed, and Home Assistant's own media
  and dashboards opening and closing.
* **About the TV**: its name, maker, model, Android version, Android ID
  (to tell your TVs apart), its installed apps and HDMI inputs (by the names
  given to them on the TV), and its network connection, Wi-Fi signal,
  storage and memory.

It receives from that Home Assistant the notifications, media and dashboards
to show, and commands (open an app, change the volume, play or pause).
Images, videos and dashboards are loaded from the addresses Home Assistant
gives, usually Home Assistant itself.

This traffic stays on your local network. It isn't encrypted (plain HTTP,
as Home Assistant usually is on a local network), but every request after
pairing carries a token only your Home Assistant has.

## What's kept on the TV

The app keeps the tokens of the Home Assistant it's paired with, your
notification settings (sizes, positions, rules), and the version of the
integration Home Assistant last reported. Clearing the app's data, or **Forget
all Home Assistant pairings** on its screen, removes them.

## What the integration does

The integration runs in your Home Assistant, which you control. It may look
up app names and icons on Google Play, and artwork for what's playing on
iTunes, TVmaze, Google Play and Wikipedia (sending them an app's package
name, or a title and artist); turn off **Look up app icons and artwork
online** in its options to stop that. To show dashboards on the TV it makes
a Home Assistant user for the TV (read-only unless you allow control),
which you can remove at any time.

## Children

The app isn't directed at children and collects nothing about anyone.

## Changes, and contact

Changes to this policy are published at this address, with their date.
Questions: open an issue at
<https://github.com/raine-works/ha-googletv/issues>.

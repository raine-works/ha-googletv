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
  is in front (with **App detection**, Android's Usage access, allowed), and what's playing in other
  apps, its title, artist and position (with **Notification access**
  allowed; the app reads media sessions only, never your notifications).
* **What happens on the TV**: buttons pressed on notifications Home
  Assistant shows, notifications dismissed, Home Assistant's own media and
  dashboards opening and closing, and apps installed or uninstalled (by
  their package name), so its list of the TV's apps stays current.
* **About the TV**: its name, maker, model, Android version, Android ID
  (to tell your TVs apart), its installed apps and HDMI inputs (by the names
  given to them on the TV), and its network connection, Wi-Fi signal,
  storage and memory.

It receives from that Home Assistant the notifications, media and dashboards
to show, and commands (open an app, change the volume, play or pause).
Images, videos and dashboards are loaded from the addresses Home Assistant
gives, usually Home Assistant itself. A video clip is downloaded to the
app's cache while its notification is up, and deleted when it comes down.

This traffic stays on your local network. It isn't encrypted (plain HTTP,
as Home Assistant usually is on a local network), but every request after
pairing carries a token only your Home Assistant has.

## What's kept on the TV

The app keeps the tokens of the Home Assistant it's paired with, your
settings (pop-ups' size and position, which apps and inputs they show over,
which apps Home Assistant leaves out), and the version of the integration
Home Assistant last reported. Clearing the app's data removes them all;
**Forget all Home Assistant pairings**, in its About section, removes the
tokens.

## What the integration does

The integration runs in your Home Assistant, which you control. It may look
up app names and icons on Google Play, and artwork for what's playing on
iTunes, TVmaze, Google Play and Wikipedia (sending them an app's package
name, or a title and artist); turn off **Look up app icons and artwork
online** in its options to stop that. To show dashboards on the TV it makes
a Home Assistant user for the TV (read-only unless you allow control),
which you can remove at any time. Links to Home Assistant that it sends the
TV carry a signature that expires after 15 minutes, made as Home
Assistant's read-only content user. Over ADB it installs and updates the
TV app from this project's GitHub releases, checking each download's
SHA-256.

## Children

The app isn't directed at children and collects nothing about anyone.

## Changes, and contact

Changes to this policy are published at this address, with their date.
Questions: open an issue at
<https://github.com/raine-works/ha-googletv/issues>.

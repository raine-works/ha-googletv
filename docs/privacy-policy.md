# Privacy policy

Raineworks TV, the TV app and the Home Assistant integration.

_Effective 21 November 2026_

This policy covers the **Raineworks TV** app for Google TV and Android TV (package
`com.raineworks.tvbridge`, in this project's GitHub releases) and the
**Raineworks TV** Home Assistant integration (`googletv`). Both are made by Raineworks (Raine
Petersen), the developer, "we" below.

## In short

- The app connects your TV to **your own Home Assistant**, on your own network, and to nothing
  else.
- **We collect nothing.** We run no servers, and the app has no account, analytics, advertising,
  crash reporting or tracking. Nothing the app sees reaches us or anyone else.
- What the app sends goes only to the Home Assistant you pair it with, which you run and control.
- Nothing is sold or shared, and you can remove everything the app keeps at any time.

## What the app sends to your Home Assistant

The app works only for the Home Assistant you pair it with: you choose **Allow** on the TV, or
Home Assistant pairs with it over ADB, which you turn on. Over your local network it sends that Home
Assistant:

- **What the TV is doing**: whether its screen is on, its volume, which app is in front (with
  **App detection**, Android's Usage access, allowed), and what's playing in other apps, its title,
  artist and position (with **Notification access** allowed; the app reads media sessions only,
  never the content of your notifications).
- **What happens on the TV**: buttons pressed on pop-ups Home Assistant shows, pop-ups dismissed,
  Home Assistant's own media and dashboards opening and closing, and apps installed or uninstalled
  (by their package name), so Home Assistant's list of the TV's apps stays current.
- **About the TV**: its name, maker, model, Android version, Android ID (to tell your TVs apart),
  its installed apps and HDMI inputs (by the names they have on the TV), its network connection and
  Wi-Fi signal, and its storage and memory.

It receives from that Home Assistant the pop-ups, media and dashboards to show, and commands (open
an app, change the volume, play or pause). To show a camera live it signs in to that Home
Assistant's websocket as the TV's own Home Assistant user and asks for the camera's stream, as Home
Assistant's own app does; the video comes straight from your camera (or Home Assistant's go2rtc)
over your network. Images, videos and dashboards are loaded from the addresses Home Assistant gives,
usually Home Assistant itself.

## Permissions the app asks for

| Permission | What it's for |
| :--- | :--- |
| Internet, network and Wi-Fi state, multicast | The local connection Home Assistant talks to, and announcing the TV on your network (mDNS) so Home Assistant finds it |
| Display over other apps | Pop-ups over whatever is on screen, apps and HDMI inputs alike |
| Notifications | The app's own notification while its service runs, and Home Assistant's notifications in the TV's panel |
| Foreground service, run at startup | Keeping the connection to Home Assistant up, and starting it again after the TV restarts |
| Usage access (App detection) | Knowing which app is in front, for Home Assistant and for the rules on where pop-ups show; optional |
| Notification access | Reading what's playing in other apps (media sessions only); optional |
| TV listings | The names of the TV's HDMI inputs, for Home Assistant and the pop-up rules |
| Seeing the TV's launcher apps | The list of apps Home Assistant can open |

Usage access and notification access are off until you turn them on in the TV's settings, and you
can turn them off there at any time; the app keeps working without them, with less to show.

## Sharing

The app shares nothing with us or with any third party. It doesn't sell data, show ads or use any
advertising or analytics service. Its traffic goes only to the Home Assistant you paired it with
and to the addresses that Home Assistant gives it.

## Security

Everything stays on your local network. Pairing is approved on the TV itself (or by ADB, which only
you can turn on), and every request after pairing carries a token only your Home Assistant has.
The local traffic isn't encrypted (plain HTTP, as Home Assistant usually is on a home network).
Links to Home Assistant that the integration sends the TV are signed and expire after 15 minutes.

## What's kept on the TV, and deleting it

The app keeps the tokens of the Home Assistant it's paired with, your settings (the pop-ups' size
and position, which apps and inputs they show over, which apps and inputs Home Assistant leaves
out), the TV's own Home Assistant user's token (for cameras), and the integration version Home
Assistant last reported. A video clip shown in a pop-up is downloaded to the app's cache while the
pop-up is up and deleted when it comes down. Nothing else is stored, and nothing is kept anywhere
but on the TV and in your Home Assistant.

To delete it: **Forget all Home Assistant pairings** in the app's About section removes the tokens;
clearing the app's data in the TV's settings, or uninstalling it, removes everything. What your Home
Assistant keeps is yours to manage there, and removing the integration removes the TV's Home
Assistant user it made.

## The Home Assistant integration

The integration runs in your Home Assistant, which you control, not on our servers. It may look up
app names and icons on Google Play, and artwork for what's playing on iTunes, TVmaze, Google Play
and Wikipedia, sending them an app's package name, or a title and artist; turn off **Look up app
icons and artwork online** in its options to stop that. Those services' own privacy policies apply
to those requests. To show dashboards on the TV it makes a Home Assistant user for the TV
(read-only unless you allow control), which you can remove at any time. Over ADB it installs and
updates the TV app from this project's GitHub releases, checking each download's SHA-256.

## Children

The app isn't directed at children and collects nothing about anyone.

## Changes

We'll publish any change to this policy here, with its effective date at the top. The policy's
history is in this project's repository on GitHub.

## Contact

Questions about this policy or your data: [raineworks.com/contact](https://raineworks.com/contact),
or an issue at [github.com/raine-works/ha-googletv](https://github.com/raine-works/ha-googletv/issues).

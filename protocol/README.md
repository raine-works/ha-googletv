# Home Assistant Bridge API (v1)

The TV app (`android/`) serves a small JSON API on the local network, which
the Home Assistant integration (`custom_components/googletv/`) calls.

* **Port** 8721, plain HTTP on the LAN.
* **Discovery**: mDNS service `_rwtvbridge._tcp` with TXT records `api` (this
  API's version), `version` (the app's), `id` (the TV's Android ID), `model`.
* **Auth**: every endpoint but `GET /api/info` and the two pairing ones needs
  `Authorization: Bearer <token>`. A missing or unknown token is `401`.
* **Errors**: a bad request is `400`, a wrong pairing code `403`, an unknown
  endpoint `404`; the body is `{"error": "<message>"}`.

## Pairing

1. `POST /api/pair/start` `{"via": "screen" | "adb"}` → `{"pairing_id": "…"}`.
   With `screen` (the default) the TV shows a 6-digit code over whatever is on
   screen for 5 minutes (or in its notification panel without the overlay
   permission). With `adb` it shows nothing and writes `<pairing_id> <code>`
   to `/sdcard/Android/data/com.raineworks.tvbridge/files/pairing_code`,
   which only ADB (the shell) can read: the integration pairs a TV it already
   reaches over ADB without anyone at the TV.
2. `POST /api/pair/finish` `{"pairing_id": "…", "code": "123456"}` →
   `{"token": "…"}`, or `403`. A code works for 5 minutes and 5 tries.

`POST /api/unpair` forgets the calling token.

## Endpoints

| Endpoint | Returns |
| :--- | :--- |
| `GET /api/info` | `{api, app_version, name, manufacturer, model, android, paired}` |
| `GET /api/state` | `{screen_on, foreground_app, overlay_permission, usage_access}` |
| `GET /api/apps` | `{apps: [{package, name}]}`: the launcher's apps |
| `GET /api/inputs` | `{inputs: [{id, name}]}`: HDMI and other external inputs, by their names on the TV |
| `GET /api/rules` | `{blocked_apps: [package], blocked_inputs: [input id], when_blocked, default_size, default_position}` |
| `POST /api/rules` | the same fields (any of them) to change; returns the rules |
| `POST /api/notify` | shows a notification; see below |
| `POST /api/dismiss` | `{tag}` takes that pop-up down; no tag takes them all down |

## Notifications

`POST /api/notify`:

| Field | Default | |
| :--- | :--- | :--- |
| `title`, `message` | | Text; at least one of these, `image_url` or `video_url` |
| `image_url` | | An image (http/https), shown on the pop-up and in the panel |
| `video_url` | | A video or live stream (http/https, HLS `.m3u8`, rtsp), played on the pop-up: a doorbell camera |
| `mode` | `popup` | `popup` over what's on screen, `panel` (the notification panel only), or `both` |
| `position` | the TV's setting (`top_right`) | `top_left`, `top`, `top_right`, `center`, `bottom_left`, `bottom`, `bottom_right` |
| `duration` | 8 (20 with a video) | Seconds on screen, 1 to 600 |
| `size` | the TV's setting (`small`) | `compact` (a one-line pill), `small`, `medium`, `large` |
| `color` | | The pop-up's border, a hex color (`#03A9F4`) |
| `mute` | `true` | A video's sound off |
| `tag` | | A pop-up with the same tag replaces it (and `/api/dismiss` takes it down) |
| `ignore_rules` | `false` | Pop up whatever is on screen |
| `when_blocked` | the TV's setting | `panel` or `drop`, for a pop-up a rule keeps off the screen |
| `context` | | `{app, input}`: what Home Assistant knows is on screen (over ADB), for the rules |

Returns `{popup, panel, blocked_by, reason}`: whether it popped up and/or went
to the panel; `blocked_by` the rule that kept it off the screen
(`app:<package>` or `input:<id>`), `reason` `blocked` or
`overlay_not_allowed` when it didn't pop up.

**Rules**: a pop-up isn't shown over an app or input in `blocked_apps` /
`blocked_inputs`. What's on screen is `context` when given (Home Assistant
knows the HDMI input over ADB), else the app in front (with usage access).
Pop-ups do show over HDMI inputs unless a rule says otherwise.

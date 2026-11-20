# Google TV by Raineworks: the TV app's API (v1)

The TV app (`android/`) serves a small JSON API on the local network, which
the Home Assistant integration (`custom_components/googletv/`) calls.

* **Port** 8721, plain HTTP on the LAN.
* **Discovery**: mDNS service `_rwtvbridge._tcp` named after the TV, with TXT
  records `api` (this API's version), `version` (the app's), `id` (the TV's
  Android ID), `model`, `name` (the TV's name). Home Assistant discovers TVs
  by it, network debugging on or not.
* **Auth**: every endpoint but `GET /api/info` and the two pairing ones needs
  `Authorization: Bearer <token>`. A missing or unknown token is `401`.
* **Errors**: a bad request is `400`, a wrong pairing code `403`, an unknown
  endpoint `404`, a body sent without a `Content-Length` `411`; the body is
  `{"error": "<message>"}`.

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
   10 wrong codes in 10 minutes, across pairings, lock pairing for 10
   minutes: `/api/pair/start` answers `429` (tokens already given keep
   working). It also answers `429` to more than one start a second.

`POST /api/unpair` forgets the calling token.

## Endpoints

| Endpoint | Returns |
| :--- | :--- |
| `GET /api/info` | `{api, app_version, name, manufacturer, model, android, paired}` |
| `GET /api/events` | What happens on the TV, as it happens: see [Events](#events) |
| `GET /api/state` | `{screen_on, foreground_app, overlay_permission, usage_access, instance, popups}`: `instance` changes when the app restarts (and has lost its pop-ups); `popups` the tags of those up now |
| `GET /api/apps` | `{apps: [{package, name}]}`: the launcher's apps |
| `GET /api/inputs` | `{inputs: [{id, name}]}`: HDMI and other external inputs, by their names on the TV |
| `GET /api/rules` | `{blocked_apps: [package], blocked_inputs: [input id], when_blocked, default_size, default_position}` |
| `POST /api/rules` | the same fields (any of them) to change; returns the rules |
| `POST /api/notify` | shows a notification; see below |
| `POST /api/play` | Plays media; see below |
| `POST /api/dashboard` | `{url, token}`: a Home Assistant dashboard full screen, signed in with `token` (the frontend's external auth, as Home Assistant's phone apps do). It stays on `url`'s address (scheme, host, port): links elsewhere aren't followed, and the token is given only to a page from there. It closes on Back from its first page, or when another app comes to the front. A page that can't load (an untrusted certificate) shows why |
| `POST /api/stop` | Closes the player and the dashboard, and stops announcing |
| `POST /api/dismiss` | `{tag}` takes that notification down, from the screen and the panel; no tag takes them all down (but a pairing code) |

## Notifications

`POST /api/notify`:

| Field | Default | |
| :--- | :--- | :--- |
| `title`, `message` | | Text; at least one of these, `image_url` or `video_url` |
| `icon` | | The badge: `mdi:<name>` (Material Design Icons 7.4.47, bundled) or an http(s) image URL; the logo if not set |
| `image_url` | | An image (http/https only), shown on the pop-up and in the panel |
| `video_url` | | A video or live stream (http/https, HLS `.m3u8`, rtsp), played on the pop-up: a doorbell camera |
| `mode` | `popup` | `popup` over what's on screen, `panel` (the notification panel only), or `both` |
| `position` | the TV's setting (`top_right`) | `top_left`, `top`, `top_right`, `center`, `bottom_left`, `bottom`, `bottom_right` |
| `duration` | 8 (20 with a video) | Seconds on screen, 1 to 600; `0` until it's dismissed (in the panel, it can't be swiped away) |
| `progress` | | A progress bar, 0 to 100 |
| `actions` | | Up to 3 buttons, `[{action, title}]` (`action`: letters, digits, `_ . : -`; `title`: up to 40 characters). The card takes the remote's focus while it's up: a button pressed is a `notification_action` event, Back a `notification_dismissed` one. The panel copy has them too. 30 seconds on screen when no `duration` is given |
| `size` | the TV's setting (`small`) | `compact` (a one-line pill; a video plays in a small tile on it), `small`, `medium`, `large` |
| `color` | | The pop-up's border, a hex color (`#03A9F4`) |
| `mute` | `true` | A video's sound off |
| `tag` | | Sent again, it updates the notification with that tag in place: the same slot, no animation, its video still playing if `video_url` is the same, and no new alert in the panel. A pop-up or panel copy the update no longer goes to comes down. `/api/dismiss` takes it down |
| `ignore_rules` | `false` | Pop up whatever is on screen |
| `when_blocked` | the TV's setting | `panel` or `drop`, for a pop-up a rule keeps off the screen |
| `context` | | `{app, input}`: what Home Assistant knows is on screen (over ADB), for the rules |

Returns `{popup, panel, blocked_by, reason, instance}`: whether it popped up and/or went
to the panel; `blocked_by` the rule that kept it off the screen
(`app:<package>` or `input:<id>`), `reason` `blocked` or
`overlay_not_allowed` when it didn't pop up.

**Stacking**: a stack per position; 3 cards show, persistent ones
(`duration: 0`) first, then the newest; a "+N more" pill counts the rest,
which show again as others go (up to 12 are kept per position).

**Rules**: a pop-up isn't shown over an app or input in `blocked_apps` /
`blocked_inputs`. What's on screen is `context` when given (Home Assistant
knows the HDMI input over ADB), else the app in front (with usage access).
Pop-ups do show over HDMI inputs unless a rule says otherwise.

## Media

`POST /api/play`:

| Field | Default | |
| :--- | :--- | :--- |
| `url` | | The media (http/https, HLS, rtsp) |
| `kind` | from `mime`, else `video` | `audio`, `video` or `image` |
| `mime` | | Its type (`audio/mpeg`) |
| `title`, `artist`, `image_url` | | Shown with a song (its cover), and in the TV's media session |
| `announce` | `false` | Audio only: spoken over what's on, which ducks (audio focus `GAIN_TRANSIENT_MAY_DUCK`, as an assistant), instead of full screen. Announcements queue |
| `message` | | With `announce`: shown on a compact pill while it plays |

Full screen media has a media session like any app's (so the TV's media
state shows it, and the remote's media keys work), and closes at its end,
on Back, when another app comes to the front, or on `/api/stop`. Audio and
video hold media audio focus: another app's media pauses them. The app
starts it over whatever's on, which its overlay permission allows: without
it, `/api/play` (but an announcement) and `/api/dashboard` answer `409`.
An announcement plays for at most a minute; up to 8 wait their turn.

## Events

`GET /api/events` streams JSON events, one a line (`application/x-ndjson`),
for as long as the connection stays open. Every event has `type` and `time`
(milliseconds since the epoch). Up to 4 streams at once (the oldest closes);
a stream that stops reading loses its oldest events.

| `type` | Fields | When |
| :--- | :--- | :--- |
| `hello` | `instance`, `app_version` | First, on connecting. A new `instance`: the app restarted |
| `ping` | | Every 15 seconds with nothing else: the connection's alive |
| `notification_action` | `tag`, `action` | A notification's button was pressed (on a pop-up or in the panel); the notification comes down |
| `notification_dismissed` | `tag`, `by` | A tagged notification came down on the TV: `by` is `remote` (Back on a card with buttons) or `timeout` |
| `player` | `state` (`opened`, `playing`, `paused`, `closed`), `kind`, `title` | The full-screen player |
| `dashboard` | `state` (`opened`, `closed`), `url` | The dashboard view |

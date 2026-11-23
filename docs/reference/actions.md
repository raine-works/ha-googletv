# Actions

Every action is registered by the integration (`custom_components/googletv/services.yaml`; names and descriptions in `strings.json`). Each one targets a Raineworks TV `media_player` entity.

| Action | What it does |
| :--- | :--- |
| `googletv.notify` | A notification on the TV |
| `googletv.dismiss_notifications` | Takes notifications down by tag, or all of them |
| `googletv.set_notification_rules` | The apps and inputs pop-ups don't show over |
| `googletv.show_dashboard` | A Home Assistant dashboard full screen |
| `googletv.install_tv_bridge` | Installs or updates the TV app over ADB |

The notify entity (`notify.<tv>_notifications`) and the media player's own services (`media_player.play_media`, `tts.speak`, `remote.send_command`) are covered in [Notifications](../notifications.md), [Media and dashboards](../media-and-dashboards.md) and [The TV in Home Assistant](../tv-in-home-assistant.md).

## googletv.notify

Shows a notification on the TV: a pop-up over what's on, in the notification panel, or both. Every field is optional. See [Notifications](../notifications.md) for how they behave.

| Field | Values | What it does |
| :--- | :--- | :--- |
| `message` | Text, multiline | The notification's text |
| `title` | Text | Its title |
| `icon` | An icon (`mdi:doorbell`), an image URL or a path | The badge; the Raineworks TV logo if not set |
| `image` | URL or Home Assistant path | An image. With a `video`, it shows until the video's first frame |
| `video` | URL or Home Assistant path | A video or live stream (HLS, RTSP, MP4) |
| `camera_entity` | A `camera` entity | A camera on the card |
| `camera_view` | `live` (default), `hls`, `snapshot` | How the camera shows: WebRTC with HLS as the fallback, HLS only, or a still |
| `mode` | `popup` (default), `panel`, `both` | Where it shows |
| `position` | `top_left`, `top`, `top_right`, `center`, `bottom_left`, `bottom`, `bottom_right` | Where the pop-up sits; the TV's setting if not given |
| `size` | `compact`, `small`, `medium`, `large` | The pop-up's size; the TV's setting if not given |
| `duration` | 0 to 600 seconds | Seconds on screen (8, or 20 with a video; 30 with buttons); `0` keeps it up until it's dismissed, or until `until_entity` changes |
| `until_entity` | Any entity | Keeps it up until this entity changes: a live notification |
| `until_state` | Text | Takes it down when the entity reaches this state, not at any change |
| `progress` | 0 to 100 | A progress bar; send again with the same `tag` to move it |
| `actions` | A list of up to 3 `{action, title}` | Buttons answered with the remote; a press fires `googletv_event` |
| `color` | A hex color (`#03A9F4`) | The pop-up's border |
| `mute` | Boolean | A video's sound; off by default |
| `tag` | Text | Send again with the same tag to update it in place; dismiss it by its tag |
| `ignore_rules` | Boolean, default off | Pop up even over apps and inputs the rules exclude |
| `when_blocked` | `panel`, `drop` | Where a pop-up the rules keep off the screen goes |

It returns whether the notification popped up, went to the panel, or why not, and its `tag`.

## googletv.dismiss_notifications

Takes notifications down, from the screen and the notification panel.

| Field | What it does |
| :--- | :--- |
| `tag` | The notification's tag; every notification if not set |

## googletv.set_notification_rules

Sets the apps and inputs pop-ups don't show over, and what happens to those notifications. Each list replaces the one before.

| Field | What it does |
| :--- | :--- |
| `blocked_apps` | Apps by name (`Netflix`) or package (`com.netflix.ninja`); a list |
| `blocked_inputs` | Inputs by name (`Xbox`, `HDMI 2`) or id; a list |
| `when_blocked` | `panel` or `drop`: where a blocked pop-up goes |

## googletv.show_dashboard

Shows a Home Assistant dashboard full screen on the TV, through the TV app. It signs in as the TV's own user, read-only unless the TV's options let dashboards control devices. Back, or the media player's stop, closes it. See [Media and dashboards](../media-and-dashboards.md).

| Field | What it does |
| :--- | :--- |
| `dashboard` | The dashboard's path: `lovelace` (the Overview, the default), or another's (`dashboard-tv`) |
| `view` | A view's path or number; its first view if not set |

## googletv.install_tv_bridge

Installs or updates the TV app (Raineworks TV) over ADB, allows its pop-ups, and pairs with it. Over ADB the app is kept up to date by itself; this does it now. A copy signed with another key can't be updated in place: it's uninstalled once, then the new one installed (its pairing is lost, and made again).

| Field | What it does |
| :--- | :--- |
| `development` | Boolean, default off: the latest build from `master` instead of the latest release |
| `url` | Install this APK instead |

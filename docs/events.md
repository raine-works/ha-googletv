# Events from the TV

The TV app tells Home Assistant what happens on the TV, as it happens, on a
connection the integration keeps open. Each event fires **`googletv_event`**
on Home Assistant's event bus, with the TV's `device_id`:

| `type` | Data | When |
| :--- | :--- | :--- |
| `notification_action` | `tag`, `action` | A notification's button was pressed |
| `notification_dismissed` | `tag`, `by` (`remote`, `timeout`) | A tagged notification came down on the TV: Back, or its time ran out |
| `notification_failed` | `tag`, `media` (`image`, `icon`, `video`, `webrtc`), `reason` | Something on a notification didn't load on the TV (a camera over WebRTC then falls back to HLS). Also logged as a warning, and on the event entity as **Couldn't load** |
| `player` | `state` (`opened`, `playing`, `paused`, `closed`), `kind`, `title` | Home Assistant's media on the TV |
| `dashboard` | `state` (`opened`, `closed`), `url` | A dashboard on the TV |
| `state` | `change` (`screen`, `volume`) | The screen turned on or off, or the volume changed (the TV is read again at once) |
| `apps` | `change` (`installed`, `uninstalled`, `changed`), `package` | An app was installed or uninstalled (the app list and buttons follow at once) |
| `rules` | `hidden_apps`, `hidden_inputs`, `blocked_apps`, `blocked_inputs`, … | A switch was flipped in the TV app's Apps section (Home Assistant follows) |

Each TV also has a **Notification events** entity
(`event.<tv>_notification_events`): `action` (with `action` and `tag`),
`dismissed` (with `by` and `tag`) or `failed` (with `media`, `reason` and
`tag`).

**Buttons on notifications**: give `googletv.notify` up to three `actions`.
The card takes the remote's focus while it's up, so the remote moves
between its buttons: select one, and its `action` comes back as an event;
press Back to dismiss it. Once it's gone, the remote is the app's again. A
card with buttons stays 30 seconds unless its `duration` says otherwise.
The copy in the notification panel has the same buttons. A live
notification dismissed on the TV isn't shown again.

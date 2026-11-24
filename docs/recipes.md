# Recipes


**Dim the lights while something plays, bring them up when it pauses:**

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

**Movie mode: no pop-ups on the theater TV while it's on.** A doorbell sent
with `ignore_rules: true` still pops up; everything else goes to the
notification panel (or nowhere, as the TV app's **When pop-ups are off**
says).

```yaml
triggers:
  - trigger: state
    entity_id: input_boolean.movie_mode
actions:
  - action: "switch.turn_{{ 'off' if trigger.to_state.state == 'on' else 'on' }}"
    target:
      entity_id: switch.theater_tv_pop_ups
```

**Who's at the door, live, in the corner:**

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.doorbell
    to: "on"
actions:
  - action: googletv.notify
    target:
      entity_id: media_player.living_room_tv
    data:
      title: Front door
      message: Someone's at the door
      icon: mdi:doorbell
      camera_entity: camera.front_door
      position: bottom_right
      duration: 30
```

**Unlock the door from the couch:**

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.doorbell
    to: "on"
actions:
  - action: googletv.notify
    target:
      entity_id: media_player.living_room_tv
    data:
      tag: doorbell
      title: Front door
      message: Someone's at the door
      camera_entity: camera.front_door
      actions:
        - action: UNLOCK
          title: Unlock
        - action: IGNORE
          title: Ignore
  - wait_for_trigger:
      - trigger: event
        event_type: googletv_event
        event_data:
          type: notification_action
          tag: doorbell
          action: UNLOCK
    timeout: 60
    continue_on_timeout: false
  - action: lock.unlock
    target:
      entity_id: lock.front_door
```

**A pill while the front door is open, gone when it closes:**

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.front_door
    to: "on"
actions:
  - action: googletv.notify
    target:
      entity_id: media_player.living_room_tv
    data:
      title: Front door open
      icon: mdi:door-open
      size: compact
      until_entity: binary_sensor.front_door
```

**The washer's progress, until it's done:**

```yaml
triggers:
  - trigger: state
    entity_id: sensor.washer_progress
actions:
  - action: googletv.notify
    target:
      entity_id: media_player.living_room_tv
    data:
      tag: washer
      title: Washer
      message: "{{ states('sensor.washer_time_left') }} left"
      progress: "{{ states('sensor.washer_progress') | int(0) }}"
      icon: mdi:washing-machine
      size: compact
      until_entity: sensor.washer_state
      until_state: idle
```

**Say it over whatever's on** (the show ducks; a pill shows the words):

```yaml
action: tts.speak
target:
  entity_id: tts.home_assistant_cloud
data:
  media_player_entity_id: media_player.living_room_tv
  message: Dinner's ready
```

**The cameras on the TV when someone rings, back to the show after a minute:**

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.doorbell
    to: "on"
actions:
  - action: googletv.show_dashboard
    target:
      entity_id: media_player.living_room_tv
    data:
      dashboard: dashboard-tv
      view: cameras
  - delay: 60
  - action: media_player.media_stop
    target:
      entity_id: media_player.living_room_tv
```

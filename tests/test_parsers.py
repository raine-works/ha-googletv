"""The parsers, on output captured from real TVs (a TCL and a Sony, Android 12)."""

from __future__ import annotations

from googletv_parsers import (
    INPUT_APPS,
    PLAYBACK_PAUSED,
    PLAYBACK_PLAYING,
    app_name,
    input_on_screen,
    now_playing,
    parse_apps,
    parse_audio,
    parse_awake,
    parse_front_app,
    parse_inputs,
    parse_props,
    parse_sessions,
    parse_state,
    split_sections,
)

# A Sony BRAVIA (Master Suite) playing YouTube TV, Spotify paused behind it
SONY_SESSIONS = """\
    package=com.google.android.youtube.tvunplugged
      active=true
      state=PlaybackState {state=3, position=46800103, buffered position=0, speed=1.0, updated=73552083, actions=382, custom actions=[], active item id=-1, error=null}
      metadata: size=5, description=Family Guy, Adult Swim, null
    package=com.spotify.tv.android
      active=true
      state=PlaybackState {state=2, position=47355, buffered position=0, speed=0.0, updated=56409, actions=3125244, custom actions=[], active item id=0, error=null}
      metadata: size=22, description=Everybody Grab a Broom, J Scott Rakozy, Hogwarts Legacy, null
"""

# A TCL's HDMI inputs as the poll's awk prints them, on the Xbox (HDMI 1)
TCL_INPUTS = """\
input com.tcl.tvinput/.TvPassThroughService/HW15 1
input com.tcl.tvinput/.TvPassThroughService/HW16 2
input com.tcl.tvinput/.TvPassThroughService/HW17 3
input com.tcl.tvinput/.TvPassThroughService/HW18 4
current com.tcl.tvinput/.TvPassThroughService/HW15
"""
TCL_LABELS = (
    "com.tcl.tvinput%2F.TvPassThroughService%2FHW15,Xbox:"
    "com.tcl.tvinput%2F.TvPassThroughService%2FHW16,Nintendo%20"
)

TCL_AUDIO = """\
- STREAM_MUSIC:
   Muted: false
   Muted Internally: false
   Min: 0
   Max: 100
   streamVolume:19
   Current: 2 (speaker): 19, 80 (bt_a2dp): 25, 400 (hdmi): 20
   Devices: speaker
"""

SONY_APPS = """\
com.android.vending/com.google.android.finsky.tvmainactivity.TvMainActivity
com.google.android.youtube.tv/com.google.android.apps.youtube.tv.activity.ShellActivity
com.sony.dtv.smartmediaapp/.MainActivity
com.netflix.ninja/.MainActivity
com.wbd.stream/com.wbd.beam.BeamActivity
com.sony.dtv.timers/com.sony.dtv.activity.TimersMainActivity
com.sony.dtv.timers/.activity.TimersMainActivity
"""


def test_awake() -> None:
    assert parse_awake("  mWakefulness=Awake\nFailed to write while dumping")
    assert not parse_awake("  mWakefulness=Asleep")
    # The screensaver is on screen: awake (the screensaver flag tells it apart)
    assert parse_awake("  mWakefulness=Dreaming")
    assert not parse_awake("  mWakefulness=Dozing")
    assert not parse_awake("")


def test_front_app() -> None:
    record = (
        "    mResumedActivity: ActivityRecord{4c9a57d u0 com.google.android.youtube."
        "tvunplugged/com.google.android.apps.youtube.tvunplugged.activity.MainActivity t28424}"
    )
    assert parse_front_app(record) == (
        "com.google.android.youtube.tvunplugged",
        "com.google.android.apps.youtube.tvunplugged.activity.MainActivity",
    )
    # A short activity name gets its package
    short = "topResumedActivity=ActivityRecord{e1b4624 u0 com.android.tv.settings/.MainSettings t1539}"
    assert parse_front_app(short) == (
        "com.android.tv.settings",
        "com.android.tv.settings.MainSettings",
    )
    assert parse_front_app("") is None


def test_audio() -> None:
    assert parse_audio(TCL_AUDIO) == (0.19, False, 100)
    assert parse_audio(TCL_AUDIO.replace("Muted: false", "Muted: true"))[1] is True
    assert parse_audio("") == (None, None, None)
    # A TV whose scale runs to 15: 9 of 15
    assert parse_audio(
        TCL_AUDIO.replace("Max: 100", "Max: 15").replace(
            "streamVolume:19", "streamVolume:9"
        )
    ) == (0.6, False, 15)


def test_sessions() -> None:
    youtube_tv, spotify = parse_sessions(SONY_SESSIONS)
    assert youtube_tv.package == "com.google.android.youtube.tvunplugged"
    assert youtube_tv.state == PLAYBACK_PLAYING
    assert (youtube_tv.title, youtube_tv.subtitle, youtube_tv.description) == (
        "Family Guy",
        "Adult Swim",
        None,
    )
    assert spotify.state == PLAYBACK_PAUSED
    # Spotify's subtitle is "artist, album"
    assert (spotify.title, spotify.subtitle, spotify.description) == (
        "Everybody Grab a Broom",
        "J Scott Rakozy, Hogwarts Legacy",
        None,
    )
    # Playing counts on from when it was reported (by the TV's uptime); paused doesn't
    assert youtube_tv.position_at(73552083 + 10_000) == 46810.103
    assert spotify.position_at(99_999_999) == 47.355


def test_commas_stay_in_the_subtitle() -> None:
    [session] = parse_sessions(
        "package=com.example\nactive=true\n"
        "state=PlaybackState {state=3, position=0, speed=1.0, updated=0}\n"
        "metadata: size=3, description=Song, Artist, Album, Live\n"
    )
    assert session.title == "Song"
    assert session.subtitle == "Artist, Album"
    assert session.description == "Live"


def test_now_playing_prefers_the_front_app() -> None:
    sessions = parse_sessions(SONY_SESSIONS)
    assert (
        now_playing(sessions, "com.google.android.youtube.tvunplugged").title
        == "Family Guy"
    )
    # The front app paused: still its session
    assert (
        now_playing(sessions, "com.spotify.tv.android").title
        == "Everybody Grab a Broom"
    )
    # Another app in front: whatever is playing
    assert now_playing(sessions, "com.android.tv.settings").title == "Family Guy"
    assert now_playing([], "x") is None


def test_inputs_named_and_on_screen() -> None:
    inputs, current = parse_inputs(TCL_INPUTS, TCL_LABELS, "null")
    assert [(i.port, i.label) for i in inputs] == [
        (1, "Xbox"),
        (2, "Nintendo"),
        (3, "HDMI 3"),
        (4, "HDMI 4"),
    ]
    assert input_on_screen(inputs, current).label == "Xbox"
    # None on screen while an app is in front
    _, none = parse_inputs(
        TCL_INPUTS.replace(
            "current com.tcl.tvinput/.TvPassThroughService/HW15", "current none"
        ),
        "",
        "",
    )
    assert none is None


def test_hidden_inputs_left_out() -> None:
    inputs, _ = parse_inputs(
        TCL_INPUTS, "null", "com.tcl.tvinput%2F.TvPassThroughService%2FHW18"
    )
    assert [i.port for i in inputs] == [1, 2, 3]


def test_a_cec_device_counts_as_its_port() -> None:
    # Lott's TCL: the Xbox's own CEC input (physical 1.0.0.0, logical 4) is on screen
    inputs, _ = parse_inputs(TCL_INPUTS, TCL_LABELS, "")
    shown = input_on_screen(inputs, "com.tcl.tvinput/.TvPassThroughService/HDMI100004")
    assert shown is not None and shown.label == "Xbox"
    assert (
        input_on_screen(inputs, "com.tcl.tvinput/.TvPassThroughService/HDMI300008").port
        == 3
    )
    assert input_on_screen(inputs, "something/else/entirely") is None


def test_sony_inputs() -> None:
    sony = "\n".join(
        f"input com.sony.dtv.tvinput.external/.ExternalTvInputService/HW{n} {n}"
        for n in (1, 2, 3, 4)
    )
    inputs, current = parse_inputs(sony + "\ncurrent none", "null", "null")
    assert [i.label for i in inputs] == ["HDMI 1", "HDMI 2", "HDMI 3", "HDMI 4"]
    assert current is None


def test_whole_poll() -> None:
    raw = "\n".join(
        [
            "@@power",
            "  mWakefulness=Awake",
            "@@app",
            "    mResumedActivity: ActivityRecord{1 u0 com.tcl.tv/.TvActivity t1}",
            "@@audio",
            TCL_AUDIO,
            "@@uptime",
            "74288.02 246430.49",
            "@@sessions",
            "",
            "@@inputs",
            TCL_INPUTS,
            "@@labels",
            TCL_LABELS,
            "@@hidden",
            "null",
        ]
    )
    state = parse_state(raw)
    assert state.awake
    assert state.app == "com.tcl.tv" and state.app in INPUT_APPS
    assert state.volume == 0.19 and state.muted is False
    assert state.uptime_ms == 74288020
    assert state.input is not None and state.input.label == "Xbox"
    assert state.now_playing is None


def test_a_known_app_in_front_means_no_input() -> None:
    raw = (
        "@@app\n    mResumedActivity: ActivityRecord{1 u0 com.netflix.ninja/.MainActivity t1}\n"
        f"@@inputs\n{TCL_INPUTS}@@labels\nnull\n@@hidden\nnull\n"
    )
    assert parse_state(raw).input is None


def test_sections() -> None:
    assert split_sections("ignored\n@@a\n1\n2\n@@b\n") == {"a": "1\n2", "b": ""}


def test_apps() -> None:
    apps = parse_apps(SONY_APPS)
    by_package = {a.package: a for a in apps}
    assert by_package["com.netflix.ninja"].name == "Netflix"
    assert by_package["com.netflix.ninja"].activity == "com.netflix.ninja.MainActivity"
    assert by_package["com.wbd.stream"].activity == "com.wbd.beam.BeamActivity"
    # Listed twice, kept once
    assert sum(a.package == "com.sony.dtv.timers" for a in apps) == 1
    # By name; an unknown app by its package
    assert [a.name for a in apps] == sorted((a.name for a in apps), key=str.lower)
    assert by_package["com.sony.dtv.smartmediaapp"].name == "com.sony.dtv.smartmediaapp"


def test_names_and_props() -> None:
    assert app_name("com.tcl.tv") == "TV input"
    assert app_name("com.example.thing") == "com.example.thing"
    assert app_name(None) is None
    assert parse_props(
        "Sony\nBRAVIA 4K VH2\n12\n4074be004113896\n38:B8:00:06:0E:41\n"
    ) == {
        "manufacturer": "Sony",
        "model": "BRAVIA 4K VH2",
        "android": "12",
        "serial": "4074be004113896",
        "bluetooth": "38:b8:00:06:0e:41",
    }
    # Bluetooth off, or no adapter: no address
    assert "bluetooth" not in parse_props("TCL\nSmart TV\n12\nX\nnull\n")


# A whole poll from Lott's TCL, verbatim: on the Xbox (its own CEC input),
# Spotify paused in the background, a disconnected Bluetooth session
LOTTS_TCL_POLL = """\
@@power
  mWakefulness=Awake
Failed to write while dumping service power: Broken pipe
@@app
    mResumedActivity: ActivityRecord{ed04c9e u0 com.tcl.tv/.TVActivity t1769}
Failed to write while dumping service activity: Broken pipe
@@audio
- STREAM_MUSIC:
   Muted: false
   Muted Internally: false
   Min: 0
   Max: 100
   streamVolume:19
   Current: 2 (speaker): 19, 80 (bt_a2dp): 25, 400 (hdmi): 20, 40000 (hmdi_arc): 26, 80000 (spdif): 20, 800000 (ip): 20, 40000000 (default): 20
   Devices: speaker
@@uptime
1294401.03 4698049.80
@@sessions
      package=com.spotify.tv.android
      active=true
      state=PlaybackState {state=2, position=76041, buffered position=0, speed=0.0, updated=1283829673, actions=3125244, custom actions=[Action:mName='Toggle shuffle, mIcon=2131232976, mExtras=Bundle[EMPTY_PARCEL], Action:mName='Start radio, mIcon=2131232983, mExtras=Bundle[EMPTY_PARCEL]], active item id=0, error=null}
      metadata: size=22, description=3 Nights, Dominic Fike, null
      package=com.android.bluetooth
      active=false
      state=PlaybackState {state=7, position=0, buffered position=0, speed=0.0, updated=1283453232, actions=0, custom actions=[], active item id=-1, error=Bluetooth audio disconnected}
      metadata: null
@@inputs
input com.tcl.tvinput/.TvPassThroughService/HW15 1
input com.tcl.tvinput/.TvPassThroughService/HW16 2
input com.tcl.tvinput/.TvPassThroughService/HW17 3
current com.tcl.tvinput/.TvPassThroughService/HDMI100004
@@labels
com.tcl.tvinput%2F.TvPassThroughService%2FHW15,Xbox
@@hidden
null"""


def test_a_real_poll() -> None:
    state = parse_state(LOTTS_TCL_POLL)
    assert state.awake and state.app == "com.tcl.tv"
    assert (state.volume, state.muted) == (0.19, False)
    assert [i.label for i in state.inputs] == ["Xbox", "HDMI 2", "HDMI 3"]
    assert state.input is not None and state.input.label == "Xbox"
    spotify, bluetooth = state.sessions
    assert (spotify.title, spotify.subtitle, spotify.state) == (
        "3 Nights",
        "Dominic Fike",
        PLAYBACK_PAUSED,
    )
    assert bluetooth.title is None and not bluetooth.active
    # On the Xbox with Spotify only paused behind it: nothing playing
    assert state.now_playing is None


def test_named_playback_states() -> None:
    # Newer builds name the state: "state=ERROR(7)", "state=PLAYING(3)"
    sessions = parse_sessions(
        "package=com.android.bluetooth\n"
        "state=PlaybackState {state=ERROR(7), position=0, buffered position=0,"
        " speed=0.0, updated=19286, actions=0, error=Bluetooth audio disconnected}\n"
        "package=com.netflix.ninja\nactive=true\n"
        "state=PlaybackState {state=PLAYING(3), position=1000, speed=1.0,"
        " updated=5000, actions=0}\n"
        "metadata: size=3, description=Wednesday, Season 1, null\n"
    )
    assert [s.state for s in sessions] == [7, PLAYBACK_PLAYING]
    assert sessions[1].playing and sessions[1].title == "Wednesday"


def test_input_kinds() -> None:
    from googletv_parsers import input_kind

    for name, key in (
        ("Xbox", "xbox"),
        ("Xbox Series X", "xbox"),
        ("PS5", "playstation"),
        ("PlayStation 4", "playstation"),
        ("Switch", "nintendo_switch"),
        ("NintendoSwitch", "nintendo_switch"),
        ("Switch 2", "nintendo_switch"),
        ("Wii U", "nintendo_wii"),
        ("Steam Deck", "steam"),
        ("Apple TV", "apple_tv"),
        ("Gaming PC", "computer"),
        ("MacBook", "laptop"),
        ("Fire TV Stick", "streamer"),
        ("SHIELD", "streamer"),
        ("Cable box", "cable"),
        ("Blu-ray", "disc"),
        ("Sonos Arc", "audio"),
        ("Retro console", "console"),
        ("HDMI switch", "hdmi"),
        ("Living room", "hdmi"),
    ):
        assert input_kind(name).key == key, name
    # The name on the TV first, then the device's own
    assert input_kind("Living room", "PS5").key == "playstation"
    assert input_kind(None, None).icon == "mdi:video-input-hdmi"


# The Sony's CEC lines, verbatim (only itself, the TV), and a console's line
# in the same format
SONY_CEC = (
    "    mDeviceInfo: CEC: logical_address: 0x00 device_type: 0 cec_version: 5"
    " vendor_id: 524358 display_name: TV power_status: 0"
    " physical_address: 0x0000 port_id: 0\n"
    "    CEC: logical_address: 0x00 device_type: 0 cec_version: 5"
    " vendor_id: 524358 display_name: TV power_status: 0"
    " physical_address: 0x0000 port_id: 0\n"
)
CONSOLE_CEC = (
    "    CEC: logical_address: 0x04 device_type: 4 cec_version: 5"
    " vendor_id: 1234 display_name: PS5 power_status: 1"
    " physical_address: 0x2000 port_id: 2\n"
)


def test_cec_devices() -> None:
    from googletv_parsers import parse_cec

    assert parse_cec(SONY_CEC) == {}
    assert parse_cec(SONY_CEC + CONSOLE_CEC) == {2: "PS5"}


def test_an_unnamed_input_known_by_its_cec_name() -> None:
    state = parse_state(LOTTS_TCL_POLL + "\n@@cec\n" + CONSOLE_CEC)
    xbox, hdmi2, hdmi3 = state.inputs
    # Named on the TV
    assert (xbox.label, xbox.icon, xbox.device) == ("Xbox", "mdi:microsoft-xbox", None)
    # Unnamed, but its device says what it is; its name stays "HDMI 2"
    assert (hdmi2.label, hdmi2.device, hdmi2.kind.key) == (
        "HDMI 2",
        "PS5",
        "playstation",
    )
    assert hdmi3.icon == "mdi:video-input-hdmi"


def test_screensaver_and_diagnostics() -> None:
    from googletv_parsers import parse_awake, parse_diagnostics, parse_wakefulness

    assert parse_awake("  mWakefulness=Dreaming") is True
    assert parse_wakefulness("  mWakefulness=Dreaming") == "Dreaming"
    assert parse_awake("  mWakefulness=Asleep") is False
    state = parse_state(LOTTS_TCL_POLL.replace("Awake", "Dreaming"))
    assert state.awake and state.screensaver
    assert state.activity_state == "screensaver"

    wifi = parse_diagnostics(
        "@@net\nlo 127.0.0.1/8\nwlan0 10.0.4.20/24\n@@wifi\nRSSI: -61\n"
        "@@storage\n/dev/block/dm-5 10000000 2500000 7500000 25% /data\n"
        "@@memory\nMemTotal: 2000000 kB\nMemAvailable: 512000 kB\n"
    )
    assert (wifi.connection, wifi.ip_address, wifi.wifi_signal) == (
        "wifi",
        "10.0.4.20",
        -61,
    )
    assert (wifi.storage_used, wifi.storage_free_mb, wifi.memory_free_mb) == (
        25,
        7324,
        500,
    )
    # Both up: Ethernet is the one in use, and there's no Wi-Fi signal to show
    both = parse_diagnostics(
        "@@net\nwlan0 10.0.4.20/24\neth0 10.0.4.14/24\n@@wifi\nRSSI: -61\n"
    )
    assert (both.connection, both.wifi_signal) == ("ethernet", None)
    assert parse_diagnostics("").connection is None


def test_the_quick_read() -> None:
    from googletv_parsers import parse_quick

    full = parse_state(LOTTS_TCL_POLL)
    quick = parse_quick(
        "@@power\n  mWakefulness=Dreaming\n@@uptime\n10.5 0\n@@sessions\n", full
    )
    # The screen and sessions are new; the app, volume and inputs carry over
    assert quick.screensaver and quick.awake and quick.sessions == []
    assert quick.uptime_ms == 10500
    assert (quick.app, quick.volume, quick.input) == (full.app, full.volume, full.input)

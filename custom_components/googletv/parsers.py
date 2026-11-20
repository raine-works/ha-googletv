"""Turn a Google TV's shell output into state.

Pure functions, no Home Assistant imports, so they're unit tested on output
captured from real TVs (a TCL and a Sony, Android TV 12). Everything a poll
needs comes back from one shell command (``POLL_COMMAND``), split into
``@@<name>`` sections.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import re
from urllib.parse import unquote

# One round trip per poll. ``dumpsys`` output is cut down on the TV (grep, sed,
# awk), so a poll moves a few hundred bytes, not the services' full dumps.
POLL_COMMAND = "; ".join(
    [
        "echo @@power",
        "dumpsys power | grep -m1 'mWakefulness='",
        "echo @@app",
        "dumpsys activity activities"
        " | grep -m1 -E 'topResumedActivity|mResumedActivity'",
        "echo @@audio",
        "dumpsys audio | sed -n '/^- STREAM_MUSIC:/,/Devices:/p'",
        "echo @@uptime",
        "cat /proc/uptime",
        "echo @@sessions",
        "dumpsys media_session"
        " | grep -E 'package=|active=|state=PlaybackState|metadata:'",
        "echo @@inputs",
        # Each HDMI input (hardware type 9) with its port, and the main
        # session's input: the one on screen, none while an app is in front
        "dumpsys tv_input | awk '"
        "/^  [^ ]/{s=0} /^  sessionStateMap:/{s=1} "
        's&&/SessionState@/{t=$1;sub(/:$/,"",t)} '
        "s&&/^      inputId: /{m[t]=$2} "
        "/^  mainSessionToken:/{c=$2} "
        "/^    TvInputHardwareInfo \\{id=[0-9]+, type=9,/{"
        "match($0,/id=[0-9]+/);i=substr($0,RSTART+3,RLENGTH-3);"
        "match($0,/hdmi_port=[0-9]+/);p[i]=substr($0,RSTART+10,RLENGTH-10)} "
        "/^  mHardwareInputIdMap:/{h=1;next} "
        'h&&/^    [0-9]+: /{d=$1;sub(/:$/,"",d);'
        'if(d in p)print "input " $2 " " p[d];next} '
        "/^  [^ ]/{h=0} "
        'END{print "current " (c in m?m[c]:"none")}\'',
        "echo @@labels",
        "settings get secure tv_input_custom_labels",
        "echo @@hidden",
        "settings get secure tv_input_hidden_inputs",
        "echo @@cec",
        # The devices HDMI-CEC knows: each one's name ("PS5") and port
        "dumpsys hdmi_control | grep 'CEC: logical_address'",
    ]
)

# The apps the TV's own launcher shows, with the screen that opens each
APPS_COMMAND = (
    "cmd package query-activities --brief "
    "-a android.intent.action.MAIN -c android.intent.category.LEANBACK_LAUNCHER"
)

# Who the TV is, for the device registry and the config entry's unique id
# The Bluetooth address is the TV's id: Google TVs announce it on the network
# (``bt`` in their ``_androidtvremote2._tcp`` record), so a TV found there is
# matched to its entry before anyone accepts a prompt.
# Read every second between full polls: what shows playing, paused or the
# screen going off (about 100 ms on a TV; the full poll is about 500)
QUICK_COMMAND = "; ".join(
    [
        "echo @@power",
        "dumpsys power | grep -m1 'mWakefulness='",
        "echo @@uptime",
        "cat /proc/uptime",
        "echo @@sessions",
        "dumpsys media_session"
        " | grep -E 'package=|active=|state=PlaybackState|metadata:'",
    ]
)

# Read with the app list (every 10 minutes): the TV's network, storage and
# memory, for its diagnostic sensors
DIAGNOSTICS_COMMAND = "; ".join(
    [
        "echo @@net",
        "ip -o -4 addr show | awk '{print $2, $4}'",
        "echo @@wifi",
        "dumpsys wifi | grep -m1 -oE 'RSSI: -?[0-9]+'",
        "echo @@storage",
        "df -k /data | tail -1",
        "echo @@memory",
        "grep -E 'MemTotal|MemAvailable' /proc/meminfo",
    ]
)

PROPS_COMMAND = "; ".join(
    [
        *(
            f"getprop {prop}"
            for prop in (
                "ro.product.manufacturer",
                "ro.product.model",
                "ro.build.version.release",
                "ro.serialno",
            )
        ),
        "settings get secure bluetooth_address",
        # Its network adapters' MACs, for Wake-on-LAN
        "ip -o link | grep -E ': (eth0|wlan0):'",
    ]
)

# Android's PlaybackState codes
PLAYBACK_STOPPED = 1
PLAYBACK_PAUSED = 2
PLAYBACK_PLAYING = 3
PLAYBACK_BUFFERING = 6

# Readable names for apps that aren't launcher apps, or whose package says
# little ("com.tcl.tv"). Launcher apps are named by ``KNOWN_APPS`` or their
# package.
KNOWN_APPS: dict[str, str] = {
    "com.raineworks.tvbridge": "Raineworks TV",
    "com.google.android.apps.tv.launcherx": "Home screen",
    "com.google.android.tvlauncher": "Home screen",
    "com.android.tv.settings": "Settings",
    "com.google.android.apps.mediashell": "Casting",
    "com.google.android.youtube.tv": "YouTube",
    "com.google.android.youtube.tvunplugged": "YouTube TV",
    "com.google.android.youtube.tvmusic": "YouTube Music",
    "com.google.android.youtube.tvkids": "YouTube Kids",
    "com.google.android.videos": "Google TV",
    "com.google.android.play.games": "Play Games",
    "com.android.vending": "Play Store",
    "com.netflix.ninja": "Netflix",
    "com.amazon.amazonvideo.livingroom": "Prime Video",
    "com.apple.atve.androidtv.appletv": "Apple TV",
    "com.apple.atve.sony.appletv": "Apple TV",
    "com.wbd.stream": "HBO Max",
    "com.hulu.livingroomplus": "Hulu",
    "com.disney.disneyplus": "Disney+",
    "com.cbs.ott": "Paramount+",
    "com.peacocktv.peacockandroid": "Peacock",
    "com.spotify.tv.android": "Spotify",
    "com.plexapp.android": "Plex",
    "tv.pluto.android": "Pluto TV",
    "com.tubitv": "Tubi",
    "com.ava.connect": "AVA Connect",
    # The TVs' own apps for what's plugged in
    "com.tcl.tv": "TV input",
    "com.sony.dtv.tvx": "TV input",
    "com.google.android.tv": "Live Channels",
    "com.android.tv": "Live Channels",
}

# Apps whose sessions are music (the rest are video)
MUSIC_APPS = frozenset(
    {
        "com.spotify.tv.android",
        "com.google.android.youtube.tvmusic",
        "com.amazon.music.tv",
        "com.pandora.android.atv",
        "com.apple.android.music",
    }
)

# The TVs' own apps for HDMI inputs: while one is in front, an input is on screen
# The home screen
HOME_APPS = frozenset(
    {
        "com.google.android.apps.tv.launcherx",  # Google TV
        "com.google.android.tvlauncher",  # Android TV
        "com.google.android.leanbacklauncher",  # older Android TV
    }
)

# What the TV is doing (the Activity sensor's states)
ACTIVITY_OFF = "off"
ACTIVITY_SCREENSAVER = "screensaver"
ACTIVITY_HOME = "home"
ACTIVITY_APP = "app"
ACTIVITY_PLAYING = "playing"
ACTIVITY_PAUSED = "paused"
ACTIVITY_INPUT = "input"
ACTIVITIES = (
    ACTIVITY_OFF,
    ACTIVITY_SCREENSAVER,
    ACTIVITY_HOME,
    ACTIVITY_APP,
    ACTIVITY_PLAYING,
    ACTIVITY_PAUSED,
    ACTIVITY_INPUT,
)

INPUT_APPS = frozenset(
    {
        "com.tcl.tv",
        "com.sony.dtv.tvx",
        "com.google.android.tv",
        "com.android.tv",
        "com.mediatek.wwtv.tvcenter",
    }
)


@dataclass(frozen=True)
class App:
    """An app the launcher shows."""

    package: str
    activity: str
    name: str
    # Its Play Store icon, when the integration has looked it up
    icon: str | None = None


@dataclass(frozen=True)
class InputKind:
    """What an input is, and its icon."""

    key: str
    icon: str


HDMI_INPUT = InputKind("hdmi", "mdi:video-input-hdmi")

# Matched in order against an input's name on the TV, then its device's CEC
# name; a name matching none is an HDMI input. "Switch" alone is Nintendo's,
# "HDMI switch" isn't.
INPUT_KINDS: tuple[tuple[InputKind, re.Pattern[str]], ...] = tuple(
    (InputKind(key, icon), re.compile(pattern, re.IGNORECASE))
    for key, icon, pattern in (
        ("xbox", "mdi:microsoft-xbox", r"xbox"),
        (
            "playstation",
            "mdi:sony-playstation",
            r"playstation|\bps ?[1-5]\b|\bps ?vita\b|\bpsx\b",
        ),
        ("nintendo_switch", "mdi:nintendo-switch", r"nintendo|^switch\b|\bswitch ?2\b"),
        ("nintendo_wii", "mdi:nintendo-wii", r"\bwii\b|\bwii ?u\b"),
        ("steam", "mdi:steam", r"steam"),
        ("apple_tv", "mdi:apple", r"apple ?tv"),
        ("laptop", "mdi:laptop", r"laptop|macbook|notebook"),
        (
            "computer",
            "mdi:desktop-tower-monitor",
            r"\bpc\b|computer|desktop|\bmac\b|imac|mac mini|gaming rig|htpc",
        ),
        (
            "streamer",
            "mdi:television-box",
            r"chromecast|google tv|fire ?tv|fire ?stick|roku|shield|streamer"
            r"|android tv|\bonn\b",
        ),
        (
            "cable",
            "mdi:set-top-box",
            r"cable|satellite|\bdish\b|directv|xfinity|spectrum|tivo|set.?top"
            r"|\bstb\b|\bbox\b",
        ),
        ("disc", "mdi:disc-player", r"blu.?ray|\bdvd\b|\bdisc\b"),
        (
            "audio",
            "mdi:soundbar",
            r"sound ?bar|receiver|\bavr\b|sonos|denon|marantz|yamaha|\bamp\b",
        ),
        ("camera", "mdi:camera", r"camera|camcorder|gopro"),
        ("console", "mdi:controller", r"\bgame|console|retro|arcade|\bsnes\b|\bnes\b"),
    )
)


def input_kind(*names: str | None) -> InputKind:
    """The kind of the first name that matches one, else an HDMI input."""
    for name in names:
        if not name:
            continue
        for kind, pattern in INPUT_KINDS:
            if pattern.search(name):
                return kind
    return HDMI_INPUT


@dataclass(frozen=True)
class TvInput:
    """One of the TV's HDMI inputs."""

    id: str
    port: int
    # The name given to it on the TV ("Xbox"), else "HDMI <port>"
    label: str
    # The name its device gives itself over HDMI-CEC ("PS5"), if it does
    device: str | None = None

    @property
    def named(self) -> bool:
        """Named on the TV (not just "HDMI <port>")."""
        return self.label != f"HDMI {self.port}"

    @property
    def kind(self) -> InputKind:
        """What's on it: by its name on the TV, else by its CEC name."""
        return input_kind(self.label if self.named else None, self.device)

    @property
    def icon(self) -> str:
        """Its icon (an Xbox's, a PlayStation's…, else an HDMI port)."""
        return self.kind.icon


@dataclass(frozen=True)
class MediaSession:
    """An app's media session: what it plays, as the TV's own "now playing" sees it."""

    package: str
    active: bool
    state: int
    position_ms: int | None
    updated_ms: int | None
    speed: float
    title: str | None
    # The show, channel or artist (Spotify: "artist, album")
    subtitle: str | None
    # The app's own line about it, seldom set
    description: str | None

    @property
    def playing(self) -> bool:
        """Playing (or buffering on its way to playing)."""
        return self.state in (PLAYBACK_PLAYING, PLAYBACK_BUFFERING)

    def position_at(self, uptime_ms: int) -> float | None:
        """Seconds in at the TV's uptime ``uptime_ms``, counting on while it plays."""
        if self.position_ms is None:
            return None
        elapsed = 0.0
        if self.playing and self.updated_ms is not None:
            elapsed = max(0, uptime_ms - self.updated_ms) * self.speed
        return (self.position_ms + elapsed) / 1000


@dataclass
class TvState:
    """One poll's worth of a TV."""

    # The screen is on: awake, or showing the screensaver
    awake: bool = False
    app: str | None = None
    activity: str | None = None
    volume: float | None = None
    muted: bool | None = None
    # The media stream's top step (100 on a Sony, 15 or 25 on others)
    volume_max: int | None = None
    # The screensaver ("Dreaming") is showing
    screensaver: bool = False
    uptime_ms: int = 0
    sessions: list[MediaSession] = field(default_factory=list)
    inputs: list[TvInput] = field(default_factory=list)
    # The input on screen, while one is
    input: TvInput | None = None

    @property
    def now_playing(self) -> MediaSession | None:
        """The front app's session, else whichever is playing."""
        return now_playing(self.sessions, self.app)

    @property
    def activity_state(self) -> str:
        """What the TV is doing, for automations (``ACTIVITIES``)."""
        if not self.awake:
            return ACTIVITY_OFF
        playing = self.now_playing
        if self.screensaver:
            # Music plays on under the screensaver (Google TV's ambient mode)
            return (
                ACTIVITY_PLAYING
                if playing and playing.playing
                else ACTIVITY_SCREENSAVER
            )
        if self.input:
            # The input's device is on screen, whatever plays behind it
            return ACTIVITY_INPUT
        if playing and playing.playing:
            return ACTIVITY_PLAYING
        if playing and playing.state == PLAYBACK_PAUSED:
            return ACTIVITY_PAUSED
        if self.app in HOME_APPS or not self.app:
            return ACTIVITY_HOME
        return ACTIVITY_APP


def split_sections(raw: str) -> dict[str, str]:
    """``@@name`` sections of a command's output, by name."""
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in raw.splitlines():
        if line.startswith("@@"):
            current = sections.setdefault(line[2:].strip(), [])
        elif current is not None:
            current.append(line)
    return {name: "\n".join(lines) for name, lines in sections.items()}


def parse_wakefulness(text: str) -> str | None:
    """``mWakefulness``: Awake, Dreaming (the screensaver), Dozing or Asleep."""
    match = re.search(r"mWakefulness=(\w+)", text)
    return match.group(1) if match else None


def parse_awake(text: str) -> bool:
    """The screen is on: awake, or showing the screensaver (Dreaming)."""
    return parse_wakefulness(text) in ("Awake", "Dreaming")


def parse_front_app(text: str) -> tuple[str, str] | None:
    """The app in front and its screen, from the resumed activity's record."""
    match = re.search(r"ActivityRecord\{\S+ \S+ ([\w.]+)/([\w.$]+)", text)
    if not match:
        return None
    package, activity = match.groups()
    if activity.startswith("."):
        activity = package + activity
    return package, activity


def parse_audio(text: str) -> tuple[float | None, bool | None, int | None]:
    """The media stream's volume (0 to 1), whether it's muted, its top step."""
    muted = re.search(r"^\s*Muted: (true|false)", text, re.M)
    volume = re.search(r"streamVolume:(\d+)", text)
    maximum = re.search(r"^\s*Max: (\d+)", text, re.M)
    top = int(maximum.group(1)) if maximum else None
    level = None
    if volume and top:
        level = min(1.0, int(volume.group(1)) / top)
    return level, (muted.group(1) == "true") if muted else None, top or None


def parse_uptime_ms(text: str) -> int:
    """The TV's uptime in ms, the clock media sessions date their position by."""
    try:
        return int(float(text.split()[0]) * 1000)
    except (IndexError, ValueError):
        return 0


def _description(text: str) -> tuple[str | None, str | None, str | None]:
    """A session's "title, subtitle, description", "null" for none.

    The fields are joined with ", " unescaped, so a comma inside one is
    ambiguous: the title is the first part and the description the last, and
    everything between is the subtitle (Spotify's "artist, album").
    """
    parts = text.split(", ")
    if len(parts) < 3:
        parts += ["null"] * (3 - len(parts))
    fields = (parts[0], ", ".join(parts[1:-1]), parts[-1])
    title, subtitle, description = (
        None if f.strip() in ("", "null") else f.strip() for f in fields
    )
    return title, subtitle, description


def parse_sessions(text: str) -> list[MediaSession]:
    """Every media session ``dumpsys media_session`` lists."""
    sessions: list[MediaSession] = []
    fields: dict[str, object] = {}

    def flush() -> None:
        if fields.get("package"):
            sessions.append(
                MediaSession(
                    package=str(fields["package"]),
                    active=bool(fields.get("active", False)),
                    state=int(fields.get("state", 0)),  # type: ignore[arg-type]
                    position_ms=fields.get("position"),  # type: ignore[arg-type]
                    updated_ms=fields.get("updated"),  # type: ignore[arg-type]
                    speed=float(fields.get("speed", 0.0)),  # type: ignore[arg-type]
                    title=fields.get("title"),  # type: ignore[arg-type]
                    subtitle=fields.get("subtitle"),  # type: ignore[arg-type]
                    description=fields.get("description"),  # type: ignore[arg-type]
                )
            )

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("package="):
            flush()
            fields = {"package": line.split("=", 1)[1].strip()}
        elif line.startswith("active="):
            fields["active"] = line.split("=", 1)[1].strip() == "true"
        elif line.startswith("state=PlaybackState"):
            for key, pattern, cast in (
                # "state=3", or by name on newer builds: "state=ERROR(7)"
                ("state", r"\{state=(?:[A-Z_]+\()?(\d+)", int),
                ("position", r"position=(-?\d+)", int),
                ("updated", r"updated=(-?\d+)", int),
                ("speed", r"speed=([\d.]+)", float),
            ):
                match = re.search(pattern, line)
                if match:
                    fields[key] = cast(match.group(1))
            if fields.get("position", 0) < 0:  # type: ignore[operator]
                fields["position"] = None
        elif line.startswith("metadata:"):
            match = re.search(r"description=(.*)$", line)
            if match:
                fields["title"], fields["subtitle"], fields["description"] = (
                    _description(match.group(1))
                )
    flush()
    return sessions


def now_playing(
    sessions: list[MediaSession], front_app: str | None
) -> MediaSession | None:
    """The front app's session while it plays or pauses, else the one playing."""
    for session in sessions:
        if (
            session.package == front_app
            and session.state in (PLAYBACK_PLAYING, PLAYBACK_PAUSED, PLAYBACK_BUFFERING)
            and session.title
        ):
            return session
    return next((s for s in sessions if s.playing and s.title), None)


def _decode(value: str) -> str:
    """The TV's URL-encoded settings text."""
    return unquote(value).strip()


def parse_inputs(
    inputs_text: str, labels_text: str, hidden_text: str
) -> tuple[list[TvInput], str | None]:
    """The TV's HDMI inputs (by port, named) and the id of the one on screen.

    The names are the TV's own (``tv_input_custom_labels``: URL-encoded
    ``id,label`` pairs separated by ``:``); hidden inputs are left out.
    """
    labels: dict[str, str] = {}
    raw_labels = labels_text.strip()
    if raw_labels and raw_labels != "null":
        for pair in raw_labels.split(":"):
            if "," in pair:
                input_id, label = pair.split(",", 1)
                labels[_decode(input_id)] = _decode(label)
    raw_hidden = hidden_text.strip()
    hidden = (
        {_decode(i) for i in raw_hidden.split(":") if i.strip()}
        if raw_hidden and raw_hidden != "null"
        else set()
    )

    inputs: list[TvInput] = []
    current: str | None = None
    for line in inputs_text.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[0] == "input" and fields[1] not in hidden:
            try:
                port = int(fields[2])
            except ValueError:
                continue
            inputs.append(
                TvInput(fields[1], port, labels.get(fields[1]) or f"HDMI {port}")
            )
        elif len(fields) >= 2 and fields[0] == "current" and fields[1] != "none":
            current = fields[1]
    inputs.sort(key=lambda i: i.port)
    return inputs, current


def input_on_screen(inputs: list[TvInput], current: str | None) -> TvInput | None:
    """The input on screen, by its id.

    A device on HDMI-CEC gets an input of its own, named for its CEC address
    (".../HDMI100004": physical address 1.0.0.0, logical address 4), so that
    one counts as its port's input (seen on a TCL with an Xbox).
    """
    if not current:
        return None
    for tv_input in inputs:
        if tv_input.id == current:
            return tv_input
    match = re.search(r"HDMI([0-9a-fA-F])[0-9a-fA-F]{5}$", current)
    if match:
        port = int(match.group(1), 16)
        return next((i for i in inputs if i.port == port), None)
    return None


def parse_quick(raw: str, previous: TvState) -> TvState:
    """``QUICK_COMMAND``'s screen and media sessions over the last full poll."""
    sections = split_sections(raw)
    power = sections.get("power", "")
    return replace(
        previous,
        awake=parse_awake(power),
        screensaver=parse_wakefulness(power) == "Dreaming",
        uptime_ms=parse_uptime_ms(sections.get("uptime", "")),
        sessions=parse_sessions(sections.get("sessions", "")),
    )


def parse_cec(text: str) -> dict[int, str]:
    """The name each HDMI-CEC device gives itself, by the port it's on.

    Lines like ``CEC: logical_address: 0x04 device_type: 4 … display_name:
    PS5 power_status: 0 physical_address: 0x2000 port_id: 2``; the TV itself
    (physical address 0.0.0.0) is left out.
    """
    devices: dict[int, str] = {}
    for line in text.splitlines():
        match = re.search(
            r"display_name: (.*?) power_status: .*?"
            r"physical_address: 0x([0-9a-fA-F]{4})(?:.*?port_id: (\d+))?",
            line,
        )
        if not match or match.group(2) == "0000":
            continue
        name = match.group(1).strip()
        port = int(match.group(3) or 0) or int(match.group(2)[0], 16)
        if name and port and port not in devices:
            devices[port] = name
    return devices


def parse_state(raw: str) -> TvState:
    """A TV's state from ``POLL_COMMAND``'s output."""
    sections = split_sections(raw)
    front = parse_front_app(sections.get("app", ""))
    volume, muted, volume_max = parse_audio(sections.get("audio", ""))
    inputs, current = parse_inputs(
        sections.get("inputs", ""),
        sections.get("labels", ""),
        sections.get("hidden", ""),
    )
    cec = parse_cec(sections.get("cec", ""))
    inputs = [replace(i, device=cec.get(i.port)) for i in inputs]
    app = front[0] if front else None
    shown = input_on_screen(inputs, current)
    # A session left from an input the TV has since left (an app in front that
    # isn't one of its input apps) doesn't count
    if shown and app and app not in INPUT_APPS and app in KNOWN_APPS:
        shown = None
    return TvState(
        awake=parse_awake(sections.get("power", "")),
        screensaver=parse_wakefulness(sections.get("power", "")) == "Dreaming",
        app=app,
        activity=front[1] if front else None,
        volume=volume,
        muted=muted,
        volume_max=volume_max,
        uptime_ms=parse_uptime_ms(sections.get("uptime", "")),
        sessions=parse_sessions(sections.get("sessions", "")),
        inputs=inputs,
        input=shown,
    )


def app_name(package: str | None) -> str | None:
    """An app's readable name: a known one, else its package."""
    if not package:
        return None
    return KNOWN_APPS.get(package, package)


def parse_apps(text: str) -> list[App]:
    """The launcher's apps (``APPS_COMMAND``), each once, by name."""
    apps: dict[str, App] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*([\w.]+)/([\w.$]+)\s*$", line)
        if not match:
            continue
        package, activity = match.groups()
        if activity.startswith("."):
            activity = package + activity
        if package not in apps:
            apps[package] = App(package, activity, KNOWN_APPS.get(package, package))
    return sorted(apps.values(), key=lambda a: a.name.lower())


def parse_props(text: str) -> dict[str, str]:
    """Maker, model, Android version, serial, Bluetooth address and MACs."""
    keys = ("manufacturer", "model", "android", "serial", "bluetooth")
    lines = text.splitlines()
    values = [line.strip() for line in lines[: len(keys)]]
    props = {k: v for k, v in zip(keys, values, strict=False) if v and v != "null"}
    if "bluetooth" in props:
        props["bluetooth"] = props["bluetooth"].lower()
    for adapter, mac in re.findall(
        r": (eth0|wlan0):.*?link/ether ([0-9a-fA-F:]{17})", text
    ):
        props["mac_ethernet" if adapter == "eth0" else "mac_wifi"] = mac.lower()
    return props


CONNECTION_ETHERNET = "ethernet"
CONNECTION_WIFI = "wifi"


@dataclass(frozen=True)
class Diagnostics:
    """The TV's network, storage and memory (``DIAGNOSTICS_COMMAND``)."""

    connection: str | None = None
    ip_address: str | None = None
    wifi_signal: int | None = None
    storage_used: int | None = None
    storage_free_mb: int | None = None
    memory_free_mb: int | None = None
    memory_total_mb: int | None = None


def parse_diagnostics(raw: str) -> Diagnostics:
    """The diagnostics from ``DIAGNOSTICS_COMMAND``'s output."""
    sections = split_sections(raw)
    connection = ip_address = None
    for line in sections.get("net", "").splitlines():
        fields = line.split()
        if len(fields) < 2 or fields[0] == "lo":
            continue
        kind = (
            CONNECTION_ETHERNET
            if fields[0].startswith("eth")
            else CONNECTION_WIFI
            if fields[0].startswith("wlan")
            else None
        )
        # Ethernet wins when both are up: it's the one the TV uses
        if kind and connection != CONNECTION_ETHERNET:
            connection, ip_address = kind, fields[1].split("/")[0]
    rssi = re.search(r"RSSI: (-?\d+)", sections.get("wifi", ""))
    wifi_signal = int(rssi.group(1)) if rssi and connection == CONNECTION_WIFI else None
    # A plausible signal only: -127 means none
    if wifi_signal is not None and not -110 <= wifi_signal < 0:
        wifi_signal = None
    storage_used = storage_free = None
    df = re.search(r"\s(\d+)\s+(\d+)\s+(\d+)\s+(\d+)%", sections.get("storage", ""))
    if df:
        storage_free = int(df.group(3)) // 1024
        storage_used = int(df.group(4))
    memory = dict(
        re.findall(
            r"^(MemTotal|MemAvailable):\s+(\d+) kB", sections.get("memory", ""), re.M
        )
    )
    return Diagnostics(
        connection=connection,
        ip_address=ip_address,
        wifi_signal=wifi_signal,
        storage_used=storage_used,
        storage_free_mb=storage_free,
        memory_free_mb=int(memory["MemAvailable"]) // 1024
        if "MemAvailable" in memory
        else None,
        memory_total_mb=int(memory["MemTotal"]) // 1024
        if "MemTotal" in memory
        else None,
    )

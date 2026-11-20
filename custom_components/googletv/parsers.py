"""Turn a Google TV's shell output into state.

Pure functions, no Home Assistant imports, so they're unit tested on output
captured from real TVs (a TCL and a Sony, Android TV 12). Everything a poll
needs comes back from one shell command (``POLL_COMMAND``), split into
``@@<name>`` sections.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
class TvInput:
    """One of the TV's HDMI inputs."""

    id: str
    port: int
    # The name given to it on the TV ("Xbox"), else "HDMI <port>"
    label: str


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

    awake: bool = False
    app: str | None = None
    activity: str | None = None
    volume: float | None = None
    muted: bool | None = None
    uptime_ms: int = 0
    sessions: list[MediaSession] = field(default_factory=list)
    inputs: list[TvInput] = field(default_factory=list)
    # The input on screen, while one is
    input: TvInput | None = None

    @property
    def now_playing(self) -> MediaSession | None:
        """The front app's session, else whichever is playing."""
        return now_playing(self.sessions, self.app)


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


def parse_awake(text: str) -> bool:
    """The screen is on (``mWakefulness=Awake``); Asleep and Dreaming count as off."""
    match = re.search(r"mWakefulness=(\w+)", text)
    return bool(match) and match.group(1) == "Awake"


def parse_front_app(text: str) -> tuple[str, str] | None:
    """The app in front and its screen, from the resumed activity's record."""
    match = re.search(r"ActivityRecord\{\S+ \S+ ([\w.]+)/([\w.$]+)", text)
    if not match:
        return None
    package, activity = match.groups()
    if activity.startswith("."):
        activity = package + activity
    return package, activity


def parse_audio(text: str) -> tuple[float | None, bool | None]:
    """The media stream's volume (0 to 1) and whether it's muted."""
    muted = re.search(r"^\s*Muted: (true|false)", text, re.M)
    volume = re.search(r"streamVolume:(\d+)", text)
    maximum = re.search(r"^\s*Max: (\d+)", text, re.M)
    level = None
    if volume and maximum and int(maximum.group(1)) > 0:
        level = int(volume.group(1)) / int(maximum.group(1))
    return level, (muted.group(1) == "true") if muted else None


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


def parse_state(raw: str) -> TvState:
    """A TV's state from ``POLL_COMMAND``'s output."""
    sections = split_sections(raw)
    front = parse_front_app(sections.get("app", ""))
    volume, muted = parse_audio(sections.get("audio", ""))
    inputs, current = parse_inputs(
        sections.get("inputs", ""),
        sections.get("labels", ""),
        sections.get("hidden", ""),
    )
    app = front[0] if front else None
    shown = input_on_screen(inputs, current)
    # A session left from an input the TV has since left (an app in front that
    # isn't one of its input apps) doesn't count
    if shown and app and app not in INPUT_APPS and app in KNOWN_APPS:
        shown = None
    return TvState(
        awake=parse_awake(sections.get("power", "")),
        app=app,
        activity=front[1] if front else None,
        volume=volume,
        muted=muted,
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
    """Maker, model, Android version, serial and Bluetooth address."""
    keys = ("manufacturer", "model", "android", "serial", "bluetooth")
    values = [line.strip() for line in text.splitlines()]
    props = {k: v for k, v in zip(keys, values, strict=False) if v and v != "null"}
    if "bluetooth" in props:
        props["bluetooth"] = props["bluetooth"].lower()
    return props

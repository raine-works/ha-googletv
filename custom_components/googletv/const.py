"""Constants for the Google TV integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "googletv"

DEFAULT_PORT = 5555

# Option: look up apps' names and icons (Google Play) and artwork for what's
# playing (iTunes, TVmaze). On by default; off keeps everything on the LAN.
CONF_ONLINE_LOOKUPS = "online_lookups"

# The TV's maker, model, serial and MACs, kept in its entry: it's set up from
# them when Home Assistant starts with the TV off its network, and Wake-on-LAN
# needs its MACs then
CONF_PROPS = "props"

# The Raineworks TV Bridge app's token, from pairing with it over ADB
CONF_BRIDGE_TOKEN = "bridge_token"
# Install the app once the TV is set up (asked when it's added)
CONF_INSTALL_BRIDGE = "install_tv_app"

# The RSA key Home Assistant signs in to every TV with, kept in its storage
# folder. Each TV trusts it once ("Allow USB debugging?", Always allow).
ADB_KEY_FILE = "googletv_adbkey"

# How often a TV is read: one shell command, a few hundred bytes back
SCAN_INTERVAL = timedelta(seconds=1)
# Of those, how often the full read (the app, volume, inputs) is; the others
# read only the screen and what's playing, so a pause shows within a second
FULL_INTERVAL = timedelta(seconds=5)
# How often the launcher's app list is read again (it changes on installs)
APPS_INTERVAL = timedelta(minutes=10)

# How long the setup waits for someone to accept the TV's prompt
AUTH_TIMEOUT_S = 60.0
# How long a connection attempt waits after that, once the TV trusts the key
CONNECT_TIMEOUT_S = 10.0
COMMAND_TIMEOUT_S = 10.0

# Android key codes the remote and media controls send (input keyevent)
KEYCODES: dict[str, int] = {
    "HOME": 3,
    "BACK": 4,
    "DPAD_UP": 19,
    "DPAD_DOWN": 20,
    "DPAD_LEFT": 21,
    "DPAD_RIGHT": 22,
    "DPAD_CENTER": 23,
    "VOLUME_UP": 24,
    "VOLUME_DOWN": 25,
    "POWER": 26,
    "MENU": 82,
    "MEDIA_PLAY_PAUSE": 85,
    "MEDIA_STOP": 86,
    "MEDIA_NEXT": 87,
    "MEDIA_PREVIOUS": 88,
    "MEDIA_REWIND": 89,
    "MEDIA_FAST_FORWARD": 90,
    "MEDIA_PLAY": 126,
    "MEDIA_PAUSE": 127,
    "VOLUME_MUTE": 164,
    "INFO": 165,
    "CHANNEL_UP": 166,
    "CHANNEL_DOWN": 167,
    "TV_INPUT": 178,
    "SETTINGS": 176,
    "SLEEP": 223,
    "WAKEUP": 224,
    "SEARCH": 84,
    "ENTER": 66,
}

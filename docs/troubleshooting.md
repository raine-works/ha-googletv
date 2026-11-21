# Troubleshooting

**The TV shows as off while it's on standby.** Keep it reachable in standby
so it can be woken and read: on Sony, Settings → Network & Internet →
**Remote start** (some models: Settings → System → Power and energy →
**Network standby**); on TCL, Hisense and others, look for **Network
standby**, **Wake on LAN** or **Quick start**. A TV that drops off its
network anyway is shown **off**, not unavailable, and **Turn on** sends
Wake-on-LAN to its MACs.

**Home Assistant asks to reconnect the TV.** The TV forgot Home Assistant's
key (debugging was turned off and on, or the TV was reset). Open the repair,
be at the TV, and accept the prompt again.

**The TV moved to a new address.** A discovered TV is followed by itself;
otherwise use the integration's **Reconfigure**.

**A live notification is stuck.** Home Assistant takes it down when its
entity changes, or with `googletv.dismiss_notifications`; on the TV, the
app's **Pop-ups → Clear pop-ups** clears them all.

**"Needs ADB".** The TV is connected through its app alone, and only ADB
can do that (the D-pad, turning it off). Add ADB: see [Setup](setup.md).

**Notifications don't show.** Check the media player's `tv_bridge`
attribute. `not_installed`: run **Install the TV app**. `installed` but not
`paired`: it pairs by itself within a few minutes. In the TV app's
**Permissions**, **Pop-ups over other apps** must say Allowed (Home
Assistant allows it when it installs the app).

**A doorbell clip or `/media` image doesn't show.** Home Assistant signs
its own links for the TV, but needs to know its address: set it in
Settings → System → Network (the local address the TV can reach).

**A camera takes seconds to go live, not one.** WebRTC (live in under a
second) needs the camera's stream in H.264: an H.265 camera (UniFi
Protect's "Enhanced encoding", many 4K cameras) is refused over WebRTC
("codecs not matched" in the TV's log) and plays over HLS instead, a few
seconds later. Many TVs (MediaTek chips: Sony, TCL, Hisense) have one
hardware H.265 decoder, which the show you're watching holds; the TV app
then decodes in software (its log says which decoder it got:
`adb logcat -s TvBridge`). For live in a second, give the camera an H.264
stream: turn off Enhanced encoding in UniFi Protect, or have go2rtc
transcode it.

**The TV app is behind the integration.** Over ADB it's updated by itself
when Home Assistant next reads the TV; `googletv.install_tv_bridge` does it
now. Through the app alone, a repair says so: update it where it came from.

**No inputs.** Inputs come from Android's TV input service, used by TCL
(Google TV) and Sony (Android TV) among others; a TV whose maker doesn't use
it shows none.

**Another ADB integration.** Only one ADB client can hold a TV comfortably:
remove the TV from Home Assistant's **Android Debug Bridge** integration (or
anything else using ADB on it) first.

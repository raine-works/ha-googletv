# Privacy and security

* **Local.** The integration talks to the TV over ADB and to the TV app over
  HTTP on your network. Neither goes through Google or the internet.
* **Online lookups**, on by default: app names and icons from Google Play
  (kept in `.storage/googletv.apps`, read again monthly), and artwork for
  what's playing from iTunes, TVmaze, Google Play and Wikipedia. No account
  or key. Turn off **Look up app icons and artwork online** in the TV's
  options (Settings → Devices & services → Raineworks TV →
  Configure → General) to keep everything on your network.
* **ADB.** Home Assistant signs in to every TV with one key, kept in
  `.storage/googletv_adbkey`; each TV trusts it once.
* **Installing or updating the TV app**, Home Assistant checks the
  download against the SHA-256 published with each release before it goes
  on the TV. Releases are signed with the project's private release key. A
  copy on the TV signed with another key (an older build) can't be updated:
  Home Assistant uninstalls it once, logs why, and installs the new one,
  which pairs again by itself.
* **The TV app** pairs with Home Assistant when you choose **Allow** on the
  TV, or over ADB; no code is typed. Every request after that carries its
  token. Ten wrong pairing codes lock pairing for ten minutes. Removing the
  TV from Home Assistant unpairs it.
* **Links sent to the TV** (a notification's image, clip or icon) that
  point at Home Assistant are signed for 15 minutes as Home Assistant's
  read-only content user, so the TV can load them without a sign-in of its
  own. A clip is kept on the TV only while its pop-up is up.
* **Cameras over WebRTC**: the TV app signs in to Home Assistant's
  websocket as the TV's own user (the one dashboards use, read-only unless
  you allow control) and asks for the camera there, as Home Assistant's
  frontend does. Home Assistant gives the app that user's token once; it's
  kept on the TV, and **Forget all Home Assistant pairings** removes it.
* **Dashboards** use the TV's own Home Assistant user
  ([see Media and dashboards](media-and-dashboards.md)), and stay on Home Assistant: a link to
  another site isn't followed, and only Home Assistant's own pages get the
  sign-in.

# Publishing the TV app on Google Play

What's ready in this repo, and what only the account holder can do. The app
is `com.raineworks.tvbridge`, the TV half of Raineworks TV.

## Ready

* **The build**: targets Android 16 (API 36), as new apps on Google Play
  must. `./gradlew bundleRelease -Pplay` builds the app bundle, signed with
  the private upload key from the environment (never the sideload key that
  sits in this repo for sideloaded builds).
* **CI**: `.github/workflows/play.yaml` builds the signed bundle after every
  release (or by hand, Actions → Google Play → Run workflow), keeps it as an
  artifact, and, given a service account, uploads it to the internal
  testing track as a draft.
* **Graphics**, in `android/play/`: the hi-res icon (512×512), the TV banner
  (1280×720), the feature graphic (1024×500), and TV screenshots
  (1920×1080) in `screenshots/`.
* **The privacy policy**: [`docs/privacy-policy.md`](docs/privacy-policy.md), published at
  `https://raineworks.com/projects/ha-googletv/docs/privacy-policy` (raineworks.com renders this repository's docs).
* **The integration** knows a Play install: it doesn't sideload over it
  (Play keeps it up to date).

## To do (the account holder)

1. **A Google Play developer account** (one-time fee) at
   <https://play.google.com/console>, with identity verification.
2. **The upload key**, made once and kept safe (a password manager, and a
   backup: losing it means asking Google to reset it):

   ```bash
   keytool -genkeypair -keystore upload.jks -alias upload \
     -keyalg RSA -keysize 4096 -validity 10000
   base64 -i upload.jks | pbcopy     # for the GitHub secret
   ```

3. **GitHub secrets** (Settings → Secrets and variables → Actions):
   `UPLOAD_KEYSTORE_BASE64`, `UPLOAD_KEYSTORE_PASSWORD` (and
   `UPLOAD_KEY_PASSWORD` if the key's differs). Then run **Actions → Google
   Play → Run workflow** and download the `.aab` artifact.
4. **Create the app** in the Play Console: name, default language, App,
   Free. Enrol in **Play App Signing** (Google keeps the app's signing key;
   you upload with yours).
5. **Android TV**: Setup → Advanced settings → **Release types** → add
   **Android TV**. Upload the TV banner and TV screenshots. Google reviews
   TV apps for TV quality (D-pad navigation, the banner, no touchscreen
   required, which this app meets).
6. **The first release**, by hand: Testing → **Internal testing** → Create
   release → upload the `.aab`. Add yourself as a tester, install it from
   the Play Store on a Google TV, and check the [things to test](#test-on-real-tvs).
7. **The App content forms**, with the answers below: privacy policy, app
   access, ads, content rating, target audience, data safety, government
   apps, financial features, health, and the foreground service
   declaration.
8. **A Play release for every GitHub release** (after the first release):
   the Release workflow starts the Google Play workflow for each release it
   publishes, which builds that tag's bundle and, with a service account,
   uploads it. Set up the service account once:
   1. Google Cloud console: a project (any), **enable the Google Play Android
      Developer API**, then IAM → Service accounts → create one (no roles
      needed) → Keys → Add key → JSON.
   2. Play Console → **Users and permissions** → Invite new users → the
      service account's email → App permissions: Raineworks TV, with
      **Release to testing tracks** (and **Release to production** for
      production) → Invite.
   3. GitHub: the JSON key's contents as the `PLAY_SERVICE_ACCOUNT_JSON`
      secret.
   Releases then land on the `PLAY_TRACK` variable's track (internal when
   unset) as drafts. Once the app is published, set `PLAY_RELEASE_STATUS` to
   `completed` to roll them out without promoting each by hand; `alpha` is
   the closed test, `production` the store. Every release needs a new
   version: the version code comes from the manifest's version.
9. **Production**: promote the tested release. New personal developer
   accounts must first run a **closed test** with at least 12 testers for 14
   days before production access.

## Listing

**App name** (30 characters at most): `Raineworks TV`

> **Why this name and icon.** Google Play's impersonation policy rejects
> apps whose name or icon suggests another company made them. The name is
> Raineworks', the icon is the Raineworks mark (Google TV's icon only as a
> small badge for where it runs), and the description and the app's About
> screen say it isn't Google's. If review still objects to the badge,
> `brand/art.py` draws every icon: drop the badge there.

**Short description** (80 characters at most):

> Home Assistant on your TV: notifications, cameras, buttons, media, dashboards.

**Full description**:

> Connect your Google TV or Android TV to Home Assistant.
>
> Notifications from Home Assistant pop up over whatever's on (shows,
> games, HDMI inputs) with an image or a live camera, a progress bar, and
> buttons you answer with the remote: Unlock the door without leaving the
> couch. Live notifications stay up while something's true, like the front
> door being open, and update as it changes.
>
> Home Assistant can also play its media on the TV, speak announcements
> over your show (which turns down, then back up), and show any dashboard
> full screen. And it knows what the TV is doing: what's playing, the app in
> front, the volume, as it happens.
>
> Choose on the TV which apps Home Assistant shows, and which ones
> notifications may pop up over.
>
> Setup takes a minute: add the Raineworks TV integration to Home
> Assistant (from the Home Assistant Marketplace), and choose Allow on the TV when it asks. No
> developer options, no codes. For the remote's keys, turning the TV off
> and knowing its HDMI input, turn on network debugging; the app shows how.
>
> Requires Home Assistant with the Raineworks TV integration
> (github.com/raine-works/ha-googletv). Everything stays on your network:
> the app talks only to your Home Assistant.
>
> Not affiliated with Google. Google TV and Android TV are trademarks of
> Google LLC.

**Category**: Tools (or House & Home). **Contact**: a support email the
Console asks for, and the website `https://github.com/raine-works/ha-googletv`.

## App content answers

**App access**: all functionality needs a Home Assistant server on the
user's network. Give the reviewers instructions: "The app connects to the
user's own Home Assistant (home-assistant.io) on their local network, with
the Raineworks TV integration installed. Without one, the app
shows its setup screen (a QR code to the integration, and the steps). No
account or login is involved."

**Ads**: no ads.

**Content rating** (IARC questionnaire): category **Utility, Productivity,
Communication or Other**; no violence, sexuality, language, controlled
substances, gambling; no user-to-user communication or sharing; no
location sharing; no purchases.

**Target audience**: 18 and over (not designed for children).

**Data safety**: the app sends data only to the user's own Home Assistant,
on their local network; nothing to the developer or third parties.

| Question | Answer |
| :--- | :--- |
| Does the app collect or share any of the required user data types? | Yes (it sends some to the user's Home Assistant: see below) |
| Is all user data encrypted in transit? | **No** (plain HTTP on the local network, as Home Assistant usually is) |
| Can users request that data be deleted? | Yes: forget the pairing, or clear the app's data; Home Assistant's data is the user's own |
| App activity → **Other actions** (which app is in front, what's playing) | Collected, not shared; processed for **App functionality**; required for the features that use it, optional overall (the user allows Usage access and Notification access) |
| App info and performance → **Diagnostics** (storage, memory, network) | Collected, not shared; App functionality |
| App activity → **Installed apps** (the launcher's apps, and installs and uninstalls as they happen) | Collected, not shared; App functionality (Home Assistant's app list and buttons) |
| Device or other IDs (the TV's Android ID, to tell TVs apart) | Collected, not shared; App functionality |

Nothing is shared with third parties, and nothing is used for advertising,
analytics or personalisation.

**Foreground service** (`specialUse`): Play Console → App content → Foreground
service permissions.

> The app keeps a local network API running so the user's own Home
> Assistant server can show notifications, cameras, media and dashboards on
> the TV when its automations call for them (a doorbell, an alarm), and can
> read what the TV is doing. It runs while the app is installed (it starts
> when the TV does), so Home Assistant can find the TV and pair with it,
> and reach it afterwards; it shows an ongoing notification while it runs.
> No other foreground service type fits: it isn't media playback,
> data sync, location or a connected device in Android's sense; it's a
> server that must answer whenever Home Assistant calls, which a job or
> WorkManager can't do. Stopping it would lose the user's alerts (someone
> at the door) while they watch TV.

Play may ask for a short video of the feature: record a notification from
Home Assistant popping up over a show, and the app's ongoing notification.

**Sensitive permissions**: none of the app's permissions has a Play
declaration form. For review notes: **Display over other apps** shows Home
Assistant's notifications over shows and inputs; **Usage access** (shown as App detection) tells
Home Assistant which app is in front; **Notification access** reads media
sessions (what's playing), not notifications. Each is the user's choice,
explained in the app's Permissions section.

## Test on real TVs

The emulator has shown setup, pairing, notifications, buttons, media and
dashboards working; before production, check on real hardware (a Chromecast
with Google TV or Google TV Streamer, and a Sony or TCL TV):

* A camera **over WebRTC** on the doorbell pop-up: live within a second or
  so with an H.264 camera, its snapshot until then; an H.265 one is
  refused over WebRTC and plays over HLS (checked on a Sony BRAVIA VH2). Also **with a
  show playing** (YouTube TV, Netflix): on MediaTek TVs the show holds the
  one hardware H.265 decoder, and HLS and clips fall back to software.
* Whether **Settings shows** Display over other apps, Notification access
  and Usage access for the app (the app's Permissions section opens each).
  Where a TV hides one, the app-alone setup loses what it gives; ADB
  allows them.
* Notifications over a show and over an HDMI input; buttons with the
  remote; Back.
* An announcement over Netflix or YouTube: the show turns down, then back
  up.
* The app staying reachable after the TV sleeps and wakes.

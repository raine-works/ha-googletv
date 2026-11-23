# Agent guidance for ha-googletv

## Raineworks base rules

This repository follows Raineworks' base rules, in [`.raineworks/base.md`](.raineworks/base.md): read them before
changing anything. They're a copy of `base.md` in `raine-works/agents`, kept current by its sync: change them there,
not here. Where this file is more specific, it wins.

@.raineworks/base.md

## This repository

Raineworks TV (`custom_components/googletv`, domain `googletv`) is a Home Assistant integration for Google TV and
Android TV that talks to the TV over ADB and to its own TV app over HTTP on the local network. The TV app is an Android
project in `android/` (package `com.raineworks.tvbridge`, API in [protocol/README.md](protocol/README.md)). Design and
how-tos are in [docs/](docs/README.md); [docs/privacy-and-security.md](docs/privacy-and-security.md) states what stays
local and how pairing and tokens work.

- **Check (integration):** `ruff check .`, `ruff format --check .`, and `pytest -q` with `requirements-test.txt` (parser
  tests, no Home Assistant) and again with `requirements-test-ha.txt` (config flow and setup); the `Test` workflow runs
  both. `Validate` runs hassfest and the Marketplace (HACS) validation. Parsers are tested on output captured from real
  TVs ([docs/development.md](docs/development.md)).
- **Check (TV app):** the `TV app` workflow (`android.yaml`) runs
  `./gradlew testReleaseUnitTest assembleRelease lintRelease` in `android/` (Java 17) and publishes the `tv-bridge-dev`
  prerelease from `master`.
- **Version and release:** `version` in `custom_components/googletv/manifest.json` is the one version: the TV app's
  `versionName` and `versionCode` are derived from it in `android/app/build.gradle.kts`. Bump it in the pull request.
  When `Test` passes on `master`, `release.yaml` creates a draft GitHub release `v<version>`, builds and attaches the
  signed APK and its SHA-256 (`raineworks-tv-bridge.apk`, which Home Assistant checks before installing) and publishes
  it.
- **Signing:** the TV app isn't on Google Play: Home Assistant installs it over ADB. Release builds are signed with a
  private key held in repository secrets (`UPLOAD_KEYSTORE_BASE64`, `UPLOAD_KEYSTORE_PASSWORD`, `UPLOAD_KEY_PASSWORD`,
  `UPLOAD_KEY_ALIAS`), given only to jobs on `master`, never to a pull request's; local and pull request builds use
  Android's debug key. See [docs/development.md](docs/development.md).
- Home Assistant checks the SHA-256 before installing the TV app, and when the TV's copy is signed with another key
  uninstalls it once and installs again (`GoogleTvClient.async_install_apk`).
- Adding or widening an Android permission, or anything the TV app serves to the network, needs a reason in the pull
  request and an update to the protocol and security docs.

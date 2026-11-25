# Agent guidance for ha-googletv

## Raineworks base rules

This repository follows Raineworks' base rules, in [`.raineworks/base.md`](.raineworks/base.md): read them before
changing anything. They're a copy of `base.md` in `raine-works/agents`, kept current by its sync: change them there,
not here. Where this file is more specific, it wins.

@.raineworks/base.md

## This repository

Google TV by Raineworks (`custom_components/googletv`, domain `googletv`) is a Home Assistant integration for Google
TV and Android TV that talks to the TV over ADB and to its own TV app over HTTP on the local network. The TV app is an
Android project in `android/` (package `com.raineworks.tvbridge`, API in [protocol/README.md](protocol/README.md)).
Design and how-tos are in [docs/](docs/README.md); [docs/privacy-and-security.md](docs/privacy-and-security.md) states
what stays local and how pairing and tokens work. The integration, its Home Assistant icon and the TV app share one
name and Google TV's icon (`brand/art.py` draws them all).

- **Check (integration):** `ruff check .`, `ruff format --check .`, and `pytest -q` with `requirements-test.txt` (parser
  tests, no Home Assistant) and again with `requirements-test-ha.txt` (config flow and setup); the `Test` workflow runs
  both. `Validate` runs hassfest and the Marketplace (HACS) validation. Parsers are tested on output captured from real
  TVs ([docs/development.md](docs/development.md)).
- **Check (TV app):** the `TV app` workflow (`android.yaml`) runs
  `./gradlew testReleaseUnitTest assembleRelease lintRelease` in `android/` (Java 17) and publishes the `tv-bridge-dev`
  prerelease from `master`.
- **Pinning exception:** `manifest.json` requires `adb-shell[async]>=0.4.4`, a minimum, not `==`. Home Assistant
  itself depends on adb-shell and hassfest refuses an exact pin on such a package, so the ecosystem doesn't allow one
  here. Its minimum is the version `requirements-test-ha.txt` pins exactly; every other requirement is `==`
  (`tests/test_manifest.py` checks both). See [docs/development.md](docs/development.md).
- **Version and release:** `version` in `custom_components/googletv/manifest.json` is the one version: the TV app's
  `versionName` and `versionCode` are derived from it in `android/app/build.gradle.kts`. Never bump it by hand:
  `release-pr.yml` (Raineworks' shared Release pull request) keeps one pull request, `Release v<version>`, open on
  `master` with the next version (major for a breaking change, `type!:`; minor for a `feat`; patch for anything else
  that changes `custom_components/`, `android/` or `protocol/`), and merging it is the release. When `Test` passes on
  `master`, `release.yaml` creates a draft GitHub release `v<version>`, builds and attaches the signed APK and its
  SHA-256 (`raineworks-tv-bridge.apk`, which Home Assistant checks before installing) and publishes it. See
  [docs/development.md](docs/development.md).
- **Signing:** the TV app isn't on Google Play: Home Assistant installs it over ADB. Release builds are signed with a
  private key held in repository secrets (`UPLOAD_KEYSTORE_BASE64`, `UPLOAD_KEYSTORE_PASSWORD`, `UPLOAD_KEY_PASSWORD`,
  `UPLOAD_KEY_ALIAS`), given only to jobs on `master`, never to a pull request's; local and pull request builds use
  Android's debug key. See [docs/development.md](docs/development.md).
- Home Assistant checks the SHA-256 before installing the TV app, and when the TV's copy is signed with another key
  uninstalls it once and installs again (`GoogleTvClient.async_install_apk`).
- Adding or widening an Android permission, or anything the TV app serves to the network, needs a reason in the pull
  request and an update to the protocol and security docs.

# Development


```bash
pip install -r requirements-test.txt     # parser tests and ruff
pytest -q
pip install -r requirements-test-ha.txt  # with Home Assistant: config flow and setup
pytest -q
```

The parsers (`custom_components/googletv/parsers.py`) are tested on output
captured from real TVs. The TV app is in `android/` (built by CI, attached
to each release); its API is documented in `protocol/README.md`.

## Dependencies

The test requirements files pin every package exactly. The one exception is
`adb-shell[async]>=0.4.4` in `manifest.json`: Home Assistant itself depends
on adb-shell (its `androidtv` integration pins it), and hassfest refuses an
exact pin on a package Home Assistant depends on ("Use a minimum version
instead, so it can follow along when Home Assistant updates it"), so the
integration follows whatever version Home Assistant installs.
`requirements-test-ha.txt` pins that minimum exactly
(`adb-shell[async]==0.4.4`), so the tests run against it.
`tests/test_manifest.py` checks that any other requirement added to the
manifest is an exact `==` pin, and that each requirement's version is the
one `requirements-test-ha.txt` pins. Raise adb-shell on purpose, in a change
of its own, in both files at once.

What runs the code is pinned too: `.python-version` holds the exact Python
release (`3.13.18`) and `.java-version` the exact Temurin JDK that builds the
TV app (`17.0.21+9`). The Test, TV app and Release workflows and the shared
setup action (`.github/actions/setup`) read them (`python-version-file`,
`java-version-file`), and `tests/test_toolchain.py` checks both are exact and
that nothing in CI names a version of its own. Use the same versions locally,
and raise them on purpose, in a change of their own.

## Testing the TV app

The TV app's access checks are plain Kotlin, tested with JUnit without a TV
or an emulator: `Access` (the bearer-token check behind every 401) in
`AccessTest`, and `PairingCodes` (pairing codes, their expiry and tries, and
the lockout after wrong codes) in `PairingCodesTest`, with an injected clock.
So is the validation of what a paired client sends: `PlayRequest`
(`/api/play`) in `PlayRequestTest` and `NotificationRequest` (`/api/notify`)
in `NotificationRequestTest`, each with a valid request and every rejection
(a URL's scheme, an unknown kind, a bad action, a value out of range). A
notification's `color` isn't covered: parsing it needs Android's `Color`,
which a JVM unit test doesn't have. The tests are in `android/app/src/test/`. Run them with Java 17 (the
release in `.java-version`):

```bash
cd android
./gradlew testReleaseUnitTest
```

## Releasing and signing the TV app

`version` in `custom_components/googletv/manifest.json` is the integration's,
the TV app's `versionName` and (derived) `versionCode`, and the release's.
Never bump it by hand: the `Release pull request` workflow (`release-pr.yml`,
Raineworks' shared workflow) keeps one pull request, `Release v<version>`, open
on `master` with the next version, worked out from what's been merged since
the last tag: major for a breaking change (`type!:`), minor for a `feat`, patch
for anything else that changes `custom_components/`, `android/` or `protocol/`
(tests excluded). Merging it is the release. When `Test` passes on `master`,
the `Release` workflow creates the draft release `v<version>`, builds the APK,
attaches it with its SHA-256 (`raineworks-tv-bridge.apk`; Home Assistant checks
the hash before installing), and publishes it. Never tag or upload by hand.

The app isn't on Google Play: Home Assistant installs it over ADB. Release
builds (and the `tv-bridge-dev` prerelease built from `master`) are signed
with a private key held in repository secrets: `UPLOAD_KEYSTORE_BASE64` (the
keystore, base64), `UPLOAD_KEYSTORE_PASSWORD`, and optionally
`UPLOAD_KEY_PASSWORD` and `UPLOAD_KEY_ALIAS` (default `upload`). The workflows
pass them to Gradle as `RELEASE_KEYSTORE*` environment variables; the
keystore is decoded to a temporary file and deleted after the build. A
release without the key fails. Pull request builds and local builds
(`./gradlew assembleRelease` in `android/`) are signed with Android's debug
key and get no secrets. Never commit a key or a password.

A TV whose app is signed with another key can't be updated in place (Android
refuses with `INSTALL_FAILED_UPDATE_INCOMPATIBLE`): `GoogleTvClient.async_install_apk`
then uninstalls the app once (`pm uninstall`), logs a warning saying why, and
installs again; the pairing is lost and made again by the coordinator, and the
app's settings, lost with its data, are given back from Home Assistant's copy
([Privacy and security](privacy-and-security.md)). Any
other install failure is an error and uninstalls nothing.

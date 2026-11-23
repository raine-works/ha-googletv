"""Tests that the integration's runtime requirements are pinned.

Home Assistant installs whatever ``manifest.json``'s ``requirements`` allow, so
each must be an exact ``==`` pin, and the same pin the Home Assistant tests run
against (``requirements-test-ha.txt``). Needs neither Home Assistant nor
adb-shell.
"""

from __future__ import annotations

import json
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_MANIFEST = _ROOT / "custom_components" / "googletv" / "manifest.json"
_TEST_HA_REQUIREMENTS = _ROOT / "requirements-test-ha.txt"


def _requirements() -> list[str]:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))["requirements"]


def test_manifest_requirements_are_exact_pins() -> None:
    """Every runtime requirement is ``name==version``, with no range."""
    requirements = _requirements()
    assert requirements
    for requirement in requirements:
        name, sep, version = requirement.partition("==")
        assert sep == "==", f"{requirement} isn't pinned with =="
        assert name and version, f"{requirement} isn't name==version"
        assert not any(c in version for c in "<>=!~*,; "), (
            f"{requirement} isn't a single exact version"
        )


def test_manifest_requirements_match_ha_test_requirements() -> None:
    """The Home Assistant tests run against the versions the manifest pins."""
    tested = {
        line.strip()
        for line in _TEST_HA_REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    for requirement in _requirements():
        assert requirement in tested, (
            f"{requirement} isn't pinned in {_TEST_HA_REQUIREMENTS.name}"
        )

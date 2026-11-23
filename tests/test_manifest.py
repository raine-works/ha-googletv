"""Tests that the integration's runtime requirements are pinned.

Home Assistant installs whatever ``manifest.json``'s ``requirements`` allow, so
each must be an exact ``==`` pin. The one exception is a package Home Assistant
itself depends on (adb-shell): hassfest refuses an exact pin on those, so it is
a ``>=`` minimum. Either way, the version must be the one the Home Assistant
tests pin exactly (``requirements-test-ha.txt``). Needs neither Home Assistant
nor adb-shell.
"""

from __future__ import annotations

import json
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_MANIFEST = _ROOT / "custom_components" / "googletv" / "manifest.json"
_TEST_HA_REQUIREMENTS = _ROOT / "requirements-test-ha.txt"

# Packages Home Assistant itself depends on, where hassfest only accepts a
# minimum version (see docs/development.md).
_HA_DEPENDENCIES = frozenset({"adb-shell"})


def _requirements() -> list[str]:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))["requirements"]


def _split(requirement: str) -> tuple[str, str, str]:
    """Split ``name[extras]<op>version`` into (name with extras, op, version)."""
    for op in ("==", ">="):
        name, sep, version = requirement.partition(op)
        if sep:
            return name, op, version
    raise AssertionError(f"{requirement} has neither == nor >=")


def _base_name(name: str) -> str:
    return name.partition("[")[0].strip().lower()


def _tested_pins() -> dict[str, str]:
    """Map each ``name[extras]`` in requirements-test-ha.txt to its pin."""
    pins = {}
    for line in _TEST_HA_REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, version = line.partition("==")
        assert sep, f"{line} in {_TEST_HA_REQUIREMENTS.name} isn't pinned with =="
        pins[name] = version
    return pins


def test_manifest_requirements_are_pinned() -> None:
    """Each requirement is ``==``, or ``>=`` for a Home Assistant dependency."""
    requirements = _requirements()
    assert requirements
    for requirement in requirements:
        name, op, version = _split(requirement)
        assert name and version, f"{requirement} isn't name{op}version"
        assert not any(c in version for c in "<>=!~*,; "), (
            f"{requirement} isn't a single version"
        )
        if op == ">=":
            assert _base_name(name) in _HA_DEPENDENCIES, (
                f"{requirement} is a range; only packages Home Assistant "
                "depends on may use >="
            )


def test_manifest_requirements_match_ha_test_requirements() -> None:
    """The Home Assistant tests pin exactly the version the manifest names."""
    tested = _tested_pins()
    for requirement in _requirements():
        name, _, version = _split(requirement)
        assert tested.get(name) == version, (
            f"{requirement} isn't the version {_TEST_HA_REQUIREMENTS.name} pins"
        )

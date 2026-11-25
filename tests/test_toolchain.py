"""Tests that the Python and JDK that run the checks and build the TV app are pinned.

``.python-version`` and ``.java-version`` hold the one exact version of each
(see docs/development.md); CI's setup reads them, so the interpreter and the
JDK that signs the release APK change only in a commit. Needs neither Home
Assistant nor a JDK.
"""

from __future__ import annotations

import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_PYTHON_VERSION = _ROOT / ".python-version"
_JAVA_VERSION = _ROOT / ".java-version"
_SETUP_ACTION = _ROOT / ".github" / "actions" / "setup" / "action.yml"
_WORKFLOWS = _ROOT / ".github" / "workflows"


def _pin(path: pathlib.Path) -> str:
    """Return the file's one non-empty line, failing if it has any other."""
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    lines = [line for line in lines if line]
    assert len(lines) == 1, f"{path.name} should hold exactly one version"
    return lines[0]


def test_python_version_is_exact() -> None:
    """``.python-version`` names a full ``major.minor.patch`` release."""
    assert re.fullmatch(r"3\.\d+\.\d+", _pin(_PYTHON_VERSION)), (
        f"{_PYTHON_VERSION.name} isn't an exact release such as 3.13.18"
    )


def test_java_version_is_exact() -> None:
    """``.java-version`` names a full Temurin 17 release with its build."""
    assert re.fullmatch(r"17\.\d+\.\d+\+\d+", _pin(_JAVA_VERSION)), (
        f"{_JAVA_VERSION.name} isn't an exact Temurin 17 release such as 17.0.21+9"
    )


def test_setup_action_reads_the_pins() -> None:
    """The setup action takes both versions from the files, not a line of its own."""
    action = _SETUP_ACTION.read_text(encoding="utf-8")
    assert "python-version-file: .python-version" in action
    assert "java-version-file: .java-version" in action
    assert not re.search(r"^\s*(python|java)-version:", action, re.MULTILINE), (
        "the setup action names a version instead of reading the pin file"
    )


def test_workflows_read_the_pins() -> None:
    """Test, TV app and Release take their versions from the files, too."""
    for name, key in (
        ("test.yaml", "python"),
        ("android.yaml", "java"),
        ("release.yaml", "java"),
    ):
        workflow = (_WORKFLOWS / name).read_text(encoding="utf-8")
        assert f"{key}-version-file: .{key}-version" in workflow, name
        assert not re.search(r"^\s*(python|java)-version:", workflow, re.MULTILINE), (
            f"{name} names a version instead of reading the pin file"
        )

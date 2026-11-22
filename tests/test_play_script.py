"""scripts/play.py: what it sends Google Play, worked out without calling it."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_spec = spec_from_file_location(
    "play", Path(__file__).parent.parent / "scripts/play.py"
)
play = module_from_spec(_spec)
_spec.loader.exec_module(play)


def test_notes_keep_features_and_fixes(tmp_path: Path) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text(
        "feat: pop-ups over HDMI inputs\n"
        "fix(play): an unset signing secret counts as unset\n"
        "docs: the README\n"
        "ci: a workflow\n"
        "Pairing remembers the TV\n"
    )
    [entry] = play.release_notes(str(notes))
    assert entry["language"] == "en-US"
    assert entry["text"] == (
        "• Pop-ups over HDMI inputs\n"
        "• An unset signing secret counts as unset\n"
        "• Pairing remembers the TV"
    )


def test_notes_from_a_github_release(tmp_path: Path) -> None:
    notes = tmp_path / "notes.md"
    notes.write_text(
        "## What's Changed\n"
        "* Faster pairing by @someone in https://github.com/x/y/pull/1\n\n"
        "**Full Changelog**: https://github.com/x/y/compare/v1...v2\n"
    )
    assert play.release_notes(str(notes))[0]["text"] == "• Faster pairing"


def test_notes_fit_plays_limit(tmp_path: Path) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text(
        "".join(f"feat: change number {n} to something\n" for n in range(60))
    )
    text = play.release_notes(str(notes))[0]["text"]
    assert len(text) <= play.NOTES_MAX
    assert text.endswith("…")


def test_no_notes_without_a_file_or_anything_for_users(tmp_path: Path) -> None:
    assert play.release_notes(None) == []
    notes = tmp_path / "notes.txt"
    notes.write_text("docs: only docs\n")
    assert play.release_notes(str(notes)) == []


def test_a_rollout_under_100_percent_is_staged() -> None:
    assert play.status_for("completed", 100) == ("completed", None)
    assert play.status_for("completed", 20) == ("inProgress", 0.2)
    assert play.status_for("draft", 20) == ("draft", None)

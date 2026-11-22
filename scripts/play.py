"""Google Play from the workflows: releases, promotion, the store listing, Data safety.

A small client for the Google Play Developer API (androidpublisher v3), with the
standard library only. It signs in with an OAuth access token in
PLAY_ACCESS_TOKEN (the workflows get one without a key, through Workload
Identity Federation: google-github-actions/auth with token_format
access_token). Every change is one edit, committed at the end.

  python scripts/play.py upload BUNDLE --track internal [--status draft] [--notes FILE]
  python scripts/play.py promote --from internal --to alpha [--rollout 20]
  python scripts/play.py listing [DIR]
  python scripts/play.py data-safety CSV

PLAY_PACKAGE overrides the package (com.raineworks.tvbridge).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import mimetypes
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

API = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"
UPLOAD = (
    "https://androidpublisher.googleapis.com/upload/androidpublisher/v3/applications"
)
PACKAGE = os.environ.get("PLAY_PACKAGE", "com.raineworks.tvbridge")
ROOT = Path(__file__).resolve().parent.parent
LISTING = ROOT / "android/play"
# Play's limit on a release's notes, per language
NOTES_MAX = 500
# The store listing's images: Play's image type → the file, or folder, here
IMAGES = {
    "icon": "icon-512.png",
    "featureGraphic": "feature-graphic-1024x500.png",
    "tvBanner": "tv-banner-1280x720.png",
    "tvScreenshots": "screenshots",
}
# Google requires phone screenshots on every store listing, a TV-only app's
# too, so the first two TV screenshots fill that slot; the app still can't be
# installed on a phone (its manifest requires a TV)
PHONE_SCREENSHOTS = ("phoneScreenshots", "screenshots", 2)
# Never on the listing: tablets
NOT_LISTED = ("sevenInchScreenshots", "tenInchScreenshots")
# A listing's text: Play's field → the file in listing/<language>/
TEXTS = {
    "title": "title.txt",
    "shortDescription": "short-description.txt",
    "fullDescription": "full-description.txt",
}


class PlayError(Exception):
    """The API refused a call: its message."""


def warn(message: str) -> None:
    # Shown as a warning on the workflow run
    print(
        f"::warning::{message}"
        if os.environ.get("GITHUB_ACTIONS")
        else f"warning: {message}"
    )


def call(
    method: str,
    url: str,
    body: dict | None = None,
    data: bytes | None = None,
    content_type: str = "application/json",
) -> dict:
    token = os.environ.get("PLAY_ACCESS_TOKEN")
    if not token:
        raise PlayError("PLAY_ACCESS_TOKEN isn't set")
    if body is not None:
        data = json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            raw = response.read()
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")
        with contextlib.suppress(ValueError, KeyError, TypeError):
            detail = json.loads(detail)["error"]["message"]
        raise PlayError(
            f"{method} {url.split('/applications/')[-1]}: {err.code} {detail}"
        ) from None
    return json.loads(raw) if raw else {}


class Edit:
    """One Play edit: changes made in it apply together when it's committed."""

    def __init__(self) -> None:
        self.id = call("POST", f"{API}/{PACKAGE}/edits", {})["id"]
        self.url = f"{API}/{PACKAGE}/edits/{self.id}"
        self.upload_url = f"{UPLOAD}/{PACKAGE}/edits/{self.id}"

    def commit(self) -> None:
        try:
            call("POST", f"{self.url}:commit")
        except PlayError as err:
            # Apps whose changes wait for "Send for review" in the Console
            if "changesNotSentForReview" not in str(err):
                raise
            call("POST", f"{self.url}:commit?changesNotSentForReview=true")
            warn(
                "Committed; Play holds the changes until you send them for review"
                " in the Play Console"
            )

    def abandon(self) -> None:
        with contextlib.suppress(PlayError):
            call("DELETE", self.url)


# A conventional commit's type: "feat(play): …" → feat
CONVENTIONAL = re.compile(r"^(\w+)(\([^)]*\))?!?:\s*")
# What people using the app notice
USER_FACING = {"feat", "fix", "perf"}


def release_notes(path: str | None) -> list[dict]:
    """A release's notes for Play's What's new, within its limit.

    From a file of commit subjects or a GitHub release's Markdown: bullets and
    links made plain, and of conventional commits only features, fixes and
    speedups (others are ours, not the app's users').
    """
    if not path or not Path(path).is_file():
        return []
    lines = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "**Full Changelog**", "<!--")):
            continue
        # "* Title by @someone in https://…/pull/1" → "Title"
        line = line.lstrip("*-• ").split(" by @")[0].split(" in https://")[0]
        kind = CONVENTIONAL.match(line)
        if kind:
            if kind.group(1) not in USER_FACING:
                continue
            line = line[kind.end() :]
        if line:
            lines.append(f"• {line[0].upper()}{line[1:]}")
    text = "\n".join(lines)
    if len(text) > NOTES_MAX:
        text = text[: NOTES_MAX - 1].rsplit("\n", 1)[0] + "\n…"
    return [{"language": "en-US", "text": text}] if text else []


def track_release(
    codes: list[int],
    status: str,
    rollout: float | None,
    notes: list[dict],
    name: str | None,
) -> dict:
    release: dict = {"versionCodes": [str(code) for code in codes], "status": status}
    if status == "inProgress":
        release["userFraction"] = rollout
    if notes:
        release["releaseNotes"] = notes
    if name:
        release["name"] = name
    return release


def status_for(status: str, rollout: int) -> tuple[str, float | None]:
    """completed / draft as given; a rollout under 100% is Play's staged inProgress."""
    if status == "completed" and rollout < 100:
        return "inProgress", rollout / 100
    return status, None


def is_draft_app(err: PlayError) -> bool:
    """Play's refusal for an app it hasn't approved: drafts only, but on internal."""
    return "draft app" in str(err).lower()


DRAFT_APP_WARNING = (
    "Google hasn't approved the app yet, so Play takes this release as a draft:"
    " it goes out with the app's review (Publishing overview → Send for review)"
)


def upload(args: argparse.Namespace) -> None:
    status, fraction = status_for(args.status, args.rollout)
    try:
        code = upload_once(args, status, fraction)
    except PlayError as err:
        # An app Google hasn't approved yet takes drafts only (but on internal)
        if status == "draft" or not is_draft_app(err):
            raise
        warn(DRAFT_APP_WARNING)
        status = "draft"
        code = upload_once(args, status, None)
    print(f"Released version code {code} on {args.track} ({status})")


def upload_once(args: argparse.Namespace, status: str, fraction: float | None) -> int:
    edit = Edit()
    try:
        code = call(
            "POST",
            f"{edit.upload_url}/bundles?uploadType=media",
            data=Path(args.bundle).read_bytes(),
            content_type="application/octet-stream",
        )["versionCode"]
        print(f"Uploaded version code {code}")
        notes = release_notes(args.notes)
        release = track_release([code], status, fraction, notes, args.name)
        call(
            "PUT",
            f"{edit.url}/tracks/{args.track}",
            {"track": args.track, "releases": [release]},
        )
        edit.commit()
        return code
    except BaseException:
        edit.abandon()
        raise


def promote(args: argparse.Namespace) -> None:
    status, fraction = status_for("completed", args.rollout)
    try:
        codes = promote_once(args, status, fraction)
    except PlayError as err:
        if not is_draft_app(err):
            raise
        warn(DRAFT_APP_WARNING)
        status, fraction = "draft", None
        codes = promote_once(args, status, fraction)
    how = (
        "as a draft"
        if status == "draft"
        else f"for {args.rollout}% of users"
        if status == "inProgress"
        else "for everyone"
    )
    print(
        f"Promoted version code {', '.join(map(str, codes))}"
        f" from {args.source} to {args.target}, {how}"
    )


def promote_once(
    args: argparse.Namespace, status: str, fraction: float | None
) -> list[int]:
    edit = Edit()
    try:
        source = call("GET", f"{edit.url}/tracks/{args.source}")
        releases = [
            r
            for r in source.get("releases", [])
            if r.get("versionCodes") and r.get("status") != "draft"
        ]
        if not releases:
            raise PlayError(
                f"{args.source} has no released version to promote"
                " (a draft has to be rolled out first)"
            )
        latest = max(releases, key=lambda r: max(int(c) for c in r["versionCodes"]))
        codes = [int(c) for c in latest["versionCodes"]]
        release = track_release(
            codes, status, fraction, latest.get("releaseNotes", []), latest.get("name")
        )
        call(
            "PUT",
            f"{edit.url}/tracks/{args.target}",
            {"track": args.target, "releases": [release]},
        )
        edit.commit()
        return codes
    except BaseException:
        edit.abandon()
        raise


def listing(args: argparse.Namespace) -> None:
    root = Path(args.dir)
    edit = Edit()
    try:
        for language_dir in sorted((root / "listing").iterdir()):
            if not language_dir.is_dir():
                continue
            language = language_dir.name
            body = {"language": language}
            for field, name in TEXTS.items():
                if (language_dir / name).is_file():
                    body[field] = (language_dir / name).read_text().strip()
            call("PUT", f"{edit.url}/listings/{language}", body)
            print(f"{language}: {', '.join(k for k in body if k != 'language')}")
            for image_type, name in IMAGES.items():
                source = root / name
                files = (
                    sorted(source.glob("*.png"))
                    if source.is_dir()
                    else [source]
                    if source.is_file()
                    else []
                )
                if not files:
                    continue
                # Replaced as a set: what's here is what the store shows, in this order
                call("DELETE", f"{edit.url}/listings/{language}/{image_type}")
                for file in files:
                    kind = mimetypes.guess_type(file.name)[0] or "image/png"
                    call(
                        "POST",
                        f"{edit.upload_url}/listings/{language}/{image_type}?uploadType=media",
                        data=file.read_bytes(),
                        content_type=kind,
                    )
                print(f"{language}: {image_type} ({len(files)})")
            image_type, name, count = PHONE_SCREENSHOTS
            files = sorted((root / name).glob("*.png"))[:count]
            if files:
                call("DELETE", f"{edit.url}/listings/{language}/{image_type}")
                for file in files:
                    call(
                        "POST",
                        f"{edit.upload_url}/listings/{language}/{image_type}?uploadType=media",
                        data=file.read_bytes(),
                        content_type="image/png",
                    )
                print(f"{language}: {image_type} ({len(files)}, required by Play)")
            for image_type in NOT_LISTED:
                call("DELETE", f"{edit.url}/listings/{language}/{image_type}")
        edit.commit()
    except BaseException:
        edit.abandon()
        raise


def status(args: argparse.Namespace) -> None:
    """What Play has now, read only: every track's releases and the listing's images."""
    edit = Edit()
    try:
        for track in call("GET", f"{edit.url}/tracks").get("tracks", []):
            releases = track.get("releases", [])
            shown = "; ".join(
                f"{r.get('name', '?')} ({', '.join(r.get('versionCodes', []))})"
                f" {r.get('status')}"
                + (
                    f" {round(r['userFraction'] * 100)}%"
                    if r.get("userFraction")
                    else ""
                )
                for r in releases
            )
            print(f"track {track['track']}: {shown or 'nothing'}")
        for item in call("GET", f"{edit.url}/listings").get("listings", []):
            language = item["language"]
            counts = []
            for image_type in (*IMAGES, PHONE_SCREENSHOTS[0], *NOT_LISTED):
                images = call("GET", f"{edit.url}/listings/{language}/{image_type}")
                counts.append(f"{image_type} {len(images.get('images', []))}")
            print(f"listing {language}: {item.get('title')!r}; {', '.join(counts)}")
    finally:
        edit.abandon()


def data_safety(args: argparse.Namespace) -> None:
    # The Data safety form, as the Play Console's own CSV export
    call(
        "POST",
        f"{API}/{PACKAGE}/dataSafety",
        {"safetyLabels": Path(args.csv).read_text()},
    )
    print("Data safety updated")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("upload", help="upload a bundle and release it on a track")
    p.add_argument("bundle")
    p.add_argument("--track", default="internal")
    p.add_argument("--status", default="completed", choices=["completed", "draft"])
    p.add_argument(
        "--rollout",
        type=int,
        default=100,
        help="percent of users, for a staged rollout",
    )
    p.add_argument(
        "--notes", help="a file with the release's notes (a GitHub release's Markdown)"
    )
    p.add_argument("--name", help="the release's name in the Play Console")
    p.set_defaults(run=upload)
    p = commands.add_parser(
        "promote", help="release a track's latest version on another track"
    )
    p.add_argument("--from", dest="source", required=True)
    p.add_argument("--to", dest="target", required=True)
    p.add_argument(
        "--rollout",
        type=int,
        default=100,
        help="percent of users, for a staged rollout",
    )
    p.set_defaults(run=promote)
    p = commands.add_parser("listing", help="the store listing's text and images")
    p.add_argument("dir", nargs="?", default=str(LISTING))
    p.set_defaults(run=listing)
    p = commands.add_parser("status", help="what Play has now, read only")
    p.set_defaults(run=status)
    p = commands.add_parser(
        "data-safety", help="the Data safety form, from the Console's CSV"
    )
    p.add_argument("csv")
    p.set_defaults(run=data_safety)
    args = parser.parse_args()
    if getattr(args, "rollout", 100) not in range(1, 101):
        parser.error("--rollout is a percentage, 1 to 100")
    try:
        args.run(args)
    except PlayError as err:
        print(
            f"::error::{err}" if os.environ.get("GITHUB_ACTIONS") else f"error: {err}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Raise the release version everywhere it is declared and prepare release notes.

Usage: ``python scripts/bump_version.py {patch|minor|major|X.Y.Z}``

Updates ``pyproject.toml``, ``manifest.json`` and ``const.py``, turns the
``[Unreleased]`` changelog section into a dated release section, and writes
``docs/release-notes-<version>.md`` from that section unless the file already
exists. Prints the new version on stdout.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path
from typing import Final

from scripts.build_release import COMPONENT, ROOT, release_version

SEMVER: Final = re.compile(r"(\d+)\.(\d+)\.(\d+)")
BUMPS: Final = ("patch", "minor", "major")
UNRELEASED_HEADING: Final = "## [Unreleased]"


def next_version(current: str, how: str) -> str:
    """Return the version after ``current`` for a bump kind or an exact version."""
    match = SEMVER.fullmatch(current)
    if match is None:
        msg = f"Current version {current!r} is not X.Y.Z"
        raise ValueError(msg)
    major, minor, patch = (int(part) for part in match.groups())
    if how == "major":
        return f"{major + 1}.0.0"
    if how == "minor":
        return f"{major}.{minor + 1}.0"
    if how == "patch":
        return f"{major}.{minor}.{patch + 1}"
    exact = SEMVER.fullmatch(how)
    if exact is None:
        msg = f"Expected one of {', '.join(BUMPS)} or X.Y.Z, got {how!r}"
        raise ValueError(msg)
    if tuple(map(int, exact.groups())) <= (major, minor, patch):
        msg = f"Version {how} is not greater than the current version {current}"
        raise ValueError(msg)
    return how


def _replace_once(path: Path, pattern: str, replacement: str) -> None:
    """Replace exactly one regex match in a file, or fail."""
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        msg = f"Version declaration not found in {path}"
        raise ValueError(msg)
    path.write_text(updated, encoding="utf-8")


def write_versions(root: Path, component: Path, version: str) -> None:
    """Write the version into every file that declares it."""
    _replace_once(
        root / "pyproject.toml", r'^version = "[^"]+"', f'version = "{version}"'
    )
    _replace_once(
        component / "manifest.json", r'"version": "[^"]+"', f'"version": "{version}"'
    )
    _replace_once(
        component / "const.py",
        r'^VERSION: Final = "[^"]+"',
        f'VERSION: Final = "{version}"',
    )


def release_changelog(changelog: Path, version: str, date: dt.date) -> str:
    """Date the unreleased changelog section as ``version`` and return its body."""
    text = changelog.read_text(encoding="utf-8")
    start = text.find(UNRELEASED_HEADING)
    if start < 0:
        msg = f"{changelog.name} has no {UNRELEASED_HEADING} section"
        raise ValueError(msg)
    body_start = start + len(UNRELEASED_HEADING)
    next_heading = text.find("\n## [", body_start)
    body_end = len(text) if next_heading < 0 else next_heading + 1
    body = text[body_start:body_end].strip()
    if not body:
        msg = (
            f"The {UNRELEASED_HEADING} section in {changelog.name} is empty. "
            "Describe the changes there before releasing."
        )
        raise ValueError(msg)
    released = (
        f"{UNRELEASED_HEADING}\n\n## [{version}] - {date.isoformat()}\n\n{body}\n\n"
    )
    changelog.write_text(text[:start] + released + text[body_end:], encoding="utf-8")
    return body


def write_release_notes(docs: Path, version: str, changes: str) -> Path:
    """Create the release notes from the changelog unless they already exist."""
    path = docs / f"release-notes-{version}.md"
    if not path.exists():
        # Demote changelog headings one level below the page title.
        body = re.sub(r"^### ", "## ", changes, flags=re.MULTILINE)
        path.write_text(
            f"# Thermal Storage Optimizer {version}\n\n{body}\n", encoding="utf-8"
        )
    return path


def bump(how: str, root: Path = ROOT, component: Path = COMPONENT) -> str:
    """Raise the version and prepare the changelog and release notes."""
    version = next_version(release_version(root, component), how)
    changes = release_changelog(
        root / "CHANGELOG.md", version, dt.datetime.now(dt.UTC).date()
    )
    write_versions(root, component, version)
    write_release_notes(root / "docs", version, changes)
    return version


def main() -> None:
    """Parse the bump kind and print the new version."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("how", help=f"one of {', '.join(BUMPS)}, or an exact X.Y.Z")
    args = parser.parse_args()
    try:
        version = bump(args.how)
    except ValueError as error:
        sys.stderr.write(f"{error}\n")
        sys.exit(1)
    sys.stdout.write(f"{version}\n")


if __name__ == "__main__":
    main()

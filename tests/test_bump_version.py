"""Release version bump tests."""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

import pytest

from scripts.build_release import COMPONENT, ROOT, release_version
from scripts.bump_version import bump, next_version, release_changelog


@pytest.mark.parametrize(
    ("how", "expected"),
    [
        ("patch", "1.4.3"),
        ("minor", "1.5.0"),
        ("major", "2.0.0"),
        ("1.10.0", "1.10.0"),
    ],
)
def test_next_version_steps_the_chosen_part(how: str, expected: str) -> None:
    """Each bump kind resets the lower parts; an exact version is taken as is."""
    assert next_version("1.4.2", how) == expected


@pytest.mark.parametrize("how", ["1.4.2", "1.3.9", "beta", "1.5"])
def test_next_version_rejects_invalid_or_older_versions(how: str) -> None:
    """Never go backwards or accept something that is not SemVer."""
    with pytest.raises(ValueError, match=r"greater than|Expected one of"):
        next_version("1.4.2", how)


def test_release_changelog_dates_the_unreleased_section(tmp_path: Path) -> None:
    """Unreleased changes become the dated section and a fresh heading remains."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- A bug.\n\n"
        "## [1.0.0] - 2026-01-01\n\n- Old.\n",
        encoding="utf-8",
    )
    body = release_changelog(changelog, "1.0.1", dt.date(2026, 2, 3))
    assert body == "### Fixed\n\n- A bug."
    assert changelog.read_text(encoding="utf-8") == (
        "# Changelog\n\n## [Unreleased]\n\n## [1.0.1] - 2026-02-03\n\n"
        "### Fixed\n\n- A bug.\n\n## [1.0.0] - 2026-01-01\n\n- Old.\n"
    )


def test_release_changelog_requires_unreleased_changes(tmp_path: Path) -> None:
    """A release without documented changes is refused."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - 2026-01-01\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="empty"):
        release_changelog(changelog, "1.0.1", dt.date(2026, 2, 3))


def test_bump_updates_every_declaration_and_writes_notes(tmp_path: Path) -> None:
    """All three version declarations agree on the new version after a bump."""
    component = tmp_path / COMPONENT.relative_to(ROOT)
    component.mkdir(parents=True)
    for name in ("manifest.json", "const.py"):
        shutil.copy(COMPONENT / name, component / name)
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    (tmp_path / "docs").mkdir()
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- Feature.\n",
        encoding="utf-8",
    )
    current = release_version()
    major = int(current.split(".")[0])

    version = bump("major", tmp_path, component)

    assert version == f"{major + 1}.0.0"
    assert release_version(tmp_path, component) == version
    notes = (tmp_path / "docs" / f"release-notes-{version}.md").read_text(
        encoding="utf-8"
    )
    assert notes == f"# Thermal Storage Optimizer {version}\n\n## Added\n\n- Feature.\n"

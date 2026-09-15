"""Release metadata and manual-installation package tests."""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import pytest

from scripts.build_release import (
    COMPONENT,
    ROOT,
    build_archive,
    package_files,
    verify_archive,
)


def test_release_metadata_is_semver_and_manual_payload_is_source_only() -> None:
    """Keep release metadata synchronized and exclude development artifacts."""
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"])
    assert manifest["single_config_entry"] is True

    relative_files = {path.relative_to(ROOT).as_posix() for path in package_files()}
    assert "custom_components/thermal_storage_optimizer/manifest.json" in relative_files
    assert (
        "custom_components/thermal_storage_optimizer/translations/en.json"
        in relative_files
    )
    assert (
        "custom_components/thermal_storage_optimizer/frontend/"
        "thermal-storage-plan-card.js" in relative_files
    )
    assert not any(
        "__pycache__" in path or path.endswith(".pyc") for path in relative_files
    )
    assert (
        "custom_components/thermal_storage_optimizer/strings.json" not in relative_files
    )


def test_release_archive_is_deterministic_and_extracts_at_config_root(
    tmp_path: Path,
) -> None:
    """Build the same safe manual-installation zip from identical source."""
    first = build_archive(tmp_path / "first.zip")
    second = build_archive(tmp_path / "second.zip")
    assert first.read_bytes() == second.read_bytes()

    with zipfile.ZipFile(first) as archive:
        names = set(archive.namelist())
    assert names == {path.relative_to(ROOT).as_posix() for path in package_files()}


def test_existing_archive_verification_detects_stale_payload(tmp_path: Path) -> None:
    """Source checks alone cannot pass an old or modified deliverable."""
    path = build_archive(tmp_path / "release.zip")
    verify_archive(path)
    with zipfile.ZipFile(path) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    contents["custom_components/thermal_storage_optimizer/frontend.py"] = b"# stale"
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in contents.items():
            archive.writestr(name, content)
    with pytest.raises(ValueError, match="differs from source"):
        verify_archive(path)

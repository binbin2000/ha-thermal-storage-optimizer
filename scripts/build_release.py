"""Validate and build the deterministic manual-installation archive."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
import zipfile
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]
COMPONENT: Final = ROOT / "custom_components" / "thermal_storage_optimizer"
INCLUDED_SUFFIXES: Final = frozenset({".js", ".json", ".png", ".py", ".yaml"})
ARCHIVE_TIMESTAMP: Final = (2026, 1, 1, 0, 0, 0)


def release_version() -> str:
    """Validate and return the single release version."""
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    with (ROOT / "pyproject.toml").open("rb") as file:
        project_version = tomllib.load(file)["project"]["version"]

    const_line = next(
        line
        for line in (COMPONENT / "const.py").read_text(encoding="utf-8").splitlines()
        if line.startswith("VERSION:")
    )
    source_version = const_line.rsplit('"', 2)[1]
    versions = {manifest["version"], project_version, source_version}
    if len(versions) != 1:
        msg = f"Release versions disagree: {sorted(versions)}"
        raise ValueError(msg)
    return source_version


def package_files() -> list[Path]:
    """Return the complete, source-only integration payload."""
    files = sorted(
        path
        for path in COMPONENT.rglob("*")
        if path.is_file() and path.suffix in INCLUDED_SUFFIXES
    )
    required = {
        COMPONENT / "__init__.py",
        COMPONENT / "manifest.json",
        COMPONENT / "translations" / "en.json",
    }
    missing = required.difference(files)
    if missing:
        msg = f"Required package files missing: {sorted(map(str, missing))}"
        raise ValueError(msg)
    return files


def build_archive(output: Path | None = None) -> Path:
    """Build an archive that can be extracted at the Home Assistant config root."""
    version = release_version()
    target = output or ROOT / "dist" / f"thermal_storage_optimizer-{version}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in package_files():
            relative = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(relative, date_time=ARCHIVE_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    verify_archive(target)
    return target


def verify_archive(path: Path) -> None:
    """Require the existing deliverable to match every package source byte."""
    expected = {p.relative_to(ROOT).as_posix(): p.read_bytes() for p in package_files()}
    with zipfile.ZipFile(path) as archive:
        if len(archive.namelist()) != len(expected) or set(archive.namelist()) != set(
            expected
        ):
            msg = "Release archive file inventory differs from package sources"
            raise ValueError(msg)
        for name, content in expected.items():
            if archive.read(name) != content:
                msg = f"Release archive differs from source: {name}"
                raise ValueError(msg)


def main() -> None:
    """Validate versions or create the release archive."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="validate without writing")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--verify", type=Path, help="compare an existing archive to sources"
    )
    args = parser.parse_args()
    version = release_version()
    files = package_files()
    if args.verify:
        verify_archive(args.verify)
        sys.stdout.write(f"Archive verified: {args.verify}\n")
        return
    if args.check:
        sys.stdout.write(f"Release {version}: {len(files)} package files validated\n")
        return
    sys.stdout.write(f"{build_archive(args.output)}\n")


if __name__ == "__main__":
    main()

# Maintainer release process

1. Update the SemVer value in `pyproject.toml`, `manifest.json`, and `const.py`; add a
   dated changelog section and `docs/release-notes-<version>.md`.
2. Install the pinned dev environment with `python -m pip install -e ".[dev]"`.
3. Run `python scripts/run_tests.py`, `python -m ruff format --check .`,
   `python -m ruff check .`, `python -m mypy`, and
   `python scripts/build_release.py --check`.
4. Build locally with `python scripts/build_release.py`. Inspect that the archive has
   exactly one `custom_components/thermal_storage_optimizer` tree and no caches,
   development harness, credentials, database, logs, or local Home Assistant state.
5. Confirm CI and Hassfest pass, create an annotated `v<version>` tag from the reviewed
   commit, and push it. The release workflow requires the tag and metadata versions to
   match, reruns quality checks, builds the archive, and creates the GitHub release.
6. On a non-production Home Assistant instance, execute the clean-install, migration,
   reload, restart, removal, dry-run, and active-control preservation tests in
   [installation and lifecycle](installation.md) and the physical checks in
   [field validation](field-validation.md). Record the result with the release.

Do not publish from a dirty or partially synchronized integration directory. A SemVer
major version indicates incompatible user-visible/config changes, minor adds backward-
compatible behavior, and patch contains backward-compatible fixes. Config-entry schema
versions are independent and change only when stored config data needs migration.

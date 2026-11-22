# Maintainer release process

1. Describe every user-visible change under `## [Unreleased]` in `CHANGELOG.md`. A
   release with an empty unreleased section is refused. To hand-write richer release
   notes, add `docs/release-notes-<version>.md` for the coming version; otherwise they
   are generated from the changelog section.
2. Confirm CI and Hassfest pass on the default branch.
3. Run the **Release** workflow from the default branch (GitHub → Actions → Release →
   Run workflow) and choose `patch`, `minor`, or `major`, or type an exact `X.Y.Z`.
   The workflow:
   - raises the version in `pyproject.toml`, `manifest.json`, and `const.py` with
     `python -m scripts.bump_version`, dates the unreleased changelog section, and
     writes the release notes if they do not exist;
   - refuses a version whose tag or release already exists;
   - runs the tests, formatting, lint, typing, and package checks;
   - commits `Release X.Y.Z` to the default branch, builds the archive, and creates
     the `v<version>` tag and GitHub release with the archive attached.

   If the default branch is protected, allow `github-actions[bot]` to push to it.
4. To rehearse locally, run `python -m scripts.bump_version patch` (or `minor`,
   `major`), then `python scripts/run_tests.py`, `python -m ruff format --check .`,
   `python -m ruff check .`, `python -m mypy`, and `python scripts/build_release.py`.
   Inspect that the archive has exactly one `custom_components/thermal_storage_optimizer`
   tree and no caches, development harness, credentials, database, logs, or local Home
   Assistant state. Discard the local version change afterwards; the workflow makes it.
5. Pull the release commit before continuing work on the default branch.
6. On a non-production Home Assistant instance, execute the clean-install, migration,
   reload, restart, removal, dry-run, and active-control preservation tests in
   [installation and lifecycle](installation.md) and the physical checks in
   [field validation](field-validation.md). Record the result with the release.

Do not publish from a dirty or partially synchronized integration directory. A SemVer
major version indicates incompatible user-visible/config changes, minor adds backward-
compatible behavior, and patch contains backward-compatible fixes. Config-entry schema
versions are independent and change only when stored config data needs migration.

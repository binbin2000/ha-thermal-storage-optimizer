# Compatibility

Version 1.0.0 is tested against:

- Home Assistant Core 2026.9.1
- Python 3.14.2 (the runtime used by that tested Home Assistant release)
- `pytest-homeassistant-custom-component` 0.13.364

Home Assistant 2026.9.1 is the supported floor for this release. Newer Home Assistant
versions may work but are not claimed compatible until CI and lifecycle testing pass;
the scheduled/current Hassfest validation in CI is intended to detect future metadata
and translation changes. Older Home Assistant releases and alternative Python
versions are unsupported.

The integration has no third-party runtime Python dependencies. It reads standard
Home Assistant entities and supports the official Nord Pool response action plus the
documented generic/custom timestamped price attributes. Provider-specific data shape,
entity units, output-domain turn-on/turn-off services, and notification behavior must
be verified at each installation.

Config-entry schema versions 1 through 6 are upgrade inputs supported by version
1.0.0. Downgrade compatibility is not guaranteed because Home Assistant blocks unknown
newer major schemas and persisted state may evolve. Restore the matching Home Assistant
backup and integration version for rollback.

Current Home Assistant references used for release validation:

- [Integration manifest](https://developers.home-assistant.io/docs/creating_integration_manifest/)
- [Config-entry migration](https://developers.home-assistant.io/docs/core/integration/config_flow/#config-entry-migration)
- [Custom-integration localization](https://developers.home-assistant.io/docs/internationalization/custom_integration/)
- [Hassfest for custom components](https://developers.home-assistant.io/blog/2020/04/16/hassfest/)

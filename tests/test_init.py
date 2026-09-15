"""Lifecycle, startup-ordering, and recovery tests."""

from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermal_storage_optimizer import async_migrate_entry
from custom_components.thermal_storage_optimizer.const import (
    CONF_ACTIVE_CONTROL,
    CONFIG_ENTRY_MINOR_VERSION,
    CONFIG_ENTRY_VERSION,
    DOMAIN,
    INTEGRATION_NAME,
    UNIQUE_ID,
)

from .helpers import REQUIRED_CONFIG, set_valid_required_states

EXPECTED_TANK_TOP = 60.0


def entity_id(hass: HomeAssistant, platform: str, unique_id: str) -> str:
    """Resolve an integration entity by unique ID."""
    resolved = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert resolved is not None
    return resolved


def state(hass: HomeAssistant, entity: str):  # noqa: ANN201
    """Return an asserted-present Home Assistant state."""
    current = hass.states.get(entity)
    assert current is not None
    return current


async def test_setup_normalizes_data_and_only_requests_safe_off(
    hass: HomeAssistant,
) -> None:
    """Test valid startup, diagnostics, device creation, and safe unload."""
    set_valid_required_states(hass)
    output_service = AsyncMock()
    hass.services.async_register("switch", "turn_on", output_service)
    hass.services.async_register("switch", "turn_off", output_service)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=INTEGRATION_NAME,
        unique_id=UNIQUE_ID,
        data=REQUIRED_CONFIG,
        version=2,
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.data.is_valid
    assert entry.runtime_data.data.values["tank_top_entity"].value == EXPECTED_TANK_TOP
    assert not entry.runtime_data.controller.config.active_control
    assert output_service.await_count == 1
    assert output_service.await_args.args[0].service == "turn_off"

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    assert device is not None
    status_id = entity_id(hass, "sensor", f"{entry.entry_id}_status")
    valid_id = entity_id(hass, "binary_sensor", f"{entry.entry_id}_data_valid")
    assert (
        er.async_get(hass).async_get(status_id).entity_category
        is EntityCategory.DIAGNOSTIC
    )  # type: ignore[union-attr]
    assert state(hass, status_id).state == "ready"
    assert state(hass, valid_id).state == STATE_ON
    energy_id = entity_id(hass, "sensor", f"{entry.entry_id}_energy")
    high_grade_id = entity_id(hass, "sensor", f"{entry.entry_id}_high_grade_energy")
    soc_id = entity_id(hass, "sensor", f"{entry.entry_id}_soc")
    quality_id = entity_id(hass, "sensor", f"{entry.entry_id}_data_quality")
    trend_id = entity_id(hass, "sensor", f"{entry.entry_id}_trend")
    demand_id = entity_id(hass, "sensor", f"{entry.entry_id}_hourly_heat_demand")
    cop_id = entity_id(hass, "sensor", f"{entry.entry_id}_estimated_cop")
    cop_source_id = entity_id(hass, "sensor", f"{entry.entry_id}_cop_source")
    assert float(state(hass, energy_id).state) == pytest.approx(9.8855)
    assert float(state(hass, high_grade_id).state) == pytest.approx(3.8766666667)
    assert float(state(hass, soc_id).state) == pytest.approx(32.9516666667)
    assert state(hass, quality_id).state == "good"
    assert state(hass, trend_id).state == "unknown"
    assert float(state(hass, demand_id).state) == pytest.approx(3.6)
    assert float(state(hass, cop_id).state) == pytest.approx(3.0)
    assert state(hass, cop_source_id).state == "fixed_fallback"

    coordinator = entry.runtime_data
    snapshot_before_unload = coordinator.data
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert state(hass, status_id).state == STATE_UNAVAILABLE
    assert state(hass, valid_id).state == STATE_UNAVAILABLE
    hass.states.async_set("sensor.tank_top", "70", {"unit_of_measurement": "°C"})
    await hass.async_block_till_done()
    assert coordinator.data is snapshot_before_unload
    assert output_service.await_count == 2
    assert all(
        call.args[0].service == "turn_off" for call in output_service.await_args_list
    )


async def test_startup_before_entities_ready_and_recovery(hass: HomeAssistant) -> None:
    """Test startup is non-fatal and state subscriptions recover automatically."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=INTEGRATION_NAME,
        unique_id=UNIQUE_ID,
        data=REQUIRED_CONFIG,
        version=2,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    status_id = entity_id(hass, "sensor", f"{entry.entry_id}_status")
    valid_id = entity_id(hass, "binary_sensor", f"{entry.entry_id}_data_valid")
    assert state(hass, status_id).state == "waiting_for_data"
    assert state(hass, valid_id).state == STATE_OFF

    set_valid_required_states(hass)
    await hass.async_block_till_done()
    assert state(hass, status_id).state == "ready"
    assert state(hass, valid_id).state == STATE_ON

    hass.states.async_set("sensor.tank_middle", "unavailable")
    await hass.async_block_till_done()
    assert state(hass, status_id).state == "invalid_data"
    assert state(hass, valid_id).state == STATE_OFF
    assert (
        "tank_middle_entity:unavailable" in state(hass, status_id).attributes["issues"]
    )

    hass.states.async_set("sensor.tank_middle", "50", {"unit_of_measurement": "°C"})
    await hass.async_block_till_done()
    assert state(hass, status_id).state == "ready"
    assert state(hass, valid_id).state == STATE_ON


async def test_milestone_one_entry_migrates_and_waits_for_configuration(
    hass: HomeAssistant,
) -> None:
    """Test an empty Milestone 1 entry upgrades without crashing."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=INTEGRATION_NAME,
        unique_id=UNIQUE_ID,
        data={},
        version=1,
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.version == CONFIG_ENTRY_VERSION
    assert entry.minor_version == CONFIG_ENTRY_MINOR_VERSION
    status_id = entity_id(hass, "sensor", f"{entry.entry_id}_status")
    assert state(hass, status_id).state == "waiting_for_data"


@pytest.mark.parametrize(
    ("version", "expected_active"),
    [(1, False), (2, False), (3, False), (4, True), (5, True), (6, True)],
)
async def test_supported_config_entries_migrate_without_losing_user_settings(
    hass: HomeAssistant,
    version: int,
    expected_active: bool,  # noqa: FBT001
) -> None:
    """Migrate every released schema and preserve valid explicit control choices."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=INTEGRATION_NAME,
        data=REQUIRED_CONFIG,
        options={CONF_ACTIVE_CONTROL: True, "future_safe_option": "retained"},
        version=version,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)
    assert entry.version == CONFIG_ENTRY_VERSION
    assert entry.minor_version == CONFIG_ENTRY_MINOR_VERSION
    assert dict(entry.data) == REQUIRED_CONFIG
    assert entry.options[CONF_ACTIVE_CONTROL] is expected_active
    assert entry.options["future_safe_option"] == "retained"


@pytest.mark.parametrize(("version", "minor_version"), [(0, 1), (7, 1), (6, 2)])
async def test_unsupported_config_entry_versions_are_rejected(
    hass: HomeAssistant, version: int, minor_version: int
) -> None:
    """Never guess how to migrate invalid or newer config schemas."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=INTEGRATION_NAME,
        data=REQUIRED_CONFIG,
        version=version,
        minor_version=minor_version,
    )
    entry.add_to_hass(hass)

    assert not await async_migrate_entry(hass, entry)
    assert entry.version == version
    assert entry.minor_version == minor_version


async def test_removal_clears_all_private_runtime_stores(hass: HomeAssistant) -> None:
    """Unload safely and leave no private runtime state after entry removal."""
    set_valid_required_states(hass)
    output_service = AsyncMock()
    hass.services.async_register("switch", "turn_on", output_service)
    hass.services.async_register("switch", "turn_off", output_service)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=INTEGRATION_NAME,
        data=REQUIRED_CONFIG,
        version=CONFIG_ENTRY_VERSION,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    stores = [
        Store[dict[str, object]](hass, 1, f"{DOMAIN}.{entry.entry_id}.{suffix}")
        for suffix in ("plan", "calibration", "controller", "advisor")
    ]
    for store in stores:
        await store.async_save({"test": True})

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    restored = [await store.async_load() for store in stores]
    assert all(payload is None for payload in restored)
    assert hass.config_entries.async_get_entry(entry.entry_id) is None
    assert output_service.await_count >= 2
    assert all(
        call.args[0].service == "turn_off" for call in output_service.await_args_list
    )

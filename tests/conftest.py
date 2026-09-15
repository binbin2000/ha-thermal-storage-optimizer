"""Shared test fixtures for Thermal Storage Optimizer."""

import sys

import pytest
import pytest_socket


def pytest_configure() -> None:
    """Keep the Windows asyncio wake-up socket available during test setup."""
    if sys.platform != "win32":
        return

    def windows_disable_socket_noop(*_args: object, **_kwargs: object) -> None:
        """Leave sockets enabled because Windows asyncio requires socketpair."""

    pytest_socket.disable_socket = windows_disable_socket_noop


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> None:
    """Enable loading integration code from custom_components."""
    assert enable_custom_integrations is None

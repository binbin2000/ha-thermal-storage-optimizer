"""Run the Home Assistant test suite on supported development platforms."""

from __future__ import annotations

import sys
from types import ModuleType
from typing import NoReturn


def _install_windows_posix_import_shims() -> None:
    """Allow Home Assistant's POSIX runner modules to import on Windows."""
    if sys.platform != "win32":
        return

    fcntl = ModuleType("fcntl")
    fcntl.LOCK_EX = 2
    fcntl.LOCK_NB = 4

    def unsupported_flock(_file_descriptor: int, _operation: int) -> NoReturn:
        """Reject runner file locking if a test unexpectedly invokes it."""
        message = "Home Assistant runner file locking is unavailable on Windows"
        raise NotImplementedError(message)

    fcntl.flock = unsupported_flock
    sys.modules["fcntl"] = fcntl

    resource = ModuleType("resource")
    resource.RLIMIT_NOFILE = 7

    def unsupported_resource_limit(*_args: object) -> NoReturn:
        """Reject POSIX resource-limit access if unexpectedly invoked."""
        message = "POSIX resource limits are unavailable on Windows"
        raise OSError(message)

    resource.getrlimit = unsupported_resource_limit
    resource.setrlimit = unsupported_resource_limit
    sys.modules["resource"] = resource


def main() -> int:
    """Run pytest after applying the narrow Windows import compatibility shim."""
    _install_windows_posix_import_shims()

    import pytest  # noqa: PLC0415

    # Python's Windows event loop creates its wake-up pipe with an IPv4
    # socketpair. The Home Assistant test plugin blocks that before async test
    # setup, so native Windows runs must allow sockets for the loop to start.
    # The integration itself contains no network client or I/O path.
    return pytest.main()


if __name__ == "__main__":
    raise SystemExit(main())

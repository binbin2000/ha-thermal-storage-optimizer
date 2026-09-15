"""Run the repository's Home Assistant test instance on native Windows."""

from __future__ import annotations

import sys
from types import ModuleType


class _UnavailableNativeFeature:
    """Reject native-only features that are outside this test harness."""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        """Prevent accidental use of a stubbed native feature."""
        message = "This native feature is unavailable in the Windows test harness"
        raise RuntimeError(message)


def _install_windows_compatibility_shims() -> None:
    """Provide modules imported by Home Assistant but unavailable on Windows."""
    if sys.platform != "win32":
        return

    fcntl = ModuleType("fcntl")
    fcntl.LOCK_EX = 2
    fcntl.LOCK_NB = 4

    def flock(_file_descriptor: int, _operation: int) -> None:
        """Accept the local runner lock; the launcher targets one test instance."""

    fcntl.flock = flock
    sys.modules["fcntl"] = fcntl

    resource = ModuleType("resource")
    resource.RLIMIT_NOFILE = 7

    def getrlimit(_resource: int) -> tuple[int, int]:
        """Report a sufficient descriptor limit on Windows."""
        return (2048, 2048)

    def setrlimit(_resource: int, _limits: tuple[int, int]) -> None:
        """Keep the Windows descriptor limit unchanged."""

    resource.getrlimit = getrlimit
    resource.setrlimit = setrlimit
    sys.modules["resource"] = resource

    # Home Assistant imports these while building its complete service catalog,
    # even though voice processing is disabled in this integration test harness.
    pymicro_vad = ModuleType("pymicro_vad")
    pymicro_vad.__dict__["MicroVad"] = _UnavailableNativeFeature
    sys.modules["pymicro_vad"] = pymicro_vad

    pyspeex_noise = ModuleType("pyspeex_noise")
    pyspeex_noise.__dict__["AudioProcessor"] = _UnavailableNativeFeature
    sys.modules["pyspeex_noise"] = pyspeex_noise


def main() -> int:
    """Install compatibility shims and invoke Home Assistant's normal CLI."""
    _install_windows_compatibility_shims()

    from homeassistant import __main__ as home_assistant_cli  # noqa: PLC0415

    if sys.platform == "win32":
        home_assistant_cli.validate_os = lambda: None
        from homeassistant.bootstrap import DEFAULT_INTEGRATIONS  # noqa: PLC0415
        from homeassistant.helpers import signal  # noqa: PLC0415

        signal.async_register_signal_handling = lambda _hass: None
        DEFAULT_INTEGRATIONS.discard("assist_satellite")
    return home_assistant_cli.main()


if __name__ == "__main__":
    raise SystemExit(main())

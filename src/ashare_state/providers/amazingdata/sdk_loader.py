"""Lazy SDK loader with runtime identity reporting (task book section 2).

The AmazingData SDK is broker-distributed and only installed on the
controlled machine. CI and any clean clone must import this module and
fail with ProviderUnavailableError - never ImportError.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import sys
from dataclasses import dataclass
from typing import Any

from ashare_state.providers.amazingdata.errors import ProviderUnavailableError

SDK_MODULE = "AmazingData"
TGW_MODULE = "tgw"


@dataclass(frozen=True)
class SdkIdentity:
    """Everything the doctor needs from a successful SDK import."""

    sdk_module: str
    sdk_version: str | None
    tgw_module: str | None
    tgw_package_version: str | None
    tgw_runtime_version: str | None  # tgw.GetVersion() - the REAL runtime line
    python_version: str
    abi_dir: str | None  # e.g. win_py314_x64_package

    @property
    def sdk_abi(self) -> str:
        impl = sys.implementation.name
        return f"{impl}{sys.version_info.major}{sys.version_info.minor}/{sys.platform}"


def load_sdk() -> Any:
    """Import AmazingData lazily; typed error when absent (CI-safe)."""
    try:
        return importlib.import_module(SDK_MODULE)
    except ImportError as exc:
        msg = (
            f"AmazingData SDK ({SDK_MODULE}) is not installed in this "
            "environment; install the broker wheels on the controlled machine "
            "(uv pip install <wheel>) - see docs/provider_verification/amazingdata.md"
        )
        raise ProviderUnavailableError(msg) from exc


def probe_identity(*, require_sdk: bool = True) -> SdkIdentity | None:
    """Collect version identity without touching the network.

    Returns None when the SDK is absent and require_sdk is False
    (doctor offline mode uses this to still report Python-side facts).
    """
    sdk: Any = None
    try:
        sdk = importlib.import_module(SDK_MODULE)
        sdk_version = importlib.metadata.version(SDK_MODULE)
    except (ImportError, importlib.metadata.PackageNotFoundError):
        if require_sdk:
            raise
        sdk_version = None

    tgw_pkg_version: str | None = None
    tgw_runtime: str | None = None
    abi_dir: str | None = None
    try:
        importlib.import_module(TGW_MODULE)
        tgw_pkg_version = importlib.metadata.version(TGW_MODULE)
        try:
            import tgw

            tgw_runtime = str(tgw.GetVersion()).strip() or None
        except Exception:  # noqa: BLE001 - GetVersion is best-effort
            tgw_runtime = None
        abi_dir = _infer_abi_dir()
    except (ImportError, importlib.metadata.PackageNotFoundError):
        pass

    if sdk is None:
        return None
    return SdkIdentity(
        sdk_module=SDK_MODULE,
        sdk_version=sdk_version,
        tgw_module=TGW_MODULE,
        tgw_package_version=tgw_pkg_version,
        tgw_runtime_version=tgw_runtime,
        python_version=sys.version.split()[0],
        abi_dir=abi_dir,
    )


def _infer_abi_dir() -> str | None:
    """Which ABI subpackage the loader would pick for this interpreter."""
    try:
        import pathlib

        import tgw

        pkg_dir = pathlib.Path(tgw.__file__).parent
        tag = f"py{sys.version_info.major}{sys.version_info.minor}_x64_package"
        prefix = "win_" if sys.platform == "win32" else "linux_"
        cand = pkg_dir / f"{prefix}{tag}"
        return cand.name if cand.is_dir() else None
    except Exception:  # noqa: BLE001 - inference is best-effort
        return None

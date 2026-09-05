"""Provider doctor: runtime identity + connectivity diagnosis (task book §2).

Output fields (ruling-mandated):
    PYTHON_VERSION, AMAZINGDATA_PACKAGE_VERSION, PYTHON_TGW_PACKAGE_VERSION,
    TGW_RUNTIME_REPORTED_VERSION, TGW_LOADED_DLL_PATH, TGW_LOADED_DLL_VERSION,
    SDK_ABI, NETWORK_REACHABLE, AUTHENTICATED, QUERY_READY, ACCOUNT_PROFILE

Verdict: RUNTIME_PACKAGE_VERIFIED | RUNTIME_ACTUAL_LOAD_VERIFIED |
         RUNTIME_VERSION_MISMATCH | RUNTIME_PATH_AMBIGUOUS

Known facts (2026-08-21): the tgw python wheel ships its own DLL set under
site-packages/tgw/win_py314_x64_package/ (runtime V4.3.0.x) - independent
from the C++ SDK 1.0.8 installed under Public Documents. DLLs carry no
version resource, so TGW_LOADED_DLL_VERSION falls back to the runtime's
self-reported GetVersion() with an explicit note.
"""

from __future__ import annotations

import ctypes
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ashare_state.providers.amazingdata.errors import (
    ProviderError,
    ProviderUnavailableError,
)
from ashare_state.providers.amazingdata.safe_diagnostics import (
    safe_diagnostic_projection,
    safe_error_code,
)
from ashare_state.providers.amazingdata.sdk_loader import (
    probe_identity,
    resolve_packaged_runtime_path,
)
from ashare_state.providers.amazingdata.session import AmazingDataSession
from ashare_state.providers.amazingdata.stdout_capture import (
    CapturedStderr,
    CapturedStdout,
    sdk_stderr_into,
    sdk_stdout_into,
)


# ---------------------------------------------------------------- win helpers
def _loaded_tgw_modules() -> list[str]:
    """Enumerate this process's loaded modules, keep tgw-related ones."""
    if sys.platform != "win32":
        return []
    try:
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        # Win32 API constants (UPPERCASE per Microsoft docs)
        process_query_information, process_vm_read = 0x0400, 0x0010
        list_modules_all = 0x03
        handle = kernel32.OpenProcess(
            process_query_information | process_vm_read, False, os.getpid()
        )
        if not handle:
            return []
        try:
            buf = (ctypes.c_void_p * 4096)()
            needed = ctypes.c_ulong()
            if not psapi.EnumProcessModulesEx(
                handle, buf, ctypes.sizeof(buf), ctypes.byref(needed), list_modules_all
            ):
                return []
            hits: list[str] = []
            count = needed.value // ctypes.sizeof(ctypes.c_void_p)
            for i in range(count):
                name = ctypes.create_unicode_buffer(1024)
                psapi.GetModuleFileNameExW(handle, ctypes.c_void_p(buf[i]), name, 1024)
                lowered = name.value.lower()
                if "tgw" in lowered or "mimalloc" in lowered:
                    hits.append(name.value)
            return hits
        finally:
            kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001 - diagnostics must never crash the doctor
        return []


def _dll_file_version(path: str) -> str | None:
    """Best-effort version-resource read (TGW DLLs ship without one)."""
    if sys.platform != "win32" or not Path(path).is_file():
        return None
    try:
        version_dll = ctypes.windll.version
        size = version_dll.GetFileVersionInfoSizeW(path, None)
        if size == 0:
            return None
        data = ctypes.create_string_buffer(size)
        if not version_dll.GetFileVersionInfoW(path, 0, size, data):
            return None
        value = ctypes.c_void_p()
        length = ctypes.c_uint()
        if (
            not version_dll.VerQueryValueW(
                data, "\\VarFileInfo\\Translation", ctypes.byref(value), ctypes.byref(length)
            )
            or not length.value
        ):
            return None
        lang_cp = ctypes.cast(value, ctypes.POINTER(ctypes.c_uint16))[0]
        code = f"{lang_cp >> 16:04X}{lang_cp & 0xFFFF:04X}"
        vptr = ctypes.c_void_p()
        vlen = ctypes.c_uint()
        for key in (
            f"\\StringFileInfo\\{code}\\FileVersion",
            f"\\StringFileInfo\\{code}\\ProductVersion",
        ):
            if (
                version_dll.VerQueryValueW(data, key, ctypes.byref(vptr), ctypes.byref(vlen))
                and vlen.value
            ):
                addr = vptr.value
                if addr is None:
                    continue
                return ctypes.wstring_at(addr, vlen.value - 1)
    except Exception:  # noqa: BLE001
        return None
    return None


# ------------------------------------------------------------------- doctor
def _network_probe(host: str, port: int, timeout_seconds: float = 5.0) -> str:
    """Raw TCP reachability (independent of the SDK)."""
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return "REACHABLE"
    except OSError as exc:
        return f"UNREACHABLE ({type(exc).__name__})"


def _collect_doctor(
    *,
    credentials: tuple[str, str, str, int] | None,
    offline: bool = False,
) -> dict[str, Any]:
    """Collect the full doctor report; never raises for expected failures."""
    report: dict[str, Any] = {
        "checked_at": datetime.now(UTC).isoformat(),
        "platform": sys.platform,
        "PYTHON_VERSION": sys.version.split()[0],
        "SDK_ABI": (
            f"{sys.implementation.name}{sys.version_info.major}"
            f"{sys.version_info.minor}/{sys.platform}-x64"
        ),
    }

    # ---- SDK presence + versions ------------------------------------
    try:
        identity = probe_identity(require_sdk=not offline)
    except ProviderUnavailableError as exc:
        report["sdk_state"] = "SDK_NOT_INSTALLED"
        report["error_code"] = safe_error_code(exc)
        report["verdict"] = "RUNTIME_PATH_AMBIGUOUS"  # nothing to verify
        return report

    if identity is None:
        report["sdk_state"] = "SDK_NOT_INSTALLED"
        report["verdict"] = "RUNTIME_PATH_AMBIGUOUS"
        return report

    report.update(
        {
            "sdk_state": "SDK_INSTALLED",
            "AMAZINGDATA_PACKAGE_VERSION": identity.sdk_version,
            "PYTHON_TGW_PACKAGE_VERSION": identity.tgw_package_version,
            "TGW_RUNTIME_REPORTED_VERSION": identity.tgw_runtime_version,
            "tgw_abi_dir": identity.abi_dir,
        }
    )

    # ---- loaded DLL identity -----------------------------------------
    modules = _loaded_tgw_modules()
    tgw_dlls = [m for m in modules if m.lower().endswith("tgw.dll")]
    pyd_modules = [m for m in modules if m.lower().endswith("_tgw.pyd")]
    if tgw_dlls or pyd_modules:
        loaded_dll = tgw_dlls[0] if tgw_dlls else None
        report["TGW_LOADED_DLL_PATH"] = loaded_dll or (pyd_modules[0] if pyd_modules else None)
        report["TGW_LOADED_DLL_VERSION"] = _dll_file_version(loaded_dll) if loaded_dll else None
        if loaded_dll and not report["TGW_LOADED_DLL_VERSION"]:
            report["dll_version_note"] = (
                "DLL has no version resource; runtime self-reports "
                f"{identity.tgw_runtime_version} (tgw.GetVersion)"
            )
    else:
        report["TGW_LOADED_DLL_PATH"] = None
        report["dll_note"] = "tgw DLL not loaded yet (loads on first SDK use)"
        # P1-11: use the SINGLE authoritative resolver from sdk_loader
        runtime_dir = resolve_packaged_runtime_path()
        if runtime_dir is not None:
            dll_name = "tgw.dll" if sys.platform == "win32" else "libtgw.so"
            candidate = runtime_dir / dll_name
            report["expected_dll_path"] = str(candidate) if candidate.is_file() else None
        else:
            report["expected_dll_path"] = None

    # ---- connectivity / auth / query --------------------------------
    report["NETWORK_REACHABLE"] = "NOT_TESTED"
    report["AUTHENTICATED"] = "NOT_TESTED"
    report["QUERY_READY"] = "NOT_TESTED"
    report["ACCOUNT_PROFILE"] = None

    if credentials and not offline:
        username, password, host, port = credentials
        report["NETWORK_REACHABLE"] = _network_probe(host, port)
        session = AmazingDataSession(username, password, host, port)
        try:
            profile = session.login()
            report["AUTHENTICATED"] = "YES" if profile.login_ok else "NO"
            report["ACCOUNT_PROFILE"] = {
                "account_profile_id": profile.account_profile_id,
                "permission_codes": profile.permission_codes,
                "subscribe_limit": profile.subscribe_limit,
                "weekly_flow_limit": profile.weekly_flow_limit,
                "used_week_flow": profile.used_week_flow,
            }
            # QUERY_READY: lightest entitled call - code list (verified PASS)
            try:
                base = session.sdk.BaseData()
                holder = CapturedStdout()
                with sdk_stdout_into(holder):
                    codes = base.get_code_list()
                report["QUERY_READY"] = "YES" if codes is not None else "NO"
            except Exception as exc:  # noqa: BLE001 - evidence, not crash
                report["QUERY_READY"] = f"NO ({type(exc).__name__})"
            # R2-P1-04: re-probe the loaded DLL AFTER real SDK activity -
            # the native runtime may load lazily on first call
            post_modules = _loaded_tgw_modules()
            post_dlls = [m for m in post_modules if m.lower().endswith("tgw.dll")]
            if post_dlls:
                report["TGW_LOADED_DLL_PATH_POST_LOGIN"] = post_dlls[0]
                report["TGW_LOADED_DLL_VERSION"] = _dll_file_version(post_dlls[0])
        except ProviderError as exc:
            report["AUTHENTICATED"] = f"NO ({type(exc).__name__})"
            report["auth_error"] = safe_error_code(exc)
        finally:
            session.logout()

    # ---- verdict (R2-P1-04: package vs ACTUAL LOAD are separate facts) --
    loaded_path = (
        report.get("TGW_LOADED_DLL_PATH_POST_LOGIN") or report.get("TGW_LOADED_DLL_PATH") or ""
    ).lower()
    expected_path = (report.get("expected_dll_path") or "").lower()
    if loaded_path:
        site_packages_ok = "site-packages" in loaded_path and "tgw" in loaded_path
        public_docs = "mdga_file" in loaded_path
        if public_docs or not site_packages_ok:
            report["verdict"] = "RUNTIME_PATH_AMBIGUOUS"
            report["verdict_detail"] = (
                "ACTUALLY LOADED tgw DLL is outside the python wheel's package "
                "dir; verify no C++ 1.0.8 runtime is being mixed in"
            )
        else:
            report["verdict"] = "RUNTIME_ACTUAL_LOAD_VERIFIED"
            report["verdict_detail"] = (
                "python wheel ships AND loaded its own runtime "
                f"({identity.tgw_runtime_version}); independent from the "
                "C++ SDK install under Public Documents"
            )
    elif expected_path:
        # DLL not loaded yet (e.g. offline mode): wheel-level verification
        # only - audit R2-P1-04: this is NOT the same as load verification
        report["verdict"] = "RUNTIME_PACKAGE_VERIFIED"
        report["verdict_detail"] = (
            "packaged runtime present (wheel-level); actual DLL load "
            "unverified - run doctor ONLINE to confirm "
            f"(self-reported {identity.tgw_runtime_version})"
        )
    else:
        report["verdict"] = "RUNTIME_PATH_AMBIGUOUS"
        report["verdict_detail"] = "no packaged runtime found for this ABI"
    return report


def run_doctor(
    *,
    credentials: tuple[str, str, str, int] | None,
    offline: bool = False,
) -> dict[str, Any]:
    """Collect under output containment and return only public safe diagnostics."""
    stdout, stderr = CapturedStdout(), CapturedStderr()
    try:
        with sdk_stdout_into(stdout), sdk_stderr_into(stderr):
            try:
                raw = _collect_doctor(credentials=credentials, offline=offline)
            except Exception as exc:  # noqa: BLE001 - do not emit SDK exception text
                raw = {
                    "sdk_state": "ERROR",
                    "verdict": "NOT_VERIFIED",
                    "error_code": safe_error_code(exc),
                }
        return safe_diagnostic_projection(raw, offline=offline)
    finally:
        stdout.text = ""
        stderr.text = ""

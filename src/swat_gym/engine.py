"""Locating and invoking the SWAT+ engine — the only platform-dependent layer.

Drop a platform-native build into ``model/TxtInOut``; :func:`find_engine` picks it by magic
and ignores backups / wrong-OS siblings. Vendored engines for this project are **rev 62.0.0**.
"""
from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

_MAGIC = {
    "macho": (
        b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce",
        b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
    ),
    "elf": (b"\x7fELF",),
    "pe": (b"MZ",),
}
_ALL_MAGIC = tuple(m for group in _MAGIC.values() for m in group)


class EngineError(RuntimeError):
    """The SWAT+ engine could not be found, or exited without producing output."""


def _family(path: Path) -> str | None:
    try:
        head = path.open("rb").read(4)
    except OSError:
        return None
    for name, magics in _MAGIC.items():
        if head.startswith(magics):
            return name
    return None


def _is_backup(path: Path) -> bool:
    n = path.name.lower()
    return n.endswith(".bak") or ".bak." in n or n.endswith(".old")


def _wanted_family() -> str:
    system = platform.system()
    if system == "Linux":
        return "elf"
    if system == "Darwin":
        return "macho"
    if system == "Windows":
        return "pe"
    return "elf"


def _is_executable_binary(path: Path) -> bool:
    if not path.is_file() or _is_backup(path):
        return False
    if os.name != "nt" and not os.access(path, os.X_OK):
        return False
    return _family(path) is not None


def find_engine(txtinout: Path) -> Path:
    """Return the platform-native SWAT+ executable inside ``txtinout``.

    Backups (``*.bak``) and wrong-OS binaries (e.g. Linux ELF on macOS) are ignored so both
    the Mac and Linux rev-62 builds can sit in the same directory.
    """
    wanted = _wanted_family()
    candidates = sorted(
        p for p in txtinout.iterdir()
        if _is_executable_binary(p) and _family(p) == wanted
    )
    if not candidates:
        raise EngineError(
            f"No native SWAT+ executable ({wanted}) found in {txtinout}. "
            f"Place a rev 62.0.0 build for this OS there "
            f"(Mac: Mach-O, Linux: ELF). Backups named *.bak are ignored."
        )
    if len(candidates) > 1:
        # Prefer a name that advertises rev 62.
        preferred = [p for p in candidates if "62" in p.name]
        if len(preferred) == 1:
            return preferred[0]
        names = ", ".join(p.name for p in candidates)
        raise EngineError(f"Multiple native executables in {txtinout}: {names}. Keep one.")
    return candidates[0]


def run_engine(exe: Path, run_dir: Path, timeout: float = 600.0) -> str:
    """Run ``exe`` with ``run_dir`` as the working directory; return its stdout."""
    try:
        proc = subprocess.run(
            [str(exe)],
            cwd=run_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise EngineError(f"SWAT+ timed out after {timeout}s in {run_dir}") from e
    if proc.returncode != 0:
        raise EngineError(
            f"SWAT+ exited {proc.returncode} in {run_dir}\n"
            f"--- stdout tail ---\n{proc.stdout[-2000:]}\n"
            f"--- stderr tail ---\n{proc.stderr[-2000:]}"
        )
    return proc.stdout

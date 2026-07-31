"""Locating and invoking the SWAT+ engine — the only platform-dependent layer.

Everything else in ``swat_gym`` reads and writes SWAT+ text files and is OS-agnostic.
When this project moves to Linux/WSL, this module is the file that changes: drop a Linux
build into ``model/TxtInOut`` and :func:`find_engine` picks it up by ELF magic instead of
Mach-O. Nothing above needs to know.

The vendored macOS engine is Mach-O **x86_64**, so on Apple Silicon it runs under Rosetta 2 —
timings here are a conservative floor, not a ceiling.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Executable magic numbers by platform family. pySWATPlus only knows ELF/PE, which is why
# runner.py needs its Mach-O shim; we do our own detection and skip the monkeypatch.
_MAGIC = {
    "macho": (
        b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe",  # 64/32-bit little-endian
        b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce",  # 64/32-bit big-endian
        b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",  # universal (fat)
    ),
    "elf": (b"\x7fELF",),
    "pe": (b"MZ",),
}
_ALL_MAGIC = tuple(m for group in _MAGIC.values() for m in group)


class EngineError(RuntimeError):
    """The SWAT+ engine could not be found, or exited without producing output."""


def _is_executable_binary(path: Path) -> bool:
    """True if ``path`` is a native executable for any supported platform."""
    if not path.is_file():
        return False
    # Windows has no execute bit; rely on magic + suffix there.
    if os.name != "nt" and not os.access(path, os.X_OK):
        return False
    try:
        head = path.open("rb").read(4)
    except OSError:
        return False
    return head.startswith(_ALL_MAGIC)


def find_engine(txtinout: Path) -> Path:
    """Return the SWAT+ executable inside ``txtinout``.

    Raises :class:`EngineError` if there is not exactly one candidate, so that a stale or
    duplicated binary fails loudly rather than being picked arbitrarily.
    """
    candidates = sorted(p for p in txtinout.iterdir() if _is_executable_binary(p))
    if not candidates:
        raise EngineError(
            f"No SWAT+ executable found in {txtinout}. On Linux/WSL, place an ELF build of "
            f"the engine there; on macOS a Mach-O build."
        )
    if len(candidates) > 1:
        names = ", ".join(p.name for p in candidates)
        raise EngineError(f"Multiple executables in {txtinout}: {names}. Keep exactly one.")
    return candidates[0]


def run_engine(exe: Path, run_dir: Path, timeout: float = 600.0) -> str:
    """Run ``exe`` with ``run_dir`` as the working directory; return its stdout.

    SWAT+ resolves every path relative to the working directory (it reads ``file.cio`` from
    there), so the engine must be invoked with ``cwd`` set — not given an absolute model path.
    """
    try:
        proc = subprocess.run(
            [str(exe)],
            cwd=run_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise EngineError(f"SWAT+ timed out after {timeout}s in {run_dir}") from exc

    if proc.returncode != 0:
        tail = (proc.stdout or "")[-2000:]
        raise EngineError(
            f"SWAT+ exited {proc.returncode} in {run_dir}\n--- stdout tail ---\n{tail}"
        )
    return proc.stdout

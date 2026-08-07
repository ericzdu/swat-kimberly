"""Terminal progress bars for long CMA / PPO runs.

Uses ``tqdm`` when installed (``uv sync --extra rl``). Falls back to quiet no-ops so unit
tests and bare installs keep working without the optional dep.
"""
from __future__ import annotations

from typing import Any


def progress(total: int, *, initial: int = 0, desc: str = "", unit: str = "it"):
    """Return a tqdm bar, or a stub with the same ``update`` / ``set_postfix_str`` / ``close`` API."""
    try:
        from tqdm.auto import tqdm
    except ImportError:
        return _NullBar(total=total, initial=initial, desc=desc)
    return tqdm(
        total=total,
        initial=initial,
        desc=desc,
        unit=unit,
        dynamic_ncols=True,
        mininterval=0.5,
    )


class _NullBar:
    def __init__(self, total: int = 0, initial: int = 0, desc: str = ""):
        self.total = total
        self.n = initial
        self.desc = desc

    def update(self, n: int = 1) -> None:
        self.n += n

    def set_postfix_str(self, _: str, refresh: bool = True) -> None:  # noqa: ARG002
        return

    def set_postfix(self, **_: Any) -> None:
        return

    def close(self) -> None:
        return

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def ppo_callbacks(checkpoint):
    """Return ``checkpoint`` alone — pair with :func:`ppo_progress_bar` on ``learn``."""
    return checkpoint


def ppo_progress_bar() -> bool:
    """Whether SB3's ``progress_bar=True`` is safe (needs ``tqdm`` *and* ``rich``)."""
    try:
        import rich  # noqa: F401
        import tqdm  # noqa: F401
    except ImportError:
        return False
    return True

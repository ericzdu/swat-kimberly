"""ASCII-safe text for API responses (Windows cp1252 compatibility)."""
from __future__ import annotations

import re

_UNICODE_REPLACEMENTS = (
    ("\u2014", "-"),   # em dash
    ("\u2013", "-"),   # en dash
    ("\u2192", "->"),  # arrow
    ("\u2022", "-"),   # bullet
    ("\u2018", "'"),
    ("\u2019", "'"),
    ("\u201c", '"'),
    ("\u201d", '"'),
)


def safe_text(value: object) -> str:
    """Return a string safe for ASCII consoles and legacy Windows encodings."""
    text = str(value)
    for old, new in _UNICODE_REPLACEMENTS:
        text = text.replace(old, new)
    return text.encode("ascii", errors="replace").decode("ascii")


def is_plausible_api_key(key: str) -> bool:
    """Reject pasted UI errors and other non-key text saved by mistake."""
    if not key or len(key.strip()) < 8:
        return False
    k = key.strip()
    lowered = k.lower()
    if any(phrase in lowered for phrase in (
        "could not load",
        "backend",
        "settings",
        "http ",
        "error",
        "failed",
        "connection refused",
    )):
        return False
    if " " in k and len(k) > 40:
        return False
    try:
        k.encode("ascii")
    except UnicodeEncodeError:
        return False
    return True


def sanitize_api_key(key: str) -> str:
    """Normalize a key for HTTP headers (ASCII only)."""
    return safe_text(key).strip()

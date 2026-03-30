"""Shared utility functions."""

from __future__ import annotations

import re


def is_wildcard(name: str) -> bool:
    """Check if name is a wildcard train name ('any' or '*')."""
    n = name.strip().lower()
    return n in ("any", "*")


def parse_price(s: str) -> int:
    """Parse a price string (e.g. 'Rp 350.000', '350000') into integer Rupiah.
    Returns 0 if parsing fails.
    """
    s = s.strip()
    s = s.removeprefix("Rp ")
    s = s.removeprefix("Rp")
    s = s.replace(".", "").replace(",", "")
    s = s.strip()

    # Remove decimal part
    if "." in s:
        s = s[: s.index(".")]

    try:
        return int(s)
    except ValueError:
        return 0


def format_rupiah(amount: int) -> str:
    """Format an integer as Indonesian Rupiah with dot separators.
    e.g. 350000 -> '350.000'
    """
    s = str(amount)
    n = len(s)
    if n <= 3:
        return s

    result = []
    for i, c in enumerate(s):
        if i > 0 and (n - i) % 3 == 0:
            result.append(".")
        result.append(c)
    return "".join(result)


def format_number(s: str) -> str:
    """Add dots to a number string: '385000' -> '385.000'."""
    digits = re.sub(r"\D", "", s)
    n = len(digits)
    if n <= 3:
        return digits

    result = []
    for i, d in enumerate(digits):
        if i > 0 and (n - i) % 3 == 0:
            result.append(".")
        result.append(d)
    return "".join(result)


def format_duration(seconds: float) -> str:
    """Format seconds into a human readable string like '1h 30m' or '5m 30s'."""
    seconds = int(seconds)
    h = seconds // 3600
    seconds %= 3600
    m = seconds // 60
    s = seconds % 60

    if h > 0:
        return f"{h}h {m}m"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"

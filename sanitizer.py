"""
Input sanitization utilities for the CarbonWise platform.

Centralizes all input cleaning, normalization, and boundary-enforcement
logic so that controllers, calculators, and services share a single
source of truth for what constitutes valid user input.

Security relevance:
    • Strips control characters and zero-width Unicode from free-text fields
      to prevent log-injection and invisible-character attacks.
    • Clamps numeric values to documented physical ranges.
    • Normalizes string identifiers to a canonical form.
"""

import re
from typing import Optional

# Pre-compiled regex: matches C0/C1 control characters (except newline/tab)
# and Unicode zero-width / directional-override code points.
_CONTROL_CHAR_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f"
    r"\u200b-\u200f\u2028-\u202e\ufeff]"
)


def sanitize_text(value: str, *, max_length: int = 500) -> str:
    """Strip control characters and enforce maximum length on free-text input.

    Args:
        value: Raw user-provided string.
        max_length: Upper bound on character count after cleaning.

    Returns:
        Cleaned, length-limited string with leading/trailing whitespace removed.
    """
    cleaned = _CONTROL_CHAR_RE.sub("", value)
    cleaned = cleaned.strip()
    return cleaned[:max_length]


def sanitize_user_id(user_id: str) -> str:
    """Normalize a user identifier to a safe canonical form.

    Allows only alphanumerics, underscores, hyphens, and periods.
    Anything else is stripped.  Final length is capped at 100 characters.

    Args:
        user_id: Raw user-provided identifier string.

    Returns:
        Sanitized identifier safe for use as a database key.
    """
    cleaned = re.sub(r"[^a-zA-Z0-9_.\-]", "", user_id.strip())
    return cleaned[:100]


def clamp_float(
    value: float,
    *,
    minimum: float = 0.0,
    maximum: float = 100_000.0,
    label: str = "value",
) -> float:
    """Clamp a numeric value to a safe physical range.

    Args:
        value: Raw numeric input.
        minimum: Lower bound (inclusive).
        maximum: Upper bound (inclusive).
        label: Human-readable field name for error messages.

    Returns:
        The value clamped to ``[minimum, maximum]``.

    Raises:
        ValueError: If *value* is ``NaN`` or ``±inf``.
    """
    import math

    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"{label} must be a finite number, got {value!r}.")
    return max(minimum, min(value, maximum))


def normalize_travel_mode(mode: str) -> str:
    """Normalize a travel-mode string to the canonical lowercase form.

    Accepts common aliases (e.g. ``"driving"`` → ``"car"``,
    ``"cycling"`` → ``"bicycle"``).

    Args:
        mode: Raw mode string from client.

    Returns:
        Canonical mode key recognized by :class:`CarbonCalculator`.
    """
    aliases = {
        "driving": "car",
        "drive": "car",
        "cycling": "bicycle",
        "cycle": "bicycle",
        "transit": "bus",
        "public_transit": "bus",
        "walking": "walk",
        "fly": "flight",
        "airplane": "flight",
        "rail": "train",
        "metro": "train",
        "subway": "train",
        "motorbike": "motorcycle",
    }
    canonical = mode.strip().lower()
    return aliases.get(canonical, canonical)


def normalize_diet_type(diet: str) -> str:
    """Normalize a diet-type string to the canonical lowercase form.

    Accepts common aliases (e.g. ``"meat_heavy"`` → ``"heavy_meat"``).

    Args:
        diet: Raw diet type string from client.

    Returns:
        Canonical diet key recognized by :class:`CarbonCalculator`.
    """
    aliases = {
        "meat_heavy": "heavy_meat",
        "omnivore": "average",
        "flexitarian": "no_beef",
        "pescatarian": "no_beef",
        "plant_based": "vegan",
        "plant-based": "vegan",
    }
    canonical = diet.strip().lower()
    return aliases.get(canonical, canonical)

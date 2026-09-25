"""Normalisation helpers, aliases, colours and intensity words."""
from __future__ import annotations

import difflib
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

from .errors import GarmentError


def normalize(value: object) -> str:
    """'T-Shirt ' -> 't_shirt'; 'Heavy  Denim' -> 'heavy_denim'."""
    s = str(value if value is not None else "").strip().lower()
    s = re.sub(r"[\s\-/]+", "_", s)
    s = re.sub(r"[^a-z0-9_.#%+]", "", s)
    return s.strip("_")


def compact(value: object) -> str:
    """normalize() with underscores removed: 't_shirt' -> 'tshirt'."""
    return normalize(value).replace("_", "")


def resolve_alias(value: object, canonical: Iterable[str], aliases: Dict[str, str]) -> Optional[str]:
    n = normalize(value)
    names = list(canonical)
    if n in names:
        return n
    if n in aliases:
        return aliases[n]
    c = n.replace("_", "")
    for name in names:
        if name.replace("_", "") == c:
            return name
    for alias, target in aliases.items():
        if alias.replace("_", "") == c:
            return target
    return None


def suggest(value: object, options: Iterable[str], n: int = 3) -> List[str]:
    opts = sorted(set(options))
    close = difflib.get_close_matches(normalize(value), opts, n=n, cutoff=0.5)
    return close or opts[:8]


# --- colours (sRGB 0..1) -------------------------------------------------------
COLORS: Dict[str, Tuple[float, float, float]] = {
    "black": (0.02, 0.02, 0.02), "white": (0.95, 0.95, 0.95), "off_white": (0.93, 0.91, 0.86),
    "cream": (0.96, 0.93, 0.82), "grey": (0.5, 0.5, 0.5), "light_grey": (0.75, 0.75, 0.75),
    "dark_grey": (0.25, 0.25, 0.25), "charcoal": (0.2, 0.21, 0.22), "heather_grey": (0.62, 0.62, 0.63),
    "navy": (0.07, 0.1, 0.25), "blue": (0.1, 0.25, 0.7), "light_blue": (0.55, 0.7, 0.9),
    "sky_blue": (0.5, 0.75, 0.95), "royal_blue": (0.15, 0.25, 0.75), "denim_blue": (0.2, 0.3, 0.45),
    "indigo": (0.18, 0.2, 0.4), "red": (0.75, 0.08, 0.08), "burgundy": (0.4, 0.06, 0.12),
    "maroon": (0.38, 0.05, 0.08), "pink": (0.95, 0.6, 0.7), "orange": (0.95, 0.45, 0.1),
    "yellow": (0.95, 0.85, 0.2), "mustard": (0.8, 0.6, 0.12), "green": (0.12, 0.5, 0.2),
    "dark_green": (0.07, 0.25, 0.12), "olive": (0.4, 0.4, 0.18), "khaki": (0.72, 0.66, 0.48),
    "beige": (0.85, 0.78, 0.65), "tan": (0.75, 0.6, 0.42), "brown": (0.4, 0.25, 0.14),
    "camel": (0.76, 0.6, 0.42), "purple": (0.4, 0.15, 0.55), "lavender": (0.72, 0.64, 0.86),
    "teal": (0.05, 0.45, 0.45), "turquoise": (0.2, 0.75, 0.75),
}
COLOR_ALIASES = {"gray": "grey", "light_gray": "light_grey", "dark_gray": "dark_grey", "heather_gray": "heather_grey",
                 "navy_blue": "navy", "dark_blue": "navy", "wine": "burgundy", "offwhite": "off_white",
                 "ivory": "cream", "army_green": "olive", "forest_green": "dark_green", "violet": "purple"}

_HEX = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")

ColorValue = Union[str, Sequence[float]]


def parse_color(value: ColorValue) -> Tuple[float, float, float, float]:
    """Return sRGB RGBA in 0..1. Accepts names, '#rrggbb', '#rgb', or 3/4 numbers."""
    if isinstance(value, (list, tuple)):
        if len(value) not in (3, 4) or not all(isinstance(c, (int, float)) and not isinstance(c, bool)
                                               for c in value):
            raise GarmentError("INVALID_COLOR", f"Colour {list(value)!r} must have 3 or 4 numbers.", path="color")
        vals = [float(c) for c in value]
        if any(c > 1.0 for c in vals[:3]):
            vals = [c / 255.0 for c in vals[:3]] + vals[3:]
        if not all(0.0 <= c <= 1.0 for c in vals):
            raise GarmentError("INVALID_COLOR", f"Colour {list(value)!r} is out of range.", path="color")
        return (vals[0], vals[1], vals[2], vals[3] if len(vals) == 4 else 1.0)
    text = str(value).strip()
    if text.startswith("#") or (len(text) == 6 and _HEX.match(text)):
        m = _HEX.match(text)
        if not m:
            raise GarmentError("INVALID_COLOR", f"'{text}' is not a valid hex colour.", path="color",
                               suggestions=["#1a1a1a", "black", "navy"])
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0, 1.0)
    name = resolve_alias(text, COLORS, COLOR_ALIASES)
    if name is None:
        raise GarmentError("INVALID_COLOR", f"Unknown colour '{text}'.", path="color",
                           suggestions=suggest(text, list(COLORS) + list(COLOR_ALIASES)))
    r, g, b = COLORS[name]
    return (r, g, b, 1.0)


def canonical_color(value: ColorValue) -> ColorValue:
    """Normalise colour names ('Navy Blue' -> 'navy'); leave hex / tuples as given."""
    if isinstance(value, str):
        name = resolve_alias(value, COLORS, COLOR_ALIASES)
        if name:
            return name
        return value.strip()
    return list(value) if isinstance(value, (list, tuple)) else value


def srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


# --- intensity -------------------------------------------------------------------
INTENSITY_WORDS: Dict[str, float] = {
    "slightly": 0.5, "a_bit": 0.5, "a_little": 0.5, "a_little_bit": 0.5, "somewhat": 0.5, "a_touch": 0.5,
    "a_tad": 0.5, "subtly": 0.5, "bit": 0.5, "little": 0.5,
    "much": 2.0, "a_lot": 2.0, "way": 2.0, "very": 2.0, "significantly": 2.0, "considerably": 2.0,
    "really": 2.0, "extremely": 2.0, "lot": 2.0,
}


def parse_intensity(value: object, default: float = 1.0) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        raise GarmentError("INVALID_PARAM", "intensity must be a number or word like 'slightly'.", path="intensity")
    if isinstance(value, (int, float)):
        if not 0.0 < float(value) <= 3.0:
            raise GarmentError("INVALID_PARAM", f"intensity {value} must be in (0, 3].", path="intensity")
        return float(value)
    n = normalize(value)
    if n in INTENSITY_WORDS:
        return INTENSITY_WORDS[n]
    if n in ("normal", "default", "moderate", "moderately"):
        return 1.0
    raise GarmentError("INVALID_PARAM", f"Unknown intensity '{value}'.", path="intensity",
                       suggestions=["slightly", "much", "0.5", "2.0"])


# --- fit vocabulary (shared by garment_spec and fit_system) -------------------------
FIT_LEVELS = ["tight", "slim", "regular", "relaxed", "loose", "oversized"]
FIT_ALIASES = {"skinny": "tight", "snug": "tight", "fitted": "slim", "slim_fit": "slim", "tailored": "slim",
               "standard": "regular", "normal": "regular", "classic": "regular", "straight": "regular",
               "comfort": "relaxed", "relaxed_fit": "relaxed", "boxy": "relaxed", "baggy": "loose",
               "wide": "loose", "roomy": "loose", "oversize": "oversized", "over_sized": "oversized",
               "big": "oversized", "huge": "oversized"}
# comparative -> direction (+1 looser / -1 tighter)
FIT_COMPARATIVES = {"tighter": -1, "slimmer": -1, "snugger": -1, "narrower": -1, "more_fitted": -1,
                    "looser": 1, "baggier": 1, "roomier": 1, "wider": 1, "bigger": 1, "fuller": 1}


def normalize_fit_level(value: object) -> Optional[str]:
    n = normalize(value)
    n = FIT_ALIASES.get(n, n)
    return n if n in FIT_LEVELS else None


def fit_direction(value: object) -> Optional[int]:
    """'tighter' -> -1, 'looser' -> +1, otherwise None."""
    n = normalize(value)
    return FIT_COMPARATIVES.get(n)

"""Relative / absolute amount parsing: '+10%', '-5%', '+3cm', '2in', 0.05 (metres)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Union

from .errors import GarmentError

_UNITS = {"cm": 0.01, "mm": 0.001, "m": 1.0, "in": 0.0254, "inch": 0.0254, "inches": 0.0254, '"': 0.0254}
_RE = re.compile(r'^\s*([+-]?)\s*(\d+(?:\.\d+)?|\.\d+)\s*(%|percent|cm|mm|inches|inch|in|m|")?\s*$',
                 re.IGNORECASE)


@dataclass(frozen=True)
class Amount:
    kind: str  # "percent" | "length"
    value: float  # percent points, or metres

    def apply(self, base: float) -> float:
        return base * (1.0 + self.value / 100.0) if self.kind == "percent" else base + self.value

    def to_string(self) -> str:
        if self.kind == "percent":
            return f"{self.value:+g}%"
        return f"{self.value * 100:+g}cm"

    def to_dict(self):
        return {"kind": self.kind, "value": self.value}


AmountLike = Union[str, int, float, Amount]


def parse_amount(value: AmountLike) -> Amount:
    if isinstance(value, Amount):
        return value
    if isinstance(value, bool) or value is None:
        raise GarmentError("INVALID_AMOUNT", f"Invalid amount {value!r}.", suggestions=["+10%", "-5%", "+3cm"])
    if isinstance(value, (int, float)):
        return Amount("length", float(value))
    m = _RE.match(str(value))
    if not m:
        raise GarmentError("INVALID_AMOUNT", f"Cannot parse amount '{value}'. Use e.g. '+10%', '-5%', '+3cm'.",
                           suggestions=["+10%", "-5%", "+3cm", "-2cm"])
    sign = -1.0 if m.group(1) == "-" else 1.0
    number = float(m.group(2)) * sign
    unit = (m.group(3) or "m").lower()
    if unit in ("%", "percent"):
        return Amount("percent", number)
    return Amount("length", number * _UNITS[unit])

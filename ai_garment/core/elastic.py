"""Elastic abstraction.

Blender's cloth modifier supports ONE shrink vertex group per garment
(``vertex_group_shrink``) with the effective shrink
``lerp(shrink_min, shrink_max, weight)``, and ONE structural-stiffness group
(``vertex_group_structural_stiffness``, ``lerp(tension, tension_max, w)``).
Multiple elastics are therefore combined into a single weighted group:
weight = tension / max_tension.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Union

from .errors import GarmentError, Issue
from .vocabulary import normalize

ELASTIC_STRENGTHS: Dict[str, Dict[str, float]] = {
    "light": {"tension": 0.08, "stiffness": 1.5},
    "medium": {"tension": 0.15, "stiffness": 2.5},
    "strong": {"tension": 0.25, "stiffness": 4.0},
}
STRENGTH_ALIASES = {"soft": "light", "loose": "light", "gentle": "light", "normal": "medium", "tight": "strong",
                    "firm": "strong", "heavy": "strong", "snug": "strong"}
TENSION_RANGE = (0.0, 0.5)
WIDTH_RANGE = (0.005, 0.15)
DEFAULT_WIDTH = 0.03
DRAWSTRING_TENSION_FACTOR = 0.8


def normalize_strength(value: Any) -> Optional[Union[str, float]]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if 0.0 <= value <= 1.0 else None
    n = normalize(value)
    n = STRENGTH_ALIASES.get(n, n)
    return n if n in ELASTIC_STRENGTHS else None


def _interp(strength: Union[str, float], key: str) -> float:
    if isinstance(strength, str):
        return ELASTIC_STRENGTHS[strength][key]
    lo, hi = ELASTIC_STRENGTHS["light"][key], ELASTIC_STRENGTHS["strong"][key]
    return lo + (hi - lo) * strength


def validate_elastic_params(params: Dict[str, Any]) -> List[Issue]:
    issues: List[Issue] = []
    if "strength" in params and params["strength"] is not None and normalize_strength(params["strength"]) is None:
        issues.append(Issue("INVALID_PARAM", f"Elastic strength {params['strength']!r} must be light, medium, strong "
                                             "or a number in 0..1.", path="strength",
                            suggestions=list(ELASTIC_STRENGTHS)))
    t = params.get("tension")
    if t is not None:
        if isinstance(t, bool) or not isinstance(t, (int, float)):
            issues.append(Issue("INVALID_PARAM", "Elastic tension must be a number.", path="tension"))
        elif not TENSION_RANGE[0] <= t <= TENSION_RANGE[1]:
            issues.append(Issue("ELASTIC_TENSION_RANGE", f"Elastic tension {t} outside {TENSION_RANGE} "
                                "(fraction the band shrinks).", path="tension", suggestions=["0.15"]))
    w = params.get("width")
    if w is not None:
        if isinstance(w, bool) or not isinstance(w, (int, float)):
            issues.append(Issue("INVALID_PARAM", "Elastic width must be a number (metres).", path="width"))
        elif not WIDTH_RANGE[0] <= w <= WIDTH_RANGE[1]:
            issues.append(Issue("ELASTIC_WIDTH_RANGE", f"Elastic width {w} m outside {WIDTH_RANGE}.", path="width",
                                suggestions=["0.03"]))
    return issues


@dataclass
class ElasticSpec:
    target: str
    kind: str
    strength: Union[str, float]
    tension: float
    width: float
    stiffness_multiplier: float

    @classmethod
    def from_params(cls, target: str, strength: Any = "medium", width: Optional[float] = None,
                    tension: Optional[float] = None, kind: str = "elastic") -> "ElasticSpec":
        issues = validate_elastic_params({"strength": strength, "width": width, "tension": tension})
        if kind not in ("elastic", "drawstring"):
            issues.append(Issue("INVALID_PARAM", "kind must be 'elastic' or 'drawstring'.", path="kind"))
        if issues:
            raise GarmentError(issues[0].code, issues[0].message, details={"issues": [i.to_dict() for i in issues]},
                               path=issues[0].path)
        s = normalize_strength(strength if strength is not None else "medium")
        base_tension = _interp(s, "tension")
        if kind == "drawstring":
            base_tension *= DRAWSTRING_TENSION_FACTOR
        return cls(target=target, kind=kind, strength=s,
                   tension=float(tension) if tension is not None else round(base_tension, 4),
                   width=float(width) if width is not None else DEFAULT_WIDTH,
                   stiffness_multiplier=1.0 if kind == "drawstring" else _interp(s, "stiffness"))

    def to_dict(self) -> Dict[str, Any]:
        return {"target": self.target, "kind": self.kind, "strength": self.strength, "tension": self.tension,
                "width": self.width, "stiffness_multiplier": self.stiffness_multiplier}


@dataclass
class CombinedElastic:
    shrink_max: float
    weights: Dict[str, float] = field(default_factory=dict)
    stiffness_max_factor: float = 1.0
    stiffness_weights: Dict[str, float] = field(default_factory=dict)


def combine_elastics(elastics: Iterable[ElasticSpec]) -> CombinedElastic:
    items = list(elastics)
    if not items:
        return CombinedElastic(0.0)
    shrink_max = max(e.tension for e in items)
    stiff_max = max(e.stiffness_multiplier for e in items)
    weights = {e.target: (e.tension / shrink_max if shrink_max > 0 else 0.0) for e in items}
    sweights = {e.target: (e.stiffness_multiplier - 1.0) / (stiff_max - 1.0) if stiff_max > 1.0 else 0.0
                for e in items}
    return CombinedElastic(shrink_max, weights, stiff_max, sweights)

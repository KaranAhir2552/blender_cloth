"""Fit system: fit levels, ease tables, region adjustments, measurement derivation.

Ease = garment circumference minus body circumference, in centimetres. The
default table follows common pattern-making ranges; it is a configurable
starting point, not a standard.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

from .component_system import SLEEVE_LENGTH_ALIASES
from .errors import GarmentError
from .garment_spec import FitSpec
from .garment_types import LENGTH_SPECS, normalize_length
from .vocabulary import (
    FIT_COMPARATIVES,
    FIT_LEVELS,
    fit_direction,
    normalize,
    normalize_fit_level,
    suggest,
)

__all__ = ["FIT_LEVELS", "FIT_COMPARATIVES", "EASE_TABLE", "EASE_KEYS", "REGION_KEYS", "SLEEVE_LENGTH_FRACTIONS",
           "ease_for", "resolve_ease", "adjust_fit", "shift_fit_level", "derive_garment_measurements",
           "hem_height", "normalize_fit_level"]

EASE_KEYS = ["chest_ease", "waist_ease", "hip_ease", "shoulder_drop", "sleeve_width_ease", "leg_width_ease",
             "cuff_width_ease", "neck_ease"]
#                      chest waist  hip  drop sleeve  leg  cuff  neck
_TABLE = {
    "tight":     (-2.0, -2.0, -2.0, 0.0, 0.0, 0.0, 0.0, 1.0),
    "slim":      (5.0, 5.0, 4.0, 0.0, 3.0, 3.0, 2.0, 2.0),
    "regular":   (10.0, 10.0, 8.0, 1.0, 6.0, 6.0, 4.0, 3.0),
    "relaxed":   (16.0, 16.0, 12.0, 3.0, 9.0, 9.0, 6.0, 4.0),
    "loose":     (24.0, 24.0, 18.0, 6.0, 13.0, 14.0, 8.0, 5.0),
    "oversized": (34.0, 34.0, 26.0, 10.0, 18.0, 20.0, 10.0, 6.0),
}
EASE_TABLE: Dict[str, Dict[str, float]] = {lvl: dict(zip(EASE_KEYS, vals)) for lvl, vals in _TABLE.items()}
KEY_ALIASES = {"leg_width": "leg_width_ease", "cuff_width": "cuff_width_ease", "sleeve_width": "sleeve_width_ease",
               "neck": "neck_ease"}
_OVERALL = ["chest_ease", "waist_ease", "hip_ease", "sleeve_width_ease", "leg_width_ease"]
REGION_KEYS: Dict[str, List[str]] = {
    "chest": ["chest_ease"], "bust": ["chest_ease"], "breast": ["chest_ease"], "pecs": ["chest_ease"],
    "waist": ["waist_ease"], "stomach": ["waist_ease"], "belly": ["waist_ease"], "midsection": ["waist_ease"],
    "hips": ["hip_ease"], "hip": ["hip_ease"], "seat": ["hip_ease"], "butt": ["hip_ease"], "bottom": ["hip_ease"],
    "shoulders": ["shoulder_drop"], "shoulder": ["shoulder_drop"],
    "arms": ["sleeve_width_ease"], "sleeves": ["sleeve_width_ease"], "biceps": ["sleeve_width_ease"],
    "upper_arms": ["sleeve_width_ease"], "sleeve": ["sleeve_width_ease"],
    "legs": ["leg_width_ease"], "leg": ["leg_width_ease"], "thighs": ["leg_width_ease"], "thigh": ["leg_width_ease"],
    "cuffs": ["cuff_width_ease"], "wrists": ["cuff_width_ease"], "ankles": ["cuff_width_ease"],
    "openings": ["cuff_width_ease"],
    "neck": ["neck_ease"], "collar": ["neck_ease"], "neckline": ["neck_ease"],
    "body": _OVERALL, "overall": _OVERALL, "all": _OVERALL, "torso": ["chest_ease", "waist_ease", "hip_ease"],
    "whole": _OVERALL, "garment": _OVERALL, "everywhere": _OVERALL,
}
STEP_CM = {"shoulder_drop": 2.0, "neck_ease": 1.0, "cuff_width_ease": 2.0}
DEFAULT_STEP_CM = 4.0
EASE_MIN_CM = -8.0
EASE_MAX_CM = 60.0

SLEEVE_LENGTH_FRACTIONS = {"sleeveless": 0.0, "cap": 0.12, "short": 0.3, "elbow": 0.5, "three_quarter": 0.75,
                           "long": 1.0, "extra_long": 1.08}


def ease_for(level: str) -> Dict[str, float]:
    lvl = normalize_fit_level(level)
    if lvl is None:
        raise GarmentError("UNKNOWN_FIT", f"Unknown fit level '{level}'.", path="fit",
                           suggestions=suggest(level, FIT_LEVELS))
    return dict(EASE_TABLE[lvl])


def shift_fit_level(level: str, steps: int) -> str:
    i = FIT_LEVELS.index(normalize_fit_level(level) or "regular") + int(steps)
    return FIT_LEVELS[max(0, min(len(FIT_LEVELS) - 1, i))]


def _clamp(v: float) -> float:
    return max(EASE_MIN_CM, min(EASE_MAX_CM, v))


def resolve_ease(fit: FitSpec, component: Optional[str] = None) -> Dict[str, float]:
    """Effective ease (cm) for the whole garment or one component."""
    level = fit.component_levels.get(component, fit.level) if component else fit.level
    e = ease_for(level)
    for key, delta in fit.overrides.items():
        if ":" in key:
            comp, k = key.split(":", 1)
            if comp != component:
                continue
        else:
            k = key
        k = KEY_ALIASES.get(k, k)
        if k in e:
            e[k] = _clamp(e[k] + float(delta))
    return e


def region_keys(region: Optional[str]) -> List[str]:
    if region is None:
        return list(_OVERALL)
    r = normalize(region)
    r = KEY_ALIASES.get(r, r)
    if r in EASE_KEYS:
        return [r]
    if r in REGION_KEYS:
        return list(REGION_KEYS[r])
    raise GarmentError("UNKNOWN_REGION", f"Unknown body region '{region}'.", path="region",
                       suggestions=suggest(r, REGION_KEYS))


def adjust_fit(fit: FitSpec, region: Optional[str] = None, direction: str = "tighter", intensity: float = 1.0,
               components: Optional[List[str]] = None) -> Tuple[FitSpec, List[str]]:
    """Return a NEW FitSpec. ``direction`` is a comparative (tighter/looser/baggier…)
    or an absolute level (loose, slim…). ``components`` scopes the change."""
    new = copy.deepcopy(fit)
    notes: List[str] = []
    absolute = normalize_fit_level(direction)
    sign = fit_direction(direction)
    if absolute is not None and sign is None:
        if components:
            for c in components:
                new.component_levels[c] = absolute
            notes.append(f"Set fit of {', '.join(components)} to {absolute}.")
        else:
            new.level = absolute
            notes.append(f"Set overall fit to {absolute}.")
        return new, notes
    if sign is None:
        raise GarmentError("INVALID_PARAM", f"Unknown fit direction '{direction}'.", path="direction",
                           suggestions=list(FIT_COMPARATIVES) + FIT_LEVELS)
    keys = region_keys(region)
    scopes = components or [None]
    for scope in scopes:
        base = resolve_ease(fit, scope)
        for k in keys:
            delta = sign * STEP_CM.get(k, DEFAULT_STEP_CM) * float(intensity)
            target = _clamp(base[k] + delta)
            okey = f"{scope}:{k}" if scope else k
            new.overrides[okey] = round(float(new.overrides.get(okey, 0.0)) + (target - base[k]), 4)
            if target != base[k] + delta:
                notes.append(f"{k} clamped to {target:g} cm.")
    word = "looser" if sign > 0 else "tighter"
    where = f" around the {region}" if region else ""
    who = f" on {', '.join(components)}" if components else ""
    notes.append(f"Made {word}{where}{who} ({', '.join(keys)}; {STEP_CM.get(keys[0], DEFAULT_STEP_CM) * intensity:g} "
                 "cm per key).")
    return new, notes


# ----------------------------------------------------------------------------
# lengths and measurements
# ----------------------------------------------------------------------------

def _lz(landmarks: Dict[str, Any], name: str) -> float:
    if name in landmarks:
        return float(landmarks[name][2])
    if name + "_l" in landmarks:
        return float(landmarks[name + "_l"][2])
    raise GarmentError("MISSING_LANDMARK", f"Avatar landmark '{name}' is missing.")


def hem_height(length: str, landmarks: Dict[str, Any]) -> float:
    key = normalize_length(length)
    if key not in LENGTH_SPECS:
        raise GarmentError("INVALID_LENGTH", f"Unknown length '{length}'.", path="length",
                           suggestions=suggest(key, LENGTH_SPECS))
    a, b, t = LENGTH_SPECS[key]
    za, zb = _lz(landmarks, a), _lz(landmarks, b)
    return za + (zb - za) * t


def _amount(adj: Optional[Dict[str, float]], base: float) -> float:
    if not adj:
        return base
    return base * (1.0 + float(adj.get("percent", 0.0)) / 100.0) + float(adj.get("meters", 0.0))


def sleeve_fraction(length: Any) -> float:
    n = normalize(length or "long")
    n = SLEEVE_LENGTH_ALIASES.get(n, n)
    if n not in SLEEVE_LENGTH_FRACTIONS:
        raise GarmentError("INVALID_PARAM", f"Unknown sleeve length '{length}'.", path="sleeve.length",
                           suggestions=list(SLEEVE_LENGTH_FRACTIONS))
    return SLEEVE_LENGTH_FRACTIONS[n]


def derive_garment_measurements(avatar_measurements: Dict[str, float], spec: Any,
                                landmarks: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Garment target measurements (metres) = body + ease, scaled by fit.scale.

    ``landmarks`` (metres) are used for the garment length; when absent they
    are estimated from the avatar height.
    """
    m = avatar_measurements
    if landmarks is None:
        from .avatar_model import estimate_landmarks_from_height  # local: avatar_model imports garment types
        landmarks = estimate_landmarks_from_height(m.get("height", 1.75))
    e = resolve_ease(spec.fit, "body")
    s = float(spec.fit.scale or 1.0)

    def circ(body_key: str, ease_key: str, ease: Optional[Dict[str, float]] = None) -> float:
        return (m[body_key] + (ease or e)[ease_key] / 100.0) * s

    out: Dict[str, Any] = {
        "chest_circumference": circ("chest_circumference", "chest_ease"),
        "waist_circumference": circ("waist_circumference", "waist_ease"),
        "hip_circumference": circ("hip_circumference", "hip_ease"),
        "neck_circumference": circ("neck_circumference", "neck_ease"),
        "shoulder_width": m["shoulder_width"] + 2.0 * e["shoulder_drop"] / 100.0,
        "thigh_circumference": circ("thigh_circumference", "leg_width_ease"),
        "ease_cm": e,
        "components": {},
    }
    category = spec.category
    length_name = spec.length or ("hip" if category != "bottom" else "ankle")
    try:
        hem_z = hem_height(length_name, landmarks)
        top_z = _lz(landmarks, "shoulder") if category != "bottom" else _lz(landmarks, "waist")
        out["garment_length"] = _amount(spec.length_adjust, max(0.05, top_z - hem_z))
    except GarmentError as err:
        out["garment_length"] = None
        out["warnings"] = [err.message]
    for comp in spec.components:
        ce = resolve_ease(spec.fit, comp.name)
        if comp.type == "sleeve":
            frac = sleeve_fraction(comp.params.get("length", "long"))
            out["components"][comp.name] = {
                "length": _amount(comp.params.get("length_adjust"), m["arm_length"] * frac),
                "bicep_circumference": (m["upper_arm_circumference"] + ce["sleeve_width_ease"] / 100.0) * s,
                "opening_circumference": (m["wrist_circumference"] * (1.0 + (1.0 - frac) * 0.6)
                                          + ce["cuff_width_ease"] / 100.0) * s,
                "rolled": int(comp.state.get("rolled", 0)),
            }
        elif comp.type == "leg":
            out["components"][comp.name] = {
                "length_adjust": dict(comp.params.get("length_adjust") or {}),
                "thigh_circumference": (m["thigh_circumference"] + ce["leg_width_ease"] / 100.0) * s,
                "knee_circumference": (m["knee_circumference"] + ce["leg_width_ease"] * 0.8 / 100.0) * s,
                "opening_circumference": (m["ankle_circumference"] + ce["cuff_width_ease"] / 100.0
                                          + ce["leg_width_ease"] * 0.6 / 100.0) * s,
                "rolled": int(comp.state.get("rolled", 0)),
            }
    return out

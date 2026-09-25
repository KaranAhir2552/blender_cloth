"""Fabric presets: high-level, qualitative, ARTISTIC characteristics.

The presets live in ``data/fabric_presets.json`` (configurable). Extra JSON
can be merged via the ``AI_GARMENT_FABRICS`` environment variable or
:func:`load_fabric_presets`. Values are not scientifically validated.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple

from .errors import GarmentError
from .vocabulary import normalize, suggest

LEVELS = ["very_low", "low", "medium", "high", "very_high"]
WEIGHT_CLASSES = ["ultralight", "light", "medium", "heavy", "very_heavy"]
BEND_LEVELS = ["very_soft", "soft", "medium", "stiff", "very_stiff"]
QUALITATIVE_FIELDS = {"weight_class": WEIGHT_CLASSES, "stretch": LEVELS, "bend": BEND_LEVELS, "drape": LEVELS,
                      "damping": LEVELS, "friction": LEVELS}

# qualifier -> {field: steps} (+ optional thickness multiplier)
QUALIFIERS: Dict[str, Dict[str, float]] = {
    "heavy": {"weight_class": 1, "bend": 1, "drape": -1}, "heavyweight": {"weight_class": 1, "bend": 1, "drape": -1},
    "light": {"weight_class": -1, "bend": -1, "drape": 1}, "lightweight": {"weight_class": -1, "bend": -1, "drape": 1},
    "thin": {"weight_class": -1, "thickness": 0.7}, "thick": {"weight_class": 1, "thickness": 1.4},
    "stiff": {"bend": 1}, "soft": {"bend": -1}, "crisp": {"bend": 1, "drape": -1},
    "flowy": {"drape": 1, "bend": -1}, "drapey": {"drape": 1, "bend": -1}, "fluid": {"drape": 1, "bend": -1},
    "stretchy": {"stretch": 2}, "stretch": {"stretch": 2}, "rigid": {"stretch": -2}, "raw": {"bend": 1},
    "washed": {"bend": -1}, "brushed": {"friction": 1}, "slick": {"friction": -1}, "smooth": {"friction": -1},
}


@dataclass(frozen=True)
class FabricPreset:
    name: str
    display_name: str
    weight_class: str
    stretch: str
    bend: str
    drape: str
    damping: str
    friction: str
    thickness_mm: float
    aliases: Tuple[str, ...] = ()
    typical_gsm: Tuple[float, float] = (0.0, 0.0)
    roughness: float = 0.8
    sheen: float = 0.2
    description: str = ""
    artistic: bool = True

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["aliases"] = list(self.aliases)
        d["typical_gsm"] = list(self.typical_gsm)
        return d


@dataclass
class ResolvedFabric:
    """A preset with qualifiers / overrides applied. Input to physics mapping."""

    base: str
    name: str
    display_name: str
    qualifiers: List[str]
    weight_class: str
    stretch: str
    bend: str
    drape: str
    damping: str
    friction: str
    thickness_mm: float
    roughness: float
    sheen: float
    typical_gsm: Tuple[float, float]
    physics_overrides: Dict[str, float] = field(default_factory=dict)
    artistic: bool = True

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["typical_gsm"] = list(self.typical_gsm)
        return d


_PRESETS: Dict[str, FabricPreset] = {}
_ALIASES: Dict[str, str] = {}
DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "fabric_presets.json")


def _validate_preset_dict(name: str, p: Dict[str, Any]) -> None:
    for fld, allowed in QUALITATIVE_FIELDS.items():
        if p.get(fld) not in allowed:
            raise GarmentError("INVALID_FABRIC_PRESET", f"Fabric preset '{name}': {fld}={p.get(fld)!r} "
                               f"must be one of {allowed}.")
    if not isinstance(p.get("thickness_mm"), (int, float)) or p["thickness_mm"] <= 0:
        raise GarmentError("INVALID_FABRIC_PRESET", f"Fabric preset '{name}': thickness_mm must be > 0.")


def register_fabric_preset(preset: FabricPreset, replace_existing: bool = False) -> None:
    key = normalize(preset.name)
    if key in _PRESETS and not replace_existing:
        raise GarmentError("DUPLICATE_FABRIC", f"Fabric preset '{key}' already exists.")
    _validate_preset_dict(key, asdict(preset))
    _PRESETS[key] = replace(preset, name=key)
    for alias in preset.aliases:
        _ALIASES[normalize(alias)] = key


def load_fabric_presets(path: str, replace_existing: bool = True) -> List[str]:
    """Load presets from a JSON file with the same layout as data/fabric_presets.json."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    loaded = []
    for name, p in data.get("presets", {}).items():
        _validate_preset_dict(name, p)
        preset = FabricPreset(
            name=name, display_name=p.get("display_name", name.replace("_", " ").title()),
            weight_class=p["weight_class"], stretch=p["stretch"], bend=p["bend"], drape=p["drape"],
            damping=p["damping"], friction=p["friction"], thickness_mm=float(p["thickness_mm"]),
            aliases=tuple(p.get("aliases", ())), typical_gsm=tuple(p.get("typical_gsm", (0, 0))),
            roughness=float(p.get("roughness", 0.8)), sheen=float(p.get("sheen", 0.2)),
            description=p.get("description", ""), artistic=bool(data.get("artistic_presets", True)))
        register_fabric_preset(preset, replace_existing=replace_existing)
        loaded.append(normalize(name))
    return loaded


def _ensure_loaded() -> None:
    if _PRESETS:
        return
    load_fabric_presets(DATA_FILE)
    extra = os.environ.get("AI_GARMENT_FABRICS")
    if extra and os.path.exists(extra):
        load_fabric_presets(extra)


def list_fabrics() -> List[str]:
    _ensure_loaded()
    return sorted(_PRESETS)


def get_fabric_preset(name: str) -> FabricPreset:
    _ensure_loaded()
    key = _lookup(name)
    if key is None:
        raise GarmentError("UNKNOWN_FABRIC", f"Unknown fabric '{name}'.", path="fabric",
                           suggestions=suggest(name, list(_PRESETS) + list(_ALIASES)))
    return _PRESETS[key]


def _lookup(name: str) -> Optional[str]:
    n = normalize(name)
    if n in _PRESETS:
        return n
    if n in _ALIASES:
        return _ALIASES[n]
    c = n.replace("_", "")
    for k in list(_PRESETS) + list(_ALIASES):
        if k.replace("_", "") == c:
            return _PRESETS[k].name if k in _PRESETS else _ALIASES[k]
    return None


def parse_fabric_name(text: str) -> Tuple[str, List[str]]:
    """'heavy denim' -> ('denim', ['heavy']); 'heavy cotton' -> ('heavy_cotton', [])."""
    _ensure_loaded()
    direct = _lookup(text)
    if direct:
        return direct, []
    words = normalize(text).split("_")
    quals: List[str] = []
    while words and words[0] in QUALIFIERS:
        quals.append(words.pop(0))
        rest = _lookup("_".join(words)) if words else None
        if rest:
            return rest, quals
    raise GarmentError("UNKNOWN_FABRIC", f"Unknown fabric '{text}'.", path="fabric",
                       suggestions=suggest(text, list(_PRESETS) + list(_ALIASES)))


def _shift(value: str, levels: List[str], steps: float) -> str:
    i = levels.index(value) + int(round(steps))
    return levels[max(0, min(len(levels) - 1, i))]


def resolve_fabric(value: Any) -> ResolvedFabric:
    """Accepts a name ('heavy denim'), a FabricSpec-like object, or a dict."""
    _ensure_loaded()
    if isinstance(value, str):
        name, quals, overrides, physics = value, [], {}, {}
    elif isinstance(value, dict):
        name = value.get("name", "")
        quals = list(value.get("qualifiers", []))
        overrides = dict(value.get("overrides", {}))
        physics = dict(value.get("physics_overrides", {}))
    else:
        name = getattr(value, "name", "")
        quals = list(getattr(value, "qualifiers", []) or [])
        overrides = dict(getattr(value, "overrides", {}) or {})
        physics = dict(getattr(value, "physics_overrides", {}) or {})
    base, parsed_quals = parse_fabric_name(name)
    for q in parsed_quals:
        if q not in quals:
            quals.append(q)
    p = _PRESETS[base]
    vals = {f: getattr(p, f) for f in QUALITATIVE_FIELDS}
    thickness = p.thickness_mm
    for q in quals:
        qn = normalize(q)
        if qn not in QUALIFIERS:
            raise GarmentError("UNKNOWN_FABRIC_QUALIFIER", f"Unknown fabric qualifier '{q}'.", path="fabric",
                               suggestions=suggest(qn, QUALIFIERS))
        for f, steps in QUALIFIERS[qn].items():
            if f == "thickness":
                thickness *= steps
            else:
                vals[f] = _shift(vals[f], QUALITATIVE_FIELDS[f], steps)
    for f, v in overrides.items():
        if f == "thickness_mm":
            if not isinstance(v, (int, float)) or v <= 0:
                raise GarmentError("INVALID_PARAM", "thickness_mm override must be > 0.", path="fabric.overrides")
            thickness = float(v)
            continue
        if f not in QUALITATIVE_FIELDS:
            raise GarmentError("INVALID_PARAM", f"Unknown fabric override '{f}'.", path="fabric.overrides",
                               suggestions=list(QUALITATIVE_FIELDS) + ["thickness_mm"])
        nv = normalize(v)
        if nv not in QUALITATIVE_FIELDS[f]:
            raise GarmentError("INVALID_PARAM", f"Fabric override {f}={v!r} must be one of {QUALITATIVE_FIELDS[f]}.",
                               path=f"fabric.overrides.{f}")
        vals[f] = nv
    if physics:
        from .physics_mapping import PHYSICS_OVERRIDE_KEYS  # local import: physics_mapping imports this module
        bad = [k for k in physics if k not in PHYSICS_OVERRIDE_KEYS]
        if bad:
            raise GarmentError("INVALID_PARAM", f"Unknown physics override(s) {bad}.", path="fabric.physics_overrides",
                               suggestions=sorted(PHYSICS_OVERRIDE_KEYS))
        for k, v in physics.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise GarmentError("INVALID_PARAM", f"Physics override {k} must be a number.",
                                   path=f"fabric.physics_overrides.{k}")
    display = " ".join([q.title() for q in quals] + [p.display_name])
    return ResolvedFabric(base=base, name="_".join([normalize(q) for q in quals] + [base]), display_name=display,
                          qualifiers=[normalize(q) for q in quals], thickness_mm=thickness, roughness=p.roughness,
                          sheen=p.sheen, typical_gsm=p.typical_gsm, physics_overrides=physics, artistic=p.artistic,
                          **vals)

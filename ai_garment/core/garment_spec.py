"""Structured garment description (the source of truth for a garment).

``GarmentSpec.from_dict`` accepts both the explicit form (``components`` list)
and the brief's shorthand (``"sleeves": {"length": "short", "cuff": {...}}``)
and normalises everything into explicit components. It is deliberately
lenient: unknown values are kept so :func:`validation.validate_spec` can
report *all* problems at once.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .component_system import (
    SLEEVE_LENGTH_ALIASES,
    fill_param_defaults,
    resolve_component_type,
)
from .errors import GarmentError
from .fabric_presets import parse_fabric_name
from .garment_types import GarmentTypeDef, normalize_length, resolve_garment_type
from .vocabulary import canonical_color, normalize, normalize_fit_level

SIM_MODES = ("natural", "preview", "draft", "production", "static")


@dataclass
class ComponentSpec:
    type: str
    name: str
    target: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    state: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ComponentSpec":
        raw = d.get("type", "")
        ctype = resolve_component_type(raw)
        tname = ctype.name if ctype else normalize(raw)
        name = normalize(d.get("name") or tname)
        target = normalize(d["target"]) if d.get("target") else None
        return cls(tname, name, target, copy.deepcopy(dict(d.get("params", {}))),
                   copy.deepcopy(dict(d.get("state", {}))))

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"type": self.type, "name": self.name, "params": copy.deepcopy(self.params)}
        if self.target:
            d["target"] = self.target
        if self.state:
            d["state"] = copy.deepcopy(self.state)
        return d


@dataclass
class FitSpec:
    level: str = "regular"
    overrides: Dict[str, float] = field(default_factory=dict)  # "<key>" or "<component>:<key>" -> cm delta
    component_levels: Dict[str, str] = field(default_factory=dict)
    scale: float = 1.0

    @classmethod
    def from_value(cls, value: Any, default: str = "regular") -> "FitSpec":
        if value is None:
            return cls(level=default)
        if isinstance(value, FitSpec):
            return copy.deepcopy(value)
        if isinstance(value, str):
            return cls(level=normalize_fit_level(value) or normalize(value))
        if isinstance(value, dict):
            lvl = value.get("level", default)
            return cls(level=normalize_fit_level(lvl) or normalize(lvl),
                       overrides={str(k): float(v) for k, v in dict(value.get("overrides", {})).items()},
                       component_levels={normalize(k): normalize_fit_level(v) or normalize(v)
                                         for k, v in dict(value.get("component_levels", {})).items()},
                       scale=float(value.get("scale", 1.0)))
        raise GarmentError("INVALID_PARAM", f"fit must be a string or object, got {type(value).__name__}.",
                           path="fit")

    def to_dict(self) -> Dict[str, Any]:
        return {"level": self.level, "overrides": dict(self.overrides),
                "component_levels": dict(self.component_levels), "scale": self.scale}


@dataclass
class FabricSpec:
    name: str = "cotton"
    qualifiers: List[str] = field(default_factory=list)
    overrides: Dict[str, Any] = field(default_factory=dict)
    physics_overrides: Dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_value(cls, value: Any, default: str = "cotton") -> "FabricSpec":
        if value is None:
            value = default
        if isinstance(value, FabricSpec):
            return copy.deepcopy(value)
        if isinstance(value, str):
            name, quals = _split_fabric(value)
            return cls(name, quals)
        if isinstance(value, dict):
            name, quals = _split_fabric(value.get("name", default))
            for q in value.get("qualifiers", []):
                if normalize(q) not in quals:
                    quals.append(normalize(q))
            return cls(name, quals, dict(value.get("overrides", {})), dict(value.get("physics_overrides", {})))
        raise GarmentError("INVALID_PARAM", "fabric must be a string or object.", path="fabric")

    @property
    def display(self) -> str:
        return " ".join(self.qualifiers + [self.name])

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "qualifiers": list(self.qualifiers), "overrides": dict(self.overrides),
                "physics_overrides": dict(self.physics_overrides)}


def _split_fabric(text: str):
    try:
        base, quals = parse_fabric_name(text)
        return base, list(quals)
    except GarmentError:
        return normalize(text), []  # kept for validation to report UNKNOWN_FABRIC


@dataclass
class SimulationSpec:
    mode: str = "natural"
    quality: str = "preview"
    gravity: bool = True
    collision: bool = True
    self_collision: Optional[bool] = None  # None -> quality/mode default
    frame_start: int = 1
    frame_end: Optional[int] = None
    settle: bool = True
    bake: Optional[bool] = None  # None -> mode default
    pin: List[str] = field(default_factory=list)

    @classmethod
    def from_value(cls, value: Any) -> "SimulationSpec":
        if value is None:
            return cls()
        if isinstance(value, SimulationSpec):
            return copy.deepcopy(value)
        if not isinstance(value, dict):
            raise GarmentError("INVALID_PARAM", "simulation must be an object.", path="simulation")
        s = cls()
        for k, v in value.items():
            if not hasattr(s, k):
                raise GarmentError("INVALID_PARAM", f"Unknown simulation setting '{k}'.", path=f"simulation.{k}",
                                   suggestions=sorted(cls().__dict__))
            setattr(s, k, normalize(v) if k in ("mode", "quality") and isinstance(v, str) else v)
        s.pin = list(s.pin)
        return s

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__, pin=list(self.pin))


_SHORTHAND_KEYS = ("sleeves", "legs", "cuffs", "pockets", "hood", "collar", "waistband", "zipper", "buttons")
_TOP_LEVEL_KEYS = {"type", "name", "fit", "fabric", "color", "length", "length_adjust", "components",
                   "simulation", "placement", "tucked", "layer", "disabled_seams", "metadata",
                   "default_components"} | set(_SHORTHAND_KEYS)


@dataclass
class GarmentSpec:
    type: str
    name: Optional[str] = None
    fit: FitSpec = field(default_factory=FitSpec)
    fabric: FabricSpec = field(default_factory=FabricSpec)
    color: Any = "white"
    length: Optional[str] = None
    length_adjust: Dict[str, float] = field(default_factory=lambda: {"percent": 0.0, "meters": 0.0})
    components: List[ComponentSpec] = field(default_factory=list)
    simulation: SimulationSpec = field(default_factory=SimulationSpec)
    placement: Dict[str, Any] = field(default_factory=lambda: {"offset": [0.0, 0.0, 0.0]})
    tucked: bool = False
    layer: int = 0
    disabled_seams: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    unknown_keys: List[str] = field(default_factory=list)

    # construction -----------------------------------------------------------
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GarmentSpec":
        if isinstance(data, GarmentSpec):
            return data.copy()
        if not isinstance(data, dict):
            raise GarmentError("INVALID_SPEC", "A garment spec must be a JSON object.")
        d = copy.deepcopy(data)
        gdef = resolve_garment_type(d.get("type"))
        spec = cls(type=gdef.name if gdef else normalize(d.get("type")))
        spec.unknown_keys = sorted(k for k in d if k not in _TOP_LEVEL_KEYS)
        spec.name = d.get("name")
        spec.fit = FitSpec.from_value(d.get("fit"), gdef.default_fit if gdef else "regular")
        spec.fabric = FabricSpec.from_value(d.get("fabric"), gdef.default_fabric if gdef else "cotton")
        spec.color = canonical_color(d.get("color", gdef.default_color if gdef else "white"))
        spec.length = normalize_length(d["length"]) if d.get("length") else (gdef.default_length if gdef else None)
        la = d.get("length_adjust") or {}
        spec.length_adjust = {"percent": float(la.get("percent", 0.0)), "meters": float(la.get("meters", 0.0))}
        spec.simulation = SimulationSpec.from_value(d.get("simulation"))
        spec.placement = dict(d.get("placement") or {"offset": [0.0, 0.0, 0.0]})
        spec.placement.setdefault("offset", [0.0, 0.0, 0.0])
        spec.tucked = bool(d.get("tucked", False))
        spec.layer = int(d.get("layer", 0))
        spec.disabled_seams = list(d.get("disabled_seams", []))
        spec.metadata = dict(d.get("metadata", {}))
        if gdef is not None and d.get("default_components", True):
            spec.components = [ComponentSpec.from_dict(c) for c in gdef.default_components]
        for key in _SHORTHAND_KEYS:
            if key in d:
                _apply_shorthand(spec, gdef, key, d[key])
        for item in d.get("components", []) or []:
            spec._merge_component(item)
        for c in spec.components:
            ctype = resolve_component_type(c.type)
            if ctype is not None:
                c.params = fill_param_defaults(ctype, c.params)
        return spec

    def _merge_component(self, item: Dict[str, Any]) -> None:
        if not isinstance(item, dict):
            raise GarmentError("INVALID_SPEC", "Each component must be an object.", path="components")
        new = ComponentSpec.from_dict(item)
        if not item.get("name"):
            new.name = self.unique_name(f"{new.target}_{new.type}" if new.target else new.type)
        existing = self.get_component(new.name)
        if existing is None:
            self.components.append(new)
            return
        if item.get("type"):
            existing.type = new.type
        if item.get("target"):
            existing.target = new.target
        existing.params.update(new.params)
        existing.state.update(new.state)

    # queries ----------------------------------------------------------------
    @property
    def type_def(self) -> Optional[GarmentTypeDef]:
        return resolve_garment_type(self.type)

    @property
    def category(self) -> Optional[str]:
        t = self.type_def
        return t.category if t else None

    @property
    def display_name(self) -> str:
        t = self.type_def
        return t.display_name if t else self.type

    def get_component(self, name: str) -> Optional[ComponentSpec]:
        n = normalize(name)
        for c in self.components:
            if c.name == n:
                return c
        return None

    def components_of_type(self, *types: str) -> List[ComponentSpec]:
        return [c for c in self.components if c.type in types]

    def children_of(self, name: str) -> List[ComponentSpec]:
        return [c for c in self.components if c.target == name]

    def unique_name(self, base: str) -> str:
        base = normalize(base)
        names = {c.name for c in self.components}
        name, i = base, 2
        while name in names:
            name = f"{base}_{i}"
            i += 1
        return name

    # mutation helpers (used by pure operation transforms on copies) ------------
    def remove_component(self, name: str) -> List[str]:
        removed = []
        for child in list(self.children_of(name)):
            removed += self.remove_component(child.name)
        self.components = [c for c in self.components if c.name != name]
        self.fit.component_levels.pop(name, None)
        self.fit.overrides = {k: v for k, v in self.fit.overrides.items() if not k.startswith(name + ":")}
        return removed + [name]

    def copy(self) -> "GarmentSpec":
        return copy.deepcopy(self)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "type": self.type, "fit": self.fit.to_dict(), "fabric": self.fabric.to_dict(), "color": self.color,
            "length": self.length, "length_adjust": dict(self.length_adjust),
            "components": [c.to_dict() for c in self.components], "simulation": self.simulation.to_dict(),
            "placement": copy.deepcopy(self.placement), "tucked": self.tucked, "layer": self.layer,
            "disabled_seams": list(self.disabled_seams), "metadata": copy.deepcopy(self.metadata),
            "default_components": False,
        }
        if self.name:
            d["name"] = self.name
        return d


# ----------------------------------------------------------------------------
# shorthand normalisation
# ----------------------------------------------------------------------------

def _cuff_component(parent: str, value: Any) -> Optional[Dict[str, Any]]:
    if value in (None, False) or (isinstance(value, str) and normalize(value) in ("none", "no", "false")):
        return None
    if isinstance(value, str):
        value = {"type": value}
    if value is True:
        value = {"type": "plain"}
    value = dict(value)
    kind = normalize(value.pop("type", "plain"))
    if kind in ("elastic", "elastic_cuff", "elasticated", "ribbed_elastic"):
        return {"type": "elastic_cuff", "name": f"{parent}_cuff", "target": parent, "params": value}
    style = kind if kind in ("plain", "rib", "buttoned", "folded") else kind
    return {"type": "cuff", "name": f"{parent}_cuff", "target": parent, "params": dict(value, style=style)}


def _set_cuffs(spec: GarmentSpec, parents: List[str], value: Any) -> None:
    for parent in parents:
        for child in spec.children_of(parent):
            if child.type in ("cuff", "elastic_cuff"):
                spec.remove_component(child.name)
        comp = _cuff_component(parent, value)
        if comp:
            spec.components.append(ComponentSpec.from_dict(comp))


def _limb_shorthand(spec: GarmentSpec, ctype: str, value: Any) -> None:
    limbs = [c for c in spec.components if c.type == ctype]
    if not limbs and ctype == "sleeve" and spec.category in ("top", "full"):
        for side in ("left", "right"):
            spec.components.append(ComponentSpec("sleeve", f"{side}_sleeve", params={"side": side}))
        limbs = [c for c in spec.components if c.type == ctype]
    if value is False or (isinstance(value, str) and normalize(value) in ("none", "sleeveless")):
        value = {"length": "sleeveless"}
    elif isinstance(value, str):
        value = {"length": value}
    elif not isinstance(value, dict):
        raise GarmentError("INVALID_SPEC", f"'{ctype}s' shorthand must be an object or a length.", path=ctype + "s")
    for limb in limbs:
        if "length" in value and ctype == "sleeve":
            n = normalize(value["length"])
            limb.params["length"] = SLEEVE_LENGTH_ALIASES.get(n, n)
        if "length_adjust" in value:
            limb.params["length_adjust"] = dict(value["length_adjust"])
        if "fit" in value:
            spec.fit.component_levels[limb.name] = normalize_fit_level(value["fit"]) or normalize(value["fit"])
        if value.get("rolled") or value.get("roll"):
            limb.state["rolled"] = int(value.get("rolled") or value.get("roll") or 1)
    if "cuff" in value or "cuffs" in value:
        _set_cuffs(spec, [limb.name for limb in limbs], value.get("cuff", value.get("cuffs")))


def _apply_shorthand(spec: GarmentSpec, gdef: Optional[GarmentTypeDef], key: str, value: Any) -> None:
    category = gdef.category if gdef else None
    if key == "sleeves":
        _limb_shorthand(spec, "sleeve", value)
    elif key == "legs":
        _limb_shorthand(spec, "leg", value)
    elif key == "cuffs":
        _limb_shorthand(spec, "leg" if category == "bottom" else "sleeve", {"cuff": value})
    elif key == "pockets":
        kind = normalize(value.get("type", "patch") if isinstance(value, dict) else value)
        if kind in ("none", "false", "no"):
            for c in [c for c in spec.components if c.type in ("pocket", "cargo_pocket", "kangaroo_pocket")]:
                spec.remove_component(c.name)
        elif kind == "cargo":
            for leg in [c for c in spec.components if c.type == "leg"]:
                spec.components.append(ComponentSpec("cargo_pocket", f"{leg.name}_cargo_pocket", leg.name))
        elif kind in ("kangaroo", "pouch"):
            spec.components.append(ComponentSpec("kangaroo_pocket", spec.unique_name("kangaroo_pocket"), "body"))
        else:
            places = ["chest_left"] if category != "bottom" else ["front_hip_left", "front_hip_right"]
            for place in places:
                spec.components.append(ComponentSpec("pocket", spec.unique_name(f"{place}_pocket"), "body",
                                                     {"placement": place}))
    elif key == "hood":
        hood = spec.get_component("hood")
        if value is False or value is None:
            if hood:
                spec.remove_component("hood")
        else:
            if hood is None:
                hood = ComponentSpec("hood", "hood", "body")
                spec.components.append(hood)
            if isinstance(value, dict):
                hood.params.update(value)
    elif key == "collar":
        collar = spec.get_component("collar")
        if collar is None:
            collar = ComponentSpec("collar", "collar", "body")
            spec.components.append(collar)
        if isinstance(value, str):
            collar.params["style"] = normalize(value)
        elif isinstance(value, dict):
            collar.params.update(value)
    elif key == "waistband":
        band = spec.get_component("waistband")
        if band is None:
            band = ComponentSpec("waistband", "waistband", "body")
            spec.components.append(band)
        if isinstance(value, dict):
            v = dict(value)
            if normalize(v.pop("type", "")) == "elastic":
                band.params["elastic"] = {k: v.pop(k) for k in list(v) if k in ("strength", "tension", "width")} \
                    or {"strength": "medium"}
            band.params.update(v)
    elif key == "zipper":
        if value and spec.get_component("zipper") is None:
            spec.components.append(ComponentSpec("zipper", "zipper", "body"))
        elif not value and spec.get_component("zipper") is not None:
            spec.remove_component("zipper")
    elif key == "buttons":
        placket = spec.get_component("button_placket")
        if value and placket is None:
            placket = ComponentSpec("button_placket", "button_placket", "body")
            spec.components.append(placket)
        if placket is not None and isinstance(value, int) and not isinstance(value, bool):
            placket.params["count"] = value

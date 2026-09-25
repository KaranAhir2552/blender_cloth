"""Garment component registry and target resolution.

Components are the unit Claude edits ("the sleeves", "the waistband").
Kinds:
  * panel   - produces its own geometry (body, sleeve, leg, hood, pockets)
  * band    - a region at the edge of a panel (collar, cuff, hem, waistband)
  * feature - behaviour on existing geometry (zipper, buttons, drawstring,
              elastic, belt loops, seams)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .elastic import ElasticSpec, validate_elastic_params
from .errors import GarmentError, Issue
from .units import parse_amount
from .vocabulary import normalize, parse_intensity, suggest

SLEEVE_LENGTHS = ("sleeveless", "cap", "short", "elbow", "three_quarter", "long", "extra_long")
SLEEVE_LENGTH_ALIASES = {"none": "sleeveless", "no_sleeves": "sleeveless", "3_4": "three_quarter",
                         "34": "three_quarter", "half": "elbow", "full": "long"}
POCKET_PLACEMENTS = ("chest_left", "chest_right", "hip_left", "hip_right", "front_hip_left", "front_hip_right",
                     "back_left", "back_right")


@dataclass(frozen=True)
class ParamDef:
    type: str  # enum|float|int|bool|str|strength|amount_dict|dict|amount|intensity|vec3|str_or_dict|any
    choices: Tuple[str, ...] = ()
    min: Optional[float] = None
    max: Optional[float] = None
    default: Any = None
    description: str = ""

    def check(self, value: Any) -> Optional[str]:
        t = self.type
        if t == "enum":
            if normalize(value) not in self.choices:
                return f"must be one of {list(self.choices)}"
        elif t in ("float", "int"):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return "must be a number"
            if t == "int" and int(value) != value:
                return "must be an integer"
            if self.min is not None and value < self.min:
                return f"must be >= {self.min}"
            if self.max is not None and value > self.max:
                return f"must be <= {self.max}"
        elif t == "bool":
            if not isinstance(value, bool):
                return "must be true or false"
        elif t == "strength":
            if isinstance(value, bool):
                return "must be light/medium/strong or 0..1"
            if isinstance(value, (int, float)):
                if not 0.0 <= value <= 1.0:
                    return "numeric strength must be within 0..1"
            elif normalize(value) not in ("light", "medium", "strong", "soft", "loose", "normal", "tight", "firm",
                                          "heavy"):
                return "must be light/medium/strong or 0..1"
        elif t == "amount_dict":
            if not isinstance(value, dict) or set(value) - {"percent", "meters"}:
                return "must be {'percent': float, 'meters': float}"
        elif t == "dict":
            if not isinstance(value, dict):
                return "must be an object"
        elif t == "str":
            if not isinstance(value, str):
                return "must be a string"
        elif t == "amount":
            try:
                parse_amount(value)
            except GarmentError as err:
                return err.message
        elif t == "intensity":
            try:
                parse_intensity(value)
            except GarmentError as err:
                return err.message
        elif t == "vec3":
            if not (isinstance(value, (list, tuple)) and len(value) == 3 and
                    all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in value)):
                return "must be [x, y, z]"
        elif t == "str_or_dict":
            if not isinstance(value, (str, dict)):
                return "must be a string or an object"
        return None

    def to_json_schema(self) -> Dict[str, Any]:
        t = self.type
        if t == "enum":
            return {"type": "string", "enum": list(self.choices)}
        if t in ("float", "int"):
            s: Dict[str, Any] = {"type": "number" if t == "float" else "integer"}
            if self.min is not None:
                s["minimum"] = self.min
            if self.max is not None:
                s["maximum"] = self.max
            return s
        if t == "bool":
            return {"type": "boolean"}
        if t == "strength":
            return {"anyOf": [{"type": "string", "enum": ["light", "medium", "strong"]},
                              {"type": "number", "minimum": 0, "maximum": 1}]}
        if t in ("amount_dict", "dict"):
            return {"type": "object"}
        if t == "amount":
            return {"anyOf": [{"type": "string"}, {"type": "number"}]}
        if t == "intensity":
            return {"anyOf": [{"type": "string"}, {"type": "number", "exclusiveMinimum": 0, "maximum": 3}]}
        if t == "vec3":
            return {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
        if t == "str_or_dict":
            return {"anyOf": [{"type": "string"}, {"type": "object"}]}
        if t == "any":
            return {}
        return {"type": "string"}


ELASTIC_PARAMS = {
    "strength": ParamDef("strength", default="medium", description="light / medium / strong or 0..1"),
    "tension": ParamDef("float", min=0.0, max=0.5, description="shrink fraction 0..0.5"),
    "width": ParamDef("float", min=0.005, max=0.15, description="band width in metres"),
}
LENGTH_ADJUST = ParamDef("amount_dict", description="{'percent': float, 'meters': float}")
SIDE = ParamDef("enum", ("left", "right"))


@dataclass(frozen=True)
class ComponentTypeDef:
    name: str
    kind: str
    description: str
    params: Dict[str, ParamDef] = field(default_factory=dict)
    categories: Tuple[str, ...] = ("top", "bottom", "full")
    target_types: Tuple[str, ...] = ()  # allowed parent component types; empty = no target
    target_required: bool = False
    aliases: Tuple[str, ...] = ()
    elastic: bool = False
    required: bool = False
    child_suffix: str = ""  # naming when created per-target: <target>_<suffix>


_COMPONENTS: Dict[str, ComponentTypeDef] = {}
_ALIASES: Dict[str, str] = {}


def register_component_type(defn: ComponentTypeDef, replace: bool = False) -> None:
    key = normalize(defn.name)
    if key in _COMPONENTS and not replace:
        raise GarmentError("DUPLICATE_COMPONENT_TYPE", f"Component type '{key}' already registered.")
    if defn.kind not in ("panel", "band", "feature"):
        raise GarmentError("INVALID_COMPONENT_TYPE", "kind must be panel, band or feature.")
    _COMPONENTS[key] = defn
    for a in defn.aliases:
        _ALIASES[normalize(a)] = key


def resolve_component_type(name: object) -> Optional[ComponentTypeDef]:
    n = normalize(name)
    n = _ALIASES.get(n, n)
    return _COMPONENTS.get(n)


def get_component_type(name: object) -> ComponentTypeDef:
    d = resolve_component_type(name)
    if d is None:
        raise GarmentError("UNKNOWN_COMPONENT", f"Unknown component type '{name}'.", path="components",
                           suggestions=suggest(name, list(_COMPONENTS) + list(_ALIASES)))
    return d


def list_component_types() -> List[str]:
    return sorted(_COMPONENTS)


PANELS_WITH_ENDS = ("sleeve", "leg", "body")
_BUILTIN = [
    ComponentTypeDef("body", "panel", "Main garment panel (torso / pelvis / skirt).", required=True,
                     params={"shape": ParamDef("enum", ("straight", "a_line", "pencil", "circle"), default="straight"),
                             "flare": ParamDef("float", min=0.0, max=1.5)}),
    ComponentTypeDef("sleeve", "panel", "Sleeve tube attached at the shoulder.", categories=("top", "full"),
                     params={"side": SIDE, "length": ParamDef("enum", SLEEVE_LENGTHS, default="long"),
                             "length_adjust": LENGTH_ADJUST}),
    ComponentTypeDef("leg", "panel", "Trouser leg tube.", categories=("bottom",),
                     params={"side": SIDE, "length_adjust": LENGTH_ADJUST}),
    ComponentTypeDef("hood", "panel", "Hood sewn to the neckline.", categories=("top", "full"),
                     target_types=("body",), params={"size": ParamDef("enum", ("snug", "regular", "oversized"),
                                                                        default="regular")}),
    ComponentTypeDef("pocket", "panel", "Patch pocket sewn onto a panel.", target_types=("body", "leg"),
                     params={"placement": ParamDef("enum", POCKET_PLACEMENTS, default="hip_left"),
                             "size": ParamDef("float", min=0.05, max=0.35, default=0.14)},
                     aliases=("patch_pocket",), child_suffix="pocket"),
    ComponentTypeDef("cargo_pocket", "panel", "Large bellows-style pocket on the outer thigh.",
                     categories=("bottom",), target_types=("leg",), target_required=True,
                     params={"size": ParamDef("float", min=0.08, max=0.35, default=0.18)},
                     aliases=("cargo",), child_suffix="cargo_pocket"),
    ComponentTypeDef("kangaroo_pocket", "panel", "Front pouch pocket (hoodies).", categories=("top", "full"),
                     target_types=("body",), aliases=("pouch", "pouch_pocket")),
    ComponentTypeDef("collar", "band", "Neckline band / collar.", categories=("top", "full"), target_types=("body",),
                     params={"style": ParamDef("enum", ("crew", "v_neck", "shirt", "stand", "scoop", "turtleneck",
                                                        "rib"), default="crew"),
                             "height": ParamDef("float", min=0.0, max=0.15)},
                     aliases=("neckline", "neck")),
    ComponentTypeDef("cuff", "band", "Cuff at a sleeve or leg opening.", target_types=("sleeve", "leg"),
                     target_required=True,
                     params={"style": ParamDef("enum", ("plain", "rib", "buttoned", "folded"), default="plain"),
                             "width": ParamDef("float", min=0.005, max=0.15, default=0.04)},
                     child_suffix="cuff"),
    ComponentTypeDef("elastic_cuff", "band", "Elastic cuff that gathers the opening.", target_types=("sleeve", "leg"),
                     target_required=True, params=dict(ELASTIC_PARAMS), elastic=True,
                     aliases=("elastic_cuffs", "ribbed_cuff", "rib_cuff"), child_suffix="cuff"),
    ComponentTypeDef("hem", "band", "Finished hem at a panel's lower edge.", target_types=PANELS_WITH_ENDS,
                     params={"width": ParamDef("float", min=0.005, max=0.1, default=0.02)}, child_suffix="hem"),
    ComponentTypeDef("waistband", "band", "Waistband (bottoms) or ribbed hem band (tops).", target_types=("body",),
                     params={"width": ParamDef("float", min=0.01, max=0.12, default=0.04),
                             "elastic": ParamDef("dict")}),
    ComponentTypeDef("elastic_waistband", "band", "Elastic waistband.", target_types=("body",),
                     params=dict(ELASTIC_PARAMS), elastic=True),
    ComponentTypeDef("zipper", "feature", "Front zipper (stiffened line).", target_types=("body",),
                     params={"state": ParamDef("enum", ("closed", "open", "half"), default="closed")},
                     aliases=("zip",)),
    ComponentTypeDef("button_placket", "feature", "Button placket (stiffened line).", target_types=("body",),
                     params={"count": ParamDef("int", min=1, max=20, default=7)}, aliases=("buttons", "placket")),
    ComponentTypeDef("button", "feature", "Single button / small button group.", target_types=("body", "sleeve",
                                                                                             "cuff", "waistband"),
                     params={"count": ParamDef("int", min=1, max=20, default=1)}),
    ComponentTypeDef("belt_loop", "feature", "Belt loops on the waistband.", categories=("bottom", "full"),
                     target_types=("waistband",), params={"count": ParamDef("int", min=1, max=12, default=5)},
                     aliases=("belt_loops",)),
    ComponentTypeDef("drawstring", "feature", "Drawstring that gathers a hood or waistband.",
                     target_types=("hood", "waistband", "elastic_waistband", "hem"), target_required=True,
                     params={"strength": ParamDef("strength", default="light"),
                             "tension": ParamDef("float", min=0.0, max=0.5)}),
    ComponentTypeDef("elastic", "feature", "Elastic applied to an existing band.",
                     target_types=("cuff", "hem", "waistband", "collar", "hood"), target_required=True,
                     params=dict(ELASTIC_PARAMS), elastic=True),
    ComponentTypeDef("seam", "feature", "Extra sewing seam between two components.",
                     params={"a": ParamDef("str"), "b": ParamDef("str")}),
]
for _c in _BUILTIN:
    register_component_type(_c)


# ----------------------------------------------------------------------------
# target resolution
# ----------------------------------------------------------------------------
GROUP_TARGETS = {
    "sleeves": ("sleeve",), "sleeve": ("sleeve",), "arms": ("sleeve",),
    "legs": ("leg",), "leg": ("leg",), "trouser_legs": ("leg",), "pant_legs": ("leg",),
    "pockets": ("pocket", "cargo_pocket", "kangaroo_pocket"),
    "body": ("body",), "torso": ("body",),
}
CHILD_GROUPS = {
    # name -> (child types, parent types)
    "cuffs": (("cuff", "elastic_cuff"), ("sleeve", "leg")),
    "sleeve_cuffs": (("cuff", "elastic_cuff"), ("sleeve",)),
    "sleeve_cuff": (("cuff", "elastic_cuff"), ("sleeve",)),
    "wrist_cuffs": (("cuff", "elastic_cuff"), ("sleeve",)),
    "ankle_cuffs": (("cuff", "elastic_cuff", "hem"), ("leg",)),
    "leg_cuffs": (("cuff", "elastic_cuff", "hem"), ("leg",)),
    "leg_openings": (("cuff", "elastic_cuff", "hem"), ("leg",)),
    "hems": (("hem",), ("body", "leg", "sleeve")),
}
TYPE_GROUPS = {"hem": ("hem",), "waistband": ("waistband", "elastic_waistband"), "waist": ("waistband",
                                                                                            "elastic_waistband"),
               "collar": ("collar",), "neckline": ("collar",), "hood": ("hood",), "zipper": ("zipper",),
               "buttons": ("button_placket", "button"), "drawstring": ("drawstring",), "belt_loops": ("belt_loop",)}


def resolve_target(spec: Any, target: Optional[str]) -> List[str]:
    """Map a user target ('sleeves', 'left_sleeve', 'cuffs', 'hood') to component names."""
    if target is None:
        return []
    t = normalize(target)
    comps = list(spec.components)
    names = [c.name for c in comps]
    if t in ("garment", "all", "whole", "it", "overall", "shirt"):
        return []
    if t in names:
        return [t]
    if t in GROUP_TARGETS:
        return [c.name for c in comps if c.type in GROUP_TARGETS[t]]
    if t in CHILD_GROUPS:
        child_types, parent_types = CHILD_GROUPS[t]
        parent_names = {c.name for c in comps if c.type in parent_types}
        return [c.name for c in comps if c.type in child_types and c.target in parent_names]
    if t in TYPE_GROUPS:
        return [c.name for c in comps if c.type in TYPE_GROUPS[t]]
    ctype = resolve_component_type(t)
    if ctype is not None:
        return [c.name for c in comps if c.type == ctype.name]
    return []


def resolve_parent_targets(spec: Any, target: Optional[str], child: ComponentTypeDef) -> Tuple[List[str], List[Issue]]:
    """Parents a new child component (e.g. elastic_cuff) should attach to."""
    issues: List[Issue] = []
    if target is None:
        if child.target_required:
            issues.append(Issue("MISSING_PARAM", f"Component '{child.name}' needs a target (e.g. 'sleeves').",
                                path="target"))
            return [], issues
        default = [c.name for c in spec.components if c.type in child.target_types][:1]
        return default, issues
    t = normalize(target)
    if t in CHILD_GROUPS:  # "sleeve_cuffs" -> parents are sleeves
        _, parent_types = CHILD_GROUPS[t]
        parents = [c.name for c in spec.components if c.type in parent_types]
    else:
        parents = resolve_target(spec, target)
    if not parents:
        issues.append(Issue("TARGET_NOT_FOUND", f"Target '{target}' does not exist on this {spec.type}.",
                            path="target", suggestions=sorted({c.name for c in spec.components})))
        return [], issues
    bad = [p for p in parents if child.target_types and spec.get_component(p).type not in child.target_types]
    if bad:
        issues.append(Issue("INVALID_TARGET", f"'{child.name}' cannot attach to {bad}; allowed parent types: "
                                              f"{list(child.target_types)}.", path="target"))
        return [], issues
    return parents, issues


def child_name(parent: str, ctype: ComponentTypeDef, existing: List[str]) -> str:
    base = f"{parent}_{ctype.child_suffix or ctype.name}"
    name, i = base, 2
    while name in existing:
        name = f"{base}_{i}"
        i += 1
    return name


def fill_param_defaults(ctype: ComponentTypeDef, params: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(params)
    for k, p in ctype.params.items():
        if k not in out and p.default is not None:
            out[k] = p.default
    if ctype.elastic:
        try:
            e = ElasticSpec.from_params(target="_", strength=out.get("strength", "medium"), width=out.get("width"),
                                        tension=out.get("tension"))
        except GarmentError:
            return out  # invalid values are reported by validate_component_params
        out.setdefault("tension", e.tension)
        out.setdefault("width", e.width)
    return out


def validate_component_params(ctype: ComponentTypeDef, params: Dict[str, Any], path: str) -> List[Issue]:
    issues: List[Issue] = []
    elastic_keys = {"strength", "tension", "width"} if ctype.elastic else set()
    for k, v in params.items():
        if k in elastic_keys or k == "elastic":
            continue
        if k not in ctype.params:
            issues.append(Issue("INVALID_PARAM", f"Component '{ctype.name}' has no parameter '{k}'.",
                                path=f"{path}.{k}", suggestions=sorted(ctype.params)))
            continue
        msg = ctype.params[k].check(v)
        if msg:
            issues.append(Issue("INVALID_PARAM", f"{ctype.name}.{k}={v!r} {msg}.", path=f"{path}.{k}"))
    eparams = params if ctype.elastic else params.get("elastic")
    if eparams is not None:
        if not isinstance(eparams, dict):
            issues.append(Issue("INVALID_PARAM", "'elastic' must be an object like {'strength': 'medium'}.",
                                path=f"{path}.elastic"))
        else:
            for issue in validate_elastic_params(eparams):
                issue.path = f"{path}.{issue.path}" if issue.path else path
                issues.append(issue)
    return issues

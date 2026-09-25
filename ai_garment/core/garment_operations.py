"""Garment operations: registry, normalisation, validation, pure spec transforms.

Every operation Claude can request is an :class:`OperationDef` with:
  * a parameter schema (validation + JSON schema generation),
  * ``effects`` telling the provider what must be redone (geometry, physics,
    material, simulation cache, ...),
  * an optional *pure* ``transform(spec, params) -> notes`` applied to a COPY
    of the spec (so dry runs can execute the whole plan without Blender),
  * a human-readable ``describe``.
Scene-only operations (fit, simulate, settle, bake, reset, inspect, ...)
leave the spec unchanged and are executed by the provider.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Tuple

from .component_system import (
    ParamDef,
    SLEEVE_LENGTH_ALIASES,
    SLEEVE_LENGTHS,
    child_name,
    fill_param_defaults,
    resolve_component_type,
    resolve_parent_targets,
    resolve_target,
    validate_component_params,
)
from .errors import GarmentError, Issue
from .fabric_presets import resolve_fabric
from .fit_system import adjust_fit, region_keys
from .garment_spec import SIM_MODES, ComponentSpec, FabricSpec, GarmentSpec
from .garment_types import normalize_length
from .quality import QUALITY_LEVELS, SELF_COLLISION_PRESETS
from .units import parse_amount
from .validation import validate_spec
from .vocabulary import (
    FIT_COMPARATIVES,
    FIT_LEVELS,
    canonical_color,
    fit_direction,
    normalize,
    normalize_fit_level,
    parse_color,
    parse_intensity,
    suggest,
)

# effect names
CREATE, GEOMETRY, PHYSICS, MATERIAL, SIMULATION = "create", "geometry", "physics", "material", "simulation"
FIT, COLLISION, SIMULATE, SETTLE, BAKE, RESET, INSPECT, WRINKLES = (
    "fit", "collision", "simulate", "settle", "bake", "reset", "inspect", "wrinkles")
SPEC_EDIT_EFFECTS = frozenset({GEOMETRY, PHYSICS, MATERIAL})


@dataclass
class Operation:
    name: str
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dict({"operation": self.name}, **self.params)


@dataclass
class OpApplication:
    spec: GarmentSpec
    notes: List[str]
    effects: FrozenSet[str]
    description: List[str]


Transform = Callable[[GarmentSpec, Dict[str, Any]], List[str]]
Validator = Callable[[GarmentSpec, Dict[str, Any]], List[Issue]]
Describe = Callable[[Optional[GarmentSpec], Dict[str, Any]], List[str]]


@dataclass(frozen=True)
class OperationDef:
    name: str
    description: str
    params: Dict[str, ParamDef] = field(default_factory=dict)
    required: Tuple[str, ...] = ()
    effects: FrozenSet[str] = frozenset()
    transform: Optional[Transform] = None
    validator: Optional[Validator] = None
    describe: Optional[Describe] = None
    requires_garment: bool = True
    mutates_scene: bool = True
    allow_extra: bool = False
    phase: int = 2  # ordering hint: 0 create, 1 spec edits, 2 fit, 3 simulate/settle, 4 bake/finish


_OPS: Dict[str, OperationDef] = {}
# alias -> (canonical op, params injected)
_ALIASES: Dict[str, Tuple[str, Dict[str, Any]]] = {
    "tighten": ("modify_fit", {"direction": "tighter"}),
    "loosen": ("modify_fit", {"direction": "looser"}),
    "lengthen": ("modify_length", {"direction": "longer"}),
    "shorten": ("modify_length", {"direction": "shorter"}),
    "fit_to_avatar": ("fit", {}),
    "fit_garment": ("fit", {}),
    "create_garment": ("create", {}),
    "simulate_garment": ("simulate", {}),
    "bake_simulation": ("bake", {}),
    "add_elastic": ("set_elastic", {}),
    "change_fabric": ("set_fabric", {}),
    "change_color": ("set_color", {}),
    "set_colour": ("set_color", {}),
    "self_collision": ("enable_self_collision", {}),
    "wrinkles": ("generate_wrinkles", {}),
    "drape": ("settle", {}),
    "remove": ("remove_component", {}),
    "add": ("add_component", {}),
}


def register_operation(defn: OperationDef, replace: bool = False) -> None:
    if defn.name in _OPS and not replace:
        raise GarmentError("DUPLICATE_OPERATION", f"Operation '{defn.name}' already registered.")
    _OPS[defn.name] = defn


def list_operations() -> List[str]:
    return sorted(_OPS)


def list_aliases() -> Dict[str, str]:
    return {k: v[0] for k, v in _ALIASES.items()}


def get_operation_def(name: str) -> Optional[OperationDef]:
    n = normalize(name)
    if n in _OPS:
        return _OPS[n]
    if n in _ALIASES:
        return _OPS[_ALIASES[n][0]]
    return None


def normalize_operation(value: Any) -> Operation:
    if isinstance(value, Operation):
        return Operation(value.name, dict(value.params))
    if not isinstance(value, dict):
        raise GarmentError("INVALID_OPERATION", f"An operation must be an object, got {type(value).__name__}.")
    d = dict(value)
    raw = d.pop("operation", None) or d.pop("op", None) or d.pop("command", None)
    if not raw:
        raise GarmentError("INVALID_OPERATION", "Operation is missing the 'operation' field.",
                           suggestions=list_operations())
    n = normalize(raw)
    params = dict(d.pop("params", {}) or {})
    params.update(d)
    if n in _ALIASES:
        canonical, injected = _ALIASES[n]
        for k, v in injected.items():
            params.setdefault(k, v)
        n = canonical
    if n not in _OPS:
        raise GarmentError("UNKNOWN_OPERATION", f"Unknown operation '{raw}'.", path="operation",
                           suggestions=suggest(n, list(_OPS) + list(_ALIASES)))
    return Operation(n, params)


def validate_operation(op: Operation, spec: Optional[GarmentSpec] = None) -> List[Issue]:
    defn = _OPS[op.name]
    issues: List[Issue] = []
    for req in defn.required:
        alts = req.split("|")
        if not any(op.params.get(a) is not None for a in alts):
            issues.append(Issue("MISSING_PARAM", f"Operation '{op.name}' requires '{' or '.join(alts)}'.",
                                path=f"{op.name}.{alts[0]}"))
    for k, v in op.params.items():
        pdef = defn.params.get(k)
        if pdef is None:
            if not defn.allow_extra:
                issues.append(Issue("INVALID_PARAM", f"Operation '{op.name}' has no parameter '{k}'.",
                                    path=f"{op.name}.{k}", suggestions=sorted(defn.params)))
            continue
        if v is None:
            continue
        msg = pdef.check(v)
        if msg:
            issues.append(Issue("INVALID_PARAM", f"{op.name}.{k}={v!r} {msg}.", path=f"{op.name}.{k}"))
    if issues:
        return issues
    if defn.requires_garment and spec is None and defn.name != "create":
        return issues
    if defn.validator is not None:
        try:
            issues += defn.validator(spec, op.params)
        except GarmentError as err:
            issues.append(err.to_issue())
    return issues


def apply_operation(spec: Optional[GarmentSpec], op: Operation) -> OpApplication:
    """Pure: returns a NEW spec. Raises GarmentError if the operation is invalid."""
    issues = validate_operation(op, spec)
    if issues:
        raise GarmentError(issues[0].code, issues[0].message, issues[0].suggestions,
                           {"issues": [i.to_dict() for i in issues]}, issues[0].path)
    defn = _OPS[op.name]
    if defn.name == "create":
        new = _spec_from_create(op.params)
        notes = [f"Created {new.display_name} spec."]
    else:
        if spec is None:
            raise GarmentError("NO_GARMENT", f"Operation '{op.name}' needs an existing garment.")
        new = spec.copy()
        notes = defn.transform(new, op.params) if defn.transform else []
    desc = defn.describe(new, op.params) if defn.describe else [defn.name.replace("_", " ").capitalize()]
    return OpApplication(new, notes, defn.effects, desc)


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------

def _p(t: str, choices=(), mn=None, mx=None, default=None, desc="") -> ParamDef:
    return ParamDef(t, tuple(choices), mn, mx, default, desc)


def _targets(spec: GarmentSpec, target: Optional[str], allowed_types: Tuple[str, ...] = ()) -> List[str]:
    names = resolve_target(spec, target)
    if allowed_types:
        names = [n for n in names if spec.get_component(n).type in allowed_types]
    return names


def _target_issue(spec: GarmentSpec, target: str, what: str = "component") -> Issue:
    return Issue("TARGET_NOT_FOUND", f"This {spec.display_name} has no {what} '{target}'.", path="target",
                 suggestions=sorted(c.name for c in spec.components))


def _default_limb_target(spec: GarmentSpec) -> str:
    return "legs" if spec.category == "bottom" else "sleeves"


def _spec_from_create(params: Dict[str, Any]) -> GarmentSpec:
    if isinstance(params.get("spec"), dict):
        data = dict(params["spec"])
    else:
        data = {k: v for k, v in params.items() if k not in ("spec", "transactional", "avatar", "provider")}
    return GarmentSpec.from_dict(data)


def _describe_create(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    out = [f"Create {spec.display_name}", f"Apply {spec.fit.level} fit", f"Apply {spec.fabric.display} preset"]
    if spec.color:
        out.append(f"Set color {spec.color}")
    return out


def _validate_create(spec: Optional[GarmentSpec], params: Dict[str, Any]) -> List[Issue]:
    if not (params.get("type") or (isinstance(params.get("spec"), dict) and params["spec"].get("type"))):
        return [Issue("MISSING_PARAM", "create requires a garment 'type' (e.g. 'tshirt').", path="create.type")]
    try:
        new = _spec_from_create(params)
    except GarmentError as err:
        return [err.to_issue()]
    return list(validate_spec(new).errors)


# --- add / remove / modify components ---------------------------------------

_COMPONENT_OP_KEYS = {"type", "target", "name", "params"}


def _component_params(params: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(params.get("params") or {})
    for k, v in params.items():
        if k not in _COMPONENT_OP_KEYS:
            out[k] = v
    return out


def _validate_add_component(spec: GarmentSpec, params: Dict[str, Any]) -> List[Issue]:
    ctype = resolve_component_type(params["type"])
    if ctype is None:
        return [Issue("UNKNOWN_COMPONENT", f"Unknown component type '{params['type']}'.", path="type")]
    if spec.category and spec.category not in ctype.categories:
        return [Issue("INVALID_COMPONENT_FOR_TYPE", f"A {ctype.name} cannot be added to a {spec.display_name}.",
                      path="type")]
    issues: List[Issue] = []
    if ctype.target_types or params.get("target"):
        _, issues = resolve_parent_targets(spec, params.get("target"), ctype)
    cparams = _component_params(params)
    issues += validate_component_params(ctype, fill_param_defaults(ctype, cparams), "params")
    return issues


def _add_component(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    ctype = resolve_component_type(params["type"])
    cparams = _component_params(params)
    notes: List[str] = []
    parents: List[Optional[str]] = [None]
    if ctype.target_types or params.get("target"):
        parents, _ = resolve_parent_targets(spec, params.get("target"), ctype)
        parents = parents or [None]
    for parent in parents:
        existing = None
        if parent and ctype.name in ("cuff", "elastic_cuff"):
            existing = next((c for c in spec.children_of(parent) if c.type in ("cuff", "elastic_cuff")), None)
        if existing is not None:
            existing.type = ctype.name
            existing.params = fill_param_defaults(ctype, {k: v for k, v in cparams.items()})
            notes.append(f"Replaced {existing.name} with {ctype.name}.")
            continue
        if params.get("name") and len(parents) == 1:
            name = spec.unique_name(params["name"])
        elif parent:
            name = child_name(parent, ctype, [c.name for c in spec.components])
        else:
            name = spec.unique_name(ctype.name)
        spec.components.append(ComponentSpec(ctype.name, name, parent, fill_param_defaults(ctype, dict(cparams))))
        notes.append(f"Added {ctype.name} '{name}'" + (f" on {parent}." if parent else "."))
    return notes


def _describe_add(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    t = normalize(params.get("type", ""))
    target = normalize(params.get("target") or "")
    if t in ("cuff", "elastic_cuff"):
        where = "sleeve" if "sleeve" in target or target in ("arms", "cuffs", "") and spec.category != "bottom" \
            else "ankle"
        out = [f"Create {where} cuffs"]
        if t == "elastic_cuff":
            out.append(f"Apply {params.get('strength') or 'medium'} elastic to {where} cuffs")
        return out
    label = t.replace("_", " ")
    return [f"Add {label}" + (f" to {target.replace('_', ' ')}" if target else "")]


def _validate_remove(spec: GarmentSpec, params: Dict[str, Any]) -> List[Issue]:
    names = resolve_target(spec, params["target"])
    if not names:
        return [_target_issue(spec, params["target"])]
    req = [n for n in names if getattr(resolve_component_type(spec.get_component(n).type), "required", False)]
    if req:
        return [Issue("REQUIRED_COMPONENT", f"Cannot remove required component(s) {req}.", path="target")]
    return []


def _remove(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    removed: List[str] = []
    for n in resolve_target(spec, params["target"]):
        if spec.get_component(n) is not None:
            removed += spec.remove_component(n)
    return [f"Removed {', '.join(removed)}."]


def _validate_modify_component(spec: GarmentSpec, params: Dict[str, Any]) -> List[Issue]:
    names = resolve_target(spec, params["target"])
    if not names:
        return [_target_issue(spec, params["target"])]
    issues: List[Issue] = []
    for n in names:
        comp = spec.get_component(n)
        ctype = resolve_component_type(comp.type)
        merged = dict(comp.params, **_component_params(params))
        issues += validate_component_params(ctype, merged, f"components.{n}.params")
    return issues


def _modify_component(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    names = resolve_target(spec, params["target"])
    for n in names:
        spec.get_component(n).params.update(_component_params(params))
    return [f"Updated {', '.join(names)}."]


# --- fit ---------------------------------------------------------------------

def _fit_scope(spec: GarmentSpec, params: Dict[str, Any]) -> Tuple[Optional[str], Optional[List[str]]]:
    region = params.get("region")
    target = params.get("target")
    comps = None
    if target and normalize(target) not in ("garment", "all", "whole", "overall"):
        comps = resolve_target(spec, target)
        if region is None:
            types = {spec.get_component(c).type for c in comps}
            region = "sleeves" if types == {"sleeve"} else "legs" if types == {"leg"} else None
    return region, comps


def _validate_modify_fit(spec: GarmentSpec, params: Dict[str, Any]) -> List[Issue]:
    d = params["direction"]
    if normalize_fit_level(d) is None and fit_direction(d) is None:
        return [Issue("INVALID_PARAM", f"Fit direction '{d}' must be tighter/looser or a fit level.",
                      path="modify_fit.direction", suggestions=list(FIT_COMPARATIVES) + FIT_LEVELS)]
    issues: List[Issue] = []
    if params.get("region") is not None:
        try:
            region_keys(params["region"])
        except GarmentError as err:
            issues.append(err.to_issue())
    if params.get("target") and normalize(params["target"]) not in ("garment", "all", "whole", "overall") and \
            not resolve_target(spec, params["target"]):
        issues.append(_target_issue(spec, params["target"]))
    return issues


def _modify_fit(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    region, comps = _fit_scope(spec, params)
    intensity = parse_intensity(params.get("intensity"), 1.0)
    new_fit, notes = adjust_fit(spec.fit, region, params["direction"], intensity, comps)
    spec.fit = new_fit
    return notes


def _describe_modify_fit(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    where = params.get("region") or params.get("target") or "garment"
    return [f"Make {where} {params['direction']}"]


def _validate_set_fit(spec: GarmentSpec, params: Dict[str, Any]) -> List[Issue]:
    if normalize_fit_level(params["level"]) is None:
        return [Issue("UNKNOWN_FIT", f"Unknown fit '{params['level']}'.", path="set_fit.level",
                      suggestions=suggest(params["level"], FIT_LEVELS))]
    if params.get("target") and not resolve_target(spec, params["target"]):
        return [_target_issue(spec, params["target"])]
    return []


def _set_fit(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    comps = resolve_target(spec, params["target"]) if params.get("target") else None
    spec.fit, notes = adjust_fit(spec.fit, None, normalize_fit_level(params["level"]), 1.0, comps)
    return notes


# --- length ------------------------------------------------------------------

LENGTH_TYPES = ("sleeve", "leg")


def _validate_modify_length(spec: GarmentSpec, params: Dict[str, Any]) -> List[Issue]:
    target = params.get("target") or "garment"
    issues: List[Issue] = []
    if params.get("amount") is None and params.get("direction") is None and params.get("length") is None:
        return [Issue("MISSING_PARAM", "modify_length needs 'amount', 'direction' or 'length'.", path="amount")]
    if params.get("direction") is not None and normalize(params["direction"]) not in ("longer", "shorter"):
        issues.append(Issue("INVALID_PARAM", "direction must be 'longer' or 'shorter'.", path="direction"))
    if normalize(target) not in ("garment", "all", "hem", "body"):
        comps = _targets(spec, target, LENGTH_TYPES)
        if not comps:
            issues.append(_target_issue(spec, target, "sleeves/legs"))
        if params.get("length") is not None:
            n = normalize(params["length"])
            if SLEEVE_LENGTH_ALIASES.get(n, n) not in SLEEVE_LENGTHS:
                issues.append(Issue("INVALID_PARAM", f"Unknown sleeve length '{params['length']}'.", path="length",
                                    suggestions=list(SLEEVE_LENGTHS)))
    elif params.get("length") is not None and spec.type_def is not None:
        if normalize_length(params["length"]) not in spec.type_def.allowed_lengths():
            issues.append(Issue("INVALID_LENGTH", f"Length '{params['length']}' is not valid for this garment.",
                                path="length", suggestions=spec.type_def.allowed_lengths()))
    return issues


def _length_delta(params: Dict[str, Any]) -> Dict[str, float]:
    if params.get("amount") is not None:
        a = parse_amount(params["amount"])
        return {"percent": a.value, "meters": 0.0} if a.kind == "percent" else {"percent": 0.0, "meters": a.value}
    sign = 1.0 if normalize(params["direction"]) == "longer" else -1.0
    return {"percent": sign * 10.0 * parse_intensity(params.get("intensity"), 1.0), "meters": 0.0}


def _modify_length(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    target = normalize(params.get("target") or "garment")
    if target in ("garment", "all", "hem", "body"):
        if params.get("length") is not None:
            spec.length = normalize_length(params["length"])
            return [f"Set garment length to {spec.length}."]
        d = _length_delta(params)
        spec.length_adjust = {"percent": spec.length_adjust.get("percent", 0.0) + d["percent"],
                              "meters": spec.length_adjust.get("meters", 0.0) + d["meters"]}
        return [f"Garment length adjusted by {d['percent']:+g}% {d['meters'] * 100:+g}cm."]
    names = _targets(spec, target, LENGTH_TYPES)
    for n in names:
        comp = spec.get_component(n)
        if params.get("length") is not None:
            ln = normalize(params["length"])
            comp.params["length"] = SLEEVE_LENGTH_ALIASES.get(ln, ln)
            comp.params.pop("length_adjust", None)
            continue
        d = _length_delta(params)
        cur = dict(comp.params.get("length_adjust") or {"percent": 0.0, "meters": 0.0})
        comp.params["length_adjust"] = {"percent": cur.get("percent", 0.0) + d["percent"],
                                        "meters": cur.get("meters", 0.0) + d["meters"]}
    return [f"Adjusted length of {', '.join(names)}."]


def _describe_length(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    what = params.get("target") or "garment"
    how = params.get("amount") or params.get("length") or params.get("direction")
    return [f"Change {what} length ({how})"]


# --- roll / fold / tuck ----------------------------------------------------------

def _validate_roll(spec: GarmentSpec, params: Dict[str, Any]) -> List[Issue]:
    target = params.get("target") or _default_limb_target(spec)
    if not _targets(spec, target, LENGTH_TYPES):
        return [_target_issue(spec, target, "sleeves/legs")]
    return []


def _roll(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    target = params.get("target") or _default_limb_target(spec)
    turns = int(params.get("turns") or 2)
    names = _targets(spec, target, LENGTH_TYPES)
    for n in names:
        spec.get_component(n).state["rolled"] = turns
    return [f"Rolled {', '.join(names)} ({turns} turns)."]


def _unroll(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    names = _targets(spec, params.get("target") or _default_limb_target(spec), LENGTH_TYPES)
    for n in names:
        spec.get_component(n).state.pop("rolled", None)
        spec.get_component(n).state.pop("folded", None)
    return [f"Unrolled {', '.join(names)}."]


def _fold(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    names = _targets(spec, params.get("target") or _default_limb_target(spec), LENGTH_TYPES)
    for n in names:
        comp = spec.get_component(n)
        comp.state["rolled"] = 1
        comp.state["folded"] = True
    return [f"Folded {', '.join(names)} once (cuffed)."]


def _validate_tuck(spec: GarmentSpec, params: Dict[str, Any]) -> List[Issue]:
    if spec.category != "top":
        return [Issue("INVALID_FOR_TYPE", f"A {spec.display_name} cannot be tucked; only tops can.", path="tuck")]
    return []


def _tuck(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    spec.tucked = True
    return ["Tucked in: hem lengthened below the waist and narrowed. Layer it under the bottoms."]


def _untuck(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    spec.tucked = False
    return ["Untucked."]


# --- elastic / fabric / colour / misc -----------------------------------------------

def _elastic_params(params: Dict[str, Any]) -> Dict[str, Any]:
    return {k: params[k] for k in ("strength", "tension", "width") if params.get(k) is not None}


def _validate_set_elastic(spec: GarmentSpec, params: Dict[str, Any]) -> List[Issue]:
    from .elastic import validate_elastic_params
    issues = list(validate_elastic_params(_elastic_params(params)))
    if not resolve_target(spec, params["target"]):
        issues.append(_target_issue(spec, params["target"]))
    return issues


def _set_elastic(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    ep = _elastic_params(params) or {"strength": "medium"}
    notes: List[str] = []
    for n in resolve_target(spec, params["target"]):
        comp = spec.get_component(n)
        if comp.type in ("sleeve", "leg"):
            notes += _add_component(spec, dict(ep, type="elastic_cuff", target=n))
        elif comp.type in ("elastic_cuff", "elastic_waistband", "elastic"):
            comp.params.update(ep)
            comp.params = fill_param_defaults(resolve_component_type(comp.type), comp.params)
            notes.append(f"Updated elastic on {n}.")
        else:
            comp.params["elastic"] = dict(ep)
            notes.append(f"Made {n} elastic.")
    return notes


def _validate_set_fabric(spec: GarmentSpec, params: Dict[str, Any]) -> List[Issue]:
    try:
        resolve_fabric(_fabric_spec(params))
    except GarmentError as err:
        return [err.to_issue()]
    return []


def _fabric_spec(params: Dict[str, Any]) -> FabricSpec:
    f = FabricSpec.from_value(params["fabric"])
    if params.get("overrides"):
        f.overrides.update(params["overrides"])
    return f


def _set_fabric(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    spec.fabric = _fabric_spec(params)
    return [f"Fabric set to {spec.fabric.display}."]


def _validate_color(spec: GarmentSpec, params: Dict[str, Any]) -> List[Issue]:
    try:
        parse_color(params["color"])
    except GarmentError as err:
        return [err.to_issue()]
    return []


def _set_color(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    spec.color = canonical_color(params["color"])
    return [f"Color set to {spec.color}."]


def _validate_seam(spec: GarmentSpec, params: Dict[str, Any]) -> List[Issue]:
    seam = params.get("seam") or f"{params.get('a')}:{params.get('b')}"
    parts = [normalize(p) for p in str(seam).split(":")]
    if len(parts) != 2:
        return [Issue("INVALID_PARAM", "seam must look like 'left_sleeve:body'.", path="seam")]
    missing = [p for p in parts if spec.get_component(p) is None]
    return [_target_issue(spec, m) for m in missing]


def _seam_name(params: Dict[str, Any]) -> str:
    seam = params.get("seam") or f"{params.get('a')}:{params.get('b')}"
    return ":".join(normalize(p) for p in str(seam).split(":"))


def _unsew(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    s = _seam_name(params)
    if s not in spec.disabled_seams:
        spec.disabled_seams.append(s)
    return [f"Seam {s} opened."]


def _sew(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    s = _seam_name(params)
    if s in spec.disabled_seams:
        spec.disabled_seams.remove(s)
        return [f"Seam {s} re-sewn."]
    a, b = s.split(":")
    if not any(c.type == "seam" and c.params.get("a") == a and c.params.get("b") == b for c in spec.components):
        spec.components.append(ComponentSpec("seam", spec.unique_name(f"seam_{a}_{b}"), None, {"a": a, "b": b}))
    return [f"Seam {s} added."]


def _resize(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    a = parse_amount(params["amount"])
    spec.fit.scale = round(spec.fit.scale * (1.0 + a.value / 100.0), 6)
    return [f"Garment circumferences scaled to {spec.fit.scale:g}x."]


def _validate_resize(spec: GarmentSpec, params: Dict[str, Any]) -> List[Issue]:
    a = parse_amount(params["amount"])
    if a.kind != "percent":
        return [Issue("INVALID_PARAM", "resize takes a percentage like '+5%'.", path="amount")]
    if not 0.7 <= spec.fit.scale * (1 + a.value / 100.0) <= 1.5:
        return [Issue("INVALID_PARAM", "resize would leave the 0.7..1.5 scale range.", path="amount")]
    return []


def _move(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    cur = list(spec.placement.get("offset", [0.0, 0.0, 0.0]))
    spec.placement["offset"] = [round(c + float(d), 6) for c, d in zip(cur, params["offset"])]
    return [f"Offset now {spec.placement['offset']}."]


def _validate_pin(spec: GarmentSpec, params: Dict[str, Any]) -> List[Issue]:
    return [] if resolve_target(spec, params["target"]) else [_target_issue(spec, params["target"])]


def _pin(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    names = resolve_target(spec, params["target"])
    for n in names:
        if n not in spec.simulation.pin:
            spec.simulation.pin.append(n)
    return [f"Pinned {', '.join(names)}."]


def _unpin(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    names = resolve_target(spec, params["target"]) if params.get("target") else list(spec.simulation.pin)
    spec.simulation.pin = [p for p in spec.simulation.pin if p not in names]
    return [f"Unpinned {', '.join(names)}."]


def _self_collision(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    preset = normalize(params.get("preset") or "preview")
    spec.simulation.self_collision = preset != "off"
    spec.metadata["self_collision_preset"] = preset
    return [f"Self collision: {preset}."]


def _fixed(*lines: str) -> Describe:
    return lambda spec, params: list(lines)


def _describe_sim(spec: GarmentSpec, params: Dict[str, Any]) -> List[str]:
    return ["Simulate"]


TARGET = _p("str", desc="component name or group: sleeves, legs, cuffs, hood, waistband, left_sleeve ...")
INTENSITY = _p("intensity", desc="'slightly' (0.5) .. 'much' (2.0) or a number")
ELASTIC = {"strength": _p("strength"), "tension": _p("float", mn=0.0, mx=1.0), "width": _p("float", mn=0.0, mx=1.0)}

_BUILTIN = [
    OperationDef("create", "Create a garment from a spec (type, fit, fabric, color, length, components...).",
                 {"type": _p("str"), "spec": _p("dict"), "fit": _p("str_or_dict"), "fabric": _p("str_or_dict"),
                  "color": _p("any"), "length": _p("str"), "name": _p("str")},
                 ("type|spec",), frozenset({CREATE, GEOMETRY, PHYSICS, MATERIAL}), None, _validate_create,
                 _describe_create, requires_garment=False, allow_extra=True, phase=0),
    OperationDef("fit", "Fit the garment to the avatar and prepare body collision.",
                 {"avatar": _p("str"), "avatar_hint": _p("str"), "metadata": _p("dict"),
                  "collision_mode": _p("enum", ("proxy", "direct")), "margin": _p("float", mn=0.0, mx=0.1)},
                 (), frozenset({FIT, GEOMETRY, COLLISION}), None, None, _fixed("Fit to avatar", "Enable collision"),
                 phase=2),
    OperationDef("prepare_collision", "Prepare avatar collision geometry (proxy by default).",
                 {"margin": _p("float", mn=0.0, mx=0.1), "mode": _p("enum", ("proxy", "direct")),
                  "regions": _p("any")}, (), frozenset({COLLISION}), None, None, _fixed("Enable collision"), phase=2),
    OperationDef("resize", "Scale garment circumferences by a percentage.", {"amount": _p("amount")}, ("amount",),
                 frozenset({GEOMETRY}), _resize, _validate_resize, _fixed("Resize garment"), phase=1),
    OperationDef("move", "Offset the garment in metres.", {"offset": _p("vec3")}, ("offset",),
                 frozenset({GEOMETRY}), _move, None, _fixed("Move garment"), phase=1),
    OperationDef("sew", "Sew (or re-sew) a seam 'a:b'.", {"seam": _p("str"), "a": _p("str"), "b": _p("str")},
                 ("seam|a",), frozenset({GEOMETRY, PHYSICS}), _sew, _validate_seam, _fixed("Sew seam"), phase=1),
    OperationDef("unsew", "Open a seam 'a:b'.", {"seam": _p("str"), "a": _p("str"), "b": _p("str")}, ("seam|a",),
                 frozenset({GEOMETRY, PHYSICS}), _unsew, _validate_seam, _fixed("Open seam"), phase=1),
    OperationDef("simulate", "Run the natural simulation pipeline (gravity, collision, settle, bake).",
                 {"mode": _p("enum", SIM_MODES), "quality": _p("enum", QUALITY_LEVELS), "frames": _p("int", mn=2,
                                                                                                        mx=2000),
                  "settle": _p("bool"), "bake": _p("bool"), "self_collision": _p("bool")},
                 (), frozenset({SIMULATE, SETTLE, BAKE}), None, None, _describe_sim, phase=3),
    OperationDef("settle", "Let the cloth fall onto the body under gravity until it stops moving.",
                 {"max_frames": _p("int", mn=2, mx=2000), "threshold": _p("float", mn=0.0, mx=0.1),
                  "apply": _p("enum", ("none", "shape_key")), "quality": _p("enum", QUALITY_LEVELS)},
                 (), frozenset({SETTLE}), None, None, _fixed("Settle under gravity"), phase=3),
    OperationDef("bake", "Bake the cloth cache.", {"frame_start": _p("int", mn=0), "frame_end": _p("int", mn=1)},
                 (), frozenset({BAKE}), None, None, _fixed("Bake simulation"), phase=4),
    OperationDef("reset", "Reset simulation (free bake, remove settled shape) or regenerate geometry.",
                 {"level": _p("enum", ("simulation", "geometry", "all"))}, (), frozenset({RESET}), None, None,
                 _fixed("Reset garment"), phase=4),
    OperationDef("inspect", "Return the garment's current state.", {}, (), frozenset({INSPECT}), None, None,
                 _fixed("Inspect garment"), mutates_scene=False, phase=4),
    OperationDef("set_fabric", "Change the fabric preset (e.g. 'heavy denim').",
                 {"fabric": _p("str_or_dict"), "overrides": _p("dict")}, ("fabric",),
                 frozenset({PHYSICS, MATERIAL, SIMULATION}), _set_fabric, _validate_set_fabric,
                 lambda s, p: [f"Apply {FabricSpec.from_value(p['fabric']).display} preset"], phase=1),
    OperationDef("set_fit", "Set an absolute fit level for the garment or some components.",
                 {"level": _p("str"), "target": TARGET}, ("level",), frozenset({GEOMETRY, SIMULATION}), _set_fit,
                 _validate_set_fit, lambda s, p: [f"Apply {normalize_fit_level(p['level'])} fit"
                                                  + (f" to {p['target']}" if p.get("target") else "")], phase=1),
    OperationDef("set_color", "Change the garment colour.", {"color": _p("any")}, ("color",),
                 frozenset({MATERIAL}), _set_color, _validate_color, lambda s, p: [f"Set color {p['color']}"],
                 phase=1),
    OperationDef("add_component", "Add a component (elastic_cuff, pocket, hood, zipper...) to a target.",
                 {"type": _p("str"), "target": TARGET, "name": _p("str"), "params": _p("dict")}, ("type",),
                 frozenset({GEOMETRY, PHYSICS, SIMULATION}), _add_component, _validate_add_component, _describe_add,
                 allow_extra=True, phase=1),
    OperationDef("remove_component", "Remove a component (and its children).", {"target": TARGET, "name": _p("str")},
                 ("target",), frozenset({GEOMETRY, PHYSICS, SIMULATION}), _remove, _validate_remove,
                 lambda s, p: [f"Remove {p['target']}"], phase=1),
    OperationDef("modify_component", "Change parameters of a component.", {"target": TARGET, "params": _p("dict")},
                 ("target",), frozenset({GEOMETRY, PHYSICS, SIMULATION}), _modify_component,
                 _validate_modify_component, lambda s, p: [f"Modify {p['target']}"], allow_extra=True, phase=1),
    OperationDef("modify_fit", "Make the garment (or a region/component) tighter or looser.",
                 {"direction": _p("str"), "region": _p("str"), "target": TARGET, "intensity": INTENSITY},
                 ("direction",), frozenset({GEOMETRY, SIMULATION}), _modify_fit, _validate_modify_fit,
                 _describe_modify_fit, phase=1),
    OperationDef("modify_length", "Lengthen/shorten the garment or sleeves/legs ('+10%', '-3cm').",
                 {"target": TARGET, "amount": _p("amount"), "direction": _p("str"), "intensity": INTENSITY,
                  "length": _p("str")}, (), frozenset({GEOMETRY, SIMULATION}), _modify_length,
                 _validate_modify_length, _describe_length, phase=1),
    OperationDef("roll", "Roll sleeves or trouser legs up.", {"target": TARGET, "turns": _p("int", mn=1, mx=4),
                                                              "direction": _p("enum", ("up",))},
                 (), frozenset({GEOMETRY, SIMULATION}), _roll, _validate_roll,
                 lambda s, p: [f"Roll up {p.get('target') or 'sleeves'}"], phase=1),
    OperationDef("unroll", "Unroll sleeves or legs.", {"target": TARGET}, (), frozenset({GEOMETRY, SIMULATION}),
                 _unroll, _validate_roll, lambda s, p: [f"Unroll {p.get('target') or 'sleeves'}"], phase=1),
    OperationDef("fold", "Fold (cuff) sleeve or trouser-leg openings once.", {"target": TARGET}, (),
                 frozenset({GEOMETRY, SIMULATION}), _fold, _validate_roll,
                 lambda s, p: [f"Fold {p.get('target') or 'openings'}"], phase=1),
    OperationDef("tuck", "Tuck a top in.", {}, (), frozenset({GEOMETRY, SIMULATION}), _tuck, _validate_tuck,
                 _fixed("Tuck in"), phase=1),
    OperationDef("untuck", "Untuck a top.", {}, (), frozenset({GEOMETRY, SIMULATION}), _untuck, _validate_tuck,
                 _fixed("Untuck"), phase=1),
    OperationDef("set_elastic", "Make a band elastic (cuffs, waistband, hem, hood) or add elastic cuffs to limbs.",
                 dict(ELASTIC, target=TARGET), ("target",), frozenset({GEOMETRY, PHYSICS, SIMULATION}), _set_elastic,
                 _validate_set_elastic, lambda s, p: [f"Set elastic on {p['target']}"], phase=1),
    OperationDef("pin", "Pin a component in place during simulation.", {"target": TARGET}, ("target",),
                 frozenset({PHYSICS, SIMULATION}), _pin, _validate_pin, lambda s, p: [f"Pin {p['target']}"], phase=1),
    OperationDef("unpin", "Remove pins.", {"target": TARGET}, (), frozenset({PHYSICS, SIMULATION}), _unpin, None,
                 _fixed("Unpin"), phase=1),
    OperationDef("enable_self_collision", "Enable cloth self collision with a preset (draft/preview/production/off).",
                 {"preset": _p("enum", tuple(SELF_COLLISION_PRESETS))}, (), frozenset({PHYSICS, SIMULATION}),
                 _self_collision, None, lambda s, p: [f"Self collision: {p.get('preset') or 'preview'}"], phase=1),
    OperationDef("generate_wrinkles", "Wrinkle enhancement via a provider that supports it (optional).",
                 {"intensity": INTENSITY, "optional": _p("bool")}, (), frozenset({WRINKLES}), None, None,
                 _fixed("Generate wrinkles (if a provider supports it)"), phase=4),
]
for _d in _BUILTIN:
    register_operation(_d)


# ----------------------------------------------------------------------------
# garment.modify(**kwargs) -> operations
# ----------------------------------------------------------------------------
POSITIONS = {"rolled_up": "roll", "rolled": "roll", "roll": "roll", "roll_up": "roll", "up": "roll",
             "unrolled": "unroll", "down": "unroll", "unroll": "unroll", "folded": "fold", "cuffed": "fold",
             "tucked": "tuck", "tucked_in": "tuck", "untucked": "untuck"}


def modify_kwargs_to_operations(**kwargs: Any) -> List[Dict[str, Any]]:
    """Translate ``garment.modify(...)`` keyword arguments into operation dicts."""
    allowed = {"length", "fit", "region", "component", "target", "position", "fabric", "color", "colour", "elastic",
               "intensity"}
    unknown = sorted(set(kwargs) - allowed)
    if unknown:
        raise GarmentError("INVALID_PARAM", f"modify() got unknown argument(s) {unknown}.",
                           suggestions=sorted(allowed))
    target = kwargs.get("component") or kwargs.get("target")
    region = kwargs.get("region")
    ops: List[Dict[str, Any]] = []
    if kwargs.get("fabric") is not None:
        ops.append({"operation": "set_fabric", "fabric": kwargs["fabric"]})
    color = kwargs.get("color", kwargs.get("colour"))
    if color is not None:
        ops.append({"operation": "set_color", "color": color})
    if kwargs.get("fit") is not None:
        fit = kwargs["fit"]
        if fit_direction(fit) is not None:
            op = {"operation": "modify_fit", "direction": normalize(fit)}
            if region:
                op["region"] = region
            if target:
                op["target"] = target
            if kwargs.get("intensity") is not None:
                op["intensity"] = kwargs["intensity"]
            ops.append(op)
        elif normalize_fit_level(fit) is not None:
            op = {"operation": "set_fit", "level": normalize_fit_level(fit)}
            if target:
                op["target"] = target
            ops.append(op)
        else:
            raise GarmentError("INVALID_PARAM", f"Unknown fit '{fit}'.", path="fit",
                               suggestions=list(FIT_COMPARATIVES) + FIT_LEVELS)
    if kwargs.get("length") is not None:
        length = kwargs["length"]
        op = {"operation": "modify_length", "target": target or "garment"}
        try:
            parse_amount(length)
            op["amount"] = length
        except GarmentError:
            n = normalize(length)
            if n in ("longer", "shorter"):
                op["direction"] = n
            else:
                op["length"] = length
        if kwargs.get("intensity") is not None:
            op["intensity"] = kwargs["intensity"]
        ops.append(op)
    if kwargs.get("position") is not None:
        pos = normalize(kwargs["position"])
        if pos not in POSITIONS:
            raise GarmentError("INVALID_PARAM", f"Unknown position '{kwargs['position']}'.", path="position",
                               suggestions=sorted(POSITIONS))
        op = {"operation": POSITIONS[pos]}
        if target and POSITIONS[pos] in ("roll", "unroll", "fold"):
            op["target"] = target
        ops.append(op)
    if kwargs.get("elastic") is not None:
        e = kwargs["elastic"]
        op = {"operation": "set_elastic", "target": target or "cuffs"}
        op.update(e if isinstance(e, dict) else {"strength": e})
        ops.append(op)
    if region and not any(o["operation"] == "modify_fit" for o in ops):
        raise GarmentError("INVALID_PARAM", "'region' is only meaningful together with a fit change "
                                            "(e.g. fit='tighter').", path="region")
    if not ops:
        raise GarmentError("MISSING_PARAM", "modify() needs at least one change.", suggestions=sorted(allowed))
    return ops

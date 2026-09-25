"""Spec validation: reports ALL problems at once, never mutates anything."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .component_system import resolve_component_type, validate_component_params
from .errors import GarmentError, Issue
from .fabric_presets import resolve_fabric
from .fit_system import EASE_KEYS, KEY_ALIASES, resolve_ease
from .garment_spec import SIM_MODES, GarmentSpec
from .garment_types import list_garment_types
from .quality import QUALITY_LEVELS, normalize_quality
from .vocabulary import FIT_LEVELS, normalize_fit_level, parse_color, suggest


@dataclass
class ValidationReport:
    errors: List[Issue] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, code: str, message: str, path: str = None, suggestions=None) -> None:
        self.errors.append(Issue(code, message, "error", path, list(suggestions or [])))

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "errors": [e.to_dict() for e in self.errors], "warnings": list(self.warnings)}

    def raise_if_invalid(self) -> None:
        if not self.ok:
            first = self.errors[0]
            raise GarmentError("VALIDATION_FAILED", f"Garment spec is invalid: {first.message}",
                               suggestions=first.suggestions, details=self.to_dict(), path=first.path)


def validate_spec(spec: GarmentSpec) -> ValidationReport:
    r = ValidationReport()
    gdef = spec.type_def
    if gdef is None:
        r.error("UNKNOWN_GARMENT_TYPE", f"Unknown garment type '{spec.type}'.", "type",
                suggest(spec.type, list_garment_types()))
    elif gdef.support == "experimental":
        r.warnings.append(f"Garment type '{gdef.name}' is experimental in v1: the native proxy geometry is coarse.")
    for key in spec.unknown_keys:
        r.warnings.append(f"Ignored unknown spec key '{key}'.")

    # fit ------------------------------------------------------------------
    fit_ok = normalize_fit_level(spec.fit.level) is not None
    if not fit_ok:
        r.error("UNKNOWN_FIT", f"Unknown fit '{spec.fit.level}'.", "fit", suggest(spec.fit.level, FIT_LEVELS))
    for comp, lvl in spec.fit.component_levels.items():
        if normalize_fit_level(lvl) is None:
            r.error("UNKNOWN_FIT", f"Unknown fit '{lvl}' for component '{comp}'.", f"fit.component_levels.{comp}",
                    suggest(lvl, FIT_LEVELS))
            fit_ok = False
        if spec.get_component(comp) is None:
            r.error("TARGET_NOT_FOUND", f"Fit override for unknown component '{comp}'.", f"fit.component_levels.{comp}")
    for key in spec.fit.overrides:
        k = key.split(":", 1)[-1]
        if KEY_ALIASES.get(k, k) not in EASE_KEYS:
            r.error("INVALID_PARAM", f"Unknown fit measurement '{k}'.", f"fit.overrides.{key}",
                    suggest(k, EASE_KEYS))
    if not 0.7 <= float(spec.fit.scale) <= 1.5:
        r.error("INVALID_PARAM", f"fit.scale {spec.fit.scale} must be within 0.7..1.5.", "fit.scale")

    # fabric ---------------------------------------------------------------
    fabric = None
    try:
        fabric = resolve_fabric(spec.fabric)
    except GarmentError as err:
        r.error(err.code, err.message, err.path or "fabric", err.suggestions)

    # colour / length --------------------------------------------------------
    try:
        parse_color(spec.color)
    except GarmentError as err:
        r.error(err.code, err.message, "color", err.suggestions)
    if gdef is not None and spec.length is not None and spec.length not in gdef.allowed_lengths():
        r.error("INVALID_LENGTH", f"Length '{spec.length}' is not valid for a {gdef.category} garment.", "length",
                gdef.allowed_lengths())
    for k in ("percent", "meters"):
        if not isinstance(spec.length_adjust.get(k, 0.0), (int, float)):
            r.error("INVALID_PARAM", f"length_adjust.{k} must be a number.", f"length_adjust.{k}")
    if abs(spec.length_adjust.get("percent", 0.0)) > 60:
        r.error("INVALID_PARAM", "length_adjust.percent must be within -60..60.", "length_adjust.percent")

    # components ---------------------------------------------------------------
    names = [c.name for c in spec.components]
    for dup in sorted({n for n in names if names.count(n) > 1}):
        r.error("DUPLICATE_COMPONENT", f"Component name '{dup}' is used more than once.", "components")
    if gdef is not None and not any(c.type == "body" for c in spec.components):
        r.error("MISSING_COMPONENT", "A garment needs a 'body' component.", "components")
    for c in spec.components:
        path = f"components.{c.name}"
        ctype = resolve_component_type(c.type)
        if ctype is None:
            r.error("UNKNOWN_COMPONENT", f"Unknown component type '{c.type}'.", path, suggest(c.type, _ctypes()))
            continue
        if gdef is not None and gdef.category not in ctype.categories:
            r.error("INVALID_COMPONENT_FOR_TYPE", f"A {ctype.name} cannot be added to a {gdef.display_name} "
                                                  f"({gdef.category} garment).", path)
        if c.target:
            parent = spec.get_component(c.target)
            if parent is None:
                r.error("TARGET_NOT_FOUND", f"Component '{c.name}' targets missing component '{c.target}'.",
                        f"{path}.target", names)
            elif ctype.target_types and parent.type not in ctype.target_types:
                r.error("INVALID_TARGET", f"'{c.name}' ({ctype.name}) cannot attach to '{c.target}' ({parent.type}).",
                        f"{path}.target", list(ctype.target_types))
        elif ctype.target_required:
            r.error("MISSING_PARAM", f"Component '{c.name}' ({ctype.name}) needs a target.", f"{path}.target")
        for issue in validate_component_params(ctype, c.params, f"{path}.params"):
            r.errors.append(issue)
        rolled = c.state.get("rolled", 0)
        if not isinstance(rolled, int) or not 0 <= rolled <= 4:
            r.error("INVALID_PARAM", "rolled must be an integer 0..4.", f"{path}.state.rolled")
    for seam in spec.disabled_seams:
        if ":" not in str(seam):
            r.error("INVALID_PARAM", f"Seam '{seam}' must look like 'left_sleeve:body'.", "disabled_seams")

    # simulation -----------------------------------------------------------------
    sim = spec.simulation
    if normalize_quality(sim.quality) is None:
        r.error("INVALID_PARAM", f"Unknown simulation quality '{sim.quality}'.", "simulation.quality",
                suggest(sim.quality, QUALITY_LEVELS))
    if sim.mode not in SIM_MODES:
        r.error("INVALID_PARAM", f"Unknown simulation mode '{sim.mode}'.", "simulation.mode", list(SIM_MODES))
    if not isinstance(sim.frame_start, int) or (sim.frame_end is not None and (
            not isinstance(sim.frame_end, int) or sim.frame_end <= sim.frame_start)):
        r.error("INVALID_PARAM", "simulation frame range is invalid.", "simulation.frame_end")
    for p in sim.pin:
        if spec.get_component(p) is None:
            r.error("TARGET_NOT_FOUND", f"Pin target '{p}' is not a component.", "simulation.pin", names)
    off = spec.placement.get("offset", [0, 0, 0])
    if not (isinstance(off, (list, tuple)) and len(off) == 3 and all(isinstance(v, (int, float)) for v in off)):
        r.error("INVALID_PARAM", "placement.offset must be [x, y, z].", "placement.offset")
    if spec.tucked and gdef is not None and gdef.category != "top":
        r.error("INVALID_FOR_TYPE", "Only tops can be tucked.", "tucked")

    # domain warnings --------------------------------------------------------------
    if fit_ok and fabric is not None:
        ease = resolve_ease(spec.fit, "body")
        keys = ("waist_ease", "hip_ease") if gdef is not None and gdef.category == "bottom" else \
            ("chest_ease", "waist_ease", "hip_ease")
        neg = {k: ease[k] for k in keys if ease[k] < 0}
        if neg and fabric.stretch in ("very_low", "low"):
            where = ", ".join(f"{k.replace('_ease', '')} {v:g} cm" for k, v in neg.items())
            r.warnings.append(f"Negative ease ({where}) with low-stretch fabric '{fabric.name}': the garment is "
                              "smaller than the body and will be shrunk onto it; expect tension or instability. "
                              "Consider a stretch fabric or a looser fit.")
    return r


def _ctypes():
    from .component_system import list_component_types
    return list_component_types()

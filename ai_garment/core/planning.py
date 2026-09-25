"""Plans: what WOULD happen, computed without touching Blender.

``registry`` arguments are duck-typed (``select(required=...)``) so core does
not import providers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .errors import Issue
from .fabric_presets import resolve_fabric
from .garment_spec import GarmentSpec
from .physics_mapping import map_fabric_to_native
from .quality import get_quality, normalize_quality
from .validation import validate_spec

MODE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "natural": {"settle": True, "bake": True, "self_collision": True, "quality": None},
    "production": {"settle": True, "bake": True, "self_collision": True, "quality": "production"},
    "preview": {"settle": True, "bake": False, "self_collision": False, "quality": "preview"},
    "draft": {"settle": True, "bake": False, "self_collision": False, "quality": "draft"},
    "static": {"settle": False, "bake": False, "self_collision": False, "quality": None},
}


@dataclass
class PlanStep:
    id: str
    description: str
    provider: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "description": self.description, "provider": self.provider, "params": self.params}


@dataclass
class Plan:
    valid: bool = True
    executable: bool = True
    provider: Optional[str] = None
    steps: List[PlanStep] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[Issue] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)

    @property
    def operations(self) -> List[str]:
        return [s.description for s in self.steps]

    def add(self, sid: str, description: str, **params: Any) -> None:
        self.steps.append(PlanStep(sid, description, self.provider, params))

    def to_dict(self) -> Dict[str, Any]:
        return {"valid": self.valid, "executable": self.executable, "provider": self.provider,
                "operations": self.operations, "steps": [s.to_dict() for s in self.steps],
                "warnings": list(self.warnings), "errors": [e.to_dict() for e in self.errors], "data": self.data}


def resolve_simulation_settings(spec: GarmentSpec, mode: Optional[str] = None, quality: Optional[str] = None,
                                **overrides: Any) -> Dict[str, Any]:
    sim = spec.simulation
    mode = (mode or sim.mode or "natural").lower()
    if mode not in MODE_DEFAULTS:
        mode = "natural"
    d = MODE_DEFAULTS[mode]
    q = normalize_quality(quality) or d["quality"] or normalize_quality(sim.quality) or "preview"
    qp = get_quality(q)
    self_col = overrides.get("self_collision")
    if self_col is None:
        self_col = sim.self_collision if sim.self_collision is not None else d["self_collision"]
    frames = overrides.get("frames")
    frame_start = int(sim.frame_start)
    frame_end = int(sim.frame_end) if sim.frame_end else frame_start + (int(frames) if frames else qp.bake_frames)
    return {
        "mode": mode, "quality": qp.name, "gravity": bool(sim.gravity), "collision": bool(sim.collision),
        "self_collision": bool(self_col),
        "self_collision_preset": spec.metadata.get("self_collision_preset") or ("production" if qp.name in (
            "medium", "production") else qp.name),
        "settle": d["settle"] if overrides.get("settle") is None else bool(overrides["settle"]),
        "bake": (sim.bake if sim.bake is not None else d["bake"]) if overrides.get("bake") is None
        else bool(overrides["bake"]),
        "frame_start": frame_start, "frame_end": frame_end,
        "settle_frames": min(qp.settle_frames, frame_end - frame_start),
        "settle_window": qp.settle_window, "settle_threshold": qp.settle_threshold,
        "use_disk_cache": qp.use_disk_cache, "pin": list(sim.pin),
    }


def plan_simulation(spec: GarmentSpec, mode: Optional[str] = None, quality: Optional[str] = None,
                    provider: Optional[str] = None, **overrides: Any) -> Plan:
    s = resolve_simulation_settings(spec, mode, quality, **overrides)
    plan = Plan(provider=provider, data=s)
    try:
        fabric = resolve_fabric(spec.fabric)
        physics = map_fabric_to_native(fabric, s["quality"], self_collision=s["self_collision"])
    except Exception as err:  # reported as a plan error, never raised from planning
        plan.valid = False
        plan.errors.append(Issue("INVALID_FABRIC", str(err)))
        return plan
    if s["gravity"]:
        plan.add("gravity", "Enable scene gravity")
    if s["collision"]:
        plan.add("collision", "Enable avatar collision (proxy copy of the body)")
    if s["self_collision"]:
        plan.add("self_collision", f"Enable self collision ({s['self_collision_preset']})")
    plan.add("fabric_settings", f"Apply {fabric.display_name} cloth settings ({s['quality']} quality)",
             **physics["cloth"])
    if any(c.type in ("sleeve", "leg", "hood", "pocket", "cargo_pocket", "kangaroo_pocket") for c in spec.components):
        plan.add("sewing", "Enable sewing springs")
    if any(c.type in ("elastic_cuff", "elastic_waistband", "elastic", "drawstring") or
           isinstance(c.params.get("elastic"), dict) for c in spec.components):
        plan.add("elastic", "Apply elastic shrink / stiffness groups")
    if s["pin"]:
        plan.add("pinning", f"Pin {', '.join(s['pin'])}")
    plan.add("cache", f"Configure cloth cache frames {s['frame_start']}-{s['frame_end']}")
    if s["settle"]:
        plan.add("settling", f"Settle under gravity (up to {s['settle_frames']} frames)")
    plan.add("diagnostics", "Check penetration / stability")
    if s["bake"]:
        plan.add("bake", "Bake simulation")
    return plan


def plan_creation(spec: GarmentSpec, registry: Any = None, avatar_available: Optional[bool] = None) -> Plan:
    report = validate_spec(spec)
    plan = Plan(valid=report.ok, errors=list(report.errors), warnings=list(report.warnings))
    plan.data = {"garment": spec.type, "fit": spec.fit.level, "fabric": spec.fabric.name,
                 "fabric_qualifiers": list(spec.fabric.qualifiers), "color": spec.color, "length": spec.length,
                 "components": [c.name for c in spec.components]}
    if registry is None:
        plan.executable = False
        plan.warnings.append("No provider registry supplied; provider not selected.")
    else:
        sel = registry.select(required={"create_garment"})
        plan.warnings.extend(sel.warnings)
        if sel.provider is None:
            plan.executable = False
            plan.warnings.append(sel.error.message if sel.error else "No garment provider available.")
        else:
            plan.provider = sel.provider.name
    if not plan.valid:
        plan.executable = False
        return plan
    plan.add("create", f"Create {spec.display_name}", type=spec.type)
    plan.add("fit_level", f"Apply {spec.fit.level} fit", level=spec.fit.level)
    plan.add("fabric", f"Apply {spec.fabric.display} preset", fabric=spec.fabric.name)
    plan.add("color", f"Set color {spec.color}")
    extras = [c for c in spec.components if c.type in ("elastic_cuff", "cuff")]
    if extras:
        plan.add("cuffs", "Create sleeve cuffs" if any("sleeve" in (c.target or "") for c in extras)
                 else "Create ankle cuffs")
    if avatar_available is False:
        plan.warnings.append("No avatar available: garment would be built for default proportions.")
    return plan

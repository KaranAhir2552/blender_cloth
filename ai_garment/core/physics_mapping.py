"""Map qualitative fabric characteristics + quality level to native Blender
cloth parameters.

The numbers start from Blender's bundled cloth presets (Cotton, Denim,
Leather, Rubber, Silk) and interpolate between them. They are ARTISTIC
defaults, not measured material constants. Keys emitted here are exactly the
Blender 4.2 RNA attribute names (see blender/api_contract.py; checked by a
static test).
"""
from __future__ import annotations

from typing import Any, Dict

from .fabric_presets import ResolvedFabric
from .quality import get_quality

MASS = {"ultralight": 0.12, "light": 0.2, "medium": 0.3, "heavy": 0.6, "very_heavy": 1.0}
# stretch level -> tension/compression stiffness (inverse relation)
TENSION = {"very_low": 80.0, "low": 30.0, "medium": 15.0, "high": 8.0, "very_high": 4.0}
BENDING = {"very_soft": 0.05, "soft": 0.5, "medium": 3.0, "stiff": 10.0, "very_stiff": 60.0}
DRAPE_BEND_MULT = {"very_low": 1.5, "low": 1.25, "medium": 1.0, "high": 0.8, "very_high": 0.6}
AIR_DAMPING = {"very_low": 0.6, "low": 0.8, "medium": 1.0, "high": 1.2, "very_high": 1.5}
DAMPING = {"very_low": 0.5, "low": 2.0, "medium": 5.0, "high": 15.0, "very_high": 25.0}
FRICTION = {"very_low": 1.0, "low": 3.0, "medium": 5.0, "high": 10.0, "very_high": 20.0}

CLOTH_KEYS = ("quality", "mass", "air_damping", "tension_stiffness", "compression_stiffness", "shear_stiffness",
              "bending_stiffness", "tension_damping", "compression_damping", "shear_damping", "bending_damping",
              "bending_model")
CLOTH_COLLISION_KEYS = ("collision_quality", "use_collision", "distance_min", "use_self_collision",
                        "self_distance_min", "self_friction")
COLLIDER_KEYS = ("thickness_outer", "cloth_friction")
PHYSICS_OVERRIDE_KEYS = frozenset(k for k in CLOTH_KEYS + CLOTH_COLLISION_KEYS + COLLIDER_KEYS
                                  if k not in ("bending_model", "use_collision", "use_self_collision"))


def map_fabric_to_native(fabric: ResolvedFabric, quality: str = "preview", unit_scale: float = 1.0,
                         self_collision: Any = None) -> Dict[str, Any]:
    """Return {"cloth": {...}, "cloth_collision": {...}, "collider": {...}, "render": {...}}.

    ``unit_scale`` is metres per scene unit (0.1 for a decimetre-scale import);
    distances are converted to scene units.
    """
    q = get_quality(quality)
    to_su = 1.0 / unit_scale if unit_scale else 1.0
    tension = TENSION[fabric.stretch]
    knit = fabric.stretch in ("high", "very_high")
    bending = BENDING[fabric.bend] * DRAPE_BEND_MULT[fabric.drape]
    damp = DAMPING[fabric.damping]
    steps = q.cloth_steps
    if tension >= 30.0 or bending >= 10.0:
        steps += 2  # stiff materials need more solver steps to stay stable
    if tension >= 80.0 or bending >= 60.0:
        steps += 2
    thickness_m = fabric.thickness_mm / 1000.0
    distance = max(q.collision_distance, thickness_m * 2.0)
    use_self = q.self_collision if self_collision is None else bool(self_collision)

    cloth = {
        "quality": int(steps),
        "mass": MASS[fabric.weight_class],
        "air_damping": AIR_DAMPING[fabric.drape],
        "tension_stiffness": tension,
        "compression_stiffness": tension,
        "shear_stiffness": tension * (0.5 if knit else 1.0),
        "bending_stiffness": round(bending, 4),
        "tension_damping": damp,
        "compression_damping": damp,
        "shear_damping": damp,
        "bending_damping": round(damp * 0.1, 4),
        "bending_model": "ANGULAR",
    }
    cloth_collision = {
        "collision_quality": int(q.collision_steps),
        "use_collision": True,
        "distance_min": distance * to_su,
        "use_self_collision": use_self,
        "self_distance_min": max(q.self_distance, thickness_m * 2.0) * to_su,
        "self_friction": FRICTION[fabric.friction],
    }
    collider = {"thickness_outer": q.collider_thickness * to_su, "cloth_friction": FRICTION[fabric.friction]}
    for key, value in fabric.physics_overrides.items():
        for section in (cloth, cloth_collision, collider):
            if key in section:
                section[key] = int(value) if key in ("quality", "collision_quality") else float(value)
    return {
        "cloth": cloth,
        "cloth_collision": cloth_collision,
        "collider": collider,
        "render": {"solidify_thickness": max(thickness_m, 0.0015) * to_su,
                   "subdivision_viewport": q.subdivision_viewport, "subdivision_render": q.subdivision_render},
        "fabric": fabric.name,
        "quality": q.name,
        "artistic": True,
        "notes": ["Artistic preset mapping derived from Blender's bundled cloth presets; not measured material data."],
    }

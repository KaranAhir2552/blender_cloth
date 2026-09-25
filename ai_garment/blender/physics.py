"""Apply mapped physics values to native Cloth / Collision settings."""
from __future__ import annotations

from typing import Any, Dict, Optional

SEWING_FORCE = 5.0  # ClothSettings.sewing_force_max; artistic default


def apply_cloth(cloth_mod: Any, mapping: Dict[str, Any], physics: Dict[str, Any], gravity: bool = True) -> None:
    s = cloth_mod.settings
    for key, value in mapping["cloth"].items():
        setattr(s, key, value)
    cs = cloth_mod.collision_settings
    for key, value in mapping["cloth_collision"].items():
        setattr(cs, key, value)
    s.use_sewing_springs = bool(physics.get("sewing"))
    s.sewing_force_max = SEWING_FORCE if physics.get("sewing") else 0.0
    shrink_group = physics.get("shrink_group") or ""
    s.vertex_group_shrink = shrink_group
    s.shrink_min = float(physics.get("shrink_min", 0.0))
    s.shrink_max = float(physics.get("shrink_max", 0.0)) if shrink_group else 0.0
    stiff_group = physics.get("stiff_group") or ""
    s.vertex_group_structural_stiffness = stiff_group
    factor = float(physics.get("stiffness_max_factor", 1.0)) if stiff_group else 1.0
    s.tension_stiffness_max = s.tension_stiffness * factor
    s.compression_stiffness_max = s.compression_stiffness * factor
    s.vertex_group_mass = physics.get("pin_group") or ""
    s.pin_stiffness = 1.0
    s.effector_weights.gravity = 1.0 if gravity else 0.0


def apply_self_collision(cloth_mod: Any, preset: Optional[Dict[str, Any]], unit_scale: float = 1.0) -> None:
    cs = cloth_mod.collision_settings
    if preset is None:
        cs.use_self_collision = False
        return
    cs.use_self_collision = True
    cs.self_distance_min = preset["self_distance_min"] / (unit_scale or 1.0)
    cs.self_friction = preset["self_friction"]
    cs.collision_quality = max(int(cs.collision_quality), int(preset["collision_quality_min"]))


def apply_collider(obj: Any, collider: Dict[str, Any], margin: Optional[float] = None) -> None:
    c = obj.collision
    c.use = True
    c.thickness_outer = float(margin if margin is not None else collider["thickness_outer"])
    c.cloth_friction = float(collider["cloth_friction"])


def cloth_summary(cloth_mod: Any) -> Dict[str, Any]:
    s, cs, pc = cloth_mod.settings, cloth_mod.collision_settings, cloth_mod.point_cache
    return {"quality": s.quality, "mass": s.mass, "tension_stiffness": s.tension_stiffness,
            "bending_stiffness": s.bending_stiffness, "air_damping": s.air_damping,
            "use_sewing_springs": s.use_sewing_springs, "shrink_group": s.vertex_group_shrink,
            "shrink_min": s.shrink_min, "shrink_max": s.shrink_max, "pin_group": s.vertex_group_mass,
            "collision_distance": cs.distance_min, "self_collision": cs.use_self_collision,
            "self_distance": cs.self_distance_min, "cache": {"frame_start": pc.frame_start,
                                                             "frame_end": pc.frame_end, "baked": pc.is_baked}}

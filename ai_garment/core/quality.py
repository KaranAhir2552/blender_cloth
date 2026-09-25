"""Simulation quality presets.

Nothing here is "maximum quality": production is a sensible upper default,
users/Claude can override individual values. Distances are metres.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, Optional

from .errors import GarmentError
from .vocabulary import normalize, suggest

QUALITY_LEVELS = ["draft", "preview", "medium", "production"]
QUALITY_ALIASES = {"fast": "draft", "quick": "draft", "low": "preview", "normal": "medium", "default": "preview",
                   "high": "production", "final": "production", "realistic": "production", "render": "production"}


@dataclass(frozen=True)
class QualityPreset:
    name: str
    cloth_steps: int            # ClothSettings.quality
    collision_steps: int        # ClothCollisionSettings.collision_quality
    self_collision: bool        # default self collision for this level
    ring_spacing: float         # target distance between garment rings (m)
    segments_torso: int         # vertices around torso tubes
    segments_limb: int          # vertices around sleeve / leg tubes
    settle_frames: int          # max frames for settling
    settle_window: int          # consecutive calm frames needed
    settle_threshold: float     # mean vertex motion per frame considered "calm" (m)
    subdivision_viewport: int
    subdivision_render: int
    collision_distance: float   # cloth <-> body distance (m)
    self_distance: float        # cloth <-> cloth distance (m)
    collider_thickness: float   # body collision margin, CollisionSettings.thickness_outer (m)
    bake_frames: int
    use_disk_cache: bool

    def to_dict(self) -> Dict:
        return asdict(self)


_PRESETS = {
    "draft": QualityPreset("draft", 4, 2, False, 0.06, 20, 10, 25, 3, 0.002, 0, 1, 0.015, 0.015, 0.015, 40, False),
    "preview": QualityPreset("preview", 5, 3, False, 0.045, 28, 14, 40, 4, 0.0015, 1, 1, 0.012, 0.012, 0.012, 60,
                             False),
    "medium": QualityPreset("medium", 8, 4, True, 0.03, 36, 16, 60, 5, 0.001, 1, 2, 0.010, 0.010, 0.010, 80, False),
    "production": QualityPreset("production", 12, 5, True, 0.02, 48, 20, 90, 6, 0.0007, 1, 2, 0.008, 0.008, 0.008,
                                120, True),
}

# Self-collision presets requested by the brief (draft / preview / production).
SELF_COLLISION_PRESETS = {
    "off": None,
    "draft": {"self_distance_min": 0.015, "self_friction": 5.0, "collision_quality_min": 2},
    "preview": {"self_distance_min": 0.012, "self_friction": 5.0, "collision_quality_min": 3},
    "medium": {"self_distance_min": 0.010, "self_friction": 5.0, "collision_quality_min": 4},
    "production": {"self_distance_min": 0.008, "self_friction": 5.0, "collision_quality_min": 5},
}


def normalize_quality(name: Optional[str]) -> Optional[str]:
    if name is None:
        return None
    n = normalize(name)
    n = QUALITY_ALIASES.get(n, n)
    return n if n in _PRESETS else None


def get_quality(name: Optional[str]) -> QualityPreset:
    n = normalize_quality(name or "preview")
    if n is None:
        raise GarmentError("INVALID_PARAM", f"Unknown simulation quality '{name}'.", path="simulation.quality",
                           suggestions=suggest(name, QUALITY_LEVELS))
    return _PRESETS[n]


def cap_quality(name: str, cap: Optional[str]) -> str:
    """Lower ``name`` to ``cap`` if it exceeds it (used for fast test/preview runs)."""
    if not cap:
        return name
    q, c = get_quality(name).name, get_quality(cap).name
    return q if QUALITY_LEVELS.index(q) <= QUALITY_LEVELS.index(c) else c


def self_collision_preset(name: str) -> Optional[Dict]:
    n = normalize(name)
    n = {"none": "off", "disabled": "off", "false": "off", "low": "draft", "high": "production"}.get(n, n)
    if n not in SELF_COLLISION_PRESETS:
        raise GarmentError("INVALID_PARAM", f"Unknown self-collision preset '{name}'.", path="preset",
                           suggestions=list(SELF_COLLISION_PRESETS))
    preset = SELF_COLLISION_PRESETS[n]
    return dict(preset) if preset else None

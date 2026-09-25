"""Pure analysis of simulation results (inputs are plain numbers from the Blender layer)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .errors import COLLISION_SUGGESTIONS, MSG_COLLISION_ISSUE, Issue


@dataclass
class Diagnostic:
    name: str
    issues: List[Issue] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "issues": [i.to_dict() for i in self.issues], **self.data}


def analyze_penetration(signed_distances: Sequence[float], tolerance: float = 0.002,
                        max_fraction: float = 0.005) -> Diagnostic:
    """Signed distances (garment vertex -> body surface; negative = inside the body)."""
    d = [x for x in signed_distances if x is not None and not math.isinf(x)]
    n = len(d)
    inside = [x for x in d if x < -tolerance]
    frac = len(inside) / n if n else 0.0
    diag = Diagnostic("penetration", data={"vertices": n, "penetrating": len(inside),
                                           "penetrating_fraction": round(frac, 4),
                                           "max_depth": round(-min(inside), 5) if inside else 0.0})
    if n and frac > max_fraction:
        severity = "error" if frac > 0.05 else "warning"
        diag.issues.append(Issue("COLLISION_ISSUE", MSG_COLLISION_ISSUE, severity, None, list(COLLISION_SUGGESTIONS)))
    return diag


def analyze_settling(mean_displacements: Sequence[float], threshold: float, window: int = 3) -> Diagnostic:
    """Settled when ``window`` consecutive per-frame mean displacements are below ``threshold``.
    ``settled_at`` is the index at which the calm window completes."""
    calm = 0
    settled_at: Optional[int] = None
    for i, v in enumerate(mean_displacements):
        calm = calm + 1 if v < threshold else 0
        if calm >= window:
            settled_at = i
            break
    diag = Diagnostic("settling", data={"settled": settled_at is not None, "settled_at": settled_at,
                                        "frames": len(mean_displacements),
                                        "final_motion": mean_displacements[-1] if mean_displacements else 0.0,
                                        "threshold": threshold})
    if settled_at is None:
        diag.issues.append(Issue("NOT_SETTLED", "Cloth did not settle within the frame budget.", "warning", None,
                                 ["increase settle frames", "increase air damping or fabric damping",
                                  "check for collision jitter (increase collision margin)"]))
    return diag


def analyze_stability(garment_bbox: Tuple[Sequence[float], Sequence[float]],
                      avatar_bbox: Tuple[Sequence[float], Sequence[float]], has_nan: bool = False,
                      max_ratio: float = 3.0) -> Diagnostic:
    gmin, gmax = garment_bbox
    amin, amax = avatar_bbox
    gdiag = math.dist(gmin, gmax)
    adiag = math.dist(amin, amax) or 1.0
    diag = Diagnostic("stability", data={"garment_extent": round(gdiag, 4), "avatar_extent": round(adiag, 4),
                                         "ratio": round(gdiag / adiag, 3), "has_nan": has_nan})
    if has_nan or gdiag / adiag > max_ratio:
        diag.issues.append(Issue("SIMULATION_UNSTABLE", "Simulation looks unstable (garment exploded or produced "
                                 "invalid coordinates).", "error", None,
                                 ["increase simulation quality steps", "reduce fabric stiffness",
                                  "check the scene scale", "reduce elastic tension"]))
    elif gmax[2] < amin[2] + 0.05 * (amax[2] - amin[2]):
        diag.issues.append(Issue("GARMENT_FELL", "Garment fell to the floor instead of staying on the body.",
                                 "error", None, ["enable avatar collision", "check the garment was fitted",
                                                 "add a pin group or elastic waistband"]))
    return diag

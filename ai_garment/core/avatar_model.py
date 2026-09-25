"""Avatar model: landmarks, measurements and body regions of a human character.

Pure Python. The Blender layer (blender/avatar_scan.py) extracts raw data
(world-space vertices, pose-bone heads/tails, vertex-group names, custom
properties) and calls :func:`build_avatar_model`.

Priority of information sources:
  1. explicit metadata (``ai_garment_avatar`` custom property / API argument)
  2. armature bones (MakeHuman/MPFB default rig, MPFB game_engine rig,
     Rigify, Mixamo; generic name heuristics)
  3. mesh cross-sections at landmark heights (convex hull = tape measure)
  4. anthropometric ratios of the height (Drillis & Contini) as fallback

All values inside AvatarModel are METRES; ``unit_scale`` (metres per scene
unit) converts back to the scene.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .errors import GarmentError
from .garment_types import resolve_garment_type
from .vocabulary import normalize

Vec3 = Tuple[float, float, float]

BODY_REGIONS = ["head", "neck", "shoulders", "chest", "waist", "hips", "left_arm", "right_arm", "left_leg",
                "right_leg"]

# Heights as fractions of stature (Drillis & Contini, approximate).
HEIGHT_RATIOS = {"head_top": 1.0, "head": 0.936, "neck_base": 0.845, "shoulder": 0.818, "chest": 0.72,
                 "elbow": 0.63, "waist": 0.62, "hip_joint": 0.53, "hips": 0.515, "wrist": 0.485, "crotch": 0.47,
                 "knee": 0.285, "ankle": 0.039, "floor": 0.0}
# Circumferences / lengths as fractions of stature (approximate adult averages).
MEASURE_RATIOS = {"chest_circumference": 0.53, "waist_circumference": 0.46, "hip_circumference": 0.56,
                  "neck_circumference": 0.21, "shoulder_width": 0.259, "arm_length": 0.332,
                  "upper_arm_circumference": 0.17, "wrist_circumference": 0.095, "thigh_circumference": 0.32,
                  "knee_circumference": 0.21, "ankle_circumference": 0.13, "inseam": 0.45}
METADATA_ALIASES = {"chest": "chest_circumference", "bust": "chest_circumference", "waist": "waist_circumference",
                    "hip": "hip_circumference", "hips": "hip_circumference", "neck": "neck_circumference",
                    "shoulders": "shoulder_width", "shoulder": "shoulder_width", "arm": "arm_length",
                    "sleeve": "arm_length", "upper_arm": "upper_arm_circumference",
                    "bicep": "upper_arm_circumference", "biceps": "upper_arm_circumference",
                    "wrist": "wrist_circumference", "thigh": "thigh_circumference", "knee": "knee_circumference",
                    "ankle": "ankle_circumference", "leg": "inseam", "stature": "height"}
UNIT_FACTORS = {"m": 1.0, "meters": 1.0, "metres": 1.0, "cm": 0.01, "mm": 0.001, "in": 0.0254, "inch": 0.0254,
                "inches": 0.0254, "dm": 0.1}

# --- rig signatures (normalised base names after side stripping) --------------
RIG_SIGNATURES: Dict[str, Dict[str, List[str]]] = {
    "makehuman": {"hips": ["root"], "chest": ["spine01"], "neck": ["neck01"], "head": ["head"],
                  "clavicle": ["clavicle"], "upperarm": ["upperarm01"], "forearm": ["lowerarm01"], "hand": ["wrist"],
                  "thigh": ["upperleg01"], "shin": ["lowerleg01"], "foot": ["foot"], "spine": ["spine03", "spine05"]},
    "game_engine": {"hips": ["pelvis"], "chest": ["spine03"], "neck": ["neck01"], "head": ["head"],
                    "clavicle": ["clavicle"], "upperarm": ["upperarm"], "forearm": ["lowerarm"], "hand": ["hand"],
                    "thigh": ["thigh"], "shin": ["calf"], "foot": ["foot"], "spine": ["spine01", "spine02"]},
    "rigify": {"hips": ["spine"], "chest": ["spine003"], "neck": ["spine004"], "head": ["spine006"],
               "clavicle": ["shoulder"], "upperarm": ["upperarm"], "forearm": ["forearm"], "hand": ["hand"],
               "thigh": ["thigh"], "shin": ["shin"], "foot": ["foot"], "spine": ["spine001", "spine002"]},
    "mixamo": {"hips": ["hips"], "chest": ["spine2"], "neck": ["neck"], "head": ["head"], "clavicle": ["shoulder"],
               "upperarm": ["arm"], "forearm": ["forearm"], "hand": ["hand"], "thigh": ["upleg"], "shin": ["leg"],
               "foot": ["foot"], "spine": ["spine", "spine1"]},
}
SOURCE_DISPLAY = {"makehuman": "MakeHuman", "game_engine": "MakeHuman/MPFB game-engine rig", "rigify": "Rigify",
                  "mixamo": "Mixamo", "generic": "Generic mesh", "metadata": "Avatar metadata"}


def register_rig_signature(name: str, roles: Dict[str, List[str]], replace: bool = False) -> None:
    """Teach the resolver a new rig naming convention.

    ``roles`` maps role -> candidate base names (lower-case, side suffix and
    punctuation removed, e.g. ``{"upperarm": ["upperarm"], "forearm": ["forearm"], ...}``).
    Roles: hips, chest, neck, head, clavicle, upperarm, forearm, hand, thigh, shin, foot, spine.
    """
    if name in RIG_SIGNATURES and not replace:
        raise GarmentError("DUPLICATE_RIG", f"Rig signature '{name}' already registered.")
    RIG_SIGNATURES[name] = {k: [re.sub(r"[^a-z0-9]", "", v.lower()) for v in vals] for k, vals in roles.items()}


GENERIC_ROLES: Dict[str, List[str]] = {
    "hips": ["hips", "pelvis", "root", "hip"], "chest": ["chest", "upperchest", "spine2", "spine03", "spine003"],
    "neck": ["neck", "neck01", "neck1"], "head": ["head"], "clavicle": ["clavicle", "collarbone", "shoulder"],
    "upperarm": ["upperarm", "upperarm01", "arm", "uparm"], "forearm": ["forearm", "lowerarm", "lowerarm01"],
    "hand": ["hand", "wrist"], "thigh": ["thigh", "upperleg", "upperleg01", "upleg"],
    "shin": ["shin", "calf", "lowerleg", "lowerleg01", "leg", "knee"], "foot": ["foot", "ankle"],
}
SIDED_ROLES = {"clavicle", "upperarm", "forearm", "hand", "thigh", "shin", "foot"}
ROLE_TO_REGION = {"head": "head", "neck": "neck", "clavicle": "shoulders", "chest": "chest", "spine": "waist",
                  "hips": "hips", "upperarm": "arm", "forearm": "arm", "hand": "arm", "thigh": "leg", "shin": "leg",
                  "foot": "leg"}

_PREFIX = re.compile(r"^(mixamorig\d*[:_]|def[-_.]|org[-_.]|mch[-_.]|bip\d*[ _]|cc_base_|b_|bone_)", re.I)
_SUFFIX_SIDE = re.compile(r"[._\- ](l|r|left|right)$", re.I)
_PREFIX_SIDE = re.compile(r"^(left|right)(?=[A-Z_ .-])|^(l|r)[_.](?=\w)", re.I)


def split_side(name: str) -> Tuple[str, Optional[str]]:
    """'mixamorig:LeftForeArm' -> ('forearm', 'L'); 'upperarm01.L' -> ('upperarm01', 'L')."""
    n = _PREFIX.sub("", name.strip())
    side = None
    m = _SUFFIX_SIDE.search(n)
    if m:
        side = "L" if m.group(1).lower().startswith("l") else "R"
        n = n[: m.start()]
    else:
        m = _PREFIX_SIDE.match(n)
        if m:
            token = (m.group(1) or m.group(2)).lower()
            side = "L" if token.startswith("l") else "R"
            n = n[m.end():]
    base = re.sub(r"[^a-z0-9]", "", n.lower())
    return base, side


def infer_unit_scale(height_in_scene_units: float) -> float:
    """Metres per scene unit, assuming the character is 0.5-2.6 m tall."""
    h = float(height_in_scene_units)
    for s in (1.0, 0.1, 0.01, 0.001):
        if 0.5 <= h * s <= 2.6:
            return s
    return 1.0


def _lerp(a: Sequence[float], b: Sequence[float], t: float) -> Vec3:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def _mid(a: Sequence[float], b: Sequence[float]) -> Vec3:
    return _lerp(a, b, 0.5)


def _dist(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


# ----------------------------------------------------------------------------
# landmarks
# ----------------------------------------------------------------------------

def _finish_landmarks(lm: Dict[str, Vec3], height: float, floor_z: float) -> Dict[str, Vec3]:
    """Derive torso heights from hip joints / shoulders (fractions checked against HEIGHT_RATIOS)."""
    hip_c = _mid(lm["hip_joint_l"], lm["hip_joint_r"])
    sh_c = _mid(lm["shoulder_l"], lm["shoulder_r"])
    span = sh_c[2] - hip_c[2]
    torso_y = hip_c[1]

    def at(frac: float) -> Vec3:
        return (hip_c[0], torso_y, hip_c[2] + span * frac)

    lm.setdefault("chest", at(0.66))
    lm.setdefault("waist", at(0.33))
    lm.setdefault("hips", at(-0.05))
    lm.setdefault("crotch", at(-0.21))
    lm.setdefault("shoulder_center", sh_c)
    lm.setdefault("floor", (hip_c[0], torso_y, floor_z))
    if "head_top" not in lm:
        lm["head_top"] = (hip_c[0], torso_y, floor_z + height)
    if "neck_base" not in lm:
        lm["neck_base"] = (sh_c[0], torso_y, sh_c[2] + 0.027 * height)
    if "head" not in lm:
        lm["head"] = _lerp(lm["neck_base"], lm["head_top"], 0.55)
    return lm


def estimate_landmarks_from_bounds(bmin: Sequence[float], bmax: Sequence[float]) -> Dict[str, Vec3]:
    """Anthropometric landmark estimate from a bounding box (front = -Y, up = +Z).
    Arm pose is guessed from the width/height ratio (T-pose ~1.0, A-pose ~0.6)."""
    H = bmax[2] - bmin[2]
    z0 = bmin[2]
    cx, cy = (bmin[0] + bmax[0]) / 2.0, (bmin[1] + bmax[1]) / 2.0
    ratio = (bmax[0] - bmin[0]) / H if H > 0 else 0.3
    angle = math.radians(90.0 if ratio > 0.85 else 45.0 if ratio > 0.45 else 8.0)
    lm: Dict[str, Vec3] = {}

    def z(key: str) -> float:
        return z0 + HEIGHT_RATIOS[key] * H

    sh_half = 0.1295 * H
    upper, fore = 0.186 * H, 0.146 * H
    for side, sx in (("l", 1.0), ("r", -1.0)):
        sh = (cx + sx * sh_half, cy, z("shoulder"))
        d = (sx * math.sin(angle), 0.0, -math.cos(angle))
        lm["shoulder_" + side] = sh
        lm["elbow_" + side] = (sh[0] + d[0] * upper, cy, sh[2] + d[2] * upper)
        lm["wrist_" + side] = (sh[0] + d[0] * (upper + fore), cy, sh[2] + d[2] * (upper + fore))
        lm["hip_joint_" + side] = (cx + sx * 0.051 * H, cy, z("hip_joint"))
        lm["knee_" + side] = (cx + sx * 0.051 * H, cy, z("knee"))
        lm["ankle_" + side] = (cx + sx * 0.051 * H, cy, z("ankle"))
    for key in ("head_top", "head", "neck_base", "chest", "waist", "hips", "crotch", "floor"):
        lm[key] = (cx, cy, z(key))
    lm["shoulder_center"] = (cx, cy, z("shoulder"))
    for key in ("knee", "ankle"):
        lm[key] = _mid(lm[key + "_l"], lm[key + "_r"])
    return lm


def estimate_landmarks_from_height(height: float) -> Dict[str, Vec3]:
    return estimate_landmarks_from_bounds((-0.25 * height, -0.12 * height, 0.0), (0.25 * height, 0.12 * height,
                                                                                  height))


def _score_rig(bases: Dict[Tuple[str, Optional[str]], str], sig: Dict[str, List[str]]) -> int:
    score = 0
    for role, names in sig.items():
        sides = ("L", "R") if role in SIDED_ROLES else (None,)
        for side in sides:
            if any((n, side) in bases for n in names):
                score += 1
    return score


def resolve_landmarks_from_bones(bones: Dict[str, Tuple[Sequence[float], Sequence[float]]],
                                 floor_z: Optional[float] = None,
                                 height: Optional[float] = None) -> Tuple[Dict[str, Vec3], str, List[str]]:
    """Map bones (name -> (head, tail), world space, metres) to landmarks.
    Returns (landmarks, rig_type, evidence). Raises GarmentError if too few roles resolve."""
    bases: Dict[Tuple[str, Optional[str]], str] = {}
    for name in bones:
        base, side = split_side(name)
        bases.setdefault((base, side), name)
    scores = {rig: _score_rig(bases, sig) for rig, sig in RIG_SIGNATURES.items()}
    # tie-breakers: distinctive naming
    names_l = " ".join(bones).lower()
    if "mixamorig" in names_l:
        scores["mixamo"] += 5
    if "def-" in names_l or "spine.006" in names_l or "org-" in names_l:
        scores["rigify"] += 3
    if "upperarm01" in names_l or "lowerleg01" in names_l:
        scores["makehuman"] += 3
    rig = max(scores, key=lambda r: scores[r])
    sig = RIG_SIGNATURES[rig] if scores[rig] >= 12 else GENERIC_ROLES
    if sig is GENERIC_ROLES:
        rig = "generic"
    evidence = [f"bone naming matches '{rig}' rig ({scores.get(rig, 0)} role matches)"]

    def find(role: str, side: Optional[str]) -> Optional[Tuple[Sequence[float], Sequence[float]]]:
        for cand in sig.get(role, []):
            key = (cand, side)
            if key in bases:
                return bones[bases[key]]
        return None

    lm: Dict[str, Vec3] = {}
    missing = []
    for side, s in (("L", "l"), ("R", "r")):
        ua, fa, hd = find("upperarm", side), find("forearm", side), find("hand", side)
        th, sh, ft = find("thigh", side), find("shin", side), find("foot", side)
        if ua:
            lm["shoulder_" + s] = tuple(ua[0])
            lm["elbow_" + s] = tuple(fa[0]) if fa else tuple(ua[1])
        if fa or hd:
            lm["wrist_" + s] = tuple(hd[0]) if hd else tuple(fa[1])
        if th:
            lm["hip_joint_" + s] = tuple(th[0])
            lm["knee_" + s] = tuple(sh[0]) if sh else tuple(th[1])
        if sh or ft:
            lm["ankle_" + s] = tuple(ft[0]) if ft else tuple(sh[1])
        for key in ("shoulder_", "elbow_", "wrist_", "hip_joint_", "knee_", "ankle_"):
            if key + s not in lm:
                missing.append(key + s)
    if missing:
        raise GarmentError("RIG_UNRESOLVED", f"Could not resolve landmarks {missing} from bone names.",
                           details={"rig": rig, "missing": missing})
    neck = find("neck", None)
    head = find("head", None)
    if neck:
        lm["neck_base"] = tuple(neck[0])
    if head:
        lm["head"] = tuple(head[0])
        if height is None:
            lm["head_top"] = tuple(head[1])
    for key in ("knee", "ankle"):
        lm[key] = _mid(lm[key + "_l"], lm[key + "_r"])
    ankle_z = min(lm["ankle_l"][2], lm["ankle_r"][2])
    if floor_z is None or height is None:
        # stature from shoulder-to-ankle span: shoulder 0.818 H, ankle 0.039 H
        est_h = (lm["shoulder_l"][2] - ankle_z) / (HEIGHT_RATIOS["shoulder"] - HEIGHT_RATIOS["ankle"])
        if floor_z is None:
            floor_z = ankle_z - HEIGHT_RATIOS["ankle"] * est_h
        if height is None:
            height = (lm["head_top"][2] - floor_z) if "head_top" in lm else est_h
    center_x = _mid(lm["shoulder_l"], lm["shoulder_r"])[0]
    if height is not None and ("head_top" not in lm or lm["head_top"][2] < lm["shoulder_l"][2]):
        lm["head_top"] = (center_x, lm["shoulder_l"][1], floor_z + height)
    lm = _finish_landmarks(lm, height, floor_z)
    evidence.append(f"resolved {len(lm)} landmarks from {len(bones)} bones")
    return lm, rig, evidence


def detect_pose(lm: Dict[str, Vec3]) -> str:
    try:
        sh, wr = lm["shoulder_l"], lm["wrist_l"]
    except KeyError:
        return "unknown"
    horiz = math.hypot(wr[0] - sh[0], wr[1] - sh[1])
    drop = sh[2] - wr[2]
    angle = math.degrees(math.atan2(drop, horiz))
    if angle < 22.0:
        return "T"
    if angle < 65.0:
        return "A"
    return "arms_down"


# ----------------------------------------------------------------------------
# sections
# ----------------------------------------------------------------------------

@dataclass
class SectionMeasurement:
    circumference: float
    width: float
    depth: float
    center: Tuple[float, float]
    count: int

    def to_dict(self) -> Dict[str, Any]:
        return {"circumference": self.circumference, "width": self.width, "depth": self.depth,
                "center": list(self.center), "count": self.count}


def convex_hull_2d(points: Iterable[Tuple[float, float]]) -> List[Tuple[float, float]]:
    pts = sorted(set((float(p[0]), float(p[1])) for p in points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: List[Tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: List[Tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def polygon_perimeter(poly: Sequence[Tuple[float, float]]) -> float:
    if len(poly) < 2:
        return 0.0
    return sum(math.dist(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))


def cluster_points_2d(points: Sequence[Tuple[float, float]], link: float) -> List[List[int]]:
    """Single-linkage clustering using a grid; points closer than ``link`` join."""
    parent = list(range(len(points)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    cells: Dict[Tuple[int, int], List[int]] = {}
    for i, p in enumerate(points):
        cells.setdefault((math.floor(p[0] / link), math.floor(p[1] / link)), []).append(i)
    link2 = link * link
    for (cx, cy), idx in cells.items():
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in cells.get((cx + dx, cy + dy), ()):
                    for i in idx:
                        if i < j and (points[i][0] - points[j][0]) ** 2 + (points[i][1] - points[j][1]) ** 2 <= link2:
                            ri, rj = root(i), root(j)
                            if ri != rj:
                                parent[ri] = rj
    groups: Dict[int, List[int]] = {}
    for i in range(len(points)):
        groups.setdefault(root(i), []).append(i)
    return list(groups.values())


def measure_section(points: Sequence[Tuple[float, float]], center_x: float = 0.0, center_y: Optional[float] = None,
                    link: float = 0.06) -> SectionMeasurement:
    """Tape-measure style section: convex hull of the cluster nearest the centre."""
    pts = [(float(p[0]), float(p[1])) for p in points]
    if len(pts) < 3:
        raise GarmentError("SECTION_FAILED", "Not enough points to measure a section.")
    clusters = cluster_points_2d(pts, link)
    cy = center_y if center_y is not None else sum(p[1] for p in pts) / len(pts)

    def dist_to_center(idx: List[int]) -> float:
        mx = sum(pts[i][0] for i in idx) / len(idx)
        my = sum(pts[i][1] for i in idx) / len(idx)
        return math.hypot(mx - center_x, my - cy)

    best = min(clusters, key=lambda c: (dist_to_center(c), -len(c)))
    sel = [pts[i] for i in best]
    if len(sel) < 3:
        raise GarmentError("SECTION_FAILED", "Section cluster too small.")
    hull = convex_hull_2d(sel)
    xs = [p[0] for p in sel]
    ys = [p[1] for p in sel]
    return SectionMeasurement(polygon_perimeter(hull), max(xs) - min(xs), max(ys) - min(ys),
                              ((max(xs) + min(xs)) / 2.0, (max(ys) + min(ys)) / 2.0), len(sel))


def ellipse_perimeter(a: float, b: float) -> float:
    return math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))


def ellipse_axes_for_perimeter(perimeter: float, depth_ratio: float) -> Tuple[float, float]:
    """Semi-axes (a, b=a*ratio) of an ellipse with the given perimeter."""
    unit = ellipse_perimeter(1.0, depth_ratio)
    a = perimeter / unit
    return a, a * depth_ratio


def _horizontal_section(verts: Sequence[Vec3], z: float, band: float, center_x: float,
                        center_y: float) -> SectionMeasurement:
    pts = [(v[0], v[1]) for v in verts if abs(v[2] - z) <= band]
    return measure_section(pts, center_x, center_y)


def _limb_section(verts: Sequence[Vec3], a: Vec3, b: Vec3, t: float, band: float, radius: float) -> SectionMeasurement:
    axis = tuple(bb - aa for aa, bb in zip(a, b))
    length = math.sqrt(sum(c * c for c in axis)) or 1.0
    ax = tuple(c / length for c in axis)
    ref = (0.0, 0.0, 1.0) if abs(ax[2]) < 0.9 else (1.0, 0.0, 0.0)
    u = (ref[1] * ax[2] - ref[2] * ax[1], ref[2] * ax[0] - ref[0] * ax[2], ref[0] * ax[1] - ref[1] * ax[0])
    ul = math.sqrt(sum(c * c for c in u)) or 1.0
    u = tuple(c / ul for c in u)
    v = (ax[1] * u[2] - ax[2] * u[1], ax[2] * u[0] - ax[0] * u[2], ax[0] * u[1] - ax[1] * u[0])
    at = length * t
    pts = []
    for p in verts:
        d = (p[0] - a[0], p[1] - a[1], p[2] - a[2])
        along = d[0] * ax[0] + d[1] * ax[1] + d[2] * ax[2]
        if abs(along - at) > band:
            continue
        pu = d[0] * u[0] + d[1] * u[1] + d[2] * u[2]
        pv = d[0] * v[0] + d[1] * v[1] + d[2] * v[2]
        if pu * pu + pv * pv <= radius * radius:
            pts.append((pu, pv))
    return measure_section(pts, 0.0, 0.0)


# ----------------------------------------------------------------------------
# model
# ----------------------------------------------------------------------------

@dataclass
class AvatarModel:
    name: str
    source: str = "generic"
    rig_type: Optional[str] = None
    unit_scale: float = 1.0
    height: float = 1.75
    landmarks: Dict[str, Vec3] = field(default_factory=dict)
    measurements: Dict[str, float] = field(default_factory=dict)
    sections: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    regions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    pose: str = "unknown"
    bounds: Tuple[Vec3, Vec3] = ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    evidence: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    confidence: float = 0.5
    measured_keys: List[str] = field(default_factory=list)
    object_name: Optional[str] = None

    @property
    def source_display(self) -> str:
        return SOURCE_DISPLAY.get(self.source, self.source)

    def get_measurements(self) -> Dict[str, float]:
        return dict(self.measurements)

    def get_body_regions(self) -> Dict[str, Dict[str, Any]]:
        return {k: dict(v) for k, v in self.regions.items()}

    def get_collision_surfaces(self, garment_type: Optional[str] = None, margin: Optional[float] = None
                               ) -> Dict[str, Any]:
        gdef = resolve_garment_type(garment_type) if garment_type else None
        regions = list(gdef.resolved_collision_regions()) if gdef else list(BODY_REGIONS)
        groups = sorted({g for r in regions for g in self.regions.get(r, {}).get("vertex_groups", [])})
        return {"regions": regions, "margin": margin if margin is not None else 0.012, "vertex_groups": groups,
                "z_range": self._z_range(regions)}

    def _z_range(self, regions: List[str]) -> Tuple[float, float]:
        lo = [self.regions[r]["z_range"][0] for r in regions if r in self.regions]
        hi = [self.regions[r]["z_range"][1] for r in regions if r in self.regions]
        return (min(lo), max(hi)) if lo else (self.bounds[0][2], self.bounds[1][2])

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "source": self.source, "rig_type": self.rig_type, "unit_scale": self.unit_scale,
                "height": self.height, "pose": self.pose, "confidence": self.confidence,
                "measurements": dict(self.measurements), "measured_keys": list(self.measured_keys),
                "landmarks": {k: list(v) for k, v in self.landmarks.items()},
                "regions": self.get_body_regions(), "sections": self.sections,
                "evidence": list(self.evidence), "warnings": list(self.warnings), "object_name": self.object_name}

    @classmethod
    def from_metadata(cls, metadata: Dict[str, Any], name: str = "metadata_avatar") -> "AvatarModel":
        meta = dict(metadata)
        unit = UNIT_FACTORS.get(normalize(meta.pop("units", "m")), None)
        if unit is None:
            raise GarmentError("INVALID_PARAM", "avatar metadata 'units' must be m, cm, mm or in.", path="units")
        warnings: List[str] = []
        values: Dict[str, float] = {}
        landmarks_in = meta.pop("landmarks", None)
        for k, v in meta.items():
            key = METADATA_ALIASES.get(normalize(k), normalize(k))
            if key == "height" or key in MEASURE_RATIOS:
                if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
                    raise GarmentError("INVALID_PARAM", f"avatar measurement '{k}' must be a positive number.",
                                       path=k)
                values[key] = float(v) * unit
        if "height" not in values:
            values["height"] = 1.75
            warnings.append("Avatar height not given; assuming 1.75 m.")
        H = values["height"]
        estimated = [k for k in MEASURE_RATIOS if k not in values]
        for k in estimated:
            values[k] = MEASURE_RATIOS[k] * H
        if estimated:
            warnings.append("Estimated from height using anthropometric ratios: " + ", ".join(estimated) + ".")
        lm = estimate_landmarks_from_height(H)
        if landmarks_in:
            lm.update({k: tuple(float(c) * unit for c in v) for k, v in landmarks_in.items()})
        model = cls(name=name, source="metadata", unit_scale=1.0, height=H, landmarks=lm, measurements=values,
                    pose="unknown", bounds=((-0.25 * H, -0.12 * H, 0.0), (0.25 * H, 0.12 * H, H)),
                    evidence=["explicit avatar metadata"], warnings=warnings, confidence=0.6,
                    measured_keys=sorted(k for k in values if k not in estimated))
        model.sections = _sections_from_measurements(values, lm)
        model.regions = _regions_from_landmarks(lm, {})
        return model


def _sections_from_measurements(m: Dict[str, float], lm: Dict[str, Vec3]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for key, circ, ratio in (("hips", "hip_circumference", 0.72), ("waist", "waist_circumference", 0.7),
                             ("chest", "chest_circumference", 0.72), ("neck_base", "neck_circumference", 0.95)):
        a, b = ellipse_axes_for_perimeter(m[circ], ratio)
        c = lm.get(key, (0.0, 0.0, 0.0))
        out[key] = {"z": c[2], "center": [c[0], c[1]], "width": 2 * a, "depth": 2 * b, "circumference": m[circ],
                    "measured": False}
    sh = lm.get("shoulder_center", lm.get("chest"))
    a = m["shoulder_width"] / 2.0 + 0.02
    out["shoulders"] = {"z": sh[2], "center": [sh[0], sh[1]], "width": 2 * a,
                        "depth": out["chest"]["depth"] * 0.85, "circumference": ellipse_perimeter(
                            a, out["chest"]["depth"] * 0.425), "measured": False}
    return out


def _regions_from_landmarks(lm: Dict[str, Vec3], role_groups: Dict[str, List[str]]) -> Dict[str, Dict[str, Any]]:
    def z(k: str) -> float:
        return lm[k][2]

    regions = {
        "head": (z("neck_base") + 0.04, z("head_top")),
        "neck": (z("shoulder_center"), z("neck_base") + 0.06),
        "shoulders": (z("chest") + 0.5 * (z("shoulder_center") - z("chest")), z("neck_base")),
        "chest": (z("waist") + 0.5 * (z("chest") - z("waist")), z("shoulder_center")),
        "waist": (z("hips"), z("chest")),
        "hips": (z("crotch") - 0.05, z("waist")),
        "left_arm": (min(lm["wrist_l"][2], lm["elbow_l"][2]) - 0.1, lm["shoulder_l"][2]),
        "right_arm": (min(lm["wrist_r"][2], lm["elbow_r"][2]) - 0.1, lm["shoulder_r"][2]),
        "left_leg": (lm["floor"][2], z("crotch") + 0.05),
        "right_leg": (lm["floor"][2], z("crotch") + 0.05),
    }
    out: Dict[str, Dict[str, Any]] = {}
    for name, (lo, hi) in regions.items():
        out[name] = {"z_range": [min(lo, hi), max(lo, hi)], "vertex_groups": sorted(role_groups.get(name, []))}
    return out


def _vertex_group_regions(names: Iterable[str]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for name in names:
        base, side = split_side(name)
        base_nodigits = base.rstrip("0123456789")
        for role, cands in GENERIC_ROLES.items():
            if base in cands or base_nodigits in cands:
                region = ROLE_TO_REGION.get(role)
                if region in ("arm", "leg"):
                    if side is None:
                        continue
                    region = ("left_" if side == "L" else "right_") + region
                out.setdefault(region, []).append(name)
                break
        else:
            if base.startswith("spine"):
                out.setdefault("chest" if base in ("spine01", "spine1", "spine2", "spine003") else "waist",
                               []).append(name)
    return out


def _detect_makehuman(properties: Dict[str, Any], name: str, vertex_count: int,
                      rig: Optional[str]) -> Tuple[bool, List[str]]:
    ev: List[str] = []
    keys = " ".join(str(k) for k in properties).lower()
    if "mpfb" in keys or "makehuman" in keys or "mhx" in keys:
        ev.append("MakeHuman/MPFB custom properties present")
    if re.search(r"makehuman|mpfb|basemesh|human\.body", name.lower()):
        ev.append(f"object name '{name}' looks like a MakeHuman export")
    if rig == "makehuman":
        ev.append("MakeHuman default-rig bone names")
    if vertex_count in (13380, 19158):
        ev.append(f"vertex count {vertex_count} matches the MakeHuman base mesh")
    return bool(ev), ev


def build_avatar_model(name: str, vertices: Sequence[Sequence[float]],
                       bones: Optional[Dict[str, Tuple[Sequence[float], Sequence[float]]]] = None,
                       vertex_groups: Optional[Any] = None, properties: Optional[Dict[str, Any]] = None,
                       metadata: Optional[Dict[str, Any]] = None) -> AvatarModel:
    """Build an AvatarModel from raw world-space data (scene units)."""
    if not vertices:
        raise GarmentError("AVATAR_NOT_FOUND", "Avatar mesh has no vertices.")
    properties = dict(properties or {})
    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    zs = [v[2] for v in vertices]
    height_su = max(zs) - min(zs)
    s = infer_unit_scale(height_su)
    warnings: List[str] = []
    evidence: List[str] = []
    if s != 1.0:
        evidence.append(f"scene scale detected: 1 unit = {s:g} m")
    verts = [(v[0] * s, v[1] * s, v[2] * s) for v in vertices]
    bmin = (min(xs) * s, min(ys) * s, min(zs) * s)
    bmax = (max(xs) * s, max(ys) * s, max(zs) * s)
    H = bmax[2] - bmin[2]
    if not 0.5 <= H <= 2.6:
        warnings.append(f"Avatar height {H:.2f} m is outside the expected human range; check scene scale.")

    rig_type: Optional[str] = None
    lm: Dict[str, Vec3]
    if bones:
        sbones = {k: (tuple(c * s for c in h), tuple(c * s for c in t)) for k, (h, t) in bones.items()}
        try:
            lm, rig_type, ev = resolve_landmarks_from_bones(sbones, floor_z=bmin[2], height=H)
            evidence += ["armature found"] + ev
        except GarmentError as err:
            warnings.append(f"{err.message} Falling back to anthropometric landmark estimates.")
            lm = estimate_landmarks_from_bounds(bmin, bmax)
    else:
        warnings.append("No armature found; landmarks estimated with anthropometric ratios of the bounding box.")
        lm = estimate_landmarks_from_bounds(bmin, bmax)
    lm["floor"] = (lm["floor"][0], lm["floor"][1], bmin[2])
    lm["head_top"] = (lm["head_top"][0], lm["head_top"][1], bmax[2])

    group_names = list(vertex_groups.keys()) if isinstance(vertex_groups, dict) else list(vertex_groups or [])
    is_mh, mh_ev = _detect_makehuman(properties, name, len(vertices), rig_type)
    evidence += mh_ev
    source = "makehuman" if is_mh else (rig_type if rig_type and rig_type != "generic" else "generic")

    # measurements -----------------------------------------------------------
    m: Dict[str, float] = {k: r * H for k, r in MEASURE_RATIOS.items()}
    m["height"] = H
    measured: List[str] = ["height"]
    sections: Dict[str, Dict[str, Any]] = {}
    band = max(0.012, 0.007 * H)
    torso_c = lm.get("hips", lm["waist"])
    for key, circ_key in (("hips", "hip_circumference"), ("waist", "waist_circumference"),
                          ("chest", "chest_circumference"), ("neck_base", "neck_circumference")):
        z = lm[key][2] - (0.02 if key == "neck_base" else 0.0)
        try:
            sec = _horizontal_section(verts, z, band, torso_c[0], torso_c[1])
            if sec.width > 0.45 * H:
                raise GarmentError("SECTION_FAILED", f"{key} section includes limbs")
            sections[key] = dict(sec.to_dict(), z=z, measured=True)
            m[circ_key] = sec.circumference
            measured.append(circ_key)
        except GarmentError as err:
            warnings.append(f"Could not measure {key} section ({err.message}); using anthropometric estimate.")
    try:
        sh_z = lm["shoulder_center"][2] - 0.03
        sec = _horizontal_section(verts, sh_z, band, torso_c[0], torso_c[1])
        sections["shoulders"] = dict(sec.to_dict(), z=sh_z, measured=True)
    except GarmentError as err:
        warnings.append(f"Could not measure shoulder section ({err.message}).")
    m["shoulder_width"] = _dist(lm["shoulder_l"], lm["shoulder_r"]) if bones else m["shoulder_width"]
    if bones:
        measured.append("shoulder_width")
    m["arm_length"] = _dist(lm["shoulder_l"], lm["elbow_l"]) + _dist(lm["elbow_l"], lm["wrist_l"])
    measured.append("arm_length")
    m["inseam"] = max(0.3 * H, lm["crotch"][2] - lm["floor"][2])
    for key, a, b, t, r in (("upper_arm_circumference", "shoulder_l", "elbow_l", 0.4, 0.12),
                            ("wrist_circumference", "elbow_l", "wrist_l", 0.9, 0.08)):
        try:
            m[key] = _limb_section(verts, lm[a], lm[b], t, band, r).circumference
            measured.append(key)
        except GarmentError:
            warnings.append(f"Could not measure {key}; using anthropometric estimate.")
    for key, z, lm_key in (("thigh_circumference", lm["crotch"][2] - 0.04, "hip_joint_l"),
                           ("knee_circumference", lm["knee_l"][2], "knee_l"),
                           ("ankle_circumference", lm["ankle_l"][2] + 0.05, "ankle_l")):
        try:
            side_sign = 1.0 if lm[lm_key][0] >= torso_c[0] else -1.0
            pts = [(v[0], v[1]) for v in verts if abs(v[2] - z) <= band and (v[0] - torso_c[0]) * side_sign > 0]
            sec = measure_section(pts, lm[lm_key][0], lm[lm_key][1])
            m[key] = sec.circumference
            measured.append(key)
        except GarmentError:
            warnings.append(f"Could not measure {key}; using anthropometric estimate.")
    for key in ("hips", "waist", "chest", "neck_base"):
        if key not in sections:
            sections.update({k: v for k, v in _sections_from_measurements(m, lm).items() if k == key})
    if "shoulders" not in sections:
        sections["shoulders"] = _sections_from_measurements(m, lm)["shoulders"]

    # metadata overrides (explicit beats measured) ------------------------------
    meta = dict(metadata or {})
    if "ai_garment_avatar" in properties and not metadata:
        raw = properties["ai_garment_avatar"]
        try:
            meta = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except (ValueError, TypeError) as err:
            warnings.append(f"Ignoring invalid ai_garment_avatar metadata: {err}")
    if meta:
        unit = UNIT_FACTORS.get(normalize(meta.pop("units", "m")), 1.0)
        for k, v in meta.items():
            key = METADATA_ALIASES.get(normalize(k), normalize(k))
            if key in MEASURE_RATIOS and isinstance(v, (int, float)) and not isinstance(v, bool):
                m[key] = float(v) * unit
                if key not in measured:
                    measured.append(key)
        evidence.append("avatar metadata overrides applied")

    regions = _regions_from_landmarks(lm, _vertex_group_regions(group_names))
    pose = detect_pose(lm) if bones else "unknown"
    confidence = 0.9 if rig_type and rig_type != "generic" else 0.6 if bones else 0.4
    return AvatarModel(name=name, source=source, rig_type=rig_type, unit_scale=s, height=H, landmarks=lm,
                       measurements=m, sections=sections, regions=regions, pose=pose, bounds=(bmin, bmax),
                       evidence=evidence, warnings=warnings, confidence=confidence, measured_keys=sorted(set(measured)),
                       object_name=name)

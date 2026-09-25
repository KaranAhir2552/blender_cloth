"""Native proxy-garment builder: GarmentSpec + AvatarModel -> GarmentMeshData.

This is the *fallback* garment construction used when no pattern-based
provider (OpenSew, Garment Tool, ...) is available. It produces a coarse,
simulation-ready starting shape: lofted elliptical tubes around the avatar's
landmarks, patches for pockets, and native sewing springs (loose edges)
joining the pieces. Blender's cloth solver does the draping.

All coordinates are metres, Z up, character facing -Y (character's left = +X).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..avatar_model import AvatarModel
from ..component_system import resolve_component_type
from ..elastic import ElasticSpec, combine_elastics
from ..errors import GarmentError
from ..fit_system import derive_garment_measurements, hem_height, resolve_ease
from ..garment_spec import GarmentSpec
from ..quality import QualityPreset, get_quality
from .mathutil import Vec3, add, basis_for_axis, dist, dot, lerp, lerp1, normalize, scale, sub
from .recipes import get_recipe, register_builder_recipe
from .tube import GROUP_PREFIX, GarmentMeshData, MeshBuilder, Ring

CLEARANCE = 0.012  # initial gap between body and garment (m)
TWO_PI = 2.0 * math.pi
STIFFNESS = {"zipper": 3.0, "button_placket": 2.0, "button": 1.5, "collar": 1.8, "cuff": 1.5, "waistband": 2.0,
             "elastic_waistband": 2.0, "hem": 1.3, "pocket": 1.2, "cargo_pocket": 1.3, "kangaroo_pocket": 1.2,
             "belt_loop": 1.5, "roll": 2.0}
FLARE = {"straight": 0.0, "a_line": 0.3, "pencil": -0.04, "circle": 0.8}


@dataclass
class Panel:
    """A generated panel: rings ordered start -> end along its axis."""

    name: str
    rings: List[List[int]]
    ring_t: List[float] = field(default_factory=list)  # distance along axis for each ring
    axis: Vec3 = (0.0, 0.0, 1.0)
    origin: Vec3 = (0.0, 0.0, 0.0)
    ring_params: List[Ring] = field(default_factory=list)
    end_rings: int = 1  # rings that form the "end" (opening) incl. roll folds
    columns: Optional[List[List[int]]] = None  # for open strips: boundary columns

    @property
    def indices(self) -> List[int]:
        return [i for r in self.rings for i in r]


@dataclass
class BuildContext:
    spec: GarmentSpec
    av: AvatarModel
    q: QualityPreset
    gm: Dict[str, Any]
    mb: MeshBuilder
    thickness: float = 0.0005
    panels: Dict[str, Panel] = field(default_factory=dict)
    groups: Dict[str, List[int]] = field(default_factory=dict)  # component name -> vertex indices
    stiff: Dict[str, float] = field(default_factory=dict)  # component name -> stiffness factor

    @property
    def lm(self) -> Dict[str, Vec3]:
        return self.av.landmarks

    def z(self, key: str) -> float:
        return float(self.lm[key][2] if key in self.lm else self.lm[key + "_l"][2])

    def ease(self, component: Optional[str] = None) -> Dict[str, float]:
        return resolve_ease(self.spec.fit, component)

    @property
    def scale(self) -> float:
        return float(self.spec.fit.scale or 1.0)


# ----------------------------------------------------------------------------
# body shape helpers
# ----------------------------------------------------------------------------

def body_section(ctx: BuildContext, z: float) -> Tuple[float, float, float, float]:
    """(cx, cy, half_width, half_depth) of the torso at height z (interpolated)."""
    secs = sorted((s for s in ctx.av.sections.values() if "z" in s), key=lambda s: s["z"])
    if not secs:
        raise GarmentError("AVATAR_INCOMPLETE", "Avatar has no body sections to fit against.")
    if z <= secs[0]["z"]:
        s = secs[0]
        return s["center"][0], s["center"][1], s["width"] / 2.0, s["depth"] / 2.0
    for s0, s1 in zip(secs, secs[1:]):
        if s0["z"] <= z <= s1["z"]:
            t = (z - s0["z"]) / max(1e-9, s1["z"] - s0["z"])
            return (lerp1(s0["center"][0], s1["center"][0], t), lerp1(s0["center"][1], s1["center"][1], t),
                    lerp1(s0["width"], s1["width"], t) / 2.0, lerp1(s0["depth"], s1["depth"], t) / 2.0)
    s = secs[-1]
    return s["center"][0], s["center"][1], s["width"] / 2.0, s["depth"] / 2.0


def torso_ease_cm(ctx: BuildContext, z: float, e: Dict[str, float]) -> float:
    pts = sorted([(ctx.z("hips"), e["hip_ease"]), (ctx.z("waist"), e["waist_ease"]), (ctx.z("chest"), e["chest_ease"])])
    if z <= pts[0][0]:
        return pts[0][1]
    for (z0, e0), (z1, e1) in zip(pts, pts[1:]):
        if z0 <= z <= z1:
            return lerp1(e0, e1, (z - z0) / max(1e-9, z1 - z0))
    return pts[-1][1]


def _zs(z0: float, z1: float, spacing: float, include: Sequence[float] = ()) -> List[float]:
    """Heights from z0 to z1 (either direction) roughly ``spacing`` apart, plus ``include`` points."""
    n = max(1, int(math.ceil(abs(z1 - z0) / spacing)))
    out = [z0 + (z1 - z0) * i / n for i in range(n + 1)]
    lo, hi = min(z0, z1), max(z0, z1)
    for z in include:
        if lo + 0.01 < z < hi - 0.01 and all(abs(z - o) > spacing * 0.35 for o in out):
            out.append(z)
    return sorted(out, reverse=z1 < z0)


def _vertical_ring(cx: float, cy: float, z: float, a: float, b: float, down: bool = False) -> Ring:
    u, v = basis_for_axis((0.0, 0.0, -1.0 if down else 1.0))
    return Ring((cx, cy, z), u, v, a, b)


def _offset_axes(a: float, b: float, ease_cm: float, ctx: BuildContext) -> Tuple[float, float]:
    d = max(0.0, ease_cm) / 100.0 / TWO_PI
    extra = CLEARANCE + ctx.thickness
    return (a + d) * ctx.scale + extra, (b + d) * ctx.scale + extra


def _limb_radius(circ: float) -> float:
    return circ / TWO_PI


# ----------------------------------------------------------------------------
# recipes
# ----------------------------------------------------------------------------

def _garment_hem_z(ctx: BuildContext, top_key: str) -> float:
    spec = ctx.spec
    length = spec.length or spec.type_def.default_length
    hem = hem_height(length, ctx.lm)
    top = ctx.z(top_key)
    adj = spec.length_adjust or {}
    L = (top - hem) * (1.0 + float(adj.get("percent", 0.0)) / 100.0) + float(adj.get("meters", 0.0))
    return max(ctx.z("floor") + 0.02, top - max(0.05, L))


def _torso_panel(ctx: BuildContext, hem_z: float, flare: float = 0.0) -> Panel:
    """Lofted torso from hem up to the neckline, with a shoulder yoke."""
    spec, q = ctx.spec, ctx.q
    e = ctx.ease("body")
    sh_z = ctx.z("shoulder")
    arm_r = _limb_radius(ctx.av.measurements["upper_arm_circumference"])
    under_z = sh_z - arm_r - 0.01
    hips_z = ctx.z("hips")
    zs = _zs(hem_z, under_z, q.ring_spacing, [hips_z, ctx.z("waist"), ctx.z("chest")])
    rings: List[Ring] = []
    for z in zs:
        cx, cy, a, b = body_section(ctx, max(z, hips_z) if z < hips_z else z)
        ease_cm = torso_ease_cm(ctx, z, e)
        if spec.tucked and z < ctx.z("waist"):
            ease_cm = min(ease_cm, e["waist_ease"])
        ga, gb = _offset_axes(a, b, ease_cm, ctx)
        if z < hips_z and flare:
            ga += flare * (hips_z - z)
            gb += flare * 0.8 * (hips_z - z)
        rings.append(_vertical_ring(cx, cy, z, ga, gb))
    # shoulder ring: wide enough to reach the (dropped) shoulder seam, above the deltoid
    cx, cy, a_s, b_s = body_section(ctx, sh_z)
    half_shoulder = ctx.gm["shoulder_width"] / 2.0
    top_a = max(rings[-1].a * 0.95, half_shoulder + arm_r * 0.5 + CLEARANCE)
    top_b = max(b_s + CLEARANCE * 2, rings[-1].b * 0.85)
    rings.append(_vertical_ring(cx, cy, sh_z + arm_r + CLEARANCE, top_a, top_b))
    # neckline
    neck_r = ctx.gm["neck_circumference"] / TWO_PI
    nz = ctx.z("neck_base") + 0.01
    ncx, ncy, _, _ = body_section(ctx, nz)
    rings.append(_vertical_ring(ncx, ncy, max(nz, sh_z + arm_r + CLEARANCE + 0.015), neck_r * 1.1 + CLEARANCE,
                                neck_r + CLEARANCE))
    collar = next((c for c in spec.components if c.type == "collar"), None)
    style = (collar.params.get("style") if collar else None) or "crew"
    stand = {"shirt": 0.035, "stand": 0.04, "turtleneck": 0.08}.get(style, 0.0)
    if collar and collar.params.get("height") is not None:
        stand = float(collar.params["height"])
    if stand > 0:
        base = rings[-1]
        steps = max(1, int(math.ceil(stand / 0.02)))
        for i in range(1, steps + 1):
            rings.append(Ring(add(base.center, (0.0, 0.0, stand * i / steps)), base.u, base.v, base.a, base.b))
    idx = ctx.mb.add_tube(rings, q.segments_torso)
    return Panel("body", idx, [r.center[2] for r in rings], (0.0, 0.0, 1.0), rings[0].center, rings,
                 end_rings=1 + (int(math.ceil(stand / 0.02)) if stand > 0 else 0))


def _sleeve_panels(ctx: BuildContext, torso: Panel) -> None:
    spec, q, lm, m = ctx.spec, ctx.q, ctx.lm, ctx.av.measurements
    for comp in spec.components_of_type("sleeve"):
        side = (comp.params.get("side") or ("left" if "left" in comp.name else "right"))[0]
        info = ctx.gm["components"].get(comp.name, {})
        length = float(info.get("length", 0.0))
        if length <= 0.0:
            ctx.mb.warnings.append(f"{comp.name}: sleeveless, no geometry generated.")
            continue
        S, E, W = lm["shoulder_" + side], lm["elbow_" + side], lm["wrist_" + side]
        axis = normalize(sub(W, S))
        arm_len = dist(S, E) + dist(E, W)
        e = ctx.ease(comp.name)
        drop = max(0.0, e["shoulder_drop"]) / 100.0
        t0 = min(drop, length * 0.5)
        rolled = int(comp.state.get("rolled", 0))
        roll_w = 0.035 * rolled
        t_end = max(t0 + 0.05, length - roll_w)
        u, v = basis_for_axis(axis)
        r_up = _limb_radius(m["upper_arm_circumference"])
        r_wr = _limb_radius(m["wrist_circumference"])
        bicep = info.get("bicep_circumference", m["upper_arm_circumference"]) / TWO_PI
        opening = info.get("opening_circumference", m["wrist_circumference"] * 1.4) / TWO_PI

        def radius(t: float) -> float:
            f = min(1.0, max(0.0, t / max(1e-6, arm_len)))
            body = lerp1(r_up, r_wr, f)
            garment = lerp1(bicep, max(opening, body + 0.005), min(1.0, t / max(1e-6, t_end)))
            return max(body + CLEARANCE, garment * ctx.scale + CLEARANCE * 0.5)

        ts = _zs(t0, t_end, q.ring_spacing)
        rings = [Ring(add(S, scale(axis, t)), u, v, radius(t), radius(t)) for t in ts]
        rings[0] = Ring(rings[0].center, u, v, max(rings[0].a, r_up * 1.3 + CLEARANCE),
                        max(rings[0].b, r_up * 1.3 + CLEARANCE))
        end_rings = 1
        if rolled:
            r_end = rings[-1].a
            c_end = rings[-1].center
            rings.append(Ring(c_end, u, v, r_end + 0.008 * rolled, r_end + 0.008 * rolled))
            rings.append(Ring(sub(c_end, scale(axis, roll_w)), u, v, r_end + 0.01 * rolled, r_end + 0.01 * rolled))
            ts += [t_end, t_end - roll_w]
            end_rings = 3
        idx = ctx.mb.add_tube(rings, q.segments_limb)
        panel = Panel(comp.name, idx, ts, axis, S, rings, end_rings)
        ctx.panels[comp.name] = panel
        if rolled:
            ctx.mb.assign(GROUP_PREFIX + comp.name + "_roll", [i for r in idx[-3:] for i in r])
            ctx.stiff[comp.name + "_roll"] = STIFFNESS["roll"]
            ctx.groups[comp.name + "_roll"] = [i for r in idx[-3:] for i in r]
        # sew the sleeve root to the upper torso on this side
        sign = 1.0 if side == "l" else -1.0
        chest_z = ctx.z("chest")
        cand = [i for i in torso.indices if ctx.mb.vertices[i][2] > chest_z
                and (ctx.mb.vertices[i][0] - torso.origin[0]) * sign > 0]
        seam = f"{comp.name}:body"
        if seam not in spec.disabled_seams:
            ctx.mb.sew(seam, idx[0], cand, max_dist=0.25)


def _hood_panel(ctx: BuildContext, torso: Panel) -> None:
    comp = ctx.spec.get_component("hood")
    if comp is None:
        return
    H = ctx.av.height
    size = {"snug": 0.8, "regular": 1.0, "oversized": 1.35}.get(comp.params.get("size", "regular"), 1.0)
    neck_ring = torso.ring_params[-torso.end_rings]
    head = ctx.lm["head"]
    top_z = ctx.z("head_top") + 0.03 * size
    head_a = 0.043 * H + 0.025 * size
    head_b = 0.055 * H + 0.03 * size
    zc = head[2]
    half_h = max(0.05, top_z - zc)
    rings = []
    zs = _zs(neck_ring.center[2], top_z, ctx.q.ring_spacing * 0.8)
    for z in zs:
        t = (z - zc) / half_h
        f = math.sqrt(max(0.16, 1.0 - t * t)) if z > zc else 1.0
        blend = min(1.0, max(0.0, (z - neck_ring.center[2]) / max(1e-6, zc - neck_ring.center[2])))
        a = lerp1(neck_ring.a, head_a * f, blend)
        b = lerp1(neck_ring.b, head_b * f, blend)
        cy = lerp1(neck_ring.center[1], head[1] + 0.015, blend)
        rings.append(_vertical_ring(neck_ring.center[0], cy, z, a, b))
    seg = max(8, int(ctx.q.segments_torso * 0.75))
    arc = (math.radians(-45.0), math.radians(225.0))  # open towards the front (-Y)
    idx = ctx.mb.add_tube(rings, seg, arc)
    columns = [[r[0] for r in idx], [r[-1] for r in idx]]
    ctx.panels["hood"] = Panel("hood", idx, zs, (0.0, 0.0, 1.0), rings[0].center, rings, 1, columns)
    if "hood:body" not in ctx.spec.disabled_seams:
        ctx.mb.sew("hood:body", idx[0], torso.rings[-torso.end_rings], max_dist=0.1)


def _surface_patch(ctx: BuildContext, panel: Panel, center_x: float, z0: float, z1: float, width: float,
                   front: bool = True, nu: int = 5, nv: int = 4) -> List[List[int]]:
    """Patch conforming to the front (-Y) or back (+Y) of a vertical elliptical panel."""
    grid = []
    for j in range(nv + 1):
        z = lerp1(z0, z1, j / nv)
        ring = min(panel.ring_params, key=lambda r: abs(r.center[2] - z))
        row = []
        for i in range(nu + 1):
            x = center_x - width / 2.0 + width * i / nu
            rx = (x - ring.center[0]) / max(1e-6, ring.a)
            yoff = ring.b * math.sqrt(max(0.0, 1.0 - min(1.0, rx * rx))) + 0.004
            y = ring.center[1] - yoff if front else ring.center[1] + yoff
            row.append((x, y, z))
        grid.append(row if front else list(reversed(row)))
    return ctx.mb.add_patch(grid)


def _sew_patch(ctx: BuildContext, name: str, target: Panel, grid: List[List[int]], edges: Sequence[str]) -> None:
    if f"{name}:{target.name}" in ctx.spec.disabled_seams:
        return
    border: List[int] = []
    if "bottom" in edges:
        border += grid[0]
    if "top" in edges:
        border += grid[-1]
    if "left" in edges:
        border += [row[0] for row in grid]
    if "right" in edges:
        border += [row[-1] for row in grid]
    ctx.mb.sew(f"{name}:{target.name}", sorted(set(border)), target.indices, max_dist=0.06)


def _pockets(ctx: BuildContext) -> None:
    body = ctx.panels.get("body")
    for comp in ctx.spec.components:
        if comp.type == "kangaroo_pocket" and body:
            w = min(0.36, body.ring_params[0].a * 1.5)
            z0 = ctx.z("hips") + 0.02
            grid = _surface_patch(ctx, body, body.origin[0], z0, z0 + 0.17, w)
            ctx.groups[comp.name] = [i for r in grid for i in r]
            _sew_patch(ctx, comp.name, body, grid, ("top", "bottom"))
        elif comp.type == "pocket":
            parent = ctx.panels.get(comp.target or "body") or body
            if parent is None:
                continue
            size = float(comp.params.get("size", 0.14))
            place = comp.params.get("placement", "hip_left")
            sign = 1.0 if place.endswith("left") else -1.0
            if place.startswith("chest"):
                zc, xoff, front = ctx.z("chest") + 0.04, 0.09, True
            elif place.startswith("back"):
                zc, xoff, front = ctx.z("hips") + 0.04, 0.08, False
            elif place.startswith("front_hip"):
                zc, xoff, front = ctx.z("hips") + 0.06, 0.1, True
            else:
                zc, xoff, front = ctx.z("hips") + 0.03, 0.12, True
            grid = _surface_patch(ctx, parent, parent.origin[0] + sign * xoff, zc - size / 2, zc + size / 2, size,
                                  front, 3, 3)
            ctx.groups[comp.name] = [i for r in grid for i in r]
            _sew_patch(ctx, comp.name, parent, grid, ("left", "right", "bottom"))
        elif comp.type == "cargo_pocket":
            leg = ctx.panels.get(comp.target or "")
            if leg is None:
                continue
            size = float(comp.params.get("size", 0.18))
            side = 1.0 if "left" in (comp.target or "") else -1.0
            zc = lerp1(ctx.z("crotch"), ctx.z("knee"), 0.4)
            ring = min(leg.ring_params, key=lambda r: abs(r.center[2] - zc))
            r = ring.a + 0.005
            out, fwd = (side, 0.0, 0.0), (0.0, -1.0, 0.0)
            grid = []
            for j in range(4):
                z = zc - size / 2 + size * j / 3
                row = []
                for i in range(4):
                    theta = (-0.5 + i / 3) * size / max(r, 1e-6)
                    p = add((ring.center[0], ring.center[1], z),
                            add(scale(out, r * math.cos(theta)), scale(fwd, -side * r * math.sin(theta))))
                    row.append(p)
                grid.append(row)
            idx = ctx.mb.add_patch(grid)
            ctx.groups[comp.name] = [i for rr in idx for i in rr]
            _sew_patch(ctx, comp.name, leg, idx, ("left", "right", "bottom"))


def recipe_top(ctx: BuildContext) -> None:
    hem_z = _garment_hem_z(ctx, "shoulder")
    if ctx.spec.tucked:
        hem_z = min(hem_z, ctx.z("hips") - 0.06)
    torso = _torso_panel(ctx, hem_z)
    ctx.panels["body"] = torso
    _sleeve_panels(ctx, torso)
    _hood_panel(ctx, torso)
    _pockets(ctx)


def recipe_dress(ctx: BuildContext) -> None:
    body = ctx.spec.get_component("body")
    shape = (body.params.get("shape") if body else None) or "a_line"
    flare = float(body.params.get("flare", FLARE.get(shape, 0.3))) if body else 0.3
    hem_z = _garment_hem_z(ctx, "shoulder")
    torso = _torso_panel(ctx, hem_z, flare=max(flare, 0.12))
    ctx.panels["body"] = torso
    _sleeve_panels(ctx, torso)
    _hood_panel(ctx, torso)
    _pockets(ctx)


def _pelvis_panel(ctx: BuildContext, z_bottom: float, flare: float = 0.0, down_to: Optional[float] = None) -> Panel:
    e = ctx.ease("body")
    top_z = ctx.z("waist") + 0.015
    start = down_to if down_to is not None else z_bottom
    zs = _zs(start, top_z, ctx.q.ring_spacing, [ctx.z("hips")])
    rings = []
    hips_z = ctx.z("hips")
    for z in zs:
        cx, cy, a, b = body_section(ctx, max(z, hips_z) if z < hips_z else z)
        ga, gb = _offset_axes(a, b, torso_ease_cm(ctx, z, e), ctx)
        if z < hips_z:
            ga += flare * (hips_z - z)
            gb += flare * 0.8 * (hips_z - z)
        rings.append(_vertical_ring(cx, cy, z, ga, gb))
    idx = ctx.mb.add_tube(rings, ctx.q.segments_torso)
    return Panel("body", idx, zs, (0.0, 0.0, 1.0), rings[0].center, rings, end_rings=1)


def recipe_pants(ctx: BuildContext) -> None:
    spec, lm, m = ctx.spec, ctx.lm, ctx.av.measurements
    crotch_z = ctx.z("crotch")
    pelvis = _pelvis_panel(ctx, crotch_z + 0.01)
    ctx.panels["body"] = pelvis
    base_hem = _garment_hem_z(ctx, "waist")
    for comp in spec.components_of_type("leg"):
        side = (comp.params.get("side") or ("left" if "left" in comp.name else "right"))[0]
        sign = 1.0 if side == "l" else -1.0
        info = ctx.gm["components"].get(comp.name, {})
        adj = comp.params.get("length_adjust") or {}
        top_z = crotch_z - 0.015
        leg_len = (top_z - base_hem) * (1.0 + float(adj.get("percent", 0.0)) / 100.0) + float(adj.get("meters", 0.0))
        rolled = int(comp.state.get("rolled", 0))
        roll_w = 0.04 * rolled
        hem_z = max(ctx.z("floor") + 0.01, top_z - max(0.05, leg_len) + roll_w)
        hip, knee, ankle = lm["hip_joint_" + side], lm["knee_" + side], lm["ankle_" + side]
        thigh = info.get("thigh_circumference", m["thigh_circumference"]) / TWO_PI
        knee_g = info.get("knee_circumference", m["knee_circumference"]) / TWO_PI
        open_g = info.get("opening_circumference", m["ankle_circumference"] * 1.5) / TWO_PI
        r_th, r_kn, r_an = (_limb_radius(m["thigh_circumference"]), _limb_radius(m["knee_circumference"]),
                            _limb_radius(m["ankle_circumference"]))

        def at(z: float) -> Tuple[Vec3, float]:
            if z >= knee[2]:
                t = (hip[2] - z) / max(1e-6, hip[2] - knee[2])
                c = lerp(hip, knee, min(1.0, max(0.0, t)))
                body_r, g = lerp1(r_th, r_kn, t), lerp1(thigh, knee_g, t)
            else:
                t = (knee[2] - z) / max(1e-6, knee[2] - ankle[2])
                c = lerp(knee, ankle, min(1.0, max(0.0, t)))
                body_r, g = lerp1(r_kn, r_an, t), lerp1(knee_g, max(open_g, r_an + 0.01), t)
            r = max(body_r + CLEARANCE, g * ctx.scale + CLEARANCE * 0.5)
            cx = sign * max(abs(c[0] - pelvis.origin[0]), r + 0.003) + pelvis.origin[0]
            return (cx, c[1], z), r

        zs = _zs(top_z, hem_z, ctx.q.ring_spacing)
        rings = []
        for z in zs:
            c, r = at(z)
            rings.append(_vertical_ring(c[0], c[1], z, r, r, down=True))
        end_rings = 1
        if rolled:
            last = rings[-1]
            rings.append(Ring(last.center, last.u, last.v, last.a + 0.008 * rolled, last.b + 0.008 * rolled))
            rings.append(Ring(add(last.center, (0.0, 0.0, roll_w)), last.u, last.v, last.a + 0.01 * rolled,
                              last.b + 0.01 * rolled))
            zs += [hem_z, hem_z + roll_w]
            end_rings = 3
        idx = ctx.mb.add_tube(rings, ctx.q.segments_limb)
        panel = Panel(comp.name, idx, [top_z - z for z in zs], (0.0, 0.0, -1.0), rings[0].center, rings, end_rings)
        ctx.panels[comp.name] = panel
        if rolled:
            ctx.groups[comp.name + "_roll"] = [i for r in idx[-3:] for i in r]
            ctx.mb.assign(GROUP_PREFIX + comp.name + "_roll", ctx.groups[comp.name + "_roll"])
            ctx.stiff[comp.name + "_roll"] = STIFFNESS["roll"]
        seam = f"{comp.name}:body"
        if seam not in spec.disabled_seams:
            cand = [i for i in pelvis.rings[0] if (ctx.mb.vertices[i][0] - pelvis.origin[0]) * sign >= -0.03]
            ctx.mb.sew(seam, idx[0], cand, max_dist=0.2)
    _pockets(ctx)


def recipe_skirt(ctx: BuildContext) -> None:
    body = ctx.spec.get_component("body")
    shape = (body.params.get("shape") if body else None) or "a_line"
    flare = float(body.params.get("flare", FLARE.get(shape, 0.3))) if body else 0.3
    hem_z = _garment_hem_z(ctx, "waist")
    ctx.panels["body"] = _pelvis_panel(ctx, hem_z, flare=flare, down_to=hem_z)
    _pockets(ctx)


for _name, _fn in (("top", recipe_top), ("pants", recipe_pants), ("skirt", recipe_skirt), ("dress", recipe_dress)):
    register_builder_recipe(_name, _fn)


# ----------------------------------------------------------------------------
# bands, features, physics groups
# ----------------------------------------------------------------------------

def _end_indices(panel: Panel, width: float, bottom: bool, ctx: BuildContext) -> List[int]:
    """Vertices within ``width`` of a panel's start (bottom=True for bodies: the hem) or end."""
    if panel.name == "body":
        rings = panel.rings[:] if bottom else panel.rings[::-1]
        zs = [ctx.mb.vertices[r[0]][2] for r in rings]
        ref = zs[0]
        chosen = [r for r, z in zip(rings, zs) if abs(z - ref) <= width + 1e-6]
        return [i for r in (chosen or rings[:1]) for i in r]
    rings = panel.rings[-panel.end_rings:]
    extra = []
    if panel.end_rings == 1 and len(panel.ring_t) >= 2:
        t_end = panel.ring_t[len(panel.rings) - 1]
        for r, t in zip(panel.rings[:-1][::-1], panel.ring_t[:len(panel.rings) - 1][::-1]):
            if abs(t_end - t) <= width + 1e-6:
                extra += r
    return [i for r in rings for i in r] + extra


def _band_vertices(ctx: BuildContext, comp) -> List[int]:
    t = comp.type
    width = float(comp.params.get("width", 0.03) or 0.03)
    if t == "collar":
        body = ctx.panels.get("body")
        if body is None:
            return []
        return [i for r in body.rings[-(body.end_rings + 1):] for i in r]
    parent = ctx.panels.get(comp.target or "body")
    if parent is None:
        return ctx.groups.get(comp.target or "", [])
    if t in ("waistband", "elastic_waistband"):
        bottom = ctx.spec.category == "top"  # rib hem band on hoodies/sweatshirts
        return _end_indices(parent, width, bottom, ctx)
    if t == "hem":
        return _end_indices(parent, width, parent.name == "body" and ctx.spec.category != "bottom"
                            or parent.name == "body", ctx)
    if t in ("cuff", "elastic_cuff"):
        return _end_indices(parent, width, False, ctx)
    return []


def _feature_vertices(ctx: BuildContext, comp) -> List[int]:
    t = comp.type
    body = ctx.panels.get("body")
    verts = ctx.mb.vertices
    if t in ("zipper", "button_placket") and body is not None:
        cx, cy = body.origin[0], body.origin[1]
        return [i for i in body.indices if abs(verts[i][0] - cx) < 0.022 and verts[i][1] < cy]
    target_verts = ctx.groups.get(comp.target or "", [])
    if t == "drawstring":
        hood = ctx.panels.get(comp.target or "")
        if hood is not None and hood.columns:
            return hood.columns[0] + hood.columns[1] + hood.rings[-1]
        return list(target_verts)
    if t == "belt_loop":
        count = int(comp.params.get("count", 5))
        tv = list(target_verts)
        if not tv:
            return []
        cx = sum(verts[i][0] for i in tv) / len(tv)
        cy = sum(verts[i][1] for i in tv) / len(tv)
        out = []
        for k in range(count):
            ang = math.pi * (0.15 + 0.7 * k / max(1, count - 1)) + math.pi  # spread around front/sides/back
            d = (math.cos(ang), math.sin(ang))
            best = max(tv, key=lambda i: (verts[i][0] - cx) * d[0] + (verts[i][1] - cy) * d[1])
            out.append(best)
        return out
    if t in ("elastic", "button"):
        return list(target_verts)
    if t == "seam":
        return ctx.groups.get(comp.params.get("a", ""), [])[:1] + ctx.groups.get(comp.params.get("b", ""), [])[:1]
    return []


def _elastic_for(comp) -> Optional[ElasticSpec]:
    ctype = resolve_component_type(comp.type)
    p = comp.params
    if ctype is not None and ctype.elastic:
        return ElasticSpec.from_params(comp.name, p.get("strength", "medium"), p.get("width"), p.get("tension"))
    if comp.type == "drawstring":
        return ElasticSpec.from_params(comp.name, p.get("strength", "light"), None, p.get("tension"),
                                       kind="drawstring")
    if isinstance(p.get("elastic"), dict):
        e = p["elastic"]
        return ElasticSpec.from_params(comp.name, e.get("strength", "medium"), e.get("width"), e.get("tension"))
    return None


def build_garment_mesh(spec: GarmentSpec, avatar: AvatarModel, quality: str = "preview",
                       fabric_thickness_mm: float = 0.5) -> GarmentMeshData:
    gdef = spec.type_def
    if gdef is None:
        raise GarmentError("UNKNOWN_GARMENT_TYPE", f"Unknown garment type '{spec.type}'.")
    q = get_quality(quality)
    gm = derive_garment_measurements(avatar.measurements, spec, avatar.landmarks)
    ctx = BuildContext(spec, avatar, q, gm, MeshBuilder(), thickness=fabric_thickness_mm / 1000.0)
    get_recipe(gdef.builder)(ctx)
    mb = ctx.mb

    # panels -> groups
    for name, panel in ctx.panels.items():
        ctx.groups[name] = panel.indices
    ordered = sorted(spec.components, key=lambda c: {"panel": 0, "band": 1, "feature": 2}.get(
        getattr(resolve_component_type(c.type), "kind", "feature"), 3))
    for comp in ordered:
        ctype = resolve_component_type(comp.type)
        if ctype is None or comp.name in ctx.groups:
            continue
        if ctype.kind == "band":
            ctx.groups[comp.name] = _band_vertices(ctx, comp)
        elif ctype.kind == "feature":
            ctx.groups[comp.name] = _feature_vertices(ctx, comp)
    # extra user seams
    for comp in spec.components_of_type("seam"):
        a, b = ctx.groups.get(comp.params.get("a", ""), []), ctx.groups.get(comp.params.get("b", ""), [])
        if a and b:
            mb.sew(f"{comp.params['a']}:{comp.params['b']}", a, b, max_dist=0.08)

    components: Dict[str, str] = {}
    for comp in spec.components:
        idx = ctx.groups.get(comp.name, [])
        if not idx:
            mb.warnings.append(f"Component '{comp.name}' has no geometry in the native proxy builder.")
            continue
        mb.assign(GROUP_PREFIX + comp.name, idx)
        components[comp.name] = GROUP_PREFIX + comp.name

    # physics groups ---------------------------------------------------------------
    elastics = []
    for comp in spec.components:
        e = _elastic_for(comp)
        if e is not None and ctx.groups.get(comp.name):
            elastics.append(e)
    combined = combine_elastics(elastics)
    if elastics:
        for e in elastics:
            mb.assign(GROUP_PREFIX + "shrink", ctx.groups[e.target], combined.weights[e.target])
    stiff_factors = dict(ctx.stiff)
    for comp in spec.components:
        f = STIFFNESS.get(comp.type)
        e = next((x for x in elastics if x.target == comp.name), None)
        if e is not None:
            f = max(f or 1.0, e.stiffness_multiplier)
        if f and ctx.groups.get(comp.name):
            stiff_factors[comp.name] = f
    max_factor = max(stiff_factors.values()) if stiff_factors else 1.0
    if max_factor > 1.0:
        for name, f in stiff_factors.items():
            mb.assign(GROUP_PREFIX + "stiff", ctx.groups.get(name, []), (f - 1.0) / (max_factor - 1.0))
    pins = [p for p in spec.simulation.pin if ctx.groups.get(p)]
    for p in pins:
        mb.assign(GROUP_PREFIX + "pin", ctx.groups[p], 1.0)
    e_body = resolve_ease(spec.fit, "body")
    keys = ("waist_ease", "hip_ease") if gdef.category == "bottom" else ("chest_ease", "waist_ease", "hip_ease")
    neg = min(e_body[k] for k in keys)
    body_circ = avatar.measurements["waist_circumference"]
    shrink_min = round(min(0.1, -neg / 100.0 / body_circ), 4) if neg < 0 else 0.0
    physics = {
        "shrink_group": GROUP_PREFIX + "shrink" if elastics else None,
        "shrink_min": shrink_min,
        "shrink_max": round(max(combined.shrink_max, shrink_min), 4),
        "stiff_group": GROUP_PREFIX + "stiff" if max_factor > 1.0 else None,
        "stiffness_max_factor": max_factor,
        "pin_group": GROUP_PREFIX + "pin" if pins else None,
        "sewing": bool(mb.edges),
        "elastics": [e.to_dict() for e in elastics],
    }
    mb.translate(spec.placement.get("offset", (0.0, 0.0, 0.0)))
    data = GarmentMeshData(mb.vertices, mb.faces, mb.edges, mb.groups, components, mb.seams, physics,
                           {"vertices": len(mb.vertices), "faces": len(mb.faces), "sewing_edges": len(mb.edges),
                            "quality": q.name, "measurements": {k: v for k, v in gm.items() if k != "components"},
                            "component_measurements": gm["components"]}, list(mb.warnings))
    problems = data.validate()
    if problems:
        raise GarmentError("GEOMETRY_INVALID", f"Generated garment geometry is invalid: {problems[0]}",
                           details={"problems": problems})
    return data


def signed_clearance(points: Sequence[Vec3], nearest) -> List[float]:
    """Signed distance of each point to a surface using ``nearest(p) -> (loc, normal)``."""
    out = []
    for p in points:
        loc, normal = nearest(p)
        out.append(dot(sub(p, loc), normal) if loc is not None else float("inf"))
    return out


def push_out(points: List[Vec3], nearest, margin: float) -> int:
    """Move points that are inside / closer than ``margin`` to the surface out along the normal."""
    moved = 0
    for i, p in enumerate(points):
        loc, normal = nearest(p)
        if loc is None:
            continue
        d = dot(sub(p, loc), normal)
        if d < margin:
            points[i] = add(p, scale(normalize(normal), margin - d))
            moved += 1
    return moved

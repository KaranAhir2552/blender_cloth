"""Synthetic humanoid used by pure, mock and real-Blender tests.

This is NOT a MakeHuman mesh. It is a lofted-ellipse mannequin with
anthropometric proportions (Drillis & Contini segment ratios). Bone names
follow several rig conventions so bone-name resolution can be tested.

Coordinate convention: Z up, character faces -Y (Blender convention), metres.
"""
import math

# --- bone naming conventions -------------------------------------------------
RIG_NAMES = {
    "makehuman": {
        "hips": "root", "spine_low": "spine05", "spine_mid": "spine03", "chest": "spine01",
        "neck": "neck01", "head": "head",
        "clavicle_L": "clavicle.L", "upperarm_L": "upperarm01.L", "forearm_L": "lowerarm01.L", "hand_L": "wrist.L",
        "thigh_L": "upperleg01.L", "shin_L": "lowerleg01.L", "foot_L": "foot.L",
        "clavicle_R": "clavicle.R", "upperarm_R": "upperarm01.R", "forearm_R": "lowerarm01.R", "hand_R": "wrist.R",
        "thigh_R": "upperleg01.R", "shin_R": "lowerleg01.R", "foot_R": "foot.R",
    },
    "game_engine": {
        "hips": "pelvis", "spine_low": "spine_01", "spine_mid": "spine_02", "chest": "spine_03",
        "neck": "neck_01", "head": "head",
        "clavicle_L": "clavicle_l", "upperarm_L": "upperarm_l", "forearm_L": "lowerarm_l", "hand_L": "hand_l",
        "thigh_L": "thigh_l", "shin_L": "calf_l", "foot_L": "foot_l",
        "clavicle_R": "clavicle_r", "upperarm_R": "upperarm_r", "forearm_R": "lowerarm_r", "hand_R": "hand_r",
        "thigh_R": "thigh_r", "shin_R": "calf_r", "foot_R": "foot_r",
    },
    "rigify": {
        "hips": "DEF-spine", "spine_low": "DEF-spine.001", "spine_mid": "DEF-spine.002", "chest": "DEF-spine.003",
        "neck": "DEF-spine.004", "head": "DEF-spine.006",
        "clavicle_L": "DEF-shoulder.L", "upperarm_L": "DEF-upper_arm.L", "forearm_L": "DEF-forearm.L", "hand_L": "DEF-hand.L",
        "thigh_L": "DEF-thigh.L", "shin_L": "DEF-shin.L", "foot_L": "DEF-foot.L",
        "clavicle_R": "DEF-shoulder.R", "upperarm_R": "DEF-upper_arm.R", "forearm_R": "DEF-forearm.R", "hand_R": "DEF-hand.R",
        "thigh_R": "DEF-thigh.R", "shin_R": "DEF-shin.R", "foot_R": "DEF-foot.R",
    },
    "mixamo": {
        "hips": "mixamorig:Hips", "spine_low": "mixamorig:Spine", "spine_mid": "mixamorig:Spine1", "chest": "mixamorig:Spine2",
        "neck": "mixamorig:Neck", "head": "mixamorig:Head",
        "clavicle_L": "mixamorig:LeftShoulder", "upperarm_L": "mixamorig:LeftArm", "forearm_L": "mixamorig:LeftForeArm", "hand_L": "mixamorig:LeftHand",
        "thigh_L": "mixamorig:LeftUpLeg", "shin_L": "mixamorig:LeftLeg", "foot_L": "mixamorig:LeftFoot",
        "clavicle_R": "mixamorig:RightShoulder", "upperarm_R": "mixamorig:RightArm", "forearm_R": "mixamorig:RightForeArm", "hand_R": "mixamorig:RightHand",
        "thigh_R": "mixamorig:RightUpLeg", "shin_R": "mixamorig:RightLeg", "foot_R": "mixamorig:RightFoot",
    },
}

SEGMENTS = 24


def _basis(axis):
    """u = sideways (X projected off the axis), v = axis x u, so u x v = axis
    and quads built ring-by-ring along +axis have outward normals."""
    ax = _norm(axis)
    for prefer in ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)):
        d = sum(p * a for p, a in zip(prefer, ax))
        u = tuple(p - a * d for p, a in zip(prefer, ax))
        if sum(c * c for c in u) > 0.01:
            u = _norm(u)
            break
    v = _cross(ax, u)
    return u, v


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a):
    length = math.sqrt(sum(c * c for c in a)) or 1.0
    return tuple(c / length for c in a)


class _Builder:
    def __init__(self):
        self.vertices = []
        self.faces = []
        self.groups = {}

    def tube(self, group, rings, axis):
        """rings: list of (center, a, b); a along u (sideways), b along v."""
        u, v = _basis(axis)
        start = len(self.vertices)
        for center, a, b in rings:
            for k in range(SEGMENTS):
                t = 2.0 * math.pi * k / SEGMENTS
                ca, sa = math.cos(t) * a, math.sin(t) * b
                self.vertices.append(tuple(center[i] + ca * u[i] + sa * v[i] for i in range(3)))
        for r in range(len(rings) - 1):
            for k in range(SEGMENTS):
                k2 = (k + 1) % SEGMENTS
                a0 = start + r * SEGMENTS + k
                a1 = start + r * SEGMENTS + k2
                b1 = start + (r + 1) * SEGMENTS + k2
                b0 = start + (r + 1) * SEGMENTS + k
                self.faces.append((a0, a1, b1, b0))
        self.groups.setdefault(group, []).extend(range(start, len(self.vertices)))


def _lerp_table(table, x):
    if x <= table[0][0]:
        return table[0][1:]
    for (x0, *v0), (x1, *v1) in zip(table, table[1:]):
        if x0 <= x <= x1:
            t = (x - x0) / (x1 - x0)
            return tuple(a + (b - a) * t for a, b in zip(v0, v1))
    return table[-1][1:]


def make_humanoid(height=1.75, pose="A", rig="makehuman", scale=1.0):
    """Return dict(vertices, faces, bones, vertex_groups, properties, expected).

    ``scale`` multiplies all coordinates (use 10.0 to emulate a decimetre import).
    """
    H = height
    b = _Builder()
    # torso: (z fraction of H, half width, half depth)
    torso_table = [
        (0.47, 0.15, 0.11),
        (0.52, 0.18, 0.13),   # hips (widest)
        (0.63, 0.145, 0.10),  # natural waist
        (0.72, 0.165, 0.12),  # chest
        (0.79, 0.19, 0.11),   # shoulders / deltoids
        (0.83, 0.10, 0.08),
        (0.845, 0.06, 0.06),  # neck
        (0.875, 0.06, 0.06),
    ]
    rings = []
    z = 0.47 * H
    while z <= 0.875 * H + 1e-9:
        a, d = _lerp_table(torso_table, z / H)
        rings.append(((0.0, 0.0, z), a * H / 1.75, d * H / 1.75))
        z += 0.02
    # For a +Z tube, u = x (sideways) and v = y (depth).
    b.tube("spine03", rings, (0.0, 0.0, 1.0))

    # head ellipsoid
    head_c = 0.94 * H
    rings = []
    for i in range(1, 13):
        zz = 0.88 * H + (H - 0.88 * H) * i / 12.0
        t = (zz - head_c) / (0.065 * H)
        f = math.sqrt(max(0.05, 1.0 - t * t))
        rings.append(((0.0, 0.0, zz), 0.075 * f * H / 1.75, 0.095 * f * H / 1.75))
    b.tube("head", rings, (0.0, 0.0, 1.0))

    shoulder_z = 0.818 * H
    shoulder_x = 0.1295 * H  # half of 0.259H biacromial width
    arm_angle = math.radians(45.0 if pose == "A" else 90.0 if pose == "T" else 10.0)
    upper, fore, hand = 0.186 * H, 0.146 * H, 0.108 * H
    bones = {}

    def add_bone(role, head, tail):
        bones[role] = (tuple(head), tuple(tail))

    add_bone("hips", (0, 0, 0.53 * H), (0, 0, 0.58 * H))
    add_bone("spine_low", (0, 0, 0.58 * H), (0, 0, 0.65 * H))
    add_bone("spine_mid", (0, 0, 0.65 * H), (0, 0, 0.72 * H))
    add_bone("chest", (0, 0, 0.72 * H), (0, 0, 0.83 * H))
    add_bone("neck", (0, 0, 0.845 * H), (0, 0, 0.88 * H))
    add_bone("head", (0, 0, 0.88 * H), (0, 0, H))

    for side, sx in (("L", 1.0), ("R", -1.0)):
        direction = (sx * math.sin(arm_angle), 0.0, -math.cos(arm_angle))
        sh = (sx * shoulder_x, 0.0, shoulder_z)
        el = tuple(sh[i] + direction[i] * upper for i in range(3))
        wr = tuple(el[i] + direction[i] * fore for i in range(3))
        hd = tuple(wr[i] + direction[i] * hand for i in range(3))
        add_bone("clavicle_" + side, (sx * 0.02 * H, 0, 0.81 * H), sh)
        add_bone("upperarm_" + side, sh, el)
        add_bone("forearm_" + side, el, wr)
        add_bone("hand_" + side, wr, hd)
        arm_rings = []
        n = 14
        for i in range(n + 1):
            t = i / n
            p = tuple(sh[k] + direction[k] * (upper + fore) * t for k in range(3))
            r = (0.05 + (0.03 - 0.05) * t) * H / 1.75
            arm_rings.append((p, r, r))
        b.tube(("upperarm01." if rig == "makehuman" else "arm.") + side, arm_rings, direction)

        hip = (sx * 0.051 * H, 0.0, 0.53 * H)
        knee = (sx * 0.051 * H, 0.0, 0.285 * H)
        ankle = (sx * 0.051 * H, 0.0, 0.039 * H)
        add_bone("thigh_" + side, hip, knee)
        add_bone("shin_" + side, knee, ankle)
        add_bone("foot_" + side, ankle, (ankle[0], -0.1 * H, 0.0))
        leg_rings = []
        z = 0.56 * H
        while z >= 0.039 * H - 1e-9:
            frac = z / H
            r = _lerp_table([(0.039, 0.035), (0.285, 0.055), (0.47, 0.085), (0.56, 0.09)], frac)[0] * H / 1.75
            leg_rings.append(((hip[0], 0.0, z), r, r))
            z -= 0.03
        leg_rings.append(((hip[0], -0.02 * H, 0.0), 0.04 * H / 1.75, 0.06 * H / 1.75))  # foot sole at floor
        b.tube(("upperleg01." if rig == "makehuman" else "leg.") + side, leg_rings, (0.0, 0.0, -1.0))

    names = RIG_NAMES[rig]
    named_bones = {names[role]: ht for role, ht in bones.items()}

    if scale != 1.0:
        b.vertices = [tuple(c * scale for c in v) for v in b.vertices]
        named_bones = {k: (tuple(c * scale for c in h), tuple(c * scale for c in t)) for k, (h, t) in named_bones.items()}

    props = {"MPFB_GEN_object_type": "Basemesh"} if rig == "makehuman" else {}
    expected = {
        "height": H,
        "chest_circumference": 0.90 * H / 1.75,
        "waist_circumference": 0.78 * H / 1.75,
        "hip_circumference": 0.98 * H / 1.75,
        "shoulder_width": 0.259 * H,
        "arm_length": upper + fore,
    }
    return {
        "vertices": b.vertices,
        "faces": b.faces,
        "bones": named_bones,
        "vertex_groups": b.groups,
        "properties": props,
        "expected": expected,
        "rig": rig,
    }

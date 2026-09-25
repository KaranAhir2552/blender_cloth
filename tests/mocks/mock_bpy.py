"""A deliberately *minimal and strict* mock of the parts of bpy/mathutils used
by ai_garment.

* Settings structs only accept attribute names that exist in Blender 4.2
  (taken from the fake-bpy-module-4.2 stubs). Setting an unknown attribute
  raises AttributeError like real bpy_structs do.
* ``Mesh.from_pydata`` refuses to run on a non-empty mesh (real Blender would
  corrupt/append geometry) so update paths must call ``clear_geometry``.
* No physics is simulated. Tests can install ``bpy._physics_stub`` =
  ``fn(obj, frame, base_coords) -> coords`` to emulate cloth motion.
* ``bpy._snapshot()`` returns a structural summary used to prove that dry
  runs and invalid plans do not mutate the scene.

This mock proves call-shape correctness against *our model* of Blender. It
does not prove real Blender behaviour.
"""
import contextlib
import math
import sys
import types

# ----------------------------------------------------------------------------
# mathutils
# ----------------------------------------------------------------------------


class Vector(tuple):
    def __new__(cls, seq=(0.0, 0.0, 0.0)):
        return super().__new__(cls, (float(c) for c in seq))

    x = property(lambda s: s[0])
    y = property(lambda s: s[1])
    z = property(lambda s: s[2])

    def __add__(self, o):
        return Vector(a + b for a, b in zip(self, o))

    def __sub__(self, o):
        return Vector(a - b for a, b in zip(self, o))

    def __mul__(self, k):
        return Vector(a * k for a in self)

    __rmul__ = __mul__

    def __neg__(self):
        return Vector(-a for a in self)

    def dot(self, o):
        return sum(a * b for a, b in zip(self, o))

    def cross(self, o):
        return Vector((self[1] * o[2] - self[2] * o[1], self[2] * o[0] - self[0] * o[2], self[0] * o[1] - self[1] * o[0]))

    @property
    def length(self):
        return math.sqrt(sum(a * a for a in self))

    def normalized(self):
        n = self.length or 1.0
        return Vector(a / n for a in self)

    def copy(self):
        return Vector(self)

    def to_tuple(self):
        return tuple(self)


class Matrix:
    """Translation-only 4x4 matrix (all mock objects are unrotated, unscaled)."""

    def __init__(self, translation=(0.0, 0.0, 0.0)):
        self.translation = Vector(translation)

    @classmethod
    def Identity(cls, size=4):
        return cls()

    def __matmul__(self, v):
        if isinstance(v, Matrix):
            return Matrix(self.translation + v.translation)
        return Vector(v) + self.translation

    def inverted(self):
        return Matrix(-self.translation)

    def copy(self):
        return Matrix(self.translation)


class _Grid:
    def __init__(self, points, cell=0.05):
        self.cell = cell
        self.points = points
        self.cells = {}
        for i, p in enumerate(points):
            self.cells.setdefault(self._key(p), []).append(i)

    def _key(self, p):
        c = self.cell
        return (math.floor(p[0] / c), math.floor(p[1] / c), math.floor(p[2] / c))

    def nearest(self, q, max_rings=40):
        kx, ky, kz = self._key(q)
        best, best_d = None, float("inf")
        for r in range(max_rings):
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    for dz in range(-r, r + 1):
                        if max(abs(dx), abs(dy), abs(dz)) != r:
                            continue
                        for i in self.cells.get((kx + dx, ky + dy, kz + dz), ()):
                            p = self.points[i]
                            d = (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2
                            if d < best_d:
                                best, best_d = i, d
            if best is not None and math.sqrt(best_d) < r * self.cell:
                break
        return best, math.sqrt(best_d) if best is not None else None


class BVHTree:
    """Nearest-*vertex* approximation of mathutils.bvhtree.BVHTree."""

    def __init__(self, vertices, polygons):
        self.vertices = [Vector(v) for v in vertices]
        normals = [Vector((0.0, 0.0, 0.0)) for _ in self.vertices]
        for poly in polygons:
            pts = [self.vertices[i] for i in poly]
            n = Vector((0.0, 0.0, 0.0))
            for a, b in zip(pts, pts[1:] + pts[:1]):
                n = n + Vector(((a.y - b.y) * (a.z + b.z), (a.z - b.z) * (a.x + b.x), (a.x - b.x) * (a.y + b.y)))
            for i in poly:
                normals[i] = normals[i] + n
        self.normals = [n.normalized() for n in normals]
        self.grid = _Grid(self.vertices)

    @classmethod
    def FromPolygons(cls, vertices, polygons, all_triangles=False, epsilon=0.0):
        return cls(vertices, polygons)

    @classmethod
    def FromObject(cls, obj, depsgraph, deform=True, render=False, cage=False, epsilon=0.0):
        mesh = obj.evaluated_get(depsgraph).to_mesh()
        verts = [obj.matrix_world @ v.co for v in mesh.vertices]
        return cls(verts, [p.vertices for p in mesh.polygons])

    def find_nearest(self, origin, distance=1.84467e19):
        i, d = self.grid.nearest(origin)
        if i is None or d > distance:
            return (None, None, None, None)
        return (self.vertices[i], self.normals[i], i, d)


# ----------------------------------------------------------------------------
# strict struct machinery
# ----------------------------------------------------------------------------


class StrictStruct:
    _fields = {}
    _readonly = ()

    def __init__(self, **overrides):
        for k, v in self._fields.items():
            object.__setattr__(self, k, _copy_default(v))
        for k, v in overrides.items():
            object.__setattr__(self, k, v)

    def __setattr__(self, key, value):
        if key.startswith("_"):
            object.__setattr__(self, key, value)
            return
        if key in self._readonly:
            raise AttributeError(f"bpy_struct: attribute \"{key}\" from \"{type(self).__name__}\" is read-only")
        if key not in self._fields:
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{key}'")
        object.__setattr__(self, key, value)


def _copy_default(v):
    if isinstance(v, (list, dict)):
        return type(v)(v)
    if isinstance(v, Vector):
        return Vector(v)
    return v


class EffectorWeights(StrictStruct):
    _fields = {k: 1.0 for k in ["all", "boid", "charge", "curve_guide", "drag", "force", "gravity", "harmonic",
                                "lennardjones", "magnetic", "smokeflow", "texture", "turbulence", "vortex", "wind"]}
    _fields.update({"apply_to_hair_growing": False, "collection": None})


CLOTH_SETTINGS_FIELDS = {
    "air_damping": 1.0, "bending_damping": 0.5, "bending_model": "ANGULAR", "bending_stiffness": 0.5,
    "bending_stiffness_max": 0.5, "collider_friction": 0.0, "compression_damping": 5.0, "compression_stiffness": 15.0,
    "compression_stiffness_max": 15.0, "density_strength": 0.0, "density_target": 0.0, "fluid_density": 0.0,
    "goal_default": 1.0, "goal_friction": 0.0, "goal_max": 1.0, "goal_min": 0.0, "goal_spring": 0.5,
    "gravity": Vector((0.0, 0.0, -9.81)), "internal_compression_stiffness": 15.0,
    "internal_compression_stiffness_max": 15.0, "internal_friction": 0.0, "internal_spring_max_diversion": 0.785,
    "internal_spring_max_length": 0.0, "internal_spring_normal_check": False, "internal_tension_stiffness": 15.0,
    "internal_tension_stiffness_max": 15.0, "mass": 0.3, "pin_stiffness": 1.0, "pressure_factor": 1.0, "quality": 5,
    "rest_shape_key": None, "sewing_force_max": 0.0, "shear_damping": 5.0, "shear_stiffness": 5.0,
    "shear_stiffness_max": 5.0, "shrink_max": 0.0, "shrink_min": 0.0, "target_volume": 0.0, "tension_damping": 5.0,
    "tension_stiffness": 15.0, "tension_stiffness_max": 15.0, "time_scale": 1.0, "uniform_pressure_force": 0.0,
    "use_dynamic_mesh": False, "use_internal_springs": False, "use_pressure": False, "use_pressure_volume": False,
    "use_sewing_springs": False, "vertex_group_bending": "", "vertex_group_intern": "", "vertex_group_mass": "",
    "vertex_group_pressure": "", "vertex_group_shear_stiffness": "", "vertex_group_shrink": "",
    "vertex_group_structural_stiffness": "", "voxel_cell_size": 0.1,
    "effector_weights": None,
}


class ClothSettings(StrictStruct):
    _fields = CLOTH_SETTINGS_FIELDS
    _readonly = ("effector_weights",)

    def __init__(self):
        super().__init__()
        object.__setattr__(self, "effector_weights", EffectorWeights())


class ClothCollisionSettings(StrictStruct):
    _fields = {
        "collection": None, "collision_quality": 2, "damping": 0.0, "distance_min": 0.015, "friction": 5.0,
        "impulse_clamp": 0.0, "self_distance_min": 0.015, "self_friction": 5.0, "self_impulse_clamp": 0.0,
        "use_collision": True, "use_self_collision": False, "vertex_group_object_collisions": "",
        "vertex_group_self_collisions": "",
    }


class CollisionSettings(StrictStruct):
    _fields = {
        "absorption": 0.0, "cloth_friction": 5.0, "damping": 0.1, "damping_factor": 0.0, "damping_random": 0.0,
        "friction_factor": 0.0, "friction_random": 0.0, "permeability": 0.0, "stickiness": 0.0,
        "thickness_inner": 0.2, "thickness_outer": 0.02, "use": True, "use_culling": True, "use_normal": False,
        "use_particle_kill": False,
    }


class PointCache(StrictStruct):
    _fields = {"compression": "NO", "filepath": "", "frame_end": 250, "frame_start": 1, "frame_step": 1,
               "index": -1, "name": "", "use_disk_cache": False, "use_external": False, "use_library_path": True}

    def __init__(self):
        super().__init__()
        self._baked = False

    @property
    def is_baked(self):
        return self._baked

    @property
    def is_outdated(self):
        return False

    @property
    def info(self):
        return "mock cache"


# ----------------------------------------------------------------------------
# modifiers
# ----------------------------------------------------------------------------

_MOD_COMMON = {"name": "", "show_viewport": True, "show_render": True, "show_in_editmode": False,
               "show_on_cage": False, "show_expanded": True}


class Modifier(StrictStruct):
    _fields = dict(_MOD_COMMON)
    _readonly = ("type",)
    TYPE = "NONE"

    def __init__(self, name):
        super().__init__(name=name)
        object.__setattr__(self, "type", self.TYPE)


class ClothModifier(Modifier):
    TYPE = "CLOTH"
    _readonly = ("type", "settings", "collision_settings", "point_cache")

    def __init__(self, name):
        super().__init__(name)
        object.__setattr__(self, "settings", ClothSettings())
        object.__setattr__(self, "collision_settings", ClothCollisionSettings())
        object.__setattr__(self, "point_cache", PointCache())


class CollisionModifier(Modifier):
    TYPE = "COLLISION"
    _readonly = ("type", "settings")


class MaskModifier(Modifier):
    TYPE = "MASK"
    _fields = dict(_MOD_COMMON, armature=None, invert_vertex_group=False, mode="VERTEX_GROUP", threshold=0.0,
                   use_smooth=False, vertex_group="")


class DecimateModifier(Modifier):
    TYPE = "DECIMATE"
    _fields = dict(_MOD_COMMON, angle_limit=0.087, decimate_type="COLLAPSE", delimit=set(), invert_vertex_group=False,
                   iterations=0, ratio=1.0, symmetry_axis="X", use_collapse_triangulate=False,
                   use_dissolve_boundaries=False, use_symmetry=False, vertex_group="", vertex_group_factor=1.0)


class SolidifyModifier(Modifier):
    TYPE = "SOLIDIFY"
    _fields = dict(_MOD_COMMON, offset=-1.0, thickness=0.01, use_even_offset=False, use_quality_normals=False,
                   use_rim=True, use_rim_only=False, use_flip_normals=False, vertex_group="",
                   solidify_mode="EXTRUDE", nonmanifold_thickness_mode="CONSTRAINTS")


class SubsurfModifier(Modifier):
    TYPE = "SUBSURF"
    _fields = dict(_MOD_COMMON, levels=1, render_levels=2, quality=3, subdivision_type="CATMULL_CLARK",
                   boundary_smooth="ALL", use_creases=True, use_custom_normals=False, use_limit_surface=True,
                   uv_smooth="PRESERVE_BOUNDARIES", show_only_control_edges=True)


class ArmatureModifier(Modifier):
    TYPE = "ARMATURE"
    _fields = dict(_MOD_COMMON, object=None, use_vertex_groups=True, use_bone_envelopes=False,
                   use_deform_preserve_volume=False, use_multi_modifier=False, vertex_group="",
                   invert_vertex_group=False)


MODIFIER_TYPES = {c.TYPE: c for c in (ClothModifier, CollisionModifier, MaskModifier, DecimateModifier,
                                      SolidifyModifier, SubsurfModifier, ArmatureModifier)}


class ObjectModifiers:
    def __init__(self, owner):
        self._owner = owner
        self._items = []

    def new(self, name, type):
        if type not in MODIFIER_TYPES:
            raise TypeError(f"ObjectModifiers.new(): enum \"{type}\" not found (mock supports {sorted(MODIFIER_TYPES)})")
        if self._owner.type != "MESH":
            raise RuntimeError("mock: modifiers only supported on meshes")
        if type in ("CLOTH", "COLLISION") and any(m.type == type for m in self._items):
            raise RuntimeError(f"mock: object already has a {type} modifier")
        mod = MODIFIER_TYPES[type](_unique_name(name, [m.name for m in self._items]))
        if type == "COLLISION":
            if self._owner.collision is None:
                object.__setattr__(self._owner, "collision", CollisionSettings())
            object.__setattr__(mod, "settings", self._owner.collision)
        self._items.append(mod)
        _BPY._log("modifier.new", self._owner.name, type)
        return mod

    def remove(self, mod):
        self._items.remove(mod)
        if mod.type == "COLLISION":
            object.__setattr__(self._owner, "collision", None)
        _BPY._log("modifier.remove", self._owner.name, mod.type)

    def get(self, name, default=None):
        for m in self._items:
            if m.name == name:
                return m
        return default

    def __iter__(self):
        return iter(list(self._items))

    def __len__(self):
        return len(self._items)

    def __getitem__(self, k):
        if isinstance(k, int):
            return self._items[k]
        m = self.get(k)
        if m is None:
            raise KeyError(k)
        return m

    def find(self, name):
        for i, m in enumerate(self._items):
            if m.name == name:
                return i
        return -1


# ----------------------------------------------------------------------------
# mesh / vertex groups / shape keys
# ----------------------------------------------------------------------------


class VertexGroupElement:
    def __init__(self, group, weight):
        self.group = group
        self.weight = weight


class MeshVertex:
    def __init__(self, index, co):
        self.index = index
        self.co = Vector(co)
        self.groups = []
        self.normal = Vector((0.0, 0.0, 1.0))


class MeshEdge:
    def __init__(self, index, verts):
        self.index = index
        self.vertices = tuple(verts)


class MeshPolygon:
    def __init__(self, index, verts):
        self.index = index
        self.vertices = tuple(verts)


class _MaterialSlots(list):
    def append(self, m):
        super().append(m)


class ShapeKeyPoint:
    def __init__(self, co):
        self.co = Vector(co)


class ShapeKey:
    def __init__(self, name, coords):
        self.name = name
        self.value = 0.0
        self.data = [ShapeKeyPoint(c) for c in coords]
        self.mute = False


class Key:
    def __init__(self):
        self.key_blocks = _NamedList()
        self.use_relative = True

    @property
    def reference_key(self):
        return self.key_blocks[0]


class _NamedList(list):
    def get(self, name, default=None):
        for x in self:
            if x.name == name:
                return x
        return default

    def __getitem__(self, k):
        if isinstance(k, str):
            v = self.get(k)
            if v is None:
                raise KeyError(k)
            return v
        return super().__getitem__(k)

    def find(self, name):
        for i, x in enumerate(self):
            if x.name == name:
                return i
        return -1


class Mesh:
    def __init__(self, name):
        self.name = name
        self.vertices = []
        self.edges = []
        self.polygons = []
        self.materials = _MaterialSlots()
        self.shape_keys = None
        self.users = 0
        self._custom = {}

    def from_pydata(self, vertices, edges, faces, shade_flat=True):
        if self.vertices:
            raise RuntimeError("mock: from_pydata called on a non-empty mesh (call clear_geometry first)")
        self.vertices = [MeshVertex(i, v) for i, v in enumerate(vertices)]
        n = len(self.vertices)
        for e in edges:
            if not all(0 <= i < n for i in e) or e[0] == e[1]:
                raise ValueError(f"mock: invalid edge {e}")
        for f in faces:
            if len(f) < 3 or not all(0 <= i < n for i in f) or len(set(f)) != len(f):
                raise ValueError(f"mock: invalid face {f}")
        self.edges = [MeshEdge(i, e) for i, e in enumerate(edges)]
        self.polygons = [MeshPolygon(i, f) for i, f in enumerate(faces)]
        _BPY._log("mesh.from_pydata", self.name, len(vertices))

    def clear_geometry(self):
        self.vertices, self.edges, self.polygons = [], [], []
        self.shape_keys = None
        _BPY._log("mesh.clear_geometry", self.name)

    def update(self, calc_edges=False, calc_edges_loose=False):
        pass

    def validate(self, verbose=False, clean_customdata=True):
        return False

    def copy(self):
        m = Mesh(self.name)
        m.name = _unique_name(self.name, [x.name for x in _BPY.data.meshes])
        m.vertices = [MeshVertex(v.index, v.co) for v in self.vertices]
        for src, dst in zip(self.vertices, m.vertices):
            dst.groups = [VertexGroupElement(g.group, g.weight) for g in src.groups]
        m.edges = [MeshEdge(e.index, e.vertices) for e in self.edges]
        m.polygons = [MeshPolygon(p.index, p.vertices) for p in self.polygons]
        _BPY.data.meshes._add(m)
        return m


class VertexGroup:
    def __init__(self, obj, name, index):
        self._obj = obj
        self.name = name
        self.index = index
        self.lock_weight = False

    def add(self, index, weight, type):
        if type not in ("REPLACE", "ADD", "SUBTRACT"):
            raise TypeError(f"bad type {type}")
        verts = self._obj.data.vertices
        for i in index:
            v = verts[i]
            for g in v.groups:
                if g.group == self.index:
                    g.weight = weight if type == "REPLACE" else min(1.0, g.weight + weight)
                    break
            else:
                v.groups.append(VertexGroupElement(self.index, float(weight)))

    def remove(self, index):
        for i in index:
            v = self._obj.data.vertices[i]
            v.groups = [g for g in v.groups if g.group != self.index]

    def weight(self, index):
        for g in self._obj.data.vertices[index].groups:
            if g.group == self.index:
                return g.weight
        raise RuntimeError("Vertex not in group")


class VertexGroups(_NamedList):
    def __init__(self, obj):
        super().__init__()
        self._obj = obj

    def new(self, name="Group"):
        vg = VertexGroup(self._obj, _unique_name(name, [g.name for g in self]), len(self))
        self.append(vg)
        return vg

    def remove(self, group):
        for v in self._obj.data.vertices:
            v.groups = [g for g in v.groups if g.group != group.index]
        list.remove(self, group)


# ----------------------------------------------------------------------------
# objects / armatures
# ----------------------------------------------------------------------------


class Bone:
    def __init__(self, name, head, tail):
        self.name = name
        self.head_local = Vector(head)
        self.tail_local = Vector(tail)


class PoseBone:
    def __init__(self, name, head, tail):
        self.name = name
        self.head = Vector(head)
        self.tail = Vector(tail)


class Armature:
    def __init__(self, name):
        self.name = name
        self.bones = _NamedList()


class Pose:
    def __init__(self):
        self.bones = _NamedList()


class Object:
    def __init__(self, name, data):
        self.name = name
        self.data = data
        if data is None:
            self.type = "EMPTY"
        elif isinstance(data, Mesh):
            self.type = "MESH"
            data.users += 1
        elif isinstance(data, Armature):
            self.type = "ARMATURE"
        else:
            raise TypeError("mock: unsupported object data")
        self.location = Vector((0.0, 0.0, 0.0))
        self.modifiers = ObjectModifiers(self)
        self.vertex_groups = VertexGroups(self)
        self.collision = None
        self.parent = None
        self.hide_render = False
        self.hide_viewport = False
        self.hide_select = False
        self.display_type = "TEXTURED"
        self.pose = Pose() if self.type == "ARMATURE" else None
        self.active_material = None
        self._props = {}
        self._selected = False
        self._hidden = False

    # custom properties -----------------------------------------------------
    def __getitem__(self, k):
        return self._props[k]

    def __setitem__(self, k, v):
        if not isinstance(v, (str, int, float, bool, list, dict)):
            raise TypeError("mock: unsupported ID property type")
        self._props[k] = v
        _BPY._log("prop.set", self.name, k)

    def __delitem__(self, k):
        del self._props[k]

    def __contains__(self, k):
        return k in self._props

    def get(self, k, default=None):
        return self._props.get(k, default)

    def keys(self):
        return list(self._props.keys())

    # misc ------------------------------------------------------------------
    @property
    def matrix_world(self):
        m = Matrix(self.location)
        if self.parent is not None:
            m = self.parent.matrix_world @ m
        return m

    @property
    def users_collection(self):
        return tuple(c for c in _BPY.data.collections._all() if self in c.objects)

    def select_set(self, state, view_layer=None):
        self._selected = bool(state)

    def select_get(self, view_layer=None):
        return self._selected

    def hide_set(self, state, view_layer=None):
        self._hidden = bool(state)

    def hide_get(self, view_layer=None):
        return self._hidden

    def find_armature(self):
        for m in self.modifiers:
            if m.type == "ARMATURE" and m.object is not None:
                return m.object
        if self.parent is not None and self.parent.type == "ARMATURE":
            return self.parent
        return None

    def copy(self):
        o = Object(_unique_name(self.name, [x.name for x in _BPY.data.objects]), self.data)
        o.location = Vector(self.location)
        o.parent = self.parent
        o._props = dict(self._props)
        for m in self.modifiers:
            nm = o.modifiers.new(m.name, m.type)
            for k in m._fields:
                if k != "name":
                    object.__setattr__(nm, k, getattr(m, k))
        for g in self.vertex_groups:
            o.vertex_groups.new(name=g.name)
        _BPY.data.objects._add(o)
        _BPY._log("object.copy", self.name, o.name)
        return o

    def shape_key_add(self, name="Key", from_mix=True):
        mesh = self.data
        if mesh.shape_keys is None:
            mesh.shape_keys = Key()
            mesh.shape_keys.key_blocks.append(ShapeKey("Basis", [v.co for v in mesh.vertices]))
            if name == "Basis":
                return mesh.shape_keys.key_blocks[0]
        sk = ShapeKey(_unique_name(name, [k.name for k in mesh.shape_keys.key_blocks]), [v.co for v in mesh.vertices])
        mesh.shape_keys.key_blocks.append(sk)
        _BPY._log("shape_key_add", self.name, sk.name)
        return sk

    def shape_key_remove(self, key):
        self.data.shape_keys.key_blocks.remove(key)
        if len(self.data.shape_keys.key_blocks) <= 1:
            self.data.shape_keys = None

    def evaluated_get(self, depsgraph):
        return EvaluatedObject(self, depsgraph)

    def to_mesh(self):
        return self.data


class EvaluatedObject:
    def __init__(self, obj, depsgraph):
        self.original = obj
        self._depsgraph = depsgraph
        self.name = obj.name
        self.type = obj.type
        self.matrix_world = obj.matrix_world
        self.modifiers = obj.modifiers

    def _coords(self):
        mesh = self.original.data
        base = [v.co for v in mesh.vertices]
        keys = mesh.shape_keys
        if keys is not None:
            ref = keys.key_blocks[0]
            base = list(base)
            for kb in keys.key_blocks[1:]:
                if kb.mute or kb.value == 0.0:
                    continue
                base = [b + (Vector(p.co) - Vector(r.co)) * kb.value for b, p, r in zip(base, kb.data, ref.data)]
        stub = _BPY._physics_stub
        has_cloth = any(m.type == "CLOTH" for m in self.original.modifiers)
        if stub is not None and has_cloth:
            base = [Vector(c) for c in stub(self.original, _BPY.context.scene.frame_current, base)]
        return base

    def to_mesh(self, preserve_all_data_layers=False, depsgraph=None):
        src = self.original.data
        m = Mesh(src.name + "_eval")
        m.vertices = [MeshVertex(i, c) for i, c in enumerate(self._coords())]
        m.edges = src.edges
        m.polygons = src.polygons
        return m

    def to_mesh_clear(self):
        pass

    @property
    def data(self):
        return self.to_mesh()


# ----------------------------------------------------------------------------
# collections / data blocks
# ----------------------------------------------------------------------------


class _CollectionObjects(list):
    def __init__(self, owner):
        super().__init__()
        self._owner = owner

    def link(self, obj):
        if obj in self:
            raise RuntimeError(f"Object '{obj.name}' already in collection '{self._owner.name}'")
        self.append(obj)
        _BPY._log("collection.link", self._owner.name, obj.name)

    def unlink(self, obj):
        self.remove(obj)

    def get(self, name, default=None):
        for o in self:
            if o.name == name:
                return o
        return default


class _CollectionChildren(list):
    def link(self, c):
        self.append(c)

    def unlink(self, c):
        self.remove(c)

    def get(self, name, default=None):
        for c in self:
            if c.name == name:
                return c
        return default


class Collection:
    def __init__(self, name):
        self.name = name
        self.objects = _CollectionObjects(self)
        self.children = _CollectionChildren()
        self.hide_render = False
        self.hide_viewport = False

    @property
    def all_objects(self):
        out = list(self.objects)
        for c in self.children:
            for o in c.all_objects:
                if o not in out:
                    out.append(o)
        return out


class _DataCollection:
    def __init__(self, factory=None):
        self._items = []
        self._factory = factory

    def _add(self, item):
        self._items.append(item)
        return item

    def new(self, name, *args):
        item = self._factory(_unique_name(name, [x.name for x in self._items]), *args)
        _BPY._log("data.new", type(item).__name__, item.name)
        return self._add(item)

    def get(self, name, default=None):
        for x in self._items:
            if x.name == name:
                return x
        return default

    def remove(self, item, do_unlink=True):
        if item not in self._items:
            raise ReferenceError("mock: item already removed")
        self._items.remove(item)
        _BPY._log("data.remove", type(item).__name__, item.name)

    def __iter__(self):
        return iter(list(self._items))

    def __len__(self):
        return len(self._items)

    def __contains__(self, name_or_item):
        if isinstance(name_or_item, str):
            return self.get(name_or_item) is not None
        return name_or_item in self._items

    def __getitem__(self, name):
        x = self.get(name)
        if x is None:
            raise KeyError(name)
        return x

    def keys(self):
        return [x.name for x in self._items]


class _Objects(_DataCollection):
    def new(self, name, object_data):
        obj = Object(_unique_name(name, [x.name for x in self._items]), object_data)
        _BPY._log("objects.new", obj.name)
        return self._add(obj)

    def remove(self, obj, do_unlink=True):
        for c in _BPY.data.collections._all():
            if obj in c.objects:
                c.objects.remove(obj)
        if obj.type == "MESH":
            obj.data.users -= 1
        super().remove(obj)


class _Meshes(_DataCollection):
    def __init__(self):
        super().__init__(Mesh)

    def new_from_object(self, obj, preserve_all_data_layers=False, depsgraph=None):
        m = obj.to_mesh() if isinstance(obj, EvaluatedObject) else obj.data
        new = Mesh(_unique_name(obj.name, [x.name for x in self._items]))
        new.vertices = [MeshVertex(i, v.co) for i, v in enumerate(m.vertices)]
        new.edges, new.polygons = list(m.edges), list(m.polygons)
        return self._add(new)


class _Collections(_DataCollection):
    def __init__(self):
        super().__init__(Collection)

    def _all(self):
        return [_BPY.context.scene.collection] + list(self._items)


class Material:
    def __init__(self, name):
        self.name = name
        self.diffuse_color = [0.8, 0.8, 0.8, 1.0]
        self.roughness = 0.4
        self._use_nodes = False
        self.node_tree = None
        self._props = {}

    def __setitem__(self, k, v):
        self._props[k] = v

    def __getitem__(self, k):
        return self._props[k]

    def get(self, k, default=None):
        return self._props.get(k, default)

    @property
    def use_nodes(self):
        return self._use_nodes

    @use_nodes.setter
    def use_nodes(self, value):
        self._use_nodes = bool(value)
        if value and self.node_tree is None:
            self.node_tree = NodeTree()


class NodeSocket:
    def __init__(self, name, value):
        self.name = name
        self.default_value = value


class _Inputs(_NamedList):
    pass


class Node:
    def __init__(self, name, inputs):
        self.name = name
        self.inputs = _Inputs(NodeSocket(k, v) for k, v in inputs.items())


class NodeTree:
    def __init__(self):
        self.nodes = _NamedList([
            Node("Principled BSDF", {"Base Color": [0.8, 0.8, 0.8, 1.0], "Roughness": 0.5, "Metallic": 0.0,
                                     "Sheen Weight": 0.0, "Sheen Roughness": 0.5, "Specular IOR Level": 0.5}),
            Node("Material Output", {"Surface": None}),
        ])


class Scene:
    def __init__(self, name="Scene"):
        self.name = name
        self.frame_start = 1
        self.frame_end = 250
        self.frame_current = 1
        self.gravity = Vector((0.0, 0.0, -9.81))
        self.use_gravity = True
        self.collection = Collection("Scene Collection")
        self.render = types.SimpleNamespace(fps=24, fps_base=1.0)
        self.unit_settings = types.SimpleNamespace(scale_length=1.0, system="METRIC", length_unit="METERS")
        self._props = {}

    @property
    def objects(self):
        return self.collection.all_objects

    def frame_set(self, frame, subframe=0.0):
        self.frame_current = int(frame)
        _BPY._frames_set += 1

    def __setitem__(self, k, v):
        self._props[k] = v

    def __getitem__(self, k):
        return self._props[k]

    def get(self, k, default=None):
        return self._props.get(k, default)


class Depsgraph:
    def update(self):
        pass


class _Addons(dict):
    pass


class Context:
    def __init__(self, bpy):
        self._bpy = bpy
        self.scene = Scene()
        self.view_layer = types.SimpleNamespace(update=lambda: None, objects=None)
        self.preferences = types.SimpleNamespace(addons=_Addons())
        self.active_object = None
        self.selected_objects = []
        self.point_cache = None
        self.object = None
        self._depsgraph = Depsgraph()

    def evaluated_depsgraph_get(self):
        return self._depsgraph

    @contextlib.contextmanager
    def temp_override(self, **kwargs):
        saved = {k: getattr(self, k, None) for k in kwargs}
        for k, v in kwargs.items():
            object.__setattr__(self, k, v)
        try:
            yield
        finally:
            for k, v in saved.items():
                object.__setattr__(self, k, v)


# ----------------------------------------------------------------------------
# ops / props / types / utils
# ----------------------------------------------------------------------------


class _OpNamespace:
    def __init__(self, name, ops):
        self._name = name
        for op_name, fn in ops.items():
            setattr(self, op_name, _Op(f"{name}.{op_name}", fn))


class _Op:
    def __init__(self, idname, fn):
        self.idname = idname
        self._fn = fn

    def __call__(self, *args, **kwargs):
        _BPY.ops_log.append((self.idname, kwargs))
        return self._fn(**kwargs)

    def poll(self):
        return True


def _op_bake(bake=False):
    cache = _BPY.context.point_cache
    if cache is None:
        raise RuntimeError("mock ptcache.bake: context has no point_cache (use temp_override)")
    if bake:
        cache._baked = True
    return {"FINISHED"}


def _op_bake_from_cache():
    cache = _BPY.context.point_cache
    if cache is None:
        raise RuntimeError("mock ptcache.bake_from_cache: context has no point_cache")
    cache._baked = True
    return {"FINISHED"}


def _op_free_bake():
    cache = _BPY.context.point_cache
    if cache is None:
        raise RuntimeError("mock ptcache.free_bake: context has no point_cache")
    cache._baked = False
    return {"FINISHED"}


class _Types:
    class Panel:
        pass

    class Operator:
        def report(self, level, message):
            _BPY.reports.append((tuple(level), message))

    class PropertyGroup:
        pass

    class Scene:
        pass

    class Object:
        pass


def _prop(kind):
    def factory(**kwargs):
        return ("mock_prop", kind, kwargs)
    return factory


class _Utils:
    def __init__(self):
        self.registered = []

    def register_class(self, cls):
        for attr in ("bl_idname", "bl_label"):
            if not hasattr(cls, attr):
                raise ValueError(f"mock register_class: {cls.__name__} missing {attr}")
        if cls in self.registered:
            raise ValueError(f"mock register_class: {cls.__name__} already registered")
        self.registered.append(cls)

    def unregister_class(self, cls):
        if cls not in self.registered:
            raise RuntimeError(f"mock unregister_class: {cls.__name__} not registered")
        self.registered.remove(cls)


class _Data:
    def __init__(self):
        self.objects = _Objects()
        self.meshes = _Meshes()
        self.materials = _DataCollection(Material)
        self.collections = _Collections()
        self.armatures = _DataCollection(Armature)
        self.texts = _DataCollection(lambda name: types.SimpleNamespace(name=name, _body="",
                                                                        clear=lambda: None, write=lambda s: None))


class MockBpy(types.ModuleType):
    __is_mock__ = True

    def __init__(self):
        super().__init__("bpy")
        self.__is_mock__ = True
        self.mutations = []
        self.ops_log = []
        self.reports = []
        self._physics_stub = None
        self._frames_set = 0
        self.data = _Data()
        self.context = Context(self)
        self.app = types.SimpleNamespace(version=(4, 2, 0), version_string="4.2.0 (mock)", background=True,
                                         binary_path="")
        self.ops = types.SimpleNamespace(
            ptcache=_OpNamespace("ptcache", {"bake": _op_bake, "bake_from_cache": _op_bake_from_cache,
                                             "free_bake": _op_free_bake}),
            ed=_OpNamespace("ed", {"undo_push": lambda message="": {"FINISHED"}}),
        )
        self.types = _Types
        self.props = types.SimpleNamespace(**{k: _prop(k) for k in (
            "StringProperty", "BoolProperty", "FloatProperty", "IntProperty", "EnumProperty", "PointerProperty")})
        self.utils = _Utils()

    def _log(self, *entry):
        self.mutations.append(entry)

    def _snapshot(self):
        objs = []
        for o in self.data.objects:
            objs.append((o.name, o.type, tuple((m.name, m.type) for m in o.modifiers),
                         tuple(sorted(o._props)), tuple(g.name for g in o.vertex_groups),
                         len(o.data.vertices) if o.type == "MESH" else 0))
        scene = self.context.scene
        return {
            "objects": sorted(objs),
            "meshes": sorted(m.name for m in self.data.meshes),
            "materials": sorted(m.name for m in self.data.materials),
            "collections": sorted(c.name for c in self.data.collections),
            "scene": (scene.frame_start, scene.frame_end, scene.frame_current, scene.use_gravity, tuple(scene.gravity)),
            "ops": len(self.ops_log),
            "mutations": len(self.mutations),
        }

    # helpers for tests ------------------------------------------------------
    def make_mesh_object(self, name, vertices, faces, link=True):
        mesh = self.data.meshes.new(name)
        mesh.from_pydata(vertices, [], faces)
        obj = self.data.objects.new(name, mesh)
        if link:
            self.context.scene.collection.objects.link(obj)
        return obj

    def make_armature_object(self, name, bones, link=True):
        arm = self.data.armatures.new(name)
        obj = self.data.objects.new(name, arm)
        for bname, (head, tail) in bones.items():
            arm.bones.append(Bone(bname, head, tail))
            obj.pose.bones.append(PoseBone(bname, head, tail))
        if link:
            self.context.scene.collection.objects.link(obj)
        return obj


def _unique_name(name, existing):
    if name not in existing:
        return name
    i = 1
    while f"{name}.{i:03d}" in existing:
        i += 1
    return f"{name}.{i:03d}"


_BPY = None


def install_mock_bpy():
    """Create a fresh mock and register it as ``bpy`` / ``mathutils``."""
    global _BPY
    _BPY = MockBpy()
    mathutils = types.ModuleType("mathutils")
    mathutils.Vector = Vector
    mathutils.Matrix = Matrix
    mathutils.__is_mock__ = True
    bvhtree = types.ModuleType("mathutils.bvhtree")
    bvhtree.BVHTree = BVHTree
    mathutils.bvhtree = bvhtree
    sys.modules["bpy"] = _BPY
    sys.modules["mathutils"] = mathutils
    sys.modules["mathutils.bvhtree"] = bvhtree
    return _BPY


def uninstall_mock_bpy():
    global _BPY
    for name in ("bpy", "mathutils", "mathutils.bvhtree"):
        sys.modules.pop(name, None)
    _BPY = None


def build_humanoid_scene(bpy, humanoid, name="Human", with_armature=True):
    """Create a mesh (+armature) avatar in the mock scene from the fixture."""
    body = bpy.make_mesh_object(name, humanoid["vertices"], humanoid["faces"])
    for gname, idx in humanoid["vertex_groups"].items():
        vg = body.vertex_groups.new(name=gname)
        vg.add(idx, 1.0, "REPLACE")
    for k, v in humanoid["properties"].items():
        body[k] = v
    arm = None
    if with_armature:
        arm = bpy.make_armature_object(name + "_rig", humanoid["bones"])
        mod = body.modifiers.new("Armature", "ARMATURE")
        mod.object = arm
        body.parent = arm
    bpy.mutations.clear()
    bpy.ops_log.clear()
    return body, arm

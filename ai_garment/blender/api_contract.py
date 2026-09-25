"""Every Blender API name ai_garment relies on.

Pure data (no bpy import). Verified two ways:
  * tests/static/test_api_contract.py checks the names against the
    fake-bpy-module-4.2 stubs (generated from Blender 4.2 RNA docs);
  * tests/blender/run_blender_tests.py checks hasattr() in real Blender.
If Blender renames something, update it here and in blender/*.py.
"""

CLOTH_SETTINGS_ATTRS = (
    "quality", "mass", "air_damping", "tension_stiffness", "compression_stiffness", "shear_stiffness",
    "bending_stiffness", "tension_damping", "compression_damping", "shear_damping", "bending_damping",
    "bending_model", "use_sewing_springs", "sewing_force_max", "shrink_min", "shrink_max", "vertex_group_shrink",
    "vertex_group_structural_stiffness", "tension_stiffness_max", "compression_stiffness_max",
    "vertex_group_mass", "pin_stiffness", "effector_weights", "time_scale", "use_dynamic_mesh",
)
CLOTH_COLLISION_ATTRS = (
    "collision_quality", "use_collision", "distance_min", "use_self_collision", "self_distance_min",
    "self_friction", "vertex_group_self_collisions", "vertex_group_object_collisions",
)
COLLISION_SETTINGS_ATTRS = ("use", "thickness_outer", "cloth_friction", "damping", "use_culling")
POINT_CACHE_ATTRS = ("frame_start", "frame_end", "is_baked", "use_disk_cache", "name")

CONTRACT = {
    "ClothSettings": CLOTH_SETTINGS_ATTRS,
    "ClothCollisionSettings": CLOTH_COLLISION_ATTRS,
    "CollisionSettings": COLLISION_SETTINGS_ATTRS,
    "PointCache": POINT_CACHE_ATTRS,
    "EffectorWeights": ("gravity",),
    "ClothModifier": ("settings", "collision_settings", "point_cache"),
    "MaskModifier": ("vertex_group", "invert_vertex_group", "mode"),
    "DecimateModifier": ("ratio", "decimate_type"),
    "SolidifyModifier": ("thickness", "offset", "use_even_offset"),
    "SubsurfModifier": ("levels", "render_levels"),
    "ArmatureModifier": ("object",),
    "Modifier": ("name", "type", "show_viewport", "show_render"),
    "Object": ("modifiers", "vertex_groups", "collision", "matrix_world", "data", "type", "parent", "hide_render",
               "display_type", "pose", "evaluated_get", "shape_key_add", "shape_key_remove", "copy",
               "users_collection", "find_armature", "select_set", "active_material", "location"),
    "Mesh": ("vertices", "edges", "polygons", "from_pydata", "clear_geometry", "update", "validate", "materials",
             "shape_keys", "copy"),
    "MeshVertex": ("co", "groups", "index"),
    "VertexGroup": ("name", "index", "add", "remove"),
    "VertexGroupElement": ("group", "weight"),
    "PoseBone": ("head", "tail", "name"),
    "Bone": ("head_local", "tail_local", "name"),
    "ShapeKey": ("name", "value", "data"),
    "Scene": ("frame_start", "frame_end", "frame_current", "frame_set", "gravity", "use_gravity", "collection",
              "objects"),
    "Collection": ("objects", "children", "hide_render"),
    "Context": ("scene", "view_layer", "active_object", "selected_objects", "preferences", "temp_override",
                "evaluated_depsgraph_get"),
    "Material": ("use_nodes", "node_tree", "diffuse_color", "roughness"),
    "BlendDataObjects": ("new", "remove", "get"),
    "BlendDataMeshes": ("new", "remove"),
    "BlendDataMaterials": ("new", "remove", "get"),
    "BlendDataCollections": ("new", "get"),
}

MODIFIER_TYPES = ("CLOTH", "COLLISION", "MASK", "DECIMATE", "SOLIDIFY", "SUBSURF", "ARMATURE")
OPERATORS = ("ptcache.bake", "ptcache.bake_from_cache", "ptcache.free_bake")

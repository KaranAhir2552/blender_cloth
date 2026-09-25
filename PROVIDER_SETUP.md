# Providers

```
Existing clothing provider (Blender native cloth | OpenSew | Simply Cloth Studio | Garment Tool | yours)
        ↓
Provider adapter (ai_garment/providers/*.py): available(), capabilities, create/fit/simulate/...
        ↓
ProviderRegistry: detection, selection by capability + priority, per-capability routing, fallback
        ↓
AI Garment Orchestrator (dispatcher: validate → dry run | transactional execute)
        ↓
Claude
```

## Capabilities

`create_garment, pattern_construction, sewing, fit, fabric, components, elastic, collision, self_collision, simulate, settle, bake, wrinkles, pinning, materials, inspect`

The orchestrator routes every operation to a provider that supports it. The garment's own provider is used first. Otherwise the highest-priority available provider with that capability is used, which usually means Blender native cloth. If no provider supports a capability, the result says so explicitly. For example, wrinkles give *"Wrinkle provider unavailable. Simulation can continue without generated wrinkle enhancement."*

## Blender Native Cloth (`blender_native`)

Always registered and always the fallback. It is available whenever `bpy` can be imported. It uses only built-in features:

| Feature | Native mechanism |
|---|---|
| Garment geometry | proxy mesh from `core/geometry/builder.py`: lofted tubes and patches (Blender has no pattern tool) |
| Sewing | loose edges + `ClothSettings.use_sewing_springs`, `sewing_force_max` |
| Elastic | `vertex_group_shrink` + `shrink_min` / `shrink_max`; `vertex_group_structural_stiffness` + `tension_stiffness_max` |
| Pinning | `vertex_group_mass` + `pin_stiffness` |
| Body collision | **proxy copy** of the avatar (Mask to the relevant regions → Decimate if large → Collision last), or `mode="direct"` (tagged `AIG_Collision` on the avatar) |
| Self collision | `ClothCollisionSettings.use_self_collision`, `self_distance_min` presets draft / preview / production |
| Settling | frame stepping with a convergence check; optional non-destructive `AIG_Settled` shape key |
| Baking | `bpy.ops.ptcache.bake_from_cache` (fallback `ptcache.bake`) via `Context.temp_override(point_cache=...)` |
| Look | Principled BSDF colour, roughness and sheen; Solidify + Subdivision after the cloth modifier |

## External add-ons (OpenSew, Simply Cloth Studio, Garment Tool)

**Important:** the Python module names and operator ids of these add-ons could **not** be verified while building this extension, because neither Blender nor the add-ons were available. The adapters therefore do not hard-code an API. Instead they:

1. **Detect** the add-on by comparing enabled add-on modules (`bpy.context.preferences.addons.keys()`, including 4.2 extension names such as `bl_ext.user_default.<id>`) with configurable candidate names:
   * OpenSew: `opensew, open_sew, opensew2, opensew_2`
   * Simply Cloth Studio: `simply_cloth, simplycloth, simply_cloth_studio, simplyclothstudio, simply_cloth_pro`
   * Garment Tool: `garment_tool, garmenttool, garment_tool_2`
2. Report **unavailable** until you provide a **verified operator mapping**. Detection alone gives *"… add-on detected (module 'x') but no verified operator mapping is configured"*, and the registry then falls back to native cloth.
3. Only expose the capabilities you mapped. Unmapped capabilities are routed to native Blender.

### Find the operator ids

In Blender's Python console, with the add-on enabled:

```python
import bpy
[k for k in bpy.context.preferences.addons.keys()]           # module name
[op for op in dir(bpy.ops) if "sew" in op.lower()]            # operator namespaces
dir(bpy.ops.<namespace>)                                        # operators
bpy.ops.<namespace>.<op>.get_rna_type().properties.keys()      # parameters
```

You can also hover a button with *Python Tooltips* enabled (Preferences → Interface).

### Configure a mapping

Python:

```python
from ai_garment import garment
from ai_garment.providers.opensew import OpenSewProvider

garment.registry.register(OpenSewProvider(
    operator_map={"create_garment": "<namespace>.<operator>"},          # verified ids only
    operator_kwargs={"create_garment": {"<param>": "{type}"}},          # templates: {type} {fabric} {fit} {color} {name}
    candidate_modules=("<module name>",),                                # optional
), replace=True)
garment.detect_provider(preferred="opensew").to_dict()
```

Or with JSON, via `AI_GARMENT_PROVIDER_CONFIG=/path/providers.json`:

```json
{"opensew": {"modules": ["opensew"],
             "operators": {"create_garment": "namespace.operator"},
             "kwargs": {"create_garment": {"preset": "{type}"}}}}
```

When a mapped operator creates exactly one new mesh object, it is tagged as the garment. Later physics and material edits and simulation go to native cloth. **Geometry edits** on add-on garments are refused with `CAPABILITY_NOT_SUPPORTED`, because regenerating them natively would replace the add-on's geometry. Every result from a mapped operator carries a warning to verify it visually.

## Writing a new provider

```python
from ai_garment.providers.base import Capability, GarmentProvider, ProviderStatus
from ai_garment.core.results import Result

class MyProvider(GarmentProvider):
    name, display_name, priority = "my_tool", "My Tool", 70
    capabilities = frozenset({Capability.CREATE_GARMENT, Capability.PATTERN_CONSTRUCTION})

    def available(self):                       # must never raise
        return ProviderStatus(self.name, self.display_name, True, "ready")

    def create_garment(self, record, avatar, context=None):
        r = Result(action="create_garment")
        # build the garment; set record.object_name; tag it:
        #   from ai_garment.blender.scene import tag; tag(obj, record.id, "garment")
        # journal scene changes for rollback: self.tx.record("description", undo_fn)
        return r

garment.registry.register(MyProvider())
```

Rules: return `Result` objects and never fail silently. Journal every scene change on `self.tx`. Tag every object you create. Never import other add-ons at module import time.

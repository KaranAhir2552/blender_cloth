# AI Garment Orchestrator — Architecture

## Purpose

This add-on is an **orchestration layer**. It is not a cloth engine. Claude, or a user, describes clothing at a high level. The orchestrator turns that into validated, structured operations and executes them through the best available *garment provider*. A provider is either an installed garment add-on or Blender's native cloth tools.

```
            Claude / user (natural language or JSON)
                            │
                ┌───────────▼────────────┐
                │ api/  (public surface) │  garment.create(...), Garment.modify(...),
                │ commands, schema,      │  execute_plan(plan, dry_run=True),
                │ dispatcher, session    │  claude_tool_definitions()
                └───────────┬────────────┘
                            │ structured Operations
                ┌───────────▼────────────┐
                │ core/  (pure Python)   │  spec · types · components · fit · fabric
                │ no bpy imports         │  elastic · avatar model · geometry builder
                │                        │  operations · planning · NL mapping
                │                        │  validation · diagnostics · transactions
                └───────────┬────────────┘
                            │ provider calls (capability-routed)
                ┌───────────▼────────────┐
                │ providers/             │  base.GarmentProvider, registry (select + fallback)
                │  blender_native  ◄──── │  default, always the fallback
                │  opensew / simply_cloth│  detected, operator mapping configured by user
                │  garment_tool          │
                └───────────┬────────────┘
                            │
                ┌───────────▼────────────┐
                │ blender/  (bpy layer)  │  objects · modifiers · physics · vertex_groups
                │ bpy only via get_bpy() │  simulation · avatar_scan · spatial · materials
                │                        │  scene (tagging/safety) · ui (panel/operators)
                └───────────┬────────────┘
                            ▼
                Blender (Cloth, Collision, Sewing springs, PointCache, Armature …)
```

### Layer rules

1. **`core/` never imports `bpy`, `mathutils` or anything in `blender/` or `providers/`.** A static test enforces this.
2. **`blender/` reaches bpy only through `blender._bpy.get_bpy()`** (and `get_mathutils()`), called at *function* time. The one exception is `blender/ui.py`, which must subclass `bpy.types.*` at import time. It is only imported from `register()`.
3. **Every import inside the package is relative.** Blender 4.2 extensions load the package as `bl_ext.<repo>.ai_garment`. A static test enforces this.
4. **No external add-on is imported.** Adapters inspect `bpy.context.preferences.addons` and look up operators with `getattr(bpy.ops, ns)`.
5. **The spec is the source of truth.** Geometry is *derived* from `GarmentSpec` + `AvatarModel`. Modifying a garment means transforming the spec purely and then regenerating or re-applying only the affected parts. Each operation declares its `effects`.

## Package layout

```
ai_garment/                     ← the Blender extension (zip this folder)
  __init__.py                   bl_info, register/unregister, public exports
  blender_manifest.toml         Blender ≥ 4.2 extension manifest
  data/fabric_presets.json      artistic fabric presets (configurable data)
  core/
    errors.py                   GarmentError hierarchy + canonical messages
    results.py                  Result (structured, JSON-serialisable)
    logging_utils.py            "[AI-GARMENT] …" logger + event capture
    vocabulary.py               normalisation, aliases, colours, intensity words, suggestions
    units.py                    Amount parsing ("+10%", "-3cm", "2in")
    garment_types.py            GarmentTypeDef registry (10 types, extensible)
    component_system.py         ComponentTypeDef registry, target resolution
    fabric_presets.py           FabricPreset, qualifiers ("heavy denim"), loading
    physics_mapping.py          qualitative fabric + quality → native cloth numbers
    quality.py                  draft / preview / medium / production presets
    fit_system.py               fit levels, ease tables, region adjustment, derivation
    elastic.py                  ElasticSpec, strength mapping, shrink-group combination
    garment_spec.py             GarmentSpec dataclasses, from_dict/to_dict, shorthand
    validation.py               validate_spec → ValidationReport
    avatar_model.py             AvatarModel, bone-alias resolution, anthropometrics
    geometry/
      mathutil.py               vectors, convex hull, ellipse helpers
      tube.py                   MeshBuilder: lofted rings, patches, groups, sewing
      recipes.py                builder-recipe registry (top, pants, skirt, dress, + custom)
      builder.py                GarmentSpec + AvatarModel → GarmentMeshData
    diagnostics.py              penetration / settling / stability analysis
    garment_operations.py       Operation, OperationDef registry, spec transforms
    planning.py                 creation & simulation plans, dry-run description
    nl_mapping.py               natural language → operations (rule based)
    transaction.py              undo journal (rollback) independent of bpy
    record.py                   GarmentRecord (runtime + persisted state of one garment)
  providers/
    base.py                     GarmentProvider ABC, Capability, ProviderStatus
    registry.py                 ProviderRegistry: detect, select, route, fallback
    blender_native.py           full native implementation (uses blender/)
    external.py                 shared add-on detection + operator-mapping adapter
    opensew.py / simply_cloth.py / garment_tool.py
  blender/
    _bpy.py                     get_bpy(), get_mathutils(), blender_available()
    api_contract.py             every bpy attribute/operator we rely on (checked)
    scene.py                    tagging, safe removal, collections, frames, gravity
    objects.py                  mesh object create/update/duplicate from mesh data
    vertex_groups.py            write groups from mesh data
    modifiers.py                add/find/order modifiers (cloth, collision, subsurf …)
    physics.py                  apply mapped cloth/collision settings
    simulation.py               frame stepping, settling loop, bake, free bake
    spatial.py                  BVH signed distance, push-out
    avatar_scan.py              scene → raw avatar data → core.avatar_model
    materials.py                fabric-aware Principled BSDF material
    ui.py                       sidebar panel + operators (Blender-only import)
  api/
    schema.py                   JSON Schemas + Claude tool definitions (generated)
    session.py                  GarmentRecord store, scene persistence
    dispatcher.py               validate-all → dry-run | transactional execute
    garment.py                  Garment handle + GarmentSystem facade (`garment`)
    commands.py                 flat command functions returning dicts + registry
scripts/run_checks.py           runs every available check, prints the STATUS block
scripts/build_extension.py      builds extension / legacy zips without Blender
tests/                          ← NOT shipped in the extension
  mocks/mock_bpy.py             strict minimal bpy/mathutils mock
  fixtures/humanoid.py          synthetic MakeHuman-like humanoid (verts + bones)
  unit/  mock/  static/         pytest suites (markers: pure, mock, static)
  blender/run_blender_tests.py  real-Blender suite (blender --background --python …)
```

## Key data model

```python
GarmentSpec(
  type="tshirt", name=None,
  fit=FitSpec(level="oversized", overrides={"chest_ease": -2.0}, component_levels={"left_sleeve": "relaxed"}, scale=1.0),
  fabric=FabricSpec(name="cotton", qualifiers=[], overrides={}, physics_overrides={}),
  color="black", length="hip", length_adjust={"percent": 0.0, "meters": 0.0},
  components=[ComponentSpec(type="body", name="body"), ComponentSpec(type="sleeve", name="left_sleeve", params={"side": "left", "length": "short"}), …],
  simulation=SimulationSpec(mode="natural", quality="preview", gravity=True, collision=True, self_collision=None, …),
  placement={"offset": [0,0,0]}, tucked=False, layer=0, disabled_seams=[], metadata={})
```

The user's example JSON shorthand (`"sleeves": {"length": "short", "cuff": {"type": "elastic"}}`) is normalised into explicit components (`left_sleeve`, `right_sleeve`, `left_sleeve_cuff`, …).

## Providers and fallback

```python
selection = registry.select(required={"create_garment", "simulate"}, preferred="opensew")
# → Selection(provider=<BlenderNativeProvider>, fallback_used=True,
#     warnings=["Provider OpenSew unavailable. Fallback provider: Blender Native Cloth. …"])
provider.supports("sewing")          # capability query
registry.provider_for("wrinkles")    # per-capability routing (None → graceful report)
```

Selection order: the preferred provider if it is available and capable, then other available providers by `priority`, then native. `available()` is always wrapped, so an exception inside an adapter becomes `available=False` with the reason. It never crashes the system.

## Native garment construction (fallback)

When no pattern-based provider is installed, `core/geometry/builder.py` builds a **proxy garment** from lofted elliptical rings around the avatar's landmarks. The torso, sleeves and legs are separate tubes. Hoods and pockets are partial tubes or patches. Pieces are joined with **native sewing springs** (loose edges). Components become vertex groups (`AIG_<component>`). Elastic, stiffened and pinned areas become the cloth modifier's shrink, structural-stiffness and pin groups. Blender's own solver then drapes the garment under gravity. This is intentionally simple; a pattern-based provider produces better garments.

## Execution pipeline

```
plan (NL text | op dicts) ─► normalise ─► validate ALL (no mutation) ─┬─► dry_run: apply to a spec copy, describe steps
                                                                     └─► execute in Transaction:
                                                                          spec ops accumulate effects → one provider.update
                                                                          scene ops (fit/simulate/settle/bake) routed by capability
                                                                          failure → rollback (journal) → structured errors
```

## Scene safety

* Every object the orchestrator creates is tagged with `ai_garment_id` and `ai_garment_role` custom properties.
* `scene.safe_remove_object()` refuses to delete untagged objects, or objects tagged for another garment.
* Collision uses a **proxy copy** of the avatar by default. The user's avatar object is not modified. `mode="direct"` adds a tagged modifier instead, which is recorded for rollback.
* Scene-level changes (`use_gravity`, frame range) are journaled and restored on rollback.
* Settled shapes are stored as a shape key (`AIG_Settled`), not applied destructively.

## Extending

* New garment type: `register_garment_type(GarmentTypeDef(...))`, reusing an existing `builder` recipe (`top`, `pants`, `skirt`, `dress`) or registering a new recipe with `register_builder_recipe`.
* New component: `register_component_type(ComponentTypeDef(...))`.
* New fabric: add it to `data/fabric_presets.json`, or call `register_fabric_preset`.
* New provider: subclass `GarmentProvider` (or `ExternalAddonProvider`) and call `registry.register`.
* New operation: `register_operation(OperationDef(...))`.

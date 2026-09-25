# API Reference

```python
from ai_garment import garment            # default GarmentSystem (alias: garment_system)
from ai_garment import commands           # flat JSON commands
from ai_garment import GarmentSpec, GarmentError, Result, parse_instruction
```

## `Result`

Every operation returns a `Result`. `result.to_dict()` gives:

```json
{"ok": true, "valid": true, "action": "execute_plan", "dry_run": false,
 "operations": ["Create T-shirt", "Apply oversized fit", "..."],
 "warnings": [], "errors": [{"code": "...", "message": "...", "path": "...", "suggestions": []}],
 "data": {"...": "..."}, "logs": ["[AI-GARMENT] Garment: T-shirt"]}
```

`bool(result)` equals `result.ok`.

## `GarmentSystem` (`garment`)

| Method | Returns | Notes |
|---|---|---|
| `create(type=None, spec=None, dry_run=False, transactional=True, avatar=None, provider=None, name=None, quality_cap=None, **fields)` | `Garment` (or `Result` when `dry_run`) | Raises `GarmentError` (`VALIDATION_FAILED`, `NO_PROVIDER_AVAILABLE`, …) with `details["errors"]` and `details["result"]` |
| `execute(plan, garment=None, dry_run=False, transactional=True, quality_cap=None)` | `Result` | `plan` is a list of operation dicts, one dict, or English text |
| `plan(plan, garment=None)` | `Result` | Dry run. `data`: `plan`, `final_spec`, `provider`, `executable`, `simulation_plan`, `parsed` (text) |
| `run(text, garment=None, quality_cap=None)` | `Result` | Execute English |
| `detect_avatar(name=None, metadata=None)` | `AvatarHandle` | Never raises; check `.ok` |
| `detect_provider(required=None, preferred=None)` | `Selection` | `.provider`, `.warnings`, `.fallback_used`, `.error`, `.to_dict()` |
| `providers()` | list of status dicts | |
| `list_garments()`, `get(id_or_name)`, `load_from_scene()` | | Garments persist as JSON custom properties on their objects |
| `capabilities()`, `schema()`, `tools()` | dict / JSON Schema / tool definitions | |

## `Garment`

Edits (validated → spec transform → one provider update): `modify(**changes)`, `set_fabric(fabric, **overrides)`, `set_fit(level, target=None)`, `set_color(color)`, `add_component(type, target=None, name=None, **params)`, `remove_component(target)`, `add_elastic(target, strength="medium", width=None, tension=None)`, `roll(target=None, turns=None)`, `tuck()`, `untuck()`, `enable_self_collision(preset="preview")`, `apply(text)`, `execute(plan)`, `plan(plan)`.

Scene operations: `fit_to_avatar(avatar=None|name|AvatarHandle|AvatarModel, metadata=None, collision_mode="proxy"|"direct", margin=None)` (alias `fit`), `simulate(mode="natural", quality=None, **settings)`, `simulate_on_copy(mode="preview", ...)`, `settle(max_frames=None, threshold=None, apply="none"|"shape_key")`, `bake(frame_start=None, frame_end=None)`, `generate_wrinkles()`, `reset(level="simulation"|"geometry"|"all")`.

Housekeeping: `inspect() -> dict`, `duplicate(name=None) -> Garment`, `rollback() -> Result` (undo the last executed change), `delete() -> Result`, `to_dict()`. Every mutating method accepts `dry_run=True`.

`inspect()` example:

```json
{"garment": "T-Shirt", "type": "tshirt", "provider": "Blender Native Cloth", "fabric": "cotton",
 "fit": "oversized", "color": "black", "components": ["body", "collar", "left_sleeve", "..."],
 "simulation": {"cloth": true, "collision": true, "self_collision": true, "baked": false},
 "physics": {"quality": 7, "mass": 0.3, "...": "..."}, "warnings": []}
```

## `AvatarHandle`

`.ok`, `.name`, `.model` (`AvatarModel`: `source`, `rig_type`, `unit_scale`, `pose`, `landmarks`, `measurements`, `sections`, `regions`, `evidence`, `warnings`), `.result`, `get_measurements()`, `get_body_regions()`, `get_collision_surfaces(garment_type=None)`, `prepare_collision(garment_type=None, mode="proxy", margin=None)`, `remove_collision()`, `to_dict()`.

Measurements (metres): `height, chest_circumference, waist_circumference, hip_circumference, neck_circumference, shoulder_width, arm_length, upper_arm_circumference, wrist_circumference, thigh_circumference, knee_circumference, ankle_circumference, inseam`.

Regions: `head, neck, shoulders, chest, waist, hips, left_arm, right_arm, left_leg, right_leg`.

## Garment spec

```json
{
  "type": "tshirt", "fit": "oversized", "fabric": "cotton", "color": "black", "length": "hip",
  "sleeves": {"length": "short", "fit": "loose", "cuff": {"type": "elastic", "strength": "medium"}},
  "simulation": {"mode": "natural", "quality": "preview", "gravity": true, "collision": true, "self_collision": true}
}
```

Explicit form: `"components": [{"type": "elastic_cuff", "name": "left_sleeve_cuff", "target": "left_sleeve", "params": {"strength": "medium"}}]`. Explicit components merge with the type's defaults by name; set `"default_components": false` to replace them. `fit` also accepts `{"level", "overrides": {"chest_ease": -2.0, "left_sleeve:sleeve_width_ease": 3.0}, "component_levels": {...}, "scale": 1.05}`. `fabric` also accepts `{"name", "qualifiers", "overrides": {"stretch": "high"}, "physics_overrides": {"tension_stiffness": 40}}`. Other keys: `length_adjust {percent, meters}`, `placement {offset}`, `tucked`, `layer`, `disabled_seams`, `metadata`, and the shorthands `legs`, `cuffs`, `pockets`, `hood`, `collar`, `waistband`, `zipper`, `buttons`.

The full JSON Schema is available from `ai_garment.api.schema.garment_spec_json_schema()`.

## Operations

| operation | params | required |
|---|---|---|
| `create` | type, spec, fit, fabric, color, length, name, (any spec key) | type or spec |
| `fit` | avatar, avatar_hint, metadata, collision_mode, margin | – |
| `prepare_collision` | margin, mode, regions | – |
| `resize` | amount (`"+5%"`) | amount |
| `move` | offset `[x, y, z]` metres | offset |
| `sew` / `unsew` | seam `"a:b"` or a, b | seam or a |
| `simulate` | mode, quality, frames, settle, bake, self_collision | – |
| `settle` | max_frames, threshold, apply (`none`/`shape_key`), quality | – |
| `bake` | frame_start, frame_end | – |
| `reset` | level | – |
| `inspect` | – | – |
| `set_fabric` | fabric, overrides | fabric |
| `set_fit` | level, target | level |
| `set_color` | color | color |
| `add_component` | type, target, name, params, (component params) | type |
| `remove_component` | target | target |
| `modify_component` | target, params, (component params) | target |
| `modify_fit` | direction, region, target, intensity | direction |
| `modify_length` | target, amount, direction, intensity, length | amount, direction or length |
| `roll` / `unroll` / `fold` | target, turns | – |
| `tuck` / `untuck` | – | – |
| `set_elastic` | target, strength, tension, width | target |
| `pin` / `unpin` | target | target (pin) |
| `enable_self_collision` | preset (`off`, `draft`, `preview`, `medium`, `production`) | – |
| `generate_wrinkles` | intensity, optional | – |

Case-insensitive aliases: `tighten`, `loosen` (→ modify_fit); `lengthen`, `shorten` (→ modify_length); `fit_to_avatar`, `fit_garment`, `create_garment`, `simulate_garment`, `bake_simulation`, `add_elastic`, `change_fabric`, `change_color`, `set_colour`, `self_collision`, `wrinkles`, `drape`, `add`, `remove`.

Each operation declares its **effects** (`geometry`, `physics`, `material`, `simulation`, …). Several edits in one plan are flushed as a single provider update before the next scene operation.

## Commands (`ai_garment.commands`)

All return dicts and never raise: `create_garment(spec, dry_run=False, avatar=None, provider=None)`, `fit_garment(garment, avatar=None)`, `modify_garment(garment, **changes)`, `set_fabric(garment, fabric)`, `add_component(garment, type, target=None, **params)`, `set_fit(garment, level, target=None)`, `simulate_garment(garment, mode="natural", quality=None)`, `settle_garment(garment, max_frames=None, apply="none")`, `bake_simulation(garment, frame_start=None, frame_end=None)`, `inspect_garment(garment)`, `reset_garment(garment, level)`, `delete_garment(garment)`, `execute_plan(plan, garment=None, dry_run=False)`, `apply_instruction(text, garment=None, dry_run=True)`, `parse_instruction(text, context=None)`, `detect_avatar(name=None, metadata=None)`, `detect_provider(required=None, preferred=None)`, `list_garments()`, `list_capabilities()`, `describe_schema()`. `COMMANDS` maps names to functions, and `run_command(name, **kwargs)` dispatches by name.

## Extension points

`register_garment_type(GarmentTypeDef(...))`, `register_component_type(ComponentTypeDef(...))`, `register_fabric_preset(FabricPreset(...))` / `load_fabric_presets(path)`, `register_operation(OperationDef(...))`, `register_builder_recipe(name, fn)`, `register_rig_signature(name, roles)`, `garment.registry.register(provider)`.

# Using AI Garment from Claude

This is the playbook for an AI assistant driving Blender through this add-on. The assistant can reach Blender through a Python-execution bridge (for example a Blender MCP server that runs Python inside Blender), or by generating scripts the user runs.

## Golden rules

1. **Inspect first.** Call `garment.capabilities()`, `garment.detect_avatar()`, `garment.list_garments()` and `g.inspect()` before acting.
2. **Plan before executing.** Use `garment.plan(...)` or `g.plan(...)` (dry run). It validates everything and returns the step list, warnings and the simulation plan **without touching the scene**.
3. **Prefer structured operations over English.** The built-in English parser is deterministic and deliberately small. Claude should translate the user's words into the operations below and use the parser only as a cross-check (`parse_instruction`).
4. **Read the result.** Every call returns structured data: `ok`, `errors[{code, message, suggestions}]`, `warnings`, `operations`, `data`, `logs`. Fix the cause named by `code` and `suggestions`; never retry blindly.
5. **Keep the default quality** (`preview`) while iterating. Use `quality="production"` only for the final bake. It is slower, but it is not "maximum".

## Minimal session

```python
from ai_garment import garment

garment.detect_avatar().to_dict()               # who am I dressing? measurements, rig, warnings
plan = garment.plan([
    {"operation": "create", "type": "tshirt", "fit": "oversized", "fabric": "cotton", "color": "black"},
    {"operation": "set_fit", "target": "sleeves", "level": "relaxed"},
    {"operation": "add_component", "type": "elastic_cuff", "target": "sleeves", "strength": "medium"},
    {"operation": "fit"},
    {"operation": "simulate", "mode": "natural"},
])
assert plan.to_dict()["valid"], plan.to_dict()["errors"]
result = garment.execute(plan.data["plan"])     # transactional: any failure rolls the scene back
shirt = garment.get(result.data["garment"]["id"])
shirt.inspect()
```

Object-style equivalent:

```python
shirt = garment.create(type="tshirt", fit="oversized", fabric="cotton", color="black")  # raises GarmentError if invalid
shirt.fit_to_avatar()
shirt.set_fit("relaxed", target="sleeves")
shirt.add_component(type="elastic_cuff", target="sleeves", strength="medium")
shirt.simulate(mode="natural")      # gravity, collision, self collision, fabric, sewing, settle, bake
shirt.bake()                        # optional re-bake of a custom frame range
```

## Translating language to operations

| User says | Operation(s) |
|---|---|
| "Create an oversized black cotton T-shirt" | `{"operation":"create","type":"tshirt","fit":"oversized","color":"black","fabric":"cotton"}` |
| "…on my MakeHuman character" | add `{"operation":"fit","avatar_hint":"makehuman"}` (or `"avatar":"<object name>"`) |
| "Make the T-shirt 10% longer" | `{"operation":"modify_length","target":"garment","amount":"+10%"}` |
| "Make it tighter around the chest" | `{"operation":"modify_fit","region":"chest","direction":"tighter"}` |
| "…slightly tighter…" / "…much looser…" | add `"intensity": 0.5` / `2.0` |
| "Make the sleeves slightly shorter" | `{"operation":"modify_length","target":"sleeves","amount":"-5%"}` |
| "Make the sleeves long" | `{"operation":"modify_length","target":"sleeves","length":"long"}` |
| "Roll the sleeves up" | `{"operation":"roll","target":"sleeves"}` (`"turns":1` for "slightly") |
| "Make the jeans baggier" | `{"operation":"modify_fit","target":"legs","direction":"looser"}` |
| "Make the legs loose" | `{"operation":"set_fit","target":"legs","level":"loose"}` |
| "Change the fabric to heavy denim" | `{"operation":"set_fabric","fabric":"heavy denim"}` |
| "Make it navy" | `{"operation":"set_color","color":"navy"}` |
| "Add medium elastic cuffs to the sleeves" | `{"operation":"add_component","type":"elastic_cuff","target":"sleeves","strength":"medium"}` |
| "Make the waistband elastic" | `{"operation":"set_elastic","target":"waistband","strength":"medium"}` |
| "Create loose cargo pants with elastic cuffs" | `create {type:pants, fit:loose}` + `add_component cargo_pocket → legs` + `add_component elastic_cuff → legs` |
| "Put a hoodie on the character and let it settle" | `create {type:hoodie}` + `fit` + `simulate {mode:natural}` |
| "Remove the hood" | `{"operation":"remove_component","target":"hood"}` |
| "Tuck the shirt in" | `{"operation":"tuck"}` (tops only) |
| "Let it fall naturally / settle" | `{"operation":"simulate","mode":"natural"}` or `{"operation":"settle"}` |
| "Make the fabric look realistic" | `simulate` with `"quality":"production"` + optional `generate_wrinkles` |
| "Bake it" | `{"operation":"bake"}` |

`garment.modify(...)` provides the same edits as keyword arguments: `modify(length="+10%")`, `modify(region="chest", fit="tighter")`, `modify(component="sleeves", length="-5%")`, `modify(component="sleeves", position="rolled_up")`, `modify(component="legs", fit="baggy")`.

## Vocabulary

* **Garment types:** tshirt, shirt, hoodie, sweatshirt, pants, jeans, shorts (v1). Jacket, skirt and dress are experimental. Aliases such as "tee", "trousers", "hooded sweatshirt" and "button-up" are accepted.
* **Fit levels:** tight, slim, regular, relaxed, loose, oversized (aliases: skinny, fitted, baggy, boxy, …). **Comparatives:** tighter, looser, baggier, slimmer, roomier, wider.
* **Regions:** chest, waist, hips, shoulders, sleeves/arms, legs/thighs, cuffs, neck, overall.
* **Targets:** `garment`, `sleeves`, `legs`, `cuffs`, `sleeve_cuffs`, `ankle_cuffs`, `hood`, `waistband`, `collar`, `hem`, `pockets`, or any component name (`left_sleeve`).
* **Fabrics:** cotton, heavy_cotton, jersey, denim, silk, wool, linen, polyester, nylon, leather, rubber, elastic, fleece. Qualifiers: heavy, light, thin, thick, stiff, soft, stretchy, rigid, flowy, crisp, … These are **artistic presets**, not measured material data.
* **Lengths:** tops use crop, waist, hip, low_hip, thigh. Bottoms use micro, mid_thigh, above_knee, knee, below_knee, capri, ankle, floor. Sleeves use sleeveless, cap, short, elbow, three_quarter, long, extra_long.
* **Simulation modes:** `natural` (settle + self collision + bake), `preview` (settle, no bake), `draft`, `production`, `static`. **Quality levels:** draft, preview, medium, production.

## Full operation list

`create, fit, prepare_collision, resize, move, sew, unsew, simulate, settle, bake, reset, inspect, set_fabric, set_fit, set_color, add_component, remove_component, modify_component, modify_fit, modify_length, roll, unroll, fold, tuck, untuck, set_elastic, pin, unpin, enable_self_collision, generate_wrinkles`

Aliases: `TIGHTEN`/`LOOSEN` → `modify_fit`; `LENGTHEN`/`SHORTEN` → `modify_length`; `SET_ELASTIC`, `ROLL`, and so on are case-insensitive. The exact parameters come from `commands.describe_schema()` (JSON Schema) or [docs/API.md](docs/API.md).

## Reading results and recovering from errors

| code | meaning | typical fix |
|---|---|---|
| `VALIDATION_FAILED` + `UNKNOWN_FABRIC` / `UNKNOWN_FIT` / `INVALID_COLOR` / `INVALID_LENGTH` | spec rejected before any scene change | use a suggested value |
| `TARGET_NOT_FOUND` | the component does not exist (e.g. sleeves on pants) | check `inspect()["components"]` |
| `INVALID_COMPONENT_FOR_TYPE` | e.g. a hood on pants | pick another component |
| `ELASTIC_TENSION_RANGE` / `ELASTIC_WIDTH_RANGE` | elastic out of range | tension 0–0.5, width 0.005–0.15 m |
| `AVATAR_NOT_FOUND` | "No supported avatar detected. Please select a character or provide avatar metadata." | select the character, pass `avatar="Name"` or `metadata={...}` |
| `NO_PROVIDER_AVAILABLE` / `BLENDER_UNAVAILABLE` | not running inside Blender | run inside Blender or use `dry_run=True` |
| `NO_GARMENT` | a plan edits a garment but has no `create` and no garment was given | call on a garment or add `create` |
| `CAPABILITY_NOT_SUPPORTED` | no provider supports this | see `warnings`; e.g. wrinkles are optional |
| warning "Potential collision issue detected. Suggested action: increase collision margin or increase simulation quality" | cloth ended inside the body | `fit(margin=0.015)` or `simulate(quality="medium")` |
| warning "Provider OpenSew unavailable. Fallback provider: Blender Native Cloth. …" | the preferred add-on is missing | informational |
| warning "Wrinkle provider unavailable. Simulation can continue without generated wrinkle enhancement." | no wrinkle provider | informational |

## Safety features to rely on

* `dry_run=True` everywhere, and `garment.plan(...)`. Validation always runs *before* the scene is touched.
* `transactional=True` (the default): a failure mid-plan rolls back everything this plan created or changed.
* `g.rollback()` undoes the last executed change on a garment. `g.reset()` frees the bake and removes the settled shape. `g.duplicate()` and `g.simulate_on_copy()` let you experiment on a copy.
* The avatar object is never modified in the default `proxy` collision mode. Deletion only removes objects tagged `ai_garment_id` for that garment.

## Flat JSON commands (tool calling)

`ai_garment.commands` exposes JSON-in / JSON-out functions that never raise: `create_garment`, `fit_garment`, `modify_garment`, `set_fabric`, `add_component`, `set_fit`, `simulate_garment`, `settle_garment`, `bake_simulation`, `inspect_garment`, `reset_garment`, `delete_garment`, `execute_plan`, `apply_instruction`, `parse_instruction`, `detect_avatar`, `detect_provider`, `list_garments`, `list_capabilities`, `describe_schema`. `ai_garment.api.schema.claude_tool_definitions()` returns ready-made tool definitions (`name`, `description`, `input_schema`).

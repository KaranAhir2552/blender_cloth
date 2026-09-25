# Test Plan

Tests are grouped by **what they can prove**. The groups are kept strictly separate.

| Suite | Marker | Location | Needs Blender? | What a pass means |
|---|---|---|---|---|
| Pure Python | `pure` | `tests/unit/` | No | The logic is correct: specs, fit math, fabrics, operations, NL mapping, geometry, diagnostics, providers (with fake providers). |
| Mock Blender | `mock` | `tests/mock/` | No (strict mock `bpy`) | The Blender-layer code calls the API *as we model it*, in the right order, without touching unrelated objects. It does **not** prove that real Blender behaves the same way. |
| Static | `static` | `tests/static/` | No | Everything compiles, imports without bpy, has no circular or absolute intra-package imports, is pyflakes-clean, and has a valid manifest and JSON schemas. Every bpy attribute and operator we use **exists in the Blender 4.2 API stubs**. |
| Real Blender | — | `tests/blender/run_blender_tests.py` | **Yes** | The add-on works in real Blender. **Not run in the development environment.** |

Run everything available with `python scripts/run_checks.py`. It prints the STATUS block.

## Required scenarios (from the brief)

| # | Scenario | Test(s) | Expected |
|---|---|---|---|
| 1 | Create T-shirt `{"type":"tshirt","fabric":"cotton","fit":"oversized"}` | `unit/test_command_planner.py::test_create_tshirt_plan` | Plan valid; a provider supporting `create_garment` is selected; `cotton` preset; `oversized` fit. |
| 2 | Create jeans | `unit/test_garment_spec.py::test_jeans_defaults` | Type `jeans`; fabric defaults to `denim`; fit is configurable (`slim` accepted). |
| 3 | Sleeve elastic "Add medium elastic cuff to sleeves" | `unit/test_operations.py::test_add_elastic_cuff_to_sleeves`, `unit/test_nl_mapping.py::test_add_elastic_cuffs` | Two `elastic_cuff` components; strength, width and tension validated; out-of-range tension rejected. |
| 4 | Avatar fitting (mock avatar with shoulder_width, chest, waist, hip, arm_length) | `unit/test_fit.py::test_measurements_derived_from_avatar` | Garment chest = avatar chest + ease; sleeve length = arm length × sleeve fraction, and so on. |
| 5 | Fabric mapping cotton/denim/silk | `unit/test_fabric_presets.py::test_fabric_name_mapping` | Each maps to its own preset; `"heavy denim"` → denim + heavy qualifier. |
| 6 | Provider unavailable | `unit/test_provider_selection.py` | The OpenSew adapter reports unavailable without bpy; nothing crashes; native is the fallback, with the canonical warning; with no fallback available, the error is structured. |
| 7 | Invalid garment `fabric="unicorn_skin"` | `unit/test_validation.py::test_unknown_fabric`, `mock/test_scene_safety.py::test_invalid_spec_does_not_touch_scene` | Validation error `UNKNOWN_FABRIC` with suggestions; mock scene unchanged. |
| 8 | Dry run | `unit/test_command_planner.py::test_dry_run_*`, `mock/test_scene_safety.py::test_dry_run_no_mutation` | Plan described; mock scene object/modifier counts and the operator-call log are identical before and after. |
| 9 | NL "Make the shirt tighter around the chest." | `unit/test_nl_mapping.py::test_tighter_chest` | `{"operation":"modify_fit","region":"chest","direction":"tighter"}` |
| 10 | "simulate naturally" | `unit/test_command_planner.py::test_natural_simulation_plan` | Plan includes gravity, collision, self_collision, fabric settings, settling, bake. |

## Additional coverage

* **Spec**: shorthand normalisation (`sleeves`, `cuff`), aliases (`t-shirt`, `tee`), round-trip `to_dict`/`from_dict`, all 10 garment types, extensibility (register a new type at runtime).
* **Units**: `+10%`, `-5%`, `+3cm`, `2in`, `0.5`, invalid strings.
* **Fit**: monotonic ease ladder, region adjustment (slightly = half step), clamping, negative-ease warning with low-stretch fabric, component-level fit, resize.
* **Fabric**: all 12 required presets present and marked artistic; qualifier shifts; overrides; unknown qualifier; physics mapping is monotonic (heavier → more mass, stiffer → more bending); production quality ≥ preview quality steps; every mapped key is a real `ClothSettings` / `ClothCollisionSettings` / `CollisionSettings` attribute.
* **Elastic**: strength presets, combined shrink group (weights = tension / max), drawstring, invalid targets.
* **Components**: target resolution (`sleeves` → both sleeves; `cuffs` on pants → ankle cuffs), a hood on pants is rejected, unique names, removal.
* **Operations**: every operation in the brief is registered; alias normalisation (`TIGHTEN` → `modify_fit`); validation messages; spec transforms (roll, tuck, lengthen, set fabric, sew/unsew); effects declared.
* **NL mapping**: create instructions (the flagship sentence, cargo pants, hoodie with gravity), length %, sleeve shortening, rolling, fabric change, colour, removal, bake, ordering (create → edits → fit → simulate), unrecognised text reported.
* **Avatar model**: bone resolution for MakeHuman (MPFB default and game-engine), Rigify, Mixamo; unit-scale inference (m/dm/cm); anthropometric fallback; convex-hull section measurement; synthetic humanoid → plausible measurements; regions; collision surfaces per garment type.
* **Geometry**: every V1 type builds valid mesh data (indices in range, no degenerate faces); groups for every component; sewing edges between sleeves and body; ease increases ring size; rolled sleeves are shorter; initial garment clears the synthetic body.
* **Diagnostics**: penetration thresholds → canonical collision message; settling convergence; explosion detection.
* **Transactions**: rollback order, errors during rollback are reported, not swallowed.
* **Mock Blender**: native provider create → fit → elastic → prepare collision (proxy) → simulate → settle → bake → inspect → reset → delete; the avatar object is never modified in proxy mode; untagged objects cannot be deleted; rollback removes only created objects; add-on `register()` / `unregister()` with a mock `bpy`; avatar scan finds the MakeHuman-like mock.
* **Static**: compileall; import every module without bpy; import graph acyclic; relative imports only; `core/` purity; pyflakes; manifest fields; generated JSON schemas validate the examples; command registry complete; provider discovery; API contract vs Blender 4.2 stubs (skipped if the stubs are not installed).

## Real Blender suite (`tests/blender/run_blender_tests.py`)

Run with `blender --background --factory-startup --python tests/blender/run_blender_tests.py`. Steps:

1. Extension registration (`register()`, panel and operator classes present)
2. API contract (`hasattr` checks on real `ClothSettings` etc.)
3. Provider detection
4. Garment creation on a synthetic rigged humanoid
5. Avatar detection
6. Fitting
7. Collision setup
8. Cloth creation (modifier + groups + sewing)
9. Simulation setup + short settle
10. Baking
11. Cleanup (only tagged objects removed; the avatar is intact)

It exits non-zero on any failure and prints a summary. **Its status must be reported as NOT RUN unless it was actually executed in Blender.**

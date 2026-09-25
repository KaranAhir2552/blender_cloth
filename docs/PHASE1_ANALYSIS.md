# Phase 1 — Repository & Environment Analysis

Written before any implementation code (2026-09-25).

## Repository state

| Item | Finding |
|---|---|
| Files | None. The repository had **no commits and no files** (only `.git`). |
| Branch | `claude/quirky-bardeen-a3purh` (unborn). |
| Existing garment code | None. Everything is built from scratch. |

## Toolchain

| Item | Finding |
|---|---|
| Python | 3.11.15. This matches the Python bundled with Blender 4.1–4.4. Blender 3.6 LTS ships 3.10, so the code avoids 3.11-only syntax. |
| Blender executable | **Not installed.** `which blender` finds nothing. |
| `bpy` module | **Not importable.** |
| `mathutils` | **Not importable.** |
| pytest | Not installed at first. Installed for development (`pytest 9.1`). |
| pyflakes | Installed for development static checks. |
| jsonschema | Installed for development, to validate the generated JSON Schemas. It is **not** a runtime dependency, because Blender does not ship it. |
| fake-bpy-module-4.2 | Installed for development. It contains `.pyi` stubs **generated from Blender 4.2's RNA documentation**. They are not importable (they use PEP 695 syntax), but they can be parsed as text. They are used as an **independent static oracle** for Blender API attribute names, such as `ClothSettings.vertex_group_shrink` and `bpy.ops.ptcache.bake_from_cache`. |

## Garment add-ons available

**None are installed.** OpenSew, Simply Cloth Studio and Garment Tool are not present, and there is no Blender to install them into. Their Python modules and operator names **cannot be verified here**. Consequences:

* The adapters for these add-ons **detect** them through Blender's add-on preferences, using configurable candidate module names.
* Their operations are driven by a **user-configurable operator mapping**. No operator id is invented and presented as fact.
* When an add-on is missing, or detected without a verified mapping, the adapter reports *unavailable* and the orchestrator falls back to Blender-native functionality.

## Native Blender capabilities we integrate with (not rebuilt)

These were verified against the Blender 4.2 API stubs.

| Need | Native Blender feature reused |
|---|---|
| Cloth physics, gravity, solver | `CLOTH` modifier (`ClothSettings`), `scene.gravity`, `effector_weights.gravity` |
| Body collision | `COLLISION` modifier + `Object.collision` (`CollisionSettings.thickness_outer`, `cloth_friction`) |
| Self collision | `ClothCollisionSettings.use_self_collision`, `self_distance_min`, `self_friction` |
| Sewing | `ClothSettings.use_sewing_springs` + loose edges + `sewing_force_max` |
| Elastic / shrinking | `ClothSettings.vertex_group_shrink`, `shrink_min`, `shrink_max` |
| Stiffened bands (zippers, elastic) | `vertex_group_structural_stiffness` + `tension_stiffness_max` |
| Pinning | `vertex_group_mass` + `pin_stiffness` |
| Cache & baking | `PointCache` + `bpy.ops.ptcache.bake / bake_from_cache / free_bake` |
| Collision proxy reduction | `MASK` (vertex group) and `DECIMATE` modifiers on a proxy copy |
| Render thickness & smoothness | `SOLIDIFY` and `SUBSURF` modifiers after the cloth modifier |
| Body landmarks | Armature pose bones (`PoseBone.head/tail`), vertex groups |
| Nearest-surface / intersection queries | `mathutils.bvhtree.BVHTree.FromObject` + `find_nearest` |
| Settled rest state | `Object.shape_key_add` |

## What must be implemented (the missing orchestration layer)

1. Garment description model (schema, normalisation, validation).
2. Garment type and component registries (extensible).
3. Fit system (ease tables, region adjustments, measurement derivation).
4. Avatar model (bone-name resolution for MakeHuman/MPFB, Rigify, Mixamo and UE-style rigs, anthropometric fallback, sections and measurements, regions).
5. Fabric presets (qualitative, artistic) plus a mapping layer to native physics values.
6. Elastic abstraction, mapped onto native shrink and stiffness vertex groups.
7. Garment proxy-geometry builder for the native fallback provider (lofted tubes + sewing springs). It is a coarse starting shape for the cloth solver, **not** a pattern-drafting system.
8. Operation and command system with validation, dry-run, structured results and a transaction/rollback log.
9. Natural-language → structured-operation mapper (deterministic, rule-based).
10. Provider abstraction, registry, capability routing and fallback.
11. Blender integration layer, isolated behind a `get_bpy()` accessor so a mock `bpy` can be injected in tests.
12. Diagnostics (penetration, settling convergence, explosion detection).
13. Blender UI panel and operators, extension manifest, and a Blender-only test runner.

## Testability plan

* Pure-Python logic (1–10, 12) runs under pytest with **no** Blender.
* Blender-layer code (11) runs against a **strict mock `bpy`**. Mock settings objects reject unknown attribute names, and the attribute list is cross-checked against the Blender 4.2 stubs by a static test.
* Real Blender behaviour (the solver running, baking, the UI) can only be tested by `tests/blender/run_blender_tests.py` inside Blender. **It was not run in this environment.**

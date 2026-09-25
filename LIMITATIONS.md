# Known Limitations

This is an honest list. Read it before relying on the add-on in production.

## Verification status

* **Nothing has been run inside Blender.** Blender was not available in the development environment. `tests/blender/run_blender_tests.py` covers registration, the API contract, avatar detection, creation, fitting, collision, cloth setup, simulation, baking, modification and cleanup, but it has **not been executed**. Until it is, treat Blender-side behaviour as *untested*.
* What *is* verified: the pure-Python logic (unit tests), call shapes against a **strict mock bpy**, and all Blender attribute and operator **names** against the `fake-bpy-module-4.2` stubs (generated from Blender 4.2's RNA docs). Runtime semantics are not verified: operator context requirements, value clamping, depsgraph timing and solver behaviour.
* Specific assumptions that the Blender suite checks and that could be wrong:
  * `bpy.ops.ptcache.bake_from_cache` / `ptcache.bake` / `ptcache.free_bake` work with `Context.temp_override(point_cache=..., object=..., scene=...)` in background mode. If not, `bake()` reports `BAKE_FAILED`; bake from the Physics panel instead.
  * Hiding post-cloth modifiers (Solidify, Subdivision) during settle/diagnostic reads may mark the cloth cache outdated. Baking re-simulates, so results stay correct, but it can cost time.
  * `operator_exists()` relies on `bpy.ops.<ns>.<op>.get_rna_type()` raising for unregistered operators.
  * MakeHuman/MPFB bone names (`upperarm01.L`, `lowerleg01.L`, `spine01`, …) and game-engine names follow the conventions as understood here. Use `register_rig_signature()` if your rig differs.

## Garment construction

* The native fallback builds **proxy garments**: lofted elliptical tubes for the torso, sleeves and legs, plus patches for pockets and a hood, joined with sewing springs. It is not pattern drafting. Real-world cut, darts, plackets, collars with lapels, gussets and waistband construction are approximated or represented only as stiffened or elastic vertex groups (zipper, buttons, belt loops, drawstring, collar styles).
* Jacket, skirt and dress are **experimental**. The jacket is a closed tube with a stiff zipper line, not an open front.
* Sleeves assume a straight arm (shoulder → wrist). Strongly bent elbows or unusual poses produce poor initial sleeves. Pose the character in A-pose or T-pose for dressing.
* Trouser legs are sewn to the pelvis panel by nearest-vertex springs. The crotch region is coarse.
* Initial placement pushes vertices out of the body with a BVH query, but a few vertices (armpits, crotch) can still start close to or inside the body, especially with `tight` fits.
* Negative ease (tight fits) is realised with global shrinking (`shrink_min`), not smaller geometry. Low-stretch fabrics with negative ease can be unstable, and validation warns about this.
* Pattern-based providers (OpenSew / Garment Tool) would give much better garments, but they are integrated only through **user-configured operator mappings**: their APIs could not be verified.

## Simulation & physics

* Fabric presets are **artistic simulation presets**, derived from Blender's bundled cloth presets and interpolated. They are **not** measured material data. `typical_gsm` is shown for orientation only.
* `mass` is Blender's per-vertex mass, so the visual weight depends on mesh density (quality level).
* Blender supports **one** shrink group and **one** structural-stiffness group per cloth modifier. Several elastics are combined into weighted groups; very different tensions on neighbouring bands interact.
* Settling uses a mean-vertex-motion threshold. Oscillating cloth may never "settle", which is reported as a warning.
* Penetration diagnostics use nearest-surface normals, so thin features such as fingers and ears can give false positives.
* No cloth-on-cloth **layering** automation. A tucked shirt under pants needs a Collision modifier on the inner garment and simulation in order: inner garment first. `tuck` only changes the shirt's geometry.
* Animation: garments are simulated from `frame_start`. Simulating over an animated character works with native cloth, but the orchestrator does not manage animation ranges beyond the cache frames.

## Wrinkles

* No wrinkle solver is included, by design. `generate_wrinkles()` works only with a provider that has a mapped `wrinkles` capability. Otherwise it returns *"Wrinkle provider unavailable. Simulation can continue without generated wrinkle enhancement."*

## Natural language

* The built-in parser is rule-based and intentionally small. Unrecognised clauses are returned in `unrecognized`, never dropped. Claude should normally send structured operations and use the parser as a cross-check.

## Avatar detection

* Scoring prefers the active object, armature-deformed meshes, MakeHuman/MPFB properties and human-like names. Scenes with several characters should pass `avatar="ObjectName"`.
* Measurements come from convex-hull cross-sections, which approximate a tape measure. Arms held against the torso can contaminate chest measurements; these are detected and replaced by estimates with a warning. Explicit metadata (`ai_garment_avatar` JSON custom property, or `metadata=`) always wins.
* Characters must be roughly Z-up and facing −Y (Blender convention). Other orientations are not auto-detected.

## Packaging

* When installed as an extension, `from ai_garment import garment` works through a `sys.modules` alias added in `register()`. Deep imports such as `import ai_garment.core.x` load a second copy of that module in extension mode; import from the top-level package instead.
* Performance: vertex data is moved with Python lists, not `foreach_get`. This is fine for garments of a few thousand vertices, but slow for very dense meshes.

## What still needs manual Blender work

* Running `tests/blender/run_blender_tests.py` and fixing anything it finds.
* Verifying and configuring operator mappings for any installed garment add-on.
* Artistic review of fabric presets against reference renders.
* Final look development (textures, UVs). Garment meshes have no UVs, and materials are plain Principled BSDF.

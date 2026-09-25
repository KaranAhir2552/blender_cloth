# Real-Blender tests (REQUIRE BLENDER)

These tests cannot run in plain Python. They were **not run** in the environment where this add-on was developed, because Blender is not installed there.

```bash
# from the repository root
blender --background --factory-startup --python tests/blender/run_blender_tests.py
# keep the generated objects and save the scene for inspection:
blender --background --factory-startup --python tests/blender/run_blender_tests.py -- --keep --save /tmp/aig.blend
```

The run exits with code `0` only if every step passed. `tests/blender/last_run.json` records each step's result and timing.

Steps: registration, API contract (real `hasattr`), synthetic rigged humanoid, provider detection, avatar detection, garment creation, fitting and collision proxy, cloth/elastic/sewing configuration, draft simulation with settle and diagnostics, baking, modification and refabric with a settled shape key, pants with dry-run and invalid-spec safety, and cleanup (only tagged objects are removed; the avatar stays intact).

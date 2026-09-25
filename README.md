# AI Garment Orchestrator for Blender

A Blender add-on (Blender 4.2+ extension) that lets **Claude**, or any caller, create, fit, modify and simulate clothing on a human character through a **small, validated, high-level API**. The caller doesn't need to know about cloth settings, vertex groups, sewing springs, collision margins or caches.

It is an **orchestration layer**, not a cloth engine. Physics comes from Blender's native Cloth, Collision, sewing springs and PointCache. Installed garment add-ons (OpenSew, Simply Cloth Studio, Garment Tool) plug in through provider adapters.

```python
from ai_garment import garment

shirt = garment.create(type="tshirt", fit="oversized", fabric="cotton", color="black")
shirt.fit_to_avatar()                                   # MakeHuman / Rigify / Mixamo / generic character
shirt.add_component(type="elastic_cuff", target="sleeves", strength="medium")
shirt.modify(region="chest", fit="tighter")             # structured edit
shirt.apply("Roll the sleeves slightly upward.")        # or plain English
shirt.simulate(mode="natural")                          # gravity + collision + self collision + settle + bake
print(shirt.inspect())                                  # structured state for Claude
```

Or in one step, with a preview first:

```python
text = ("Create an oversized black cotton T-shirt on my MakeHuman character. Make the sleeves slightly loose "
        "with medium elastic cuffs. Let gravity naturally settle the shirt and make the fabric look realistic.")
garment.plan(text).to_dict()   # dry run: parsed operations, validation, simulation plan; no scene changes
garment.run(text)              # execute (transactional; rolled back on failure)
```

## What's inside

| Area | Summary |
|---|---|
| Garment model | JSON-able `GarmentSpec` with shorthand (`"sleeves": {"length": "short", "cuff": {"type": "elastic"}}`) normalised into explicit components |
| Garment types | tshirt, shirt, hoodie, sweatshirt, pants, jeans, shorts (v1); jacket, skirt, dress (experimental); registry is extensible |
| Components | body, sleeve, leg, hood, collar, cuff, elastic_cuff, hem, waistband, elastic_waistband, pocket, cargo_pocket, kangaroo_pocket, zipper, button_placket, button, belt_loop, drawstring, elastic, seam |
| Fit | tight … oversized ease tables; region edits (chest, waist, hips, shoulders, sleeves, legs, cuffs, neck) with "slightly"/"much" intensity |
| Fabrics | 13 **artistic** presets (12 required + fleece) with qualifiers ("heavy denim", "stretchy cotton"), mapped to native cloth parameters |
| Elastic | strength presets, tension and width, combined into Blender's single shrink group plus a structural-stiffness group |
| Avatar | bone-name resolution (MakeHuman/MPFB, game-engine, Rigify, Mixamo, custom), cross-section measurements, anthropometric fallback, unit-scale detection |
| Simulation | one call: gravity, proxy collision, self collision, fabric settings, sewing, pins, cache, settling with convergence detection, penetration and stability diagnostics, bake |
| Safety | tagging, refusal to delete untagged objects, avatar untouched (collision proxy), transactions and rollback, dry run, validation before any scene change |
| Claude interface | object API, flat JSON commands, generated JSON Schemas and tool definitions, NL → operation mapper |

## Test status (development environment)

```
STATUS:
Static compilation (compileall): PASS
Pure Python tests: PASS (243 passed, 0 failed)
Mock Blender tests: PASS (44 passed, 0 failed)
Static checks (imports, cycles, lint, manifest, schemas, API contract): PASS (103 passed, 0 failed)
Real Blender tests: NOT RUN - Blender unavailable
```

Blender was not available where this was built. Nothing here claims verified behaviour inside Blender. The mock tests check call shapes against a strict mock whose attribute names were cross-checked against Blender 4.2 API stubs. The real-Blender suite (`tests/blender/run_blender_tests.py`) is ready to run. See [TEST_PLAN.md](TEST_PLAN.md) and [LIMITATIONS.md](LIMITATIONS.md).

## Documentation

* [INSTALL.md](INSTALL.md): install in Blender, run the tests
* [CLAUDE_USAGE.md](CLAUDE_USAGE.md): how Claude should drive the system (workflow, operations, examples)
* [docs/API.md](docs/API.md): API reference
* [PROVIDER_SETUP.md](PROVIDER_SETUP.md): Blender native, OpenSew / Simply Cloth / Garment Tool adapters, writing providers
* [LIMITATIONS.md](LIMITATIONS.md): what does not work (yet) and what needs manual Blender work
* [ARCHITECTURE.md](ARCHITECTURE.md), [TEST_PLAN.md](TEST_PLAN.md), [docs/PHASE1_ANALYSIS.md](docs/PHASE1_ANALYSIS.md)

## Repository layout

```
ai_garment/        the add-on / extension (core = pure Python, blender = bpy layer, providers, api)
tests/unit         pure-Python tests            tests/mock    strict-mock bpy tests
tests/static       compile/import/lint/contract tests/blender real-Blender suite (run inside Blender)
scripts/           run_checks.py (STATUS block), build_extension.py (zips)
```

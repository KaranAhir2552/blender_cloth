# Installation & Testing

## Requirements

* Blender **4.2 or newer**. The package is a Blender 4.2 extension (`blender_manifest.toml`), and the code avoids Python-3.11-only syntax. It also carries `bl_info` for legacy add-on installs, but only 4.2+ has been targeted.
* No third-party Python packages at runtime.
* For development only: Python 3.10+, `pytest`, and optionally `pyflakes`, `jsonschema` and `fake-bpy-module-4.2` (the last one enables the API-contract checks).

## Build the zip

```bash
# Preferred (validates the manifest), run from the repository root:
blender --command extension build --source-dir ai_garment --output-dir dist

# Without Blender:
python scripts/build_extension.py
#   dist/ai_garment-0.1.0-extension.zip   (Blender 4.2+ "Install from Disk")
#   dist/ai_garment-0.1.0-legacy.zip      (legacy add-on install, top-level ai_garment/ folder)
```

## Install in Blender 4.2+

1. *Edit → Preferences → Get Extensions → ⌄ (top right) → Install from Disk…*
2. Pick `dist/ai_garment-0.1.0-extension.zip` and make sure the extension is enabled.
3. In the 3D Viewport press **N** and open the **AI Garment** tab: instruction field, *Preview Plan*, *Execute*, *Detect Avatar*, *Inspect*, *Bake*. Reports go to the text datablock `AI_Garment_Report`.

Command line alternative:

```bash
blender --command extension install-file -r user_default -e dist/ai_garment-0.1.0-extension.zip
```

## Use from Python / Claude inside Blender

```python
import ai_garment              # works after the extension is enabled (register() adds the alias)
from ai_garment import garment
garment.capabilities()
```

When installed as an extension, the real module name is `bl_ext.user_default.ai_garment`. `register()` adds `sys.modules["ai_garment"]` so `from ai_garment import garment` works. Only the top-level package is aliased, so import names from the package (`from ai_garment import garment, commands`) rather than deep submodule paths.

## Development without installing

```bash
cd /path/to/blender_cloth
blender --python-expr "import sys; sys.path.insert(0, '.'); import ai_garment; ai_garment.register()"
```

## Run the tests

```bash
pip install pytest pyflakes jsonschema fake-bpy-module-4.2   # optional extras enable more static checks
python scripts/run_checks.py                                  # everything available + STATUS block
python -m pytest tests -m pure      # pure-Python logic
python -m pytest tests -m mock      # strict mock bpy
python -m pytest tests -m static    # compile, imports, cycles, lint, manifest, schemas, API contract

# REAL Blender (required to verify Blender behaviour):
blender --background --factory-startup --python tests/blender/run_blender_tests.py
# report: tests/blender/last_run.json ; exit code 0 = all steps passed
```

`scripts/run_checks.py` runs the real-Blender suite automatically when `$BLENDER`, or `blender` on `PATH`, is available. Otherwise it reports `Real Blender tests: NOT RUN`.

## Optional configuration

| Env var | Purpose |
|---|---|
| `AI_GARMENT_FABRICS` | Path to a JSON file with extra or overriding fabric presets (same layout as `ai_garment/data/fabric_presets.json`) |
| `AI_GARMENT_PROVIDER_CONFIG` | Path to a JSON file with add-on operator mappings (see PROVIDER_SETUP.md) |

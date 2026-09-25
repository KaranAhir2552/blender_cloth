"""Build installable zips without Blender.

    python scripts/build_extension.py
      -> dist/ai_garment-<version>-extension.zip  (Blender 4.2+: files at zip root, manifest included)
      -> dist/ai_garment-<version>-legacy.zip     (legacy add-on install: top-level ai_garment/ folder)

Blender 4.2+ can also build the extension natively (preferred; it validates the manifest):
    blender --command extension build --source-dir ai_garment --output-dir dist
"""
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "ai_garment")


def main():
    with open(os.path.join(PKG, "blender_manifest.toml"), encoding="utf-8") as fh:
        version = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.M).group(1)
    out_dir = os.path.join(ROOT, "dist")
    os.makedirs(out_dir, exist_ok=True)
    files = []
    for dirpath, dirnames, names in os.walk(PKG):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        files += [os.path.join(dirpath, f) for f in names if not f.endswith((".pyc", ".zip"))]
    for layout, base in (("extension", PKG), ("legacy", ROOT)):
        out = os.path.join(out_dir, f"ai_garment-{version}-{layout}.zip")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for full in sorted(files):
                zf.write(full, os.path.relpath(full, base))
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

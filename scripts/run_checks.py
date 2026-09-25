"""Run every check available in this environment and print an honest STATUS block.

    python scripts/run_checks.py

Real-Blender tests run only if a Blender executable is found (``$BLENDER`` or
``blender`` on PATH); otherwise they are reported as NOT RUN.
"""
import compileall
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pytest_marker(marker):
    proc = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", "-m", marker, "-p", "no:cacheprovider"],
                          cwd=ROOT, capture_output=True, text=True)
    tail = (proc.stdout.strip().splitlines() or [""])[-1]
    counts = dict((k, int(v)) for v, k in re.findall(r"(\d+) (passed|failed|errors?|skipped)", tail))
    ok = proc.returncode == 0
    return ok, counts, tail, proc.stdout


def main():
    status = {}
    comp = all(compileall.compile_dir(os.path.join(ROOT, d), quiet=1, force=True)
               for d in ("ai_garment", "tests", "scripts"))
    status["Static compilation (compileall)"] = "PASS" if comp else "FAIL"
    labels = {"pure": "Pure Python tests", "mock": "Mock Blender tests",
              "static": "Static checks (imports, cycles, lint, manifest, schemas, API contract)"}
    all_ok = comp
    for marker, label in labels.items():
        ok, counts, tail, out = pytest_marker(marker)
        all_ok &= ok
        skipped = f", {counts['skipped']} skipped" if counts.get("skipped") else ""
        status[label] = f"{'PASS' if ok else 'FAIL'} ({counts.get('passed', 0)} passed, " \
                        f"{counts.get('failed', 0)} failed{skipped})"
        if not ok:
            print(out)
    blender = os.environ.get("BLENDER") or shutil.which("blender")
    if blender:
        proc = subprocess.run([blender, "--background", "--factory-startup", "--python",
                               os.path.join(ROOT, "tests", "blender", "run_blender_tests.py")], cwd=ROOT)
        status["Real Blender tests"] = "PASS" if proc.returncode == 0 else f"FAIL (exit {proc.returncode})"
        all_ok &= proc.returncode == 0
    else:
        status["Real Blender tests"] = "NOT RUN - Blender unavailable"
    print("\nSTATUS:")
    for k, v in status.items():
        print(f"{k}: {v}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())

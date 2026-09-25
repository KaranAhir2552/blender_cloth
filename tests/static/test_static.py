"""Static validation that does not need Blender."""
import ast
import compileall
import importlib
import os
import pkgutil
import re
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKG = os.path.join(ROOT, "ai_garment")
BLENDER_ONLY_MODULES = {"ai_garment.blender.ui"}


def package_modules():
    out = []
    for dirpath, _, files in os.walk(PKG):
        for f in files:
            if f.endswith(".py"):
                rel = os.path.relpath(os.path.join(dirpath, f), ROOT)[:-3].replace(os.sep, ".")
                out.append(rel[:-9] if rel.endswith(".__init__") else rel)
    return sorted(out)


def module_path(mod):
    p = os.path.join(ROOT, *mod.split("."))
    return p + ".py" if os.path.exists(p + ".py") else os.path.join(p, "__init__.py")


def parse(mod):
    with open(module_path(mod), encoding="utf-8") as fh:
        return ast.parse(fh.read(), module_path(mod))


def test_compileall():
    assert compileall.compile_dir(PKG, quiet=1, force=True)
    assert compileall.compile_dir(os.path.join(ROOT, "tests"), quiet=1, force=True)
    assert compileall.compile_dir(os.path.join(ROOT, "scripts"), quiet=1, force=True)


@pytest.mark.parametrize("mod", [m for m in package_modules() if m not in BLENDER_ONLY_MODULES])
def test_every_module_imports_without_bpy(mod):
    assert "bpy" not in sys.modules
    importlib.import_module(mod)
    assert "bpy" not in sys.modules, f"importing {mod} pulled in bpy"


def _resolve_relative(mod, node):
    is_pkg = module_path(mod).endswith("__init__.py")
    base = mod.split(".") if is_pkg else mod.split(".")[:-1]
    if node.level > 1:
        base = base[: -(node.level - 1)]
    return ".".join(base + ([node.module] if node.module else []))


def top_level_imports(mod):
    """Intra-package imports executed at import time (module/class level, not inside functions)."""
    tree = parse(mod)
    found = set()

    def visit(body):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if isinstance(node, ast.ImportFrom) and node.level > 0:
                target = _resolve_relative(mod, node)
                for alias in node.names:
                    sub = target + "." + alias.name
                    found.add(sub if os.path.exists(module_path(sub)) else target)
            elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("ai_garment"):
                found.add(node.module)
            for field in ("body", "orelse", "finalbody", "handlers"):
                inner = getattr(node, field, None)
                if isinstance(inner, list):
                    visit(inner)

    visit(tree.body)
    return {f for f in found if f in set(package_modules())}


def test_no_circular_imports():
    mods = package_modules()
    graph = {m: top_level_imports(m) - {m} for m in mods}
    # a package __init__ importing its own submodules is not a cycle participant for parents
    visiting, done, cycles = set(), set(), []

    def dfs(m, stack):
        visiting.add(m)
        stack.append(m)
        for n in graph.get(m, ()):
            if n in visiting:
                cyc = stack[stack.index(n):] + [n]
                # ignore package->child->package edges created only by `from . import x` in __init__
                if not all(a.startswith(b) or b.startswith(a) for a, b in zip(cyc, cyc[1:])):
                    cycles.append(cyc)
            elif n not in done:
                dfs(n, stack)
        stack.pop()
        visiting.discard(m)
        done.add(m)

    for m in mods:
        if m not in done:
            dfs(m, [])
    assert cycles == []


def test_only_relative_intra_package_imports():
    """Blender 4.2 extensions are loaded as bl_ext.<repo>.ai_garment: absolute imports break."""
    offenders = []
    for mod in package_modules():
        for node in ast.walk(parse(mod)):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and \
                    node.module.split(".")[0] == "ai_garment":
                offenders.append((mod, node.module))
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.split(".")[0] == "ai_garment":
                        offenders.append((mod, a.name))
    assert offenders == []


def test_core_is_pure_python():
    forbidden_abs = {"bpy", "mathutils", "bmesh", "addon_utils"}
    offenders = []
    for mod in package_modules():
        if not mod.startswith("ai_garment.core"):
            continue
        for node in ast.walk(parse(mod)):
            if isinstance(node, ast.Import):
                offenders += [(mod, a.name) for a in node.names if a.name.split(".")[0] in forbidden_abs]
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module and node.module.split(".")[0] in forbidden_abs:
                    offenders.append((mod, node.module))
                if node.level > 0:
                    target = _resolve_relative(mod, node)
                    if not target.startswith("ai_garment.core"):
                        offenders.append((mod, target))
    assert offenders == []


def test_bpy_only_imported_through_accessor():
    allowed = {"ai_garment.blender._bpy", "ai_garment.blender.ui"}
    offenders = []
    for mod in package_modules():
        if mod in allowed:
            continue
        for node in ast.walk(parse(mod)):
            if isinstance(node, ast.Import) and any(a.name.split(".")[0] in ("bpy", "mathutils", "addon_utils")
                                                    for a in node.names):
                offenders.append(mod)
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and \
                    node.module.split(".")[0] in ("bpy", "mathutils", "addon_utils"):
                offenders.append(mod)
    assert offenders == []


def test_no_silent_exception_swallowing():
    """'Never silently fail': an except block must not consist solely of `pass`."""
    offenders = []
    for mod in package_modules():
        for node in ast.walk(parse(mod)):
            if isinstance(node, ast.ExceptHandler):
                if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    offenders.append((mod, node.lineno))
                if node.type is None:
                    offenders.append((mod, node.lineno, "bare except"))
    assert offenders == []


def test_pyflakes_clean():
    pyflakes = pytest.importorskip("pyflakes")
    assert pyflakes
    proc = subprocess.run([sys.executable, "-m", "pyflakes", PKG, os.path.join(ROOT, "tests"),
                           os.path.join(ROOT, "scripts")], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_extension_manifest():
    import tomllib
    with open(os.path.join(PKG, "blender_manifest.toml"), "rb") as fh:
        m = tomllib.load(fh)
    for key in ("schema_version", "id", "version", "name", "tagline", "maintainer", "type",
                "blender_version_min", "license"):
        assert key in m, key
    assert m["id"] == "ai_garment"
    assert m["type"] == "add-on"
    assert re.fullmatch(r"\d+\.\d+\.\d+", m["version"])
    assert len(m["tagline"]) <= 64 and not m["tagline"].endswith((".", "!", "?"))
    assert all(lic.startswith("SPDX:") for lic in m["license"])
    import ai_garment
    assert ".".join(map(str, ai_garment.bl_info["version"])) == m["version"]
    assert tuple(int(x) for x in m["blender_version_min"].split(".")) >= (4, 2, 0)


def test_fabric_presets_data_file():
    import json
    from ai_garment.core import fabric_presets as fp
    with open(os.path.join(PKG, "data", "fabric_presets.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["artistic_presets"] is True
    for name, p in data["presets"].items():
        assert p["weight_class"] in fp.WEIGHT_CLASSES, name
        assert p["stretch"] in fp.LEVELS, name
        assert p["bend"] in fp.BEND_LEVELS, name
        assert p["drape"] in fp.LEVELS, name
        assert p["damping"] in fp.LEVELS, name
        assert p["friction"] in fp.LEVELS, name
        assert p["thickness_mm"] > 0


def test_provider_discovery():
    from ai_garment.providers.base import Capability, GarmentProvider
    from ai_garment.providers.registry import default_registry
    reg = default_registry()
    names = [p.name for p in reg.providers()]
    assert len(names) == len(set(names))
    for p in reg.providers():
        assert isinstance(p, GarmentProvider)
        assert p.display_name
        assert p.capabilities <= Capability.ALL
        st = p.available()  # must not raise without Blender
        assert st.available is False


def test_command_registration():
    from ai_garment.api.commands import COMMANDS
    required = ["create_garment", "fit_garment", "modify_garment", "set_fabric", "add_component", "set_fit",
                "simulate_garment", "bake_simulation", "inspect_garment", "settle_garment", "execute_plan",
                "parse_instruction", "detect_avatar", "detect_provider", "describe_schema", "apply_instruction"]
    for name in required:
        assert name in COMMANDS, name
        assert callable(COMMANDS[name])
        assert (COMMANDS[name].__doc__ or "").strip(), f"{name} lacks a docstring"


def test_commands_never_raise_without_blender():
    from ai_garment.api import commands
    r = commands.create_garment({"type": "tshirt"})
    assert r["ok"] is False
    assert r["errors"]
    r = commands.create_garment({"type": "tshirt", "fabric": "unicorn_skin"}, dry_run=True)
    assert r["ok"] is False and r["errors"][0]["code"] == "UNKNOWN_FABRIC"
    r = commands.inspect_garment("does-not-exist")
    assert r["ok"] is False and r["errors"][0]["code"] == "GARMENT_NOT_FOUND"
    r = commands.detect_avatar()
    assert r["ok"] is False


def test_all_submodules_discoverable():
    import ai_garment
    names = {m.name for m in pkgutil.walk_packages(ai_garment.__path__, "ai_garment.")}
    assert "ai_garment.core.garment_spec" in names
    assert "ai_garment.providers.blender_native" in names

"""Cross-check every Blender API name ai_garment relies on against the
fake-bpy-module-4.2 stubs (generated from Blender 4.2's RNA docs).

This catches misspelled / non-existent attributes WITHOUT Blender. It cannot
prove runtime semantics; tests/blender/run_blender_tests.py repeats the
check with hasattr() inside real Blender.
"""
import os
import re
import sysconfig

import pytest

from ai_garment.blender.api_contract import CONTRACT, MODIFIER_TYPES, OPERATORS


def _stub_root():
    for base in {sysconfig.get_paths()["purelib"], sysconfig.get_paths()["platlib"]} | set(
            p for p in __import__("sys").path if p.endswith(("site-packages", "dist-packages"))):
        cand = os.path.join(base, "bpy-stubs")
        if os.path.isdir(cand):
            return cand
    return None


STUBS = _stub_root()
pytestmark = pytest.mark.skipif(STUBS is None, reason="fake-bpy-module-4.2 not installed")


def _types_source():
    with open(os.path.join(STUBS, "types", "__init__.pyi"), encoding="utf-8") as fh:
        return fh.read()


def _class_members(src, name):
    m = re.search(r"^class " + re.escape(name) + r"\b[^\n]*:\n(.*?)(?=^class |\Z)", src, re.S | re.M)
    assert m, f"class {name} not found in stubs"
    body = m.group(1)
    return set(re.findall(r"^    (\w+)\s*:", body, re.M)) | set(re.findall(r"^    def (\w+)\(", body, re.M))


def _all_members(src, name, seen=None):
    """Members including (single-level) base classes declared in the stub."""
    seen = seen or set()
    if name in seen:
        return set()
    seen.add(name)
    members = _class_members(src, name)
    header = re.search(r"^class " + re.escape(name) + r"\(([^)]*)\)", src, re.M)
    if header:
        for base in header.group(1).split(","):
            base = base.strip().split("[")[0].split(".")[-1]
            if base and re.search(r"^class " + re.escape(base) + r"\b", src, re.M):
                members |= _all_members(src, base, seen)
    return members


@pytest.mark.parametrize("cls_name", sorted(CONTRACT))
def test_attributes_exist_in_blender_42(cls_name):
    src = _types_source()
    members = _all_members(src, cls_name)
    missing = sorted(set(CONTRACT[cls_name]) - members)
    assert missing == [], f"{cls_name} has no {missing} in Blender 4.2"


def test_modifier_types_exist():
    with open(os.path.join(STUBS, "stub_internal", "rna_enums", "__init__.pyi"), encoding="utf-8") as fh:
        src = fh.read()
    block = re.search(r"type ObjectModifierTypeItems = typing.Literal\[(.*?)\]", src, re.S).group(1)
    names = set(re.findall(r'"([A-Z_]+)"', block))
    assert set(MODIFIER_TYPES) <= names


@pytest.mark.parametrize("idname", OPERATORS)
def test_operators_exist(idname):
    ns, op = idname.split(".")
    path = os.path.join(STUBS, "ops", ns, "__init__.pyi")
    with open(path, encoding="utf-8") as fh:
        assert re.search(r"^class " + re.escape(op) + r"\(", fh.read(), re.M), idname

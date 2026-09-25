"""Shared pytest configuration.

Suites are classified by directory:
    tests/unit   -> marker ``pure``   (no Blender, no mock)
    tests/mock   -> marker ``mock``   (strict mock bpy injected)
    tests/static -> marker ``static`` (compile/import/lint/contract checks)
tests/blender is NOT collected by pytest; it must run inside Blender.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
for p in (ROOT, TESTS):
    if p not in sys.path:
        sys.path.insert(0, p)

collect_ignore_glob = ["blender/*"]


def pytest_collection_modifyitems(config, items):
    for item in items:
        path = str(item.fspath).replace("\\", "/")
        if "/tests/unit/" in path:
            item.add_marker(pytest.mark.pure)
        elif "/tests/mock/" in path:
            item.add_marker(pytest.mark.mock)
        elif "/tests/static/" in path:
            item.add_marker(pytest.mark.static)


@pytest.fixture(autouse=True)
def _no_real_bpy_leak(request):
    """Pure/static tests must never see a bpy module (real or mock)."""
    is_mock = "/tests/mock/" in str(request.node.fspath).replace("\\", "/")
    if not is_mock:
        assert "bpy" not in sys.modules or getattr(sys.modules["bpy"], "__is_mock__", False) is False
        sys.modules.pop("bpy", None)
    yield
    if not is_mock:
        sys.modules.pop("bpy", None)


@pytest.fixture
def mock_bpy():
    """Install the strict mock bpy/mathutils for the duration of a test."""
    from mocks.mock_bpy import install_mock_bpy, uninstall_mock_bpy

    bpy = install_mock_bpy()
    try:
        yield bpy
    finally:
        uninstall_mock_bpy()


@pytest.fixture
def humanoid():
    from fixtures.humanoid import make_humanoid

    return make_humanoid()

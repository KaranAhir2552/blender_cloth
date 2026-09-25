import pytest

from ai_garment.api.garment import GarmentSystem
from ai_garment.blender import scene as bscene
from ai_garment.core.errors import GarmentError
from ai_garment.providers.blender_native import BlenderNativeProvider
from mocks.mock_bpy import build_humanoid_scene

FLAGSHIP = [
    {"operation": "create", "type": "tshirt", "fit": "oversized", "fabric": "cotton", "color": "black"},
    {"operation": "add_component", "type": "elastic_cuff", "target": "sleeves", "strength": "medium"},
    {"operation": "fit"},
    {"operation": "simulate", "mode": "natural", "quality": "draft"},
]


@pytest.fixture
def env(mock_bpy, humanoid):
    body, arm = build_humanoid_scene(mock_bpy, humanoid)
    return mock_bpy, body, arm, GarmentSystem()


def test_dry_run_no_mutation(env):
    """Brief test 8."""
    bpy, body, arm, system = env
    before = bpy._snapshot()
    res = system.execute(FLAGSHIP, dry_run=True)
    assert res.to_dict()["valid"]
    res = system.create(type="tshirt", dry_run=True)
    assert res.dry_run
    system.plan("Create a loose black hoodie and let it settle")
    assert bpy._snapshot() == before


def test_invalid_spec_does_not_touch_scene(env):
    """Brief test 7."""
    bpy, body, arm, system = env
    before = bpy._snapshot()
    with pytest.raises(GarmentError) as exc:
        system.create(type="tshirt", fabric="unicorn_skin")
    assert exc.value.code == "VALIDATION_FAILED"
    assert "UNKNOWN_FABRIC" in [e["code"] for e in exc.value.to_dict()["details"]["errors"]]
    res = system.execute([{"operation": "create", "type": "tshirt", "fabric": "unicorn_skin"}])
    assert not res.ok
    assert bpy._snapshot() == before


def test_safe_remove_refuses_untagged_objects(env):
    bpy, body, arm, system = env
    with pytest.raises(GarmentError) as exc:
        bscene.safe_remove_object(body, garment_id="anything")
    assert exc.value.code == "UNSAFE_DELETE"
    assert bpy.data.objects.get("Human") is body


def test_safe_remove_refuses_other_garments(env):
    bpy, body, arm, system = env
    a = system.create(type="tshirt")
    b = system.create(type="pants")
    obj_a = bpy.data.objects.get(a.object_name)
    with pytest.raises(GarmentError):
        bscene.safe_remove_object(obj_a, garment_id=b.id)
    b.delete()
    assert bpy.data.objects.get(a.object_name) is obj_a


def test_failure_mid_plan_rolls_back_scene(env, monkeypatch):
    bpy, body, arm, system = env
    bpy.context.scene.use_gravity = False
    before = bpy._snapshot()

    def boom(self, record, settings, avatar=None):
        raise RuntimeError("solver crashed")

    monkeypatch.setattr(BlenderNativeProvider, "simulate", boom)
    res = system.execute(FLAGSHIP, transactional=True)
    assert not res.ok
    assert any("solver crashed" in e.message for e in res.errors)
    assert res.data["rolled_back"] is True
    after = bpy._snapshot()
    assert after["objects"] == before["objects"]
    assert bpy.context.scene.use_gravity is False
    assert system.list_garments() == []


def test_non_transactional_failure_keeps_partial_work(env, monkeypatch):
    bpy, body, arm, system = env

    def boom(self, record, settings, avatar=None):
        raise RuntimeError("solver crashed")

    monkeypatch.setattr(BlenderNativeProvider, "simulate", boom)
    res = system.execute(FLAGSHIP, transactional=False)
    assert not res.ok and res.data["rolled_back"] is False
    assert len(system.list_garments()) == 1


def test_avatar_untouched_by_full_pipeline(env):
    bpy, body, arm, system = env
    snap_body = ([(m.name, m.type) for m in body.modifiers], [g.name for g in body.vertex_groups],
                 sorted(body.keys()), [tuple(v.co) for v in body.data.vertices[:50]])
    res = system.execute(FLAGSHIP)
    assert res.ok, res.to_dict()
    assert snap_body == ([(m.name, m.type) for m in body.modifiers], [g.name for g in body.vertex_groups],
                         sorted(body.keys()), [tuple(v.co) for v in body.data.vertices[:50]])


def test_direct_collision_mode_is_tagged_and_reversible(env):
    bpy, body, arm, system = env
    av = system.detect_avatar()
    r = av.prepare_collision(garment_type="tshirt", mode="direct")
    assert r.ok
    mod = body.modifiers.get("AIG_Collision")
    assert mod is not None and mod.type == "COLLISION"
    r = av.remove_collision()
    assert r.ok
    assert body.modifiers.get("AIG_Collision") is None


def test_direct_mode_refuses_existing_foreign_collision(env):
    bpy, body, arm, system = env
    body.modifiers.new("UserCollision", "COLLISION")
    av = system.detect_avatar()
    r = av.prepare_collision(garment_type="tshirt", mode="direct")
    assert r.ok
    assert any("existing collision" in w.lower() for w in r.warnings)
    assert body.modifiers.get("AIG_Collision") is None
    av.remove_collision()
    assert body.modifiers.get("UserCollision") is not None


def test_rollback_method_on_garment(env):
    bpy, body, arm, system = env
    shirt = system.create(type="tshirt", transactional=True)
    name = shirt.object_name
    r = shirt.rollback()
    assert r.ok
    assert bpy.data.objects.get(name) is None

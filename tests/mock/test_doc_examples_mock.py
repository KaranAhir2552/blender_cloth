"""The code examples in README.md / CLAUDE_USAGE.md must actually work (against the mock)."""
import json

from ai_garment.api.garment import GarmentSystem
from mocks.mock_bpy import build_humanoid_scene


def test_readme_example(mock_bpy, humanoid):
    build_humanoid_scene(mock_bpy, humanoid)
    garment = GarmentSystem()
    shirt = garment.create(type="tshirt", fit="oversized", fabric="cotton", color="black")
    assert shirt.fit_to_avatar().ok
    assert shirt.add_component(type="elastic_cuff", target="sleeves", strength="medium").ok
    assert shirt.modify(region="chest", fit="tighter").ok
    assert shirt.apply("Roll the sleeves slightly upward.").ok
    assert shirt.simulate(mode="natural", quality="draft").ok
    json.dumps(shirt.inspect())


def test_claude_usage_minimal_session(mock_bpy, humanoid):
    build_humanoid_scene(mock_bpy, humanoid)
    garment = GarmentSystem()
    assert garment.detect_avatar().to_dict()["ok"]
    plan = garment.plan([
        {"operation": "create", "type": "tshirt", "fit": "oversized", "fabric": "cotton", "color": "black"},
        {"operation": "set_fit", "target": "sleeves", "level": "relaxed"},
        {"operation": "add_component", "type": "elastic_cuff", "target": "sleeves", "strength": "medium"},
        {"operation": "fit"},
        {"operation": "simulate", "mode": "natural", "quality": "draft"},
    ])
    assert plan.to_dict()["valid"], plan.to_dict()["errors"]
    result = garment.execute(plan.data["plan"])
    assert result.ok, result.to_dict()
    shirt = garment.get(result.data["garment"]["id"])
    info = shirt.inspect()
    assert info["simulation"]["baked"] is True
    assert shirt.spec.fit.component_levels["left_sleeve"] == "relaxed"


def test_commands_round_trip(mock_bpy, humanoid):
    build_humanoid_scene(mock_bpy, humanoid)
    from ai_garment.api import commands, garment as gmod
    gmod.garment.store.clear()
    r = commands.create_garment({"type": "jeans", "fit": "slim"})
    assert r["ok"], r
    gid = r["garment"]
    assert commands.modify_garment(gid, component="legs", fit="baggy")["ok"]
    assert commands.inspect_garment(gid)["data"]["type"] == "jeans"
    assert commands.run_command("list_garments")["data"][0]["id"] == gid
    assert commands.delete_garment(gid)["ok"]

import json

from ai_garment.api.garment import GarmentSystem
from ai_garment.core.garment_spec import GarmentSpec
from ai_garment.core.planning import plan_creation, plan_simulation
from ai_garment.providers.registry import ProviderRegistry, default_registry
from fixtures.fake_providers import RecordingProvider


def registry_with_fake():
    reg = ProviderRegistry()
    fake = RecordingProvider()
    reg.register(fake)
    return reg, fake


def test_create_tshirt_plan():
    """Brief test 1."""
    reg, _ = registry_with_fake()
    spec = GarmentSpec.from_dict({"type": "tshirt", "fabric": "cotton", "fit": "oversized"})
    plan = plan_creation(spec, registry=reg)
    assert plan.valid
    assert plan.executable
    assert plan.provider == "fake_native"
    assert plan.data["garment"] == "tshirt"
    assert plan.data["fabric"] == "cotton"
    assert plan.data["fit"] == "oversized"
    assert plan.operations[0] == "Create T-shirt"
    assert "Apply oversized fit" in plan.operations
    assert "Apply cotton preset" in plan.operations
    json.dumps(plan.to_dict())


def test_create_plan_outside_blender_is_valid_but_not_executable():
    spec = GarmentSpec.from_dict({"type": "tshirt"})
    plan = plan_creation(spec, registry=default_registry())
    assert plan.valid
    assert not plan.executable
    assert any("Blender" in w for w in plan.warnings)


def test_invalid_spec_plan():
    reg, _ = registry_with_fake()
    plan = plan_creation(GarmentSpec.from_dict({"type": "tshirt", "fabric": "unicorn_skin"}), registry=reg)
    assert not plan.valid
    assert plan.errors[0].code == "UNKNOWN_FABRIC"


def step_ids(plan):
    return [s.id for s in plan.steps]


def test_natural_simulation_plan():
    """Brief test 10."""
    spec = GarmentSpec.from_dict({"type": "tshirt"})
    plan = plan_simulation(spec, mode="natural")
    ids = step_ids(plan)
    for required in ("gravity", "collision", "self_collision", "fabric_settings", "settling", "bake"):
        assert required in ids, required
    assert ids.index("fabric_settings") < ids.index("settling") < ids.index("bake")


def test_preview_simulation_is_cheap():
    plan = plan_simulation(GarmentSpec.from_dict({"type": "tshirt"}), mode="preview")
    ids = step_ids(plan)
    assert "bake" not in ids
    assert "self_collision" not in ids
    assert plan.data["quality"] in ("draft", "preview")


def test_elastic_and_sewing_steps_present_when_needed():
    spec = GarmentSpec.from_dict({"type": "hoodie"})
    ids = step_ids(plan_simulation(spec, mode="natural"))
    assert "sewing" in ids
    assert "elastic" in ids


FLAGSHIP = [
    {"operation": "create", "type": "tshirt", "fit": "oversized", "fabric": "cotton", "color": "black"},
    {"operation": "add_component", "type": "elastic_cuff", "target": "sleeves", "strength": "medium"},
    {"operation": "fit"},
    {"operation": "simulate", "mode": "natural"},
]


def test_dry_run_describes_and_does_not_touch_provider():
    """Brief test 8 (pure part)."""
    reg, fake = registry_with_fake()
    system = GarmentSystem(registry=reg)
    res = system.execute(FLAGSHIP, dry_run=True)
    d = res.to_dict()
    json.dumps(d)
    assert d["valid"] is True
    assert d["dry_run"] is True
    for expected in ("Create T-shirt", "Apply oversized fit", "Apply cotton preset", "Create sleeve cuffs",
                     "Fit to avatar", "Enable collision", "Simulate"):
        assert expected in d["operations"], expected
    assert isinstance(d["warnings"], list)
    assert fake.calls == []
    assert system.list_garments() == []


def test_dry_run_invalid_plan_reports_all_errors():
    reg, fake = registry_with_fake()
    system = GarmentSystem(registry=reg)
    res = system.execute([
        {"operation": "create", "type": "tshirt", "fabric": "unicorn_skin"},
        {"operation": "frobnicate"},
    ], dry_run=True)
    d = res.to_dict()
    assert d["valid"] is False
    got = {e["code"] for e in d["errors"]}
    assert {"UNKNOWN_FABRIC", "UNKNOWN_OPERATION"} <= got
    assert fake.calls == []


def test_execute_invalid_plan_never_calls_provider():
    reg, fake = registry_with_fake()
    system = GarmentSystem(registry=reg)
    res = system.execute([{"operation": "create", "type": "tshirt", "fabric": "unicorn_skin"}])
    assert res.ok is False
    assert fake.calls == []


def test_plan_without_create_needs_garment():
    reg, _ = registry_with_fake()
    system = GarmentSystem(registry=reg)
    res = system.execute([{"operation": "set_fabric", "fabric": "silk"}], dry_run=True)
    assert res.ok is False
    assert res.errors[0].code == "NO_GARMENT"


def test_natural_language_plan_dry_run():
    reg, fake = registry_with_fake()
    system = GarmentSystem(registry=reg)
    res = system.plan("Create an oversized black cotton T-shirt. Make the sleeves slightly shorter.")
    d = res.to_dict()
    assert d["valid"] is True and d["dry_run"] is True
    assert d["data"]["parsed"]["operations"][0]["operation"] == "create"
    assert fake.calls == []

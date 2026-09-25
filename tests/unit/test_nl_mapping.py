import json

import pytest

from ai_garment.core.nl_mapping import parse_instruction


def ops(text, **kw):
    return parse_instruction(text, **kw).operations


def test_tighter_chest():
    """Brief test 9."""
    assert ops("Make the shirt tighter around the chest.") == [
        {"operation": "modify_fit", "region": "chest", "direction": "tighter"}
    ]


def test_slightly_tighter_has_intensity():
    [op] = ops("Make it slightly tighter around the waist")
    assert op["operation"] == "modify_fit" and op["region"] == "waist" and op["intensity"] == 0.5


def test_percent_longer():
    assert ops("Make the T-shirt 10% longer.") == [
        {"operation": "modify_length", "target": "garment", "amount": "+10%"}
    ]


def test_sleeves_slightly_shorter():
    assert ops("Make the sleeves slightly shorter.") == [
        {"operation": "modify_length", "target": "sleeves", "amount": "-5%"}
    ]


def test_roll_sleeves():
    [op] = ops("Roll the sleeves up.")
    assert op["operation"] == "roll" and op["target"] == "sleeves"
    [op] = ops("Roll the sleeves slightly upward.")
    assert op["operation"] == "roll" and op["turns"] == 1


def test_jeans_baggier():
    assert ops("Make the jeans baggier.") == [
        {"operation": "modify_fit", "target": "legs", "direction": "looser"}
    ]


def test_context_type_used_for_pronouns():
    [op] = ops("Make them baggier", context={"type": "jeans"})
    assert op["target"] == "legs"


def test_change_fabric():
    assert ops("Change the fabric to heavy denim.") == [{"operation": "set_fabric", "fabric": "heavy denim"}]


def test_colour():
    assert ops("Make it navy blue.") == [{"operation": "set_color", "color": "navy"}]


def test_add_elastic_cuffs():
    """Brief test 3 (language form)."""
    assert ops("Add medium elastic cuff to sleeves.") == [
        {"operation": "add_component", "type": "elastic_cuff", "target": "sleeves", "strength": "medium"}
    ]


def test_remove_hood_and_bake_and_tuck():
    assert ops("Remove the hood.") == [{"operation": "remove_component", "target": "hood"}]
    assert ops("Bake the simulation.") == [{"operation": "bake"}]
    assert ops("Tuck the shirt in.") == [{"operation": "tuck"}]
    assert ops("Enable self collision.") == [{"operation": "enable_self_collision"}]


def test_flagship_sentence():
    text = ("Create an oversized black cotton T-shirt on my MakeHuman character. Make the sleeves slightly loose "
            "with medium elastic cuffs. Let gravity naturally settle the shirt and make the fabric look realistic.")
    r = parse_instruction(text)
    names = [o["operation"] for o in r.operations]
    create = r.operations[0]
    assert create == {"operation": "create", "type": "tshirt", "fit": "oversized", "color": "black",
                      "fabric": "cotton"}
    assert {"operation": "set_fit", "target": "sleeves", "level": "relaxed"} in r.operations
    assert {"operation": "add_component", "type": "elastic_cuff", "target": "sleeves",
            "strength": "medium"} in r.operations
    fit = next(o for o in r.operations if o["operation"] == "fit")
    assert fit["avatar_hint"] == "makehuman"
    sim = next(o for o in r.operations if o["operation"] == "simulate")
    assert sim["mode"] == "natural"
    assert sim["quality"] == "production"
    assert names.index("add_component") < names.index("fit") < names.index("simulate")
    assert r.unrecognized == []
    json.dumps(r.to_dict())


def test_cargo_pants():
    r = parse_instruction("Create loose cargo pants with elastic cuffs.")
    assert r.operations[0] == {"operation": "create", "type": "pants", "fit": "loose"}
    assert {"operation": "add_component", "type": "cargo_pocket", "target": "legs"} in r.operations
    assert {"operation": "add_component", "type": "elastic_cuff", "target": "legs"} in r.operations


def test_hoodie_gravity():
    r = parse_instruction("Put a hoodie on the character and let it naturally settle using gravity.")
    names = [o["operation"] for o in r.operations]
    assert r.operations[0] == {"operation": "create", "type": "hoodie"}
    assert "fit" in names
    assert any(o["operation"] == "simulate" and o["mode"] == "natural" for o in r.operations)


def test_unrecognised_is_reported_not_dropped():
    r = parse_instruction("Sing me a song.")
    assert r.operations == []
    assert r.unrecognized == ["Sing me a song"]
    assert r.warnings


@pytest.mark.parametrize("text", ["", "   "])
def test_empty(text):
    r = parse_instruction(text)
    assert r.operations == [] and r.warnings

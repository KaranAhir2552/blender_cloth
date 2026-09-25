import json

import pytest

from ai_garment.api.schema import claude_tool_definitions, garment_spec_json_schema, operation_json_schema

jsonschema = pytest.importorskip("jsonschema")

BRIEF_SPEC = {
    "type": "tshirt", "fit": "oversized", "fabric": "cotton", "color": "black",
    "sleeves": {"length": "short", "fit": "loose", "cuff": {"type": "elastic", "strength": "medium"}},
    "length": "hip",
    "simulation": {"gravity": True, "collision": True, "self_collision": True},
}


def test_spec_schema_is_valid_and_accepts_brief_example():
    schema = garment_spec_json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(BRIEF_SPEC, schema)
    assert "tshirt" in schema["properties"]["type"]["enum"]
    assert "cotton" in schema["properties"]["fabric"]["anyOf"][0]["enum"]
    json.dumps(schema)


def test_spec_schema_rejects_unknown_fabric_and_type():
    schema = garment_spec_json_schema()
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"type": "spacesuit"}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"type": "tshirt", "fit": "vacuum"}, schema)


def test_operation_schema():
    schema = operation_json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate({"operation": "modify_fit", "region": "chest", "direction": "tighter"}, schema)
    jsonschema.validate({"operation": "add_component", "type": "elastic_cuff", "target": "sleeves",
                         "strength": "medium"}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"operation": "frobnicate"}, schema)


def test_claude_tool_definitions():
    tools = claude_tool_definitions()
    names = {t["name"] for t in tools}
    assert {"create_garment", "modify_garment", "execute_plan", "inspect_garment", "simulate_garment",
            "parse_instruction", "apply_instruction"} <= names
    for t in tools:
        assert t["description"]
        jsonschema.Draft202012Validator.check_schema(t["input_schema"])
        assert t["input_schema"]["type"] == "object"
    json.dumps(tools)

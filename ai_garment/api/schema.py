"""JSON Schemas (Draft 2020-12) generated from the registries, plus Claude tool definitions.

Generated, not hand-written: registering a garment type, fabric, component or
operation updates the schema automatically.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Dict, List

from ..core.component_system import SLEEVE_LENGTHS, list_component_types
from ..core.fabric_presets import QUALIFIERS, get_fabric_preset, list_fabrics
from ..core.garment_operations import get_operation_def, list_operations
from ..core.garment_spec import SIM_MODES
from ..core.garment_types import LENGTH_SPECS, list_garment_types
from ..core.quality import QUALITY_LEVELS
from ..core.vocabulary import COLORS, FIT_ALIASES, FIT_LEVELS

DRAFT = "https://json-schema.org/draft/2020-12/schema"


def _fabric_names() -> List[str]:
    names = set(list_fabrics())
    for n in list_fabrics():
        names.update(a.lower() for a in get_fabric_preset(n).aliases)
    return sorted(names)


def garment_spec_json_schema() -> Dict[str, Any]:
    fabrics = _fabric_names()
    fabric_re = "^((" + "|".join(sorted(QUALIFIERS)) + ")[ _])+(" + "|".join(re.escape(f) for f in fabrics) + ")$"
    fit_values = sorted(set(FIT_LEVELS) | set(FIT_ALIASES))
    cuff = {"anyOf": [{"type": "string"}, {"type": "boolean"}, {"type": "object", "properties": {
        "type": {"type": "string", "enum": ["elastic", "plain", "rib", "buttoned", "folded", "none"]},
        "strength": {"anyOf": [{"type": "string", "enum": ["light", "medium", "strong"]},
                               {"type": "number", "minimum": 0, "maximum": 1}]},
        "tension": {"type": "number", "minimum": 0, "maximum": 0.5},
        "width": {"type": "number", "minimum": 0.005, "maximum": 0.15}}}]}
    limb = {"anyOf": [{"type": "string"}, {"type": "boolean"}, {"type": "object", "properties": {
        "length": {"type": "string", "enum": list(SLEEVE_LENGTHS)},
        "fit": {"type": "string", "enum": fit_values}, "cuff": cuff, "rolled": {"type": "integer", "minimum": 0,
                                                                                 "maximum": 4},
        "length_adjust": {"type": "object"}}}]}
    return {
        "$schema": DRAFT,
        "title": "AI Garment spec",
        "type": "object",
        "required": ["type"],
        "additionalProperties": False,
        "properties": {
            "type": {"type": "string", "enum": list_garment_types(), "description": "Garment type"},
            "name": {"type": "string"},
            "fit": {"anyOf": [{"type": "string", "enum": fit_values},
                              {"type": "object", "properties": {
                                  "level": {"type": "string", "enum": fit_values},
                                  "overrides": {"type": "object", "additionalProperties": {"type": "number"}},
                                  "component_levels": {"type": "object"},
                                  "scale": {"type": "number", "minimum": 0.7, "maximum": 1.5}}}]},
            "fabric": {"anyOf": [{"type": "string", "enum": fabrics},
                                 {"type": "string", "pattern": fabric_re},
                                 {"type": "object", "required": ["name"], "properties": {
                                     "name": {"type": "string"}, "qualifiers": {"type": "array"},
                                     "overrides": {"type": "object"}, "physics_overrides": {"type": "object"}}}],
                       "description": "Artistic fabric preset, optionally with qualifiers like 'heavy denim'"},
            "color": {"anyOf": [{"type": "string", "description": "name (" + ", ".join(sorted(COLORS)[:12])
                                 + ", ...) or #rrggbb"},
                                {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 4}]},
            "length": {"type": ["string", "null"], "enum": sorted(LENGTH_SPECS) + [None]},
            "length_adjust": {"type": "object", "properties": {"percent": {"type": "number"},
                                                               "meters": {"type": "number"}}},
            "sleeves": limb, "legs": limb, "cuffs": cuff,
            "pockets": {"anyOf": [{"type": "string"}, {"type": "object"}]},
            "hood": {"anyOf": [{"type": "boolean"}, {"type": "object"}]},
            "collar": {"anyOf": [{"type": "string"}, {"type": "object"}]},
            "waistband": {"type": "object"}, "zipper": {"type": "boolean"},
            "buttons": {"anyOf": [{"type": "boolean"}, {"type": "integer"}]},
            "components": {"type": "array", "items": {"type": "object", "required": ["type"], "properties": {
                "type": {"type": "string", "enum": list_component_types()}, "name": {"type": "string"},
                "target": {"type": "string"}, "params": {"type": "object"}, "state": {"type": "object"}}}},
            "default_components": {"type": "boolean"},
            "simulation": {"type": "object", "additionalProperties": False, "properties": {
                "mode": {"type": "string", "enum": list(SIM_MODES)},
                "quality": {"type": "string", "enum": list(QUALITY_LEVELS)},
                "gravity": {"type": "boolean"}, "collision": {"type": "boolean"},
                "self_collision": {"type": ["boolean", "null"]}, "frame_start": {"type": "integer"},
                "frame_end": {"type": ["integer", "null"]}, "settle": {"type": "boolean"},
                "bake": {"type": ["boolean", "null"]}, "pin": {"type": "array", "items": {"type": "string"}}}},
            "placement": {"type": "object", "properties": {"offset": {"type": "array", "items": {"type": "number"},
                                                                      "minItems": 3, "maxItems": 3}}},
            "tucked": {"type": "boolean"}, "layer": {"type": "integer"},
            "disabled_seams": {"type": "array", "items": {"type": "string"}}, "metadata": {"type": "object"},
        },
    }


def operation_json_schema() -> Dict[str, Any]:
    branches = []
    for name in list_operations():
        d = get_operation_def(name)
        props: Dict[str, Any] = {"operation": {"const": name}}
        for k, p in d.params.items():
            props[k] = p.to_json_schema()
        required = ["operation"] + [r for r in d.required if "|" not in r]
        branch = {"type": "object", "description": d.description, "properties": props, "required": required}
        if not d.allow_extra:
            branch["additionalProperties"] = False
        alts = [r.split("|") for r in d.required if "|" in r]
        if alts:
            branch["anyOf"] = [{"required": [a]} for a in alts[0]]
        branches.append(branch)
    return {"$schema": DRAFT, "title": "AI Garment operation", "oneOf": branches}


def _embed(schema: Dict[str, Any]) -> Dict[str, Any]:
    s = copy.deepcopy(schema)
    s.pop("$schema", None)
    return s


def claude_tool_definitions() -> List[Dict[str, Any]]:
    spec = _embed(garment_spec_json_schema())
    op = _embed(operation_json_schema())
    g = {"type": "string", "description": "garment id or name"}
    dry = {"type": "boolean", "description": "validate and describe only; no scene changes"}

    def tool(name: str, desc: str, props: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
        return {"name": name, "description": desc,
                "input_schema": {"type": "object", "properties": props, "required": required}}

    return [
        tool("create_garment", "Create a garment on the detected character from a structured spec.",
             {"spec": spec, "dry_run": dry, "avatar": {"type": "string"}}, ["spec"]),
        tool("modify_garment", "High-level edit of an existing garment.",
             {"garment": g, "dry_run": dry, "length": {"type": "string", "description": "'+10%', '-3cm', 'long'"},
              "fit": {"type": "string", "description": "tighter/looser/baggier or a level"},
              "region": {"type": "string"}, "component": {"type": "string"},
              "position": {"type": "string", "enum": ["rolled_up", "unrolled", "folded", "tucked", "untucked"]},
              "fabric": {"type": "string"}, "color": {"type": "string"}}, ["garment"]),
        tool("execute_plan", "Validate and execute (or dry-run) a list of structured operations.",
             {"plan": {"type": "array", "items": op}, "garment": g, "dry_run": dry,
              "transactional": {"type": "boolean"}}, ["plan"]),
        tool("apply_instruction", "Translate an English instruction into operations and dry-run/execute them.",
             {"text": {"type": "string"}, "garment": g, "dry_run": dry}, ["text"]),
        tool("parse_instruction", "Show how an English instruction maps to operations (no execution).",
             {"text": {"type": "string"}, "context": {"type": "object"}}, ["text"]),
        tool("inspect_garment", "Get the current structured state of a garment.", {"garment": g}, ["garment"]),
        tool("simulate_garment", "Run gravity/collision/settle/bake simulation for a garment.",
             {"garment": g, "mode": {"type": "string", "enum": list(SIM_MODES)},
              "quality": {"type": "string", "enum": list(QUALITY_LEVELS)}, "dry_run": dry}, ["garment"]),
        tool("fit_garment", "Fit a garment to the character and prepare collision.",
             {"garment": g, "avatar": {"type": "string"}, "dry_run": dry}, ["garment"]),
        tool("bake_simulation", "Bake the garment's cloth cache.", {"garment": g, "frame_start": {"type": "integer"},
                                                                    "frame_end": {"type": "integer"}}, ["garment"]),
        tool("detect_avatar", "Find the human character and report measurements.",
             {"name": {"type": "string"}, "metadata": {"type": "object"}}, []),
        tool("list_capabilities", "List garment types, fabrics, fits, components, operations and providers.", {}, []),
    ]

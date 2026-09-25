"""Garment type registry.

A garment type is data: a category, a geometry ``builder`` recipe, defaults
and default components. New types are added with :func:`register_garment_type`
without touching the rest of the architecture.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .errors import GarmentError
from .vocabulary import normalize, resolve_alias, suggest

CATEGORIES = ("top", "bottom", "full")
BUILDERS = ("top", "pants", "skirt", "dress")

# Length name -> (landmark_a, landmark_b, t): hem height = lerp(z_a, z_b, t)
LENGTH_SPECS: Dict[str, Tuple[str, str, float]] = {
    "crop": ("chest", "waist", 0.55),
    "waist": ("waist", "waist", 0.0),
    "hip": ("hips", "crotch", 0.35),
    "low_hip": ("crotch", "crotch", 0.0),
    "thigh": ("crotch", "knee", 0.35),
    "micro": ("crotch", "knee", 0.12),
    "mid_thigh": ("crotch", "knee", 0.45),
    "above_knee": ("knee", "crotch", 0.2),
    "knee": ("knee", "knee", 0.0),
    "below_knee": ("knee", "ankle", 0.2),
    "midi": ("knee", "ankle", 0.5),
    "capri": ("knee", "ankle", 0.55),
    "ankle": ("ankle", "floor", 0.3),
    "floor": ("floor", "ankle", 0.25),
}
CATEGORY_LENGTHS = {
    "top": ["crop", "waist", "hip", "low_hip", "thigh"],
    "bottom": ["micro", "mid_thigh", "above_knee", "knee", "below_knee", "capri", "ankle", "floor"],
    "full": ["hip", "low_hip", "thigh", "mid_thigh", "above_knee", "knee", "below_knee", "midi", "ankle", "floor"],
}
LENGTH_ALIASES = {"cropped": "crop", "hips": "hip", "hip_length": "hip", "full": "ankle", "full_length": "ankle",
                  "maxi": "floor", "mini": "mid_thigh", "three_quarter": "capri",
                  "calf": "midi", "tunic": "thigh"}

DEFAULT_COLLISION_REGIONS = {
    "top": ("neck", "shoulders", "chest", "waist", "hips", "left_arm", "right_arm"),
    "bottom": ("waist", "hips", "left_leg", "right_leg"),
    "full": ("neck", "shoulders", "chest", "waist", "hips", "left_arm", "right_arm", "left_leg", "right_leg"),
}


@dataclass(frozen=True)
class GarmentTypeDef:
    name: str
    display_name: str
    category: str
    builder: str
    default_fabric: str = "cotton"
    default_fit: str = "regular"
    default_length: Optional[str] = None
    default_components: Tuple[dict, ...] = ()
    aliases: Tuple[str, ...] = ()
    support: str = "v1"  # "v1" | "experimental"
    description: str = ""
    collision_regions: Optional[Tuple[str, ...]] = None
    default_color: str = "white"

    def allowed_lengths(self) -> List[str]:
        return list(CATEGORY_LENGTHS[self.category])

    def resolved_collision_regions(self) -> Tuple[str, ...]:
        return self.collision_regions or DEFAULT_COLLISION_REGIONS[self.category]


_TYPES: Dict[str, GarmentTypeDef] = {}
_ALIASES: Dict[str, str] = {}


def register_garment_type(defn: GarmentTypeDef, replace: bool = False) -> None:
    name = normalize(defn.name)
    if name in _TYPES and not replace:
        raise GarmentError("DUPLICATE_GARMENT_TYPE", f"Garment type '{name}' is already registered.")
    if defn.category not in CATEGORIES:
        raise GarmentError("INVALID_GARMENT_TYPE", f"category must be one of {CATEGORIES}.")
    if defn.builder not in BUILDERS and not _is_custom_builder(defn.builder):
        raise GarmentError("INVALID_GARMENT_TYPE", f"builder '{defn.builder}' is not registered.")
    _TYPES[name] = defn
    for alias in defn.aliases:
        _ALIASES[normalize(alias)] = name


def unregister_garment_type(name: str) -> None:
    key = normalize(name)
    defn = _TYPES.pop(key, None)
    if defn is None:
        raise GarmentError("UNKNOWN_GARMENT_TYPE", f"Garment type '{name}' is not registered.")
    for alias in [a for a, t in _ALIASES.items() if t == key]:
        del _ALIASES[alias]


def _is_custom_builder(name: str) -> bool:
    from .geometry.recipes import has_recipe  # local: geometry depends on this module
    return has_recipe(name)


def resolve_garment_type(name: object) -> Optional[GarmentTypeDef]:
    key = resolve_alias(name, _TYPES, _ALIASES)
    return _TYPES.get(key) if key else None


def get_garment_type(name: object) -> GarmentTypeDef:
    defn = resolve_garment_type(name)
    if defn is None:
        raise GarmentError("UNKNOWN_GARMENT_TYPE", f"Unknown garment type '{name}'.", path="type",
                           suggestions=suggest(name, list(_TYPES) + list(_ALIASES)))
    return defn


def list_garment_types() -> List[str]:
    return sorted(_TYPES)


def normalize_length(value: object) -> str:
    n = normalize(value)
    return LENGTH_ALIASES.get(n, n)


def _sleeves(length: str, cuff: Optional[dict] = None) -> Tuple[dict, ...]:
    out = []
    for side in ("left", "right"):
        out.append({"type": "sleeve", "name": f"{side}_sleeve", "params": {"side": side, "length": length}})
    if cuff:
        for side in ("left", "right"):
            c = dict(cuff)
            out.append({"type": c.pop("type"), "name": f"{side}_sleeve_cuff", "target": f"{side}_sleeve",
                        "params": c})
    return tuple(out)


def _legs(hem: Optional[dict] = None) -> Tuple[dict, ...]:
    out = [{"type": "leg", "name": f"{side}_leg", "params": {"side": side}} for side in ("left", "right")]
    for side in ("left", "right"):
        h = dict(hem or {"type": "hem"})
        out.append({"type": h.pop("type"), "name": f"{side}_leg_hem", "target": f"{side}_leg", "params": h})
    return tuple(out)


BODY = {"type": "body", "name": "body"}
HEM = {"type": "hem", "name": "hem", "target": "body"}

_BUILTIN = [
    GarmentTypeDef("tshirt", "T-shirt", "top", "top", "cotton", "regular", "hip",
                   (BODY, {"type": "collar", "name": "collar", "target": "body", "params": {"style": "crew"}})
                   + _sleeves("short") + (HEM,),
                   aliases=("t_shirt", "tee", "tee_shirt", "tees"), default_color="white",
                   description="Short-sleeved crew-neck knit top."),
    GarmentTypeDef("shirt", "Shirt", "top", "top", "cotton", "regular", "hip",
                   (BODY, {"type": "collar", "name": "collar", "target": "body", "params": {"style": "shirt"}})
                   + _sleeves("long", {"type": "cuff", "style": "buttoned"})
                   + ({"type": "button_placket", "name": "button_placket", "target": "body", "params": {"count": 7}},
                      HEM),
                   aliases=("button_up", "button_down", "dress_shirt", "blouse", "oxford_shirt"),
                   description="Collared, buttoned woven shirt."),
    GarmentTypeDef("hoodie", "Hoodie", "top", "top", "fleece", "relaxed", "hip",
                   (BODY, {"type": "hood", "name": "hood", "target": "body"})
                   + _sleeves("long", {"type": "elastic_cuff", "strength": "light"})
                   + ({"type": "waistband", "name": "waistband", "target": "body",
                       "params": {"elastic": {"strength": "light"}}},
                      {"type": "kangaroo_pocket", "name": "kangaroo_pocket", "target": "body"},
                      {"type": "drawstring", "name": "drawstring", "target": "hood", "params": {"strength": "light"}}),
                   aliases=("hooded_sweatshirt", "hooded_top", "hoody"), default_color="grey",
                   description="Hooded fleece top with rib cuffs and hem."),
    GarmentTypeDef("sweatshirt", "Sweatshirt", "top", "top", "fleece", "relaxed", "hip",
                   (BODY, {"type": "collar", "name": "collar", "target": "body", "params": {"style": "rib"}})
                   + _sleeves("long", {"type": "elastic_cuff", "strength": "light"})
                   + ({"type": "waistband", "name": "waistband", "target": "body",
                       "params": {"elastic": {"strength": "light"}}},),
                   aliases=("crewneck", "crew_neck_sweatshirt", "jumper", "pullover"), default_color="grey",
                   description="Crew-neck fleece top."),
    GarmentTypeDef("jacket", "Jacket", "top", "top", "nylon", "relaxed", "hip",
                   (BODY, {"type": "collar", "name": "collar", "target": "body", "params": {"style": "stand"}})
                   + _sleeves("long", {"type": "cuff", "style": "plain"})
                   + ({"type": "zipper", "name": "zipper", "target": "body"},
                      {"type": "pocket", "name": "left_pocket", "target": "body", "params": {"placement": "hip_left"}},
                      {"type": "pocket", "name": "right_pocket", "target": "body", "params": {"placement": "hip_right"}},
                      HEM),
                   aliases=("bomber", "windbreaker", "coat", "zip_jacket"), support="experimental",
                   default_color="black", description="Zip-front jacket (closed-front proxy; experimental)."),
    GarmentTypeDef("pants", "Pants", "bottom", "pants", "heavy_cotton", "regular", "ankle",
                   (BODY, {"type": "waistband", "name": "waistband", "target": "body"}) + _legs(),
                   aliases=("trousers", "chinos", "slacks", "cargo_pants", "joggers", "sweatpants"),
                   default_color="khaki", description="Full-length trousers."),
    GarmentTypeDef("jeans", "Jeans", "bottom", "pants", "denim", "regular", "ankle",
                   (BODY, {"type": "waistband", "name": "waistband", "target": "body"}) + _legs()
                   + ({"type": "belt_loop", "name": "belt_loops", "target": "waistband", "params": {"count": 5}},
                      {"type": "pocket", "name": "left_front_pocket", "target": "body",
                       "params": {"placement": "front_hip_left"}},
                      {"type": "pocket", "name": "right_front_pocket", "target": "body",
                       "params": {"placement": "front_hip_right"}},
                      {"type": "pocket", "name": "left_back_pocket", "target": "body",
                       "params": {"placement": "back_left"}},
                      {"type": "pocket", "name": "right_back_pocket", "target": "body",
                       "params": {"placement": "back_right"}}),
                   aliases=("denim_pants", "denim_jeans", "blue_jeans"), default_color="denim_blue",
                   description="Five-pocket denim trousers."),
    GarmentTypeDef("shorts", "Shorts", "bottom", "pants", "cotton", "regular", "mid_thigh",
                   (BODY, {"type": "waistband", "name": "waistband", "target": "body"}) + _legs(),
                   aliases=("short_pants", "bermudas", "cargo_shorts"), default_color="khaki",
                   description="Above-knee trousers."),
    GarmentTypeDef("skirt", "Skirt", "bottom", "skirt", "cotton", "regular", "knee",
                   ({"type": "body", "name": "body", "params": {"shape": "a_line"}},
                    {"type": "waistband", "name": "waistband", "target": "body"}, HEM),
                   aliases=("miniskirt", "midi_skirt", "a_line_skirt", "pencil_skirt"), support="experimental",
                   default_color="black", description="Tube skirt with flare (experimental)."),
    GarmentTypeDef("dress", "Dress", "full", "dress", "cotton", "regular", "knee",
                   ({"type": "body", "name": "body", "params": {"shape": "a_line"}},
                    {"type": "collar", "name": "collar", "target": "body", "params": {"style": "scoop"}})
                   + _sleeves("short") + (HEM,),
                   aliases=("gown", "sundress", "frock"), support="experimental", default_color="red",
                   description="One-piece dress: bodice and flared skirt (experimental)."),
]
for _t in _BUILTIN:
    register_garment_type(_t)

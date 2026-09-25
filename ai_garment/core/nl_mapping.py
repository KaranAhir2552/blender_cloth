"""Deterministic natural-language -> structured operations mapping.

Claude can (and usually should) emit structured operations directly; this
parser exists so plain-English instructions work too, and so Claude can
check its interpretation (``garment.plan(text)``) before executing.

Design: split into clauses, detect intents per clause with small lexicons
derived from the registries, emit operation dicts, order them by phase
(create -> spec edits -> fit -> simulate -> bake). Anything not understood is
returned in ``unrecognized``; nothing is silently dropped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .fabric_presets import QUALIFIERS, list_fabrics, get_fabric_preset
from .fit_system import shift_fit_level
from .garment_operations import get_operation_def
from .garment_types import list_garment_types, resolve_garment_type, get_garment_type
from .vocabulary import COLOR_ALIASES, COLORS, FIT_ALIASES, FIT_COMPARATIVES, FIT_LEVELS, INTENSITY_WORDS

# --- lexicons ---------------------------------------------------------------------

EXTRA_GARMENT_WORDS = {"sweater": "sweatshirt", "hoody": "hoodie", "top": None, "garment": None, "clothes": None}
COMPONENT_WORDS = {
    "sleeves": "sleeves", "sleeve": "sleeves", "arms": "sleeves",
    "legs": "legs", "leg": "legs", "pant_legs": "legs", "trouser_legs": "legs", "pants_legs": "legs",
    "left_sleeve": "left_sleeve", "right_sleeve": "right_sleeve", "left_leg": "left_leg", "right_leg": "right_leg",
    "cuffs": "cuffs", "cuff": "cuffs", "hood": "hood", "waistband": "waistband", "waist_band": "waistband",
    "collar": "collar", "neckline": "collar", "hem": "hem", "hems": "hem", "pockets": "pockets",
    "pocket": "pockets", "zipper": "zipper", "zip": "zipper", "drawstring": "drawstring", "buttons": "buttons",
    "belt_loops": "belt_loops",
}
ADDABLE = {"cuff": "cuff", "cuffs": "cuff", "hood": "hood", "pocket": "pocket", "pockets": "pocket",
           "cargo_pockets": "cargo_pocket", "cargo_pocket": "cargo_pocket", "zipper": "zipper", "zip": "zipper",
           "drawstring": "drawstring", "waistband": "waistband", "belt_loops": "belt_loop", "buttons": "button_placket",
           "kangaroo_pocket": "kangaroo_pocket", "pouch": "kangaroo_pocket"}
REGION_WORDS = ["chest", "bust", "waist", "hips", "hip", "shoulders", "shoulder", "stomach", "belly", "seat", "butt",
                "thighs", "thigh", "neck", "biceps", "wrists", "ankles"]
STRENGTH_WORDS = {"light": "light", "soft": "light", "gentle": "light", "medium": "medium", "moderate": "medium",
                  "strong": "strong", "tight": "strong", "firm": "strong"}
CREATE_VERBS = {"create", "generate", "build", "put", "dress", "design", "model", "make", "add", "give", "want",
                "need"}
STRONG_CREATE_VERBS = {"create", "generate", "build", "put", "dress", "design", "model"}
ARTICLES = {"a", "an", "some", "new"}
AVATAR_WORDS = {"character", "avatar", "model", "body", "person", "human", "him", "her", "them", "figure", "mannequin"}
SETTLE_WORDS = {"settle", "settles", "settling", "drape", "drapes", "gravity", "fall", "hang", "simulate",
                "simulation"}
REALISM_WORDS = {"realistic", "realism", "lifelike", "natural-looking", "believable", "photorealistic"}
LONGER = {"longer", "lengthen", "extend"}
SHORTER = {"shorter", "shorten", "crop", "cropped"}
FIT_COMPARATIVE_CANON = {k: ("looser" if v > 0 else "tighter") for k, v in FIT_COMPARATIVES.items()}

_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*(%|percent|cm|mm|inches|inch|in)\b")


@dataclass
class ParseResult:
    text: str
    operations: List[Dict[str, Any]] = field(default_factory=list)
    unrecognized: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    clauses: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        total = len(self.clauses) or 1
        return round(1.0 - len(self.unrecognized) / total, 3)

    def to_dict(self) -> Dict[str, Any]:
        return {"text": self.text, "operations": self.operations, "unrecognized": self.unrecognized,
                "warnings": self.warnings, "clauses": self.clauses, "confidence": self.confidence}


def _garment_lexicon() -> Dict[str, str]:
    lex: Dict[str, str] = {}
    for name in list_garment_types():
        d = get_garment_type(name)
        lex[name] = name
        for a in d.aliases:
            lex[a] = name
    for k, v in EXTRA_GARMENT_WORDS.items():
        if v:
            lex[k] = v
    lex["trouser"] = "pants"
    lex["pant"] = "pants"
    return lex


def _fabric_lexicon() -> Dict[str, str]:
    lex = {}
    for name in list_fabrics():
        p = get_fabric_preset(name)
        lex[name] = name
        for a in p.aliases:
            lex[re.sub(r"[\s\-]+", "_", a.lower())] = name
    return lex


def _color_lexicon() -> Dict[str, str]:
    lex = {c: c for c in COLORS}
    lex.update(COLOR_ALIASES)
    return lex


def _prep(text: str) -> str:
    t = text.lower()
    t = re.sub(r"\bt[\s\-]?shirts?\b|\btee[\s\-]?shirts?\b", "tshirt", t)
    t = re.sub(r"\bself[\s\-]collisions?\b", "self_collision", t)
    t = re.sub(r"\bbutton[\s\-](?:up|down)\b", "button_up", t)
    t = t.replace("make-human", "makehuman").replace("make human", "makehuman")
    t = re.sub(r"\b(\w+)-(\w+)\b", r"\1_\2", t)
    return t


def _tokens(clause: str) -> List[str]:
    return re.findall(r"[a-z0-9_%+.]+", clause)


def _ngram_find(tokens: List[str], lexicon: Dict[str, Any], max_n: int = 3) -> List[Tuple[int, int, Any]]:
    """Longest-match n-gram lookup. Returns (start, end, value)."""
    out = []
    i = 0
    while i < len(tokens):
        for n in range(max_n, 0, -1):
            key = "_".join(tokens[i:i + n])
            if n <= len(tokens) - i and key in lexicon:
                out.append((i, i + n, lexicon[key]))
                i += n
                break
        else:
            i += 1
    return out


def _intensity(tokens: List[str]) -> Optional[float]:
    joined = "_".join(tokens)
    for phrase in sorted(INTENSITY_WORDS, key=len, reverse=True):
        if re.search(r"(^|_)" + re.escape(phrase) + r"(_|$)", joined):
            return INTENSITY_WORDS[phrase]
    return None


def _split_clauses(text: str) -> List[str]:
    sentences = re.split(r"(?<!\d)[.!?;]+(?!\d)", text)
    verbs = ("make|let|add|remove|roll|unroll|change|put|create|tuck|untuck|bake|simulate|set|use|give|enable|"
             "turn|fold|switch|pin|generate|dress|color|colour|dye|shorten|lengthen|tighten|loosen|inspect")
    clauses: List[str] = []
    for s in sentences:
        parts = re.split(r",?\s+(?:and\s+then|and|then)\s+(?=(?:" + verbs + r")\b)|,\s*(?=(?:" + verbs + r")\b)", s)
        clauses += [p.strip(" ,") for p in parts if p and p.strip(" ,")]
    return clauses


# --- main -----------------------------------------------------------------------

def parse_instruction(text: str, context: Optional[Dict[str, Any]] = None) -> ParseResult:
    """Map an English instruction to operation dicts (``{"operation": ..., ...}``)."""
    result = ParseResult(text=text or "")
    if not text or not text.strip():
        result.warnings.append("Empty instruction.")
        return result
    ctx_type = resolve_garment_type((context or {}).get("type")) if context and context.get("type") else None
    category = ctx_type.category if ctx_type else None
    garments, fabrics, colors = _garment_lexicon(), _fabric_lexicon(), _color_lexicon()
    sim: Dict[str, Any] = {}
    ops: List[Dict[str, Any]] = []

    for raw_clause in _split_clauses(text):
        clause = _prep(raw_clause)
        toks = _tokens(clause)
        emitted: List[Dict[str, Any]] = []
        g_hits = _ngram_find(toks, garments)
        g_type = g_hits[0][2] if g_hits else None
        if g_type:
            category = resolve_garment_type(g_type).category
        with_at = toks.index("with") if "with" in toks else len(toks)
        f_hits = [h for h in _ngram_find(toks, fabrics)
                  if h[0] < with_at and not (h[1] < len(toks) and toks[h[1]] in COMPONENT_WORDS)]
        c_hits = _ngram_find(toks, colors)
        comp_hits = _ngram_find(toks, COMPONENT_WORDS)
        comp = comp_hits[0][2] if comp_hits else None
        intensity = _intensity(toks)
        tokset = set(toks)
        first = toks[0] if toks else ""

        def fabric_phrase() -> Optional[str]:
            if not f_hits:
                return None
            s, e, _ = f_hits[0]
            q = []
            j = s - 1
            while j >= 0 and toks[j] in QUALIFIERS:
                q.insert(0, toks[j])
                j -= 1
            return " ".join(q + [t.replace("_", " ") for t in toks[s:e]])

        fit_abs = None
        for t in toks:
            lvl = t if t in FIT_LEVELS else FIT_ALIASES.get(t)
            if lvl and t not in ("tight",):
                fit_abs = lvl
            elif t == "tight" and "elastic" not in tokset:
                fit_abs = "tight"
        comparative = next((FIT_COMPARATIVE_CANON[t] for t in toks if t in FIT_COMPARATIVE_CANON), None)
        avatar_ref = ("on" in tokset and (tokset & AVATAR_WORDS or "makehuman" in tokset)) or (
            first in ("dress",) and tokset & AVATAR_WORDS)

        # 1. creation -------------------------------------------------------------
        article_before_garment = bool(g_hits) and any(t in ARTICLES for t in toks[:g_hits[0][0]])
        is_create = bool(g_type) and not comparative and (
            first in STRONG_CREATE_VERBS or bool(tokset & STRONG_CREATE_VERBS) or
            (first in CREATE_VERBS and article_before_garment))
        if is_create:
            op: Dict[str, Any] = {"operation": "create", "type": g_type}
            if fit_abs:
                op["fit"] = fit_abs
            if c_hits:
                op["color"] = c_hits[0][2]
            fp = fabric_phrase()
            if fp:
                op["fabric"] = fp
            emitted.append(op)
            s0 = g_hits[0][0]
            if "cargo" in toks[:s0 + 1] or "cargo_pants" in toks:
                emitted.append({"operation": "add_component", "type": "cargo_pocket", "target": "legs"})
            if avatar_ref:
                fit_op: Dict[str, Any] = {"operation": "fit"}
                if "makehuman" in tokset or "mpfb" in tokset:
                    fit_op["avatar_hint"] = "makehuman"
                emitted.append(fit_op)
            emitted += _with_components(toks, category)
        # 2. removal / addition --------------------------------------------------------
        elif first in ("remove", "delete", "drop") or (first == "take" and "off" in tokset):
            target = comp or next((ADDABLE.get(t) for t in toks if t in ADDABLE), None)
            if target:
                emitted.append({"operation": "remove_component", "target": target})
        elif first == "add" and not g_type:
            emitted += _add_ops(toks, comp_hits, category)
        # 3. roll / fold / tuck ------------------------------------------------------
        elif first in ("roll", "unroll") or "roll" in tokset:
            target = comp if comp in ("sleeves", "legs", "left_sleeve", "right_sleeve", "left_leg", "right_leg") \
                else ("legs" if category == "bottom" else "sleeves")
            if first == "unroll" or "down" in tokset:
                emitted.append({"operation": "unroll", "target": target})
            else:
                op = {"operation": "roll", "target": target}
                if intensity is not None:
                    op["turns"] = 1 if intensity < 1 else 3
                emitted.append(op)
        elif first in ("fold", "cuff") and not comp_hits[1:]:
            emitted.append({"operation": "fold", "target": comp if comp in ("sleeves", "legs") else
                            ("legs" if category == "bottom" else "sleeves")})
        elif first in ("tuck", "untuck") or "untuck" in tokset or ("tuck" in tokset and "in" in tokset):
            emitted.append({"operation": "untuck" if "untuck" in tokset or "out" in tokset else "tuck"})
        elif first == "bake" or ("bake" in tokset and len(toks) <= 4):
            emitted.append({"operation": "bake"})
        elif "self_collision" in tokset:
            emitted.append({"operation": "enable_self_collision"} if not tokset & {"disable", "off", "no"}
                           else {"operation": "enable_self_collision", "preset": "off"})
        elif first in ("inspect", "describe", "show", "what", "whats"):
            emitted.append({"operation": "inspect"})
        elif first == "pin" and comp:
            emitted.append({"operation": "pin", "target": comp})
        else:
            # 4. fabric / colour ---------------------------------------------------------
            fabric_change = f_hits and (tokset & {"fabric", "material", "change", "switch", "use", "out", "from",
                                                  "into"} or first in ("make", "change", "switch", "use"))
            if fabric_change:
                emitted.append({"operation": "set_fabric", "fabric": fabric_phrase()})
            if c_hits and (tokset & {"color", "colour", "dye", "paint", "it", "them"} or first in ("make", "color",
                                                                                                  "colour", "dye")):
                emitted.append({"operation": "set_color", "color": c_hits[0][2]})
            # 5. length ------------------------------------------------------------------------
            lengthen, shorten = tokset & LONGER, tokset & SHORTER
            if lengthen or shorten:
                sign = "+" if lengthen else "-"
                m = _AMOUNT.search(clause)
                if m:
                    unit = "%" if m.group(2) in ("%", "percent") else ("cm" if m.group(2) not in ("mm", "in", "inch",
                                                                                                  "inches") else
                                                                       m.group(2)[:2])
                    amount = f"{sign}{m.group(1)}{unit}"
                else:
                    amount = f"{sign}{10 * (intensity or 1.0):g}%"
                target = comp if comp in ("sleeves", "legs", "left_sleeve", "right_sleeve", "left_leg",
                                          "right_leg") else "garment"
                emitted.append({"operation": "modify_length", "target": target, "amount": amount})
            # 6. fit ---------------------------------------------------------------------------------
            if comparative:
                op = {"operation": "modify_fit"}
                region = next((t for t in toks if t in REGION_WORDS), None)
                if region:
                    op["region"] = region
                elif comp in ("sleeves", "legs", "left_sleeve", "right_sleeve", "left_leg", "right_leg"):
                    op["target"] = comp
                elif category == "bottom":
                    op["target"] = "legs"
                op["direction"] = comparative
                if intensity is not None and intensity != 1.0:
                    op["intensity"] = intensity
                emitted.append(op)
            elif fit_abs and first in ("make", "set", "change") and not (lengthen or shorten):
                level = fit_abs
                if intensity is not None and intensity < 1.0:
                    level = shift_fit_level(fit_abs, -1 if FIT_LEVELS.index(fit_abs) > 2 else 1)
                elif intensity is not None and intensity > 1.0:
                    level = shift_fit_level(fit_abs, 1 if FIT_LEVELS.index(fit_abs) > 2 else -1)
                op = {"operation": "set_fit", "level": level}
                if comp in ("sleeves", "legs", "left_sleeve", "right_sleeve", "left_leg", "right_leg"):
                    op["target"] = comp
                emitted.append(op)
            if "elastic" in tokset and first in ("make", "set") and comp in ("waistband", "cuffs", "hem", "hood"):
                emitted.append({"operation": "set_elastic", "target": comp})
            if "with" in tokset and emitted:
                emitted += _with_components(toks, category, default_target=comp)
            # 7. simulation --------------------------------------------------------------------------
            if tokset & SETTLE_WORDS:
                sim.setdefault("mode", "natural")
                if tokset & {"quick", "quickly", "preview", "fast"}:
                    sim["mode"] = "preview"
                emitted.append({"_sim": True})
            if tokset & REALISM_WORDS:
                sim["quality"] = "production"
                sim.setdefault("mode", "natural")
                sim["wrinkles"] = True
                emitted.append({"_sim": True})
            if avatar_ref and not emitted:
                emitted.append({"operation": "fit"})
        real = [e for e in emitted if "_sim" not in e]
        result.clauses.append({"text": raw_clause.strip(), "operations": [e["operation"] for e in real],
                               "simulation": any("_sim" in e for e in emitted)})
        if not emitted:
            result.unrecognized.append(raw_clause.strip())
        ops += real

    if sim:
        sim_op: Dict[str, Any] = {"operation": "simulate", "mode": sim.get("mode", "natural")}
        if "quality" in sim:
            sim_op["quality"] = sim["quality"]
        ops.append(sim_op)
        if sim.get("wrinkles"):
            ops.append({"operation": "generate_wrinkles", "optional": True})
    ops = _dedupe(ops)
    ops.sort(key=lambda o: get_operation_def(o["operation"]).phase)
    result.operations = ops
    if result.unrecognized:
        result.warnings.append("Could not interpret: " + "; ".join(f"'{u}'" for u in result.unrecognized)
                               + ". Rephrase or send structured operations.")
    return result


def _with_components(toks: List[str], category: Optional[str], default_target: Optional[str] = None
                     ) -> List[Dict[str, Any]]:
    if "with" not in toks:
        return []
    tail = toks[toks.index("with") + 1:]
    return _add_ops(["add"] + tail, _ngram_find(tail, COMPONENT_WORDS), category, default_target)


def _add_ops(toks: List[str], comp_hits, category: Optional[str], default_target: Optional[str] = None
             ) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    tokset = set(toks)
    strength = next((STRENGTH_WORDS[t] for t in toks if t in STRENGTH_WORDS), None)
    limb = "legs" if category == "bottom" else "sleeves"
    explicit_target = None
    if "to" in tokset or "on" in tokset:
        idx = max(toks.index(w) for w in ("to", "on") if w in tokset)
        after = _ngram_find(toks[idx + 1:], COMPONENT_WORDS)
        explicit_target = after[0][2] if after else None
    if tokset & {"cuff", "cuffs"}:
        op: Dict[str, Any] = {"operation": "add_component",
                              "type": "elastic_cuff" if "elastic" in tokset or "ribbed" in tokset else "cuff",
                              "target": explicit_target or (default_target if default_target in ("sleeves", "legs")
                                                            else limb)}
        if strength and op["type"] == "elastic_cuff":
            op["strength"] = strength
        out.append(op)
    if tokset & {"cargo", "cargo_pockets", "cargo_pocket"}:
        out.append({"operation": "add_component", "type": "cargo_pocket", "target": "legs"})
    elif tokset & {"pocket", "pockets"}:
        out.append({"operation": "add_component", "type": "kangaroo_pocket" if tokset & {"kangaroo", "pouch"}
                    else "pocket"})
    for word, ctype in (("hood", "hood"), ("zipper", "zipper"), ("zip", "zipper"), ("drawstring", "drawstring"),
                        ("belt_loops", "belt_loop")):
        if word in tokset:
            op = {"operation": "add_component", "type": ctype}
            if ctype == "drawstring":
                op["target"] = "hood" if "hood" in tokset or category != "bottom" else "waistband"
            out.append(op)
    if "waistband" in tokset and "elastic" in tokset:
        out.append({"operation": "set_elastic", "target": "waistband", **({"strength": strength} if strength else {})})
    return out


def _dedupe(ops: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for o in ops:
        key = tuple(sorted((k, str(v)) for k, v in o.items()))
        if key not in seen:
            seen.add(key)
            out.append(o)
    return out

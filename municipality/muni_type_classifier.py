"""
muni_type_classifier.py

Importable utility for classifying a Wikipedia place article (given full wikitext)
into a Census-style municipality type.

Public function:
  determine_municipality_type(wikitext: str) -> dict
    returns { "type": str, "confidence": str, "reasons": list[str] }
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any


# -----------------------------
# Canonical output space
# -----------------------------

CANONICAL_TYPES = {
    "(balance)",
    "CDP",
    "borough",
    "city",
    "city and borough",
    "comunidad",
    "consolidated government",
    "consolidated government (balance)",
    "corporation",
    "metropolitan government (balance)",
    "municipality",
    "town",
    "unified government",
    "unified government (balance)",
    "unknown",
    "urban county",
    "village",
    "zona urbana",
}

WEIGHT_INFOBOX = 80
WEIGHT_CATEGORY = 60
WEIGHT_LEDE = 40


# -----------------------------
# Pattern dictionaries
# -----------------------------

LEDE_PATTERNS: List[Tuple[str, List[str]]] = [
    ("city and borough", [r"\bcity and borough\b"]),
    ("consolidated government", [r"\bconsolidated (city-)?county\b", r"\bconsolidated government\b"]),
    ("unified government", [r"\bunified government\b", r"\bunified (city-)?county\b"]),
    ("metropolitan government", [r"\bmetropolitan government\b", r"\bmetro government\b"]),
    ("urban county", [r"\burban county\b"]),
    ("CDP", [r"\bcensus[- ]designated place\b", r"\bcdp\b"]),
    ("borough", [r"\bborough\b"]),
    ("village", [r"\bvillage\b"]),
    ("town", [r"\btown\b(?!ship)"]),
    ("city", [r"\bcity\b"]),
    ("municipality", [r"\bmunicipality\b"]),
    ("corporation", [r"\bcorporation\b"]),
    ("comunidad", [r"\bcomunidad\b"]),
    ("zona urbana", [r"\bzona urbana\b"]),
]

INFOBOX_PATTERNS: List[Tuple[str, List[str]]] = [
    ("city and borough", ["city and borough"]),
    ("consolidated government", ["consolidated government", "consolidated city-county", "consolidated city county"]),
    ("unified government", ["unified government", "unified city-county", "unified city county"]),
    ("metropolitan government", ["metropolitan government", "metro government"]),
    ("urban county", ["urban county"]),
    ("CDP", ["census-designated place", "census designated place", "(cdp)"]),
    ("borough", ["borough"]),
    ("village", ["village"]),
    ("town", ["town"]),
    ("city", ["city"]),
    ("municipality", ["municipality"]),
    ("corporation", ["corporation"]),
    ("comunidad", ["comunidad"]),
    ("zona urbana", ["zona urbana"]),
]

CATEGORY_PATTERNS: List[Tuple[str, List[str]]] = [
    ("city and borough", ["cities and boroughs in "]),
    ("consolidated government", ["consolidated city-counties in ", "consolidated city-county governments in "]),
    ("unified government", ["unified city-counties in ", "unified governments in ", "unified government in "]),
    ("metropolitan government", ["metropolitan governments in "]),
    ("urban county", ["urban counties in "]),
    ("CDP", ["census-designated places in ", "census designated places in "]),
    ("borough", ["boroughs in "]),
    ("village", ["villages in "]),
    ("town", ["towns in "]),
    ("city", ["cities in "]),
    ("municipality", ["municipalities in "]),
    ("corporation", ["corporations in "]),
    ("comunidad", ["comunidades in ", "comunidades of "]),
    ("zona urbana", ["zonas urbanas in ", "zonas urbanas of "]),
]


# -----------------------------
# Data classes
# -----------------------------

@dataclass(frozen=True)
class Candidate:
    muni_type: str
    weight: int
    source: str
    matched: str


@dataclass(frozen=True)
class Result:
    muni_type: str
    confidence: str  # "high"|"medium"|"low"
    reasons: List[str]


# -----------------------------
# Wikitext cleanup helpers
# -----------------------------

_REF_TAG_RE = re.compile(r"<ref\b[^>/]*?>.*?</ref\s*>", re.IGNORECASE | re.DOTALL)
_REF_SELF_CLOSING_RE = re.compile(r"<ref\b[^>]*/\s*>", re.IGNORECASE)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_HTML_TAG_RE = re.compile(r"</?[^>]+>")
_FILE_LINK_RE = re.compile(r"\[\[(?:File|Image):[^\]]+\]\]", re.IGNORECASE)
_SIMPLE_TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}", re.DOTALL)
_WIKITABLE_RE = re.compile(r"\{\|.*?\|\}", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[([^|\]]+)(?:\|([^\]]+))?\]\]")
_FOR_TEMPLATE_RE = re.compile(r"\{\{\s*For\b.*?\}\}", re.IGNORECASE | re.DOTALL)


def strip_templates_simple(text: str, max_iters: int = 20) -> str:
    """Remove non-nested {{...}} templates iteratively (heuristic, not a full parser)."""
    t = text
    for _ in range(max_iters):
        new = _SIMPLE_TEMPLATE_RE.sub(" ", t)
        if new == t:
            break
        t = new
    return t


def normalize_text(text: str) -> str:
    """Lowercase + strip common noise (refs, comments, some templates/tables/tags)."""
    if not text:
        return ""

    t = text
    t = _COMMENT_RE.sub(" ", t)
    t = _REF_TAG_RE.sub(" ", t)
    t = _REF_SELF_CLOSING_RE.sub(" ", t)
    t = _WIKITABLE_RE.sub(" ", t)
    t = strip_templates_simple(t, max_iters=40)
    t = _FILE_LINK_RE.sub(" ", t)
    t = _HTML_TAG_RE.sub(" ", t)

    # simplify wikilinks: [[A|B]] -> B, [[A]] -> A
    def _wikilink_sub(m: re.Match) -> str:
        return (m.group(2) or m.group(1) or "").strip()

    t = _WIKILINK_RE.sub(_wikilink_sub, t)

    # remove bold/italics markup
    t = t.replace("'''", "").replace("''", "")

    # normalize whitespace
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


# -----------------------------
# Extraction: categories, infobox, lede
# -----------------------------

_CATEGORY_RE = re.compile(r"\[\[Category:([^|\]]+)(?:\|[^\]]*)?\]\]", re.IGNORECASE)


def extract_categories(wikitext: str) -> List[str]:
    return [c.strip() for c in _CATEGORY_RE.findall(wikitext or "")]


def find_template_block(wikitext: str, start_idx: int) -> Optional[Tuple[int, int]]:
    """Brace-stack scan to extract a {{ ... }} block starting at start_idx."""
    if start_idx < 0 or start_idx + 1 >= len(wikitext):
        return None
    if wikitext[start_idx:start_idx + 2] != "{{":
        return None

    i = start_idx
    depth = 0
    n = len(wikitext)

    while i < n - 1:
        two = wikitext[i:i + 2]
        if two == "{{":
            depth += 1
            i += 2
            continue
        if two == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                return (start_idx, i)
            continue
        i += 1

    return None


def extract_first_infobox(wikitext: str) -> Optional[str]:
    """Extract the first {{Infobox ...}} template block (heuristic)."""
    if not wikitext:
        return None
    m = re.search(r"\{\{\s*Infobox", wikitext, flags=re.IGNORECASE)
    if not m:
        return None
    block = find_template_block(wikitext, m.start())
    if not block:
        return None
    return wikitext[block[0]:block[1]]


def parse_infobox_params(infobox_text: str) -> Dict[str, str]:
    """Parse key=value params from an infobox (heuristic)."""
    if not infobox_text:
        return {}

    body = infobox_text.strip()
    if body.startswith("{{"):
        body = body[2:]
    if body.endswith("}}"):
        body = body[:-2]

    parts = body.split("\n|")
    params: Dict[str, str] = {}

    for p in parts[1:]:
        p = p.strip()
        if not p or "=" not in p:
            continue
        k, v = p.split("=", 1)
        params[k.strip().lower()] = v.strip()

    return params


def extract_lede_first_sentence(wikitext: str) -> Optional[str]:
    """
    Extract the first sentence from the lead section (before first heading).
    """
    if not wikitext:
        return None

    # Lead region: before first "== Heading =="
    split = re.split(r"\n==[^=].*?==\s*\n", wikitext, maxsplit=1)
    lead = split[0] if split else wikitext

    # Remove categories from lead
    lead = _CATEGORY_RE.sub(" ", lead)

    cleaned = normalize_text(lead)
    if not cleaned:
        return None

    m = re.search(r"^(.+?[.!?])\s", cleaned)
    if m:
        return m.group(1).strip()
    return cleaned.strip()[:400]


def _extract_lede_raw(wikitext: str) -> str:
    if not wikitext:
        return ""
    split = re.split(r"\n==[^=].*?==\s*\n", wikitext, maxsplit=1)
    lead = split[0] if split else wikitext
    return _CATEGORY_RE.sub(" ", lead)


def _lede_mentions_unincorporated_community(wikitext: str) -> bool:
    lead = _extract_lede_raw(wikitext)
    if not lead:
        return False
    lead = _FOR_TEMPLATE_RE.sub(" ", lead)
    cleaned = normalize_text(lead)
    return bool(
        re.search(r"\bunincorporated(?:\s+rural)?\s+community\b", cleaned)
    )


# -----------------------------
# Classification logic
# -----------------------------

def is_disambiguation_wikitext(wikitext: str) -> bool:
    """
    Best-effort disambiguation detection using templates in wikitext.
    """
    if not wikitext:
        return False
    return bool(re.search(
        r"\{\{\s*(disambiguation|hndis|geodis|schooldis|roadis|numberdis)\b",
        wikitext,
        flags=re.IGNORECASE
    ))


def detect_balance(wikitext: str, infobox_params: Optional[Dict[str, str]] = None) -> bool:
    """
    Detect '(balance)' using:
      - literal '(balance)' substring anywhere
      - infobox settlement_type/government_type/type containing 'balance'
    """
    if wikitext and re.search(r"\(balance\)", wikitext, flags=re.IGNORECASE):
        return True
    if infobox_params:
        blob = " ".join([
            infobox_params.get("settlement_type", ""),
            infobox_params.get("government_type", ""),
            infobox_params.get("type", ""),
        ])
        if re.search(r"\bbalance\b", blob, flags=re.IGNORECASE):
            return True
    return False


def candidates_from_infobox(infobox_params: Dict[str, str]) -> List[Candidate]:
    fields = []
    for k in ("settlement_type", "government_type", "type"):
        v = infobox_params.get(k)
        if v:
            fields.append(v)

    blob = normalize_text(" ".join(fields))
    out: List[Candidate] = []

    for muni_type, needles in INFOBOX_PATTERNS:
        for needle in needles:
            if needle.lower() in blob:
                out.append(Candidate(muni_type=muni_type, weight=WEIGHT_INFOBOX, source="infobox", matched=needle))
                break

    return out


def candidates_from_categories(categories: List[str]) -> List[Candidate]:
    cats = [normalize_text(c) for c in categories]
    out: List[Candidate] = []

    for muni_type, needles in CATEGORY_PATTERNS:
        for cat in cats:
            for needle in needles:
                if needle.lower() in cat:
                    out.append(Candidate(muni_type=muni_type, weight=WEIGHT_CATEGORY, source="category", matched=needle))
                    break

    return out


def candidates_from_lede(lede_sentence: str) -> List[Candidate]:
    s = normalize_text(lede_sentence)
    out: List[Candidate] = []

    for muni_type, regex_list in LEDE_PATTERNS:
        for rx in regex_list:
            if re.search(rx, s):
                # Guard: "cdp" alone is risky; require context unless "(cdp)" appears
                if muni_type == "CDP" and rx == r"\bcdp\b":
                    if "(cdp)" not in s and not re.search(r"\bcensus[- ]designated place\b", s):
                        continue
                out.append(Candidate(muni_type=muni_type, weight=WEIGHT_LEDE, source="lede", matched=rx))
                break

    return out


def apply_balance_mapping(base_type: str, balance_flag: bool) -> str:
    """
    Map base types to canonical balance variants when applicable.
    """
    if not balance_flag:
        # "metropolitan government" base isn't in the canonical list; use balance variant.
        if base_type == "metropolitan government":
            return "metropolitan government (balance)"
        return base_type

    if base_type == "consolidated government":
        return "consolidated government (balance)"
    if base_type == "unified government":
        return "unified government (balance)"
    if base_type == "metropolitan government":
        return "metropolitan government (balance)"

    return "(balance)"


def reconcile(cands: List[Candidate], balance_flag: bool) -> Result:
    if not cands:
        return Result(muni_type="unknown", confidence="low", reasons=["no classification signals found"])

    scores: Dict[str, int] = {}
    reasons: Dict[str, List[str]] = {}

    def add(mtype: str, w: int, src: str, matched: str) -> None:
        scores[mtype] = scores.get(mtype, 0) + w
        reasons.setdefault(mtype, []).append(f"{src}: {matched}")

    for c in cands:
        add(c.muni_type, c.weight, c.source, c.matched)

    # Bump rules to resolve overlaps
    if "city and borough" in scores:
        scores["city and borough"] += 50

    for gov in ("consolidated government", "unified government", "metropolitan government", "urban county"):
        if gov in scores:
            scores[gov] += 20

    if "CDP" in scores:
        scores["CDP"] += 20

    best_base = max(scores.items(), key=lambda kv: kv[1])[0]
    best_score = scores[best_base]

    final_type = apply_balance_mapping(best_base, balance_flag)
    if final_type not in CANONICAL_TYPES:
        final_type = best_base if best_base in CANONICAL_TYPES else "unknown"

    # Confidence heuristic
    if best_score >= 140:
        conf = "high"
    elif best_score >= 90:
        conf = "medium"
    else:
        conf = "low"

    best_reasons = reasons.get(best_base, [])
    if final_type != best_base:
        best_reasons = best_reasons + [f"balance-mapping applied => {final_type}"]

    return Result(muni_type=final_type, confidence=conf, reasons=best_reasons)


def determine_municipality_type_from_wikitext(wikitext: str) -> Result:
    """
    Internal: returns a Result dataclass.
    """
    if not wikitext or not wikitext.strip():
        return Result(muni_type="unknown", confidence="low", reasons=["empty wikitext"])

    if is_disambiguation_wikitext(wikitext):
        return Result(muni_type="unknown", confidence="low", reasons=["disambiguation template detected"])

    categories = extract_categories(wikitext)

    infobox_text = extract_first_infobox(wikitext)
    infobox_params = parse_infobox_params(infobox_text) if infobox_text else {}

    balance_flag = detect_balance(wikitext, infobox_params)

    lede_sentence = extract_lede_first_sentence(wikitext) or ""

    cands: List[Candidate] = []
    if infobox_params:
        cands.extend(candidates_from_infobox(infobox_params))
    if categories:
        cands.extend(candidates_from_categories(categories))
    if lede_sentence:
        cands.extend(candidates_from_lede(lede_sentence))

    result = reconcile(cands, balance_flag)
    if result.muni_type == "unknown" and _lede_mentions_unincorporated_community(wikitext):
        reasons = list(result.reasons) + [
            "fallback: lede mentions unincorporated community",
        ]
        return Result(muni_type="CDP", confidence="low", reasons=reasons)
    return result


def determine_municipality_type(wikitext: str) -> Dict[str, Any]:
    """
    Public API: import this function and call it.
    Returns:
      {
        "type": <canonical type>,
        "confidence": "high"|"medium"|"low",
        "reasons": [ ... ]
      }
    """
    res = determine_municipality_type_from_wikitext(wikitext)
    return {"type": res.muni_type, "confidence": res.confidence, "reasons": res.reasons}

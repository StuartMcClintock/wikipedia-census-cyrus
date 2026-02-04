"""
lede_classifier.py

Classify a Wikipedia municipality lede as:

- SKIP     => very likely already contains a 2020+ population (or modern estimate) in the lede
- NO_SKIP  => otherwise (conservative: run your LLM/update logic)

Accepts either plain-text lede or wikitext. Plain text is preferred.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple


# ----------------------------
# Regexes / heuristics
# ----------------------------

YEAR_RE = re.compile(r"\b(18|19|20)\d{2}\b")

# "Population-like" number token (avoid matching years by filtering later)
NUMBER_RE = re.compile(r"\b\d{1,3}(?:,\d{3})*\b|\b\d+\b")

# We treat these as signals that the year is related to population/census.
POP_CUES = (
    "population",
    "inhabitant",
    "resident",
    "people",
    "persons",
    "census",
    "estimated",   # for "estimated population"
)

# Window (chars) around a YEAR token to look for cues like "census" / "population"
CUE_WINDOW = 60


@dataclass(frozen=True)
class Classification:
    label: str               # "SKIP" | "NO_SKIP"
    reasons: List[str]       # debug-friendly
    matched_years: List[int] # years that looked population-related


def _strip_wikitext_minimally(text: str) -> str:
    """
    Best-effort, low-cost wikitext cleanup.
    If you can, pass plain text extracts instead — that will be more reliable.
    """
    s = text

    # Remove <ref>...</ref> and <ref .../>
    s = re.sub(r"<ref\b[^>/]*?/?>", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"<ref\b[^>]*?>.*?</ref>", " ", s, flags=re.IGNORECASE | re.DOTALL)

    # Remove HTML comments
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.DOTALL)

    # Replace wiki links:
    # [[Target|Text]] -> Text, [[Target]] -> Target
    s = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", r"\2", s)
    s = re.sub(r"\[\[([^\]]+)\]\]", r"\1", s)

    # External links: [url text] -> text ; [url] -> ""
    s = re.sub(r"\[(https?://[^\s\]]+)\s+([^\]]+)\]", r"\2", s, flags=re.IGNORECASE)
    s = re.sub(r"\[(https?://[^\s\]]+)\]", " ", s, flags=re.IGNORECASE)

    # Very shallow template removal: {{...}} (repeat to handle simple nesting)
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"\{\{[^{}]*\}\}", " ", s)

    # Remove remaining HTML-ish tags
    s = re.sub(r"</?[^>]+>", " ", s)

    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _split_sentences(text: str) -> List[str]:
    """
    Naive sentence splitter, good enough for leads.
    """
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _sentence_has_cue_near_year(sentence_lc: str, year_span: Tuple[int, int]) -> bool:
    start, end = year_span
    lo = max(0, start - CUE_WINDOW)
    hi = min(len(sentence_lc), end + CUE_WINDOW)
    window = sentence_lc[lo:hi]
    return any(cue in window for cue in POP_CUES)


def _sentence_has_non_year_number(sentence: str, year_value: int) -> bool:
    """
    True if the sentence contains a numeric token that is not the year itself.
    """
    for m in NUMBER_RE.finditer(sentence):
        tok = m.group(0)
        try:
            val = int(tok.replace(",", ""))
        except ValueError:
            continue
        if val != year_value:
            return True
    return False


def _population_related_years(clean_text: str) -> List[int]:
    """
    Extract years in the lede that look related to population/census statements.
    """
    years: List[int] = []
    for sent in _split_sentences(clean_text):
        sent_lc = sent.lower()

        # Quick prefilter: sentence must mention at least one cue
        if not any(cue in sent_lc for cue in POP_CUES):
            continue

        for ym in YEAR_RE.finditer(sent):
            year = int(ym.group(0))

            # Only count years that are near a population/census cue
            if not _sentence_has_cue_near_year(sent_lc, ym.span()):
                continue

            # Require the sentence to contain some non-year numeric token
            # (prevents classifying "As of the 2020 census," with no population figure)
            if not _sentence_has_non_year_number(sent, year):
                continue

            years.append(year)

    return years


def classify_lede(lede_text_or_wikitext: str) -> str:
    """
    Convenience wrapper returning only "SKIP" or "NO_SKIP".
    """
    return classify_lede_debug(lede_text_or_wikitext).label


def classify_lede_debug(lede_text_or_wikitext: str) -> Classification:
    """
    Debug-friendly classifier.

    Conservative: returns SKIP only when it finds a 2020+ year that appears to be
    tied to a population-related cue AND a non-year numeric value in the same
    sentence.

    This avoids skipping leads that mention "2020 census" but do not actually
    contain the population figure.
    """
    cleaned = _strip_wikitext_minimally(lede_text_or_wikitext)
    matched_years = _population_related_years(cleaned)

    reasons: List[str] = []
    if not matched_years:
        reasons.append("No population/census-related year+number pattern found in lede.")
        return Classification(label="NO_SKIP", reasons=reasons, matched_years=[])

    unique_years = sorted(set(matched_years))
    max_year = max(unique_years)
    reasons.append(f"Found population-related year(s): {unique_years} (max={max_year}).")

    if any(y >= 2020 for y in matched_years):
        reasons.append("Detected 2020+ population mention in lede => SKIP.")
        return Classification(label="SKIP", reasons=reasons, matched_years=matched_years)

    reasons.append("Only pre-2020 population year(s) found in lede => NO_SKIP.")
    return Classification(label="NO_SKIP", reasons=reasons, matched_years=matched_years)


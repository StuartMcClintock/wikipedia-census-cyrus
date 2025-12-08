"""
Helper utilities for parser-related cleanup tasks.
"""

import re


ALIGN_FIELD_RE = re.compile(r"(\|\s*align\s*=\s*)([^\n|}]*)", re.IGNORECASE)
ALIGN_FN_FIELD_RE = re.compile(r"(\|\s*align-fn\s*=\s*)([^\n|}]*)", re.IGNORECASE)
GENERAL_HEADING_RE = re.compile(r"^={2,6}.*=+\s*$", re.MULTILINE)
CENSUS_HEADING_RE = re.compile(
    r"^(?P<equals>={3,})\s*(?P<year>20(?:20|10|00))\s+census\s*(?P=equals)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(\|([^\]]+))?\]\]")
REF_CITE_RE = re.compile(r"(<ref[^>]*>)(.*?)(</ref>)", re.IGNORECASE | re.DOTALL)
REF_LEADING_WS_RE = re.compile(r"(\s+)(<ref[^>]*>)", re.IGNORECASE)


def _find_template_end(text: str, start_index: int) -> int:
    """
    Return the index just after the matching closing braces for the template
    starting at start_index, or -1 if no matching end is found.
    """
    depth = 0
    i = start_index
    length = len(text)

    while i < length:
        if text.startswith("{{", i):
            depth += 1
            i += 2
            continue
        if text.startswith("}}", i):
            depth -= 1
            i += 2
            if depth == 0:
                return i
            continue
        i += 1

    return -1


def fix_us_census_population_align(wikitext: str) -> str:
    """
    Ensure any US Census population template uses |align = right and
    |align-fn = center without touching other fields.
    """
    if "{{US Census population" not in wikitext:
        return wikitext

    def _insert_field(template_text: str, field_line: str) -> str:
        end = template_text.rfind("}}")
        if end == -1:
            return template_text + "\n" + field_line
        prefix = template_text[:end]
        suffix = template_text[end:]
        newline = "" if prefix.endswith("\n") else "\n"
        return f"{prefix}{newline}{field_line}\n{suffix.lstrip()}"

    def normalize_align(template_text: str) -> str:
        match = ALIGN_FIELD_RE.search(template_text)
        if match:
            current_value = match.group(2).strip().lower()
            if current_value != "right":
                template_text = ALIGN_FIELD_RE.sub(
                    lambda m: m.group(1) + "right", template_text, count=1
                )
        else:
            template_text = _insert_field(template_text, "| align = right")

        fn_match = ALIGN_FN_FIELD_RE.search(template_text)
        if fn_match:
            fn_value = fn_match.group(2).strip().lower()
            if fn_value != "center":
                template_text = ALIGN_FN_FIELD_RE.sub(
                    lambda m: m.group(1) + "center", template_text, count=1
                )
        else:
            template_text = _insert_field(template_text, "| align-fn = center")
        return template_text

    parts = []
    cursor = 0
    text_length = len(wikitext)

    while cursor < text_length:
        start = wikitext.find("{{US Census population", cursor)
        if start == -1:
            parts.append(wikitext[cursor:])
            break

        parts.append(wikitext[cursor:start])

        end = _find_template_end(wikitext, start)
        if end == -1:
            parts.append(wikitext[start:])
            break

        template_block = wikitext[start:end]
        parts.append(normalize_align(template_block))
        cursor = end

    return "".join(parts)


def fix_census_section_order(wikitext: str) -> str:
    """
    Reorder census sections to ensure 2020, then 2010, then 2000 census.
    """
    matches = list(CENSUS_HEADING_RE.finditer(wikitext))
    if len(matches) < 2:
        return wikitext

    heading_positions = sorted(m.start() for m in GENERAL_HEADING_RE.finditer(wikitext))
    heading_positions.append(len(wikitext))

    sections = []
    for match in matches:
        start = match.start()
        end_candidates = [pos for pos in heading_positions if pos > start]
        end = end_candidates[0] if end_candidates else len(wikitext)
        year = match.group("year")
        sections.append((start, end, year, wikitext[start:end]))

    sections.sort(key=lambda item: item[0])
    current_order = [year for _, _, year, _ in sections]
    desired_years = ["2020", "2010", "2000"]
    desired_order = [year for year in desired_years if year in current_order]
    if current_order == desired_order:
        return wikitext

    section_by_year = {year: text for _, _, year, text in sections}
    first_start = sections[0][0]
    last_end = sections[-1][1]

    prefix = wikitext[:first_start]
    suffix = wikitext[last_end:]
    reordered = "".join(section_by_year[year] for year in desired_order)

    return prefix + reordered + suffix


def restore_wikilinks_from_original(original_text: str, updated_text: str) -> str:
    """
    Ensure that any display text that was linked in the original text remains linked.
    """
    link_entries = []
    for match in WIKILINK_RE.finditer(original_text):
        target = match.group(1).strip()
        display = match.group(3).strip() if match.group(3) else target
        if not target or not display:
            continue
        link_entries.append((display, match.group(0)))

    fixed_text = updated_text
    for display, link_markup in link_entries:
        if display not in fixed_text:
            continue
        # Skip if already linked
        if WIKILINK_RE.search(fixed_text) and re.search(r"\[\[[^\]]*?" + re.escape(display) + r"[^\]]*?\]\]", fixed_text):
            continue
        pattern = re.compile(r"(?<!\[\[)" + re.escape(display) + r"(?![^\[]*\]\])")
        fixed_text, count = pattern.subn(link_markup, fixed_text, count=1)
        if count == 0:
            continue
    return fixed_text


def normalize_ref_citation_braces(wikitext: str) -> str:
    """
    Ensure citations inside <ref>...</ref> are wrapped with exactly '{{' and '}}'.
    """
    def normalize_body(body: str) -> str:
        stripped = body.strip()
        if not stripped:
            return body
        # Remove leading/trailing braces
        while stripped.startswith("{"):
            stripped = stripped[1:]
        while stripped.endswith("}"):
            stripped = stripped[:-1]
        stripped = stripped.strip()
        return "{{" + stripped + "}}"

    def replace(match):
        open_tag, body, close_tag = match.groups()
        return f"{open_tag}{normalize_body(body)}{close_tag}"

    return REF_CITE_RE.sub(replace, wikitext)


def strip_whitespace_before_refs(wikitext: str) -> str:
    """
    Remove whitespace immediately preceding <ref> tags.
    """
    return REF_LEADING_WS_RE.sub(r"\2", wikitext)

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
CITATION_PARAM_RE = re.compile(r"(?:^|\|)\s*[A-Za-z0-9_-]+\s*=")
CITATION_SHORT_NAMES = {
    "sfn",
    "sfnp",
    "sfnm",
    "sfnmp",
    "harv",
    "harvnb",
    "harvp",
    "harvc",
    "harvtxt",
    "r",
}


def _count_leading_chars(text: str, char: str) -> int:
    count = 0
    for current in text:
        if current == char:
            count += 1
        else:
            break
    return count


def _count_trailing_chars(text: str, char: str) -> int:
    count = 0
    for current in reversed(text):
        if current == char:
            count += 1
        else:
            break
    return count


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
    return enforce_ref_citation_template_braces(wikitext)


def _looks_like_citation_template(content: str) -> bool:
    """
    Return True when the provided template content resembles a citation template call.
    """
    text = content.strip()
    if not text or "|" not in text:
        return False

    name, rest = text.split("|", 1)
    name = name.strip().lstrip("{").rstrip("}")
    lowered = name.lower()

    if lowered.startswith("cite") or lowered.startswith("citation"):
        return True
    if lowered in CITATION_SHORT_NAMES:
        return True

    if CITATION_PARAM_RE.search(rest) and re.match(r"[A-Za-z][A-Za-z0-9_-]*$", name):
        return True

    return False


def enforce_ref_citation_template_braces(wikitext: str) -> str:
    """
    Normalize <ref>...</ref> blocks so citation templates use '{{' and '}}' at the edges.
    """

    def normalize_ref(match: re.Match) -> str:
        open_tag, body, close_tag = match.groups()
        stripped_body = body.strip()
        if not stripped_body:
            return match.group(0)

        leading_ws = body[: len(body) - len(body.lstrip())]
        trailing_ws = body[len(body.rstrip()) :]

        leading_braces = _count_leading_chars(stripped_body, "{")
        trailing_braces = _count_trailing_chars(stripped_body, "}")

        # Skip complex cases to avoid breaking nested or intentional constructs.
        if leading_braces > 3:
            return match.group(0)

        if stripped_body.startswith("{{"):
            template_end = _find_template_end(stripped_body, 0)
            suffix = stripped_body[template_end:].strip() if template_end != -1 else ""

            # Avoid touching refs where the template is followed by other text.
            if suffix and any(char != "}" for char in suffix):
                return match.group(0)

            if template_end == len(stripped_body) and leading_braces == 2:
                inner = stripped_body[2:-2]
                if _looks_like_citation_template(inner):
                    return match.group(0)

            if template_end != -1:
                inner = stripped_body[2 : template_end - 2]
            else:
                simulated = stripped_body + "}}"
                simulated_end = _find_template_end(simulated, 0)
                if simulated_end != -1:
                    inner = simulated[2 : simulated_end - 2]
                else:
                    inner = stripped_body[2:]

            extra_leading = max(0, leading_braces - 2)
            if extra_leading:
                inner = inner[extra_leading:]

            if not _looks_like_citation_template(inner):
                return match.group(0)

            normalized_inner = inner.strip()
            return f"{open_tag}{leading_ws}{{{{{normalized_inner}}}}}{trailing_ws}{close_tag}"

        if stripped_body.startswith("{"):
            simulated = "{" + stripped_body  # add the missing opening brace
            simulated_end = _find_template_end(simulated, 0)
            suffix = simulated[simulated_end:].strip() if simulated_end != -1 else ""

            if suffix and any(char != "}" for char in suffix):
                return match.group(0)

            if simulated_end != -1:
                inner = simulated[2 : simulated_end - 2]
            else:
                inner = stripped_body.lstrip("{").rstrip("}")

            if not _looks_like_citation_template(inner):
                return match.group(0)

            normalized_inner = inner.strip().lstrip("{").rstrip("}")
            return f"{open_tag}{leading_ws}{{{{{normalized_inner}}}}}{trailing_ws}{close_tag}"

        if not _looks_like_citation_template(stripped_body):
            return match.group(0)

        normalized_inner = stripped_body.strip()
        return f"{open_tag}{leading_ws}{{{{{normalized_inner}}}}}{trailing_ws}{close_tag}"

    return REF_CITE_RE.sub(normalize_ref, wikitext)


def strip_whitespace_before_refs(wikitext: str) -> str:
    """
    Remove whitespace immediately preceding <ref> tags.
    """
    return REF_LEADING_WS_RE.sub(r"\2", wikitext)

def collapse_extra_newlines(wikitext: str) -> str:
    """
    Replace any run of 3+ newlines with exactly 2.
    """
    return re.sub(r"\n{3,}", "\n\n", wikitext)


def _is_citation_body(body: str) -> bool:
    """
    Return True when the ref body appears to be a citation template invocation.
    """
    candidate = body.strip()
    if not candidate:
        return False

    while candidate.startswith("{"):
        candidate = candidate[1:]
    while candidate.endswith("}"):
        candidate = candidate[:-1]
    candidate = candidate.strip()

    if not candidate:
        return False

    return _looks_like_citation_template(candidate)


def strip_whitespace_before_citation_refs(wikitext: str) -> str:
    """
    Remove whitespace (spaces, tabs, newlines) immediately before citation refs only.
    """
    if "<ref" not in wikitext:
        return wikitext

    parts = []
    cursor = 0

    for match in REF_CITE_RE.finditer(wikitext):
        open_start = match.start(1)
        end = match.end(0)
        body = match.group(2)

        replaced = False
        if _is_citation_body(body):
            block_start = open_start
            while block_start > cursor and wikitext[block_start - 1].isspace():
                block_start -= 1

            if block_start != open_start and wikitext[:block_start].strip():
                parts.append(wikitext[cursor:block_start])
                parts.append(wikitext[open_start:end])
                cursor = end
                replaced = True

        if replaced:
            continue

        parts.append(wikitext[cursor:end])
        cursor = end

    parts.append(wikitext[cursor:])
    return "".join(parts)

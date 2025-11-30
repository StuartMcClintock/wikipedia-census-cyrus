"""
Helper utilities for parser-related cleanup tasks.
"""

import re


ALIGN_FIELD_RE = re.compile(r"(\|\s*align\s*=\s*)([^\n|}]*)", re.IGNORECASE)
ALIGN_FN_FIELD_RE = re.compile(r"(\|\s*align-fn\s*=\s*)([^\n|}]*)", re.IGNORECASE)


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

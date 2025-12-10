import copy
import re

from .parser_utils import (
    enforce_ref_citation_template_braces,
    fix_census_section_order,
    fix_us_census_population_align,
    collapse_extra_newlines,
    move_heading_refs_to_first_paragraph,
    restore_wikilinks_from_original,
    strip_whitespace_before_citation_refs,
)


class ParsedWikitext:
    """
    Encapsulates parsed Wikipedia wikitext and offers helpers for inspection,
    mutation, and serialization back to raw wikitext.
    """

    __slots__ = ("_sections", "_original_length")

    def __init__(self, sections=None, original_length=None, wikitext=None):
        """
        Construct a ParsedWikitext either from a precomputed section list or a raw string.

        wikitext takes precedence and triggers parsing when provided. Passing sections
        allows for direct construction from already parsed structures (e.g., tests).
        """
        if wikitext is not None:
            if sections is not None:
                raise ValueError("Provide either sections or wikitext, not both.")
            sections = _parse_wikitext(wikitext)
            original_length = len(wikitext)

        if sections is None:
            sections = []

        # store a deep copy to decouple from external references
        self._sections = copy.deepcopy(sections)
        self._original_length = original_length if original_length is not None else 0

    # @property exposes a read-only view of the parsed section structure.
    @property
    def sections(self):
        """Return the underlying parsed sections."""
        return self._sections

    @property
    def original_length(self):
        """Return the number of characters the article had when parsed."""
        return self._original_length

    def section_keys(self, level=0):
        """
        Return a newline-delimited string of headings reflecting section nesting.

        level controls indentation depth; H2 sections start at level 0, H3 at 1, etc.
        """
        lines = []

        def collect(sections, depth):
            indent = "  " * depth
            for heading, content in sections:
                lines.append(f"{indent}{heading}")
                if isinstance(content, list):
                    collect(content, depth + 1)

        collect(self._sections, level)
        return "\n".join(lines)

    def outline(self, article_title):
        """
        Return a formatted outline headed by article_title and indented section keys.
        """
        body = self.section_keys(level=1)
        if body:
            return f"{article_title}\n{body}"
        return article_title

    def to_wikitext(self):
        """
        Convert the parsed structure back into wikitext.
        """
        parts = []

        def render(items, depth):
            for heading, content in items:
                if heading in {"__lead__", "__content__"}:
                    if content:
                        parts.append(content)
                    continue

                level = depth + 2
                marker = "=" * level
                parts.append(f"{marker}{heading}{marker}\n")

                if isinstance(content, list):
                    render(content, depth + 1)
                elif content:
                    parts.append(content)

        render(self._sections, 0)
        return "".join(parts)

    def overwrite_section(self, key_path, new_text):
        """
        Overwrite the content of a specific section in the parsed structure.
        """
        path_str, parent_sections, current_entry = self._locate_section(key_path)
        if isinstance(current_entry[1], list):
            raise ValueError(f"Section path {path_str} refers to subsections, not content.")

        index = parent_sections.index(current_entry)
        parent_sections[index] = (current_entry[0], new_text)

    def get_section(self, key_path):
        """
        Retrieve the text content for a specific section identified by key_path.
        """
        path_str, _, current_entry = self._locate_section(key_path)
        if isinstance(current_entry[1], list):
            raise ValueError(f"Section path {path_str} refers to subsections, not content.")
        return current_entry[1]

    def clone(self):
        """Return a deep copy of this ParsedWikitext instance."""
        return ParsedWikitext(copy.deepcopy(self._sections), self._original_length)

    def _locate_section(self, key_path):
        """
        Locate a section and return (path_str, parent_sections, current_entry).
        """
        path_tuple = tuple(key_path)
        if not path_tuple:
            raise ValueError("key_path must identify a section.")

        path_str = " > ".join(path_tuple)
        parent_sections = None
        current_sections = self._sections
        current_entry = None

        for heading in path_tuple:
            if current_sections is None:
                raise ValueError(
                    f"Section path {path_str} extends beyond available headings."
                )

            for entry in current_sections:
                if entry[0] == heading:
                    parent_sections = current_sections
                    current_entry = entry
                    break
            else:
                raise KeyError(f"Section path {path_str} not found.")

            current_sections = (
                current_entry[1] if isinstance(current_entry[1], list) else None
            )

        return path_str, parent_sections, current_entry


def _parse_wikitext(wikitext):
    """
    Parse wikitext into nested tuples keyed by headings while preserving order.
    """
    heading_pattern = re.compile(r"^(=+)\s*(.*?)\s*\1\s*$")
    max_heading_level = 6

    class Section:
        __slots__ = ("title", "level", "content", "children")

        def __init__(self, title, level):
            self.title = title
            self.level = level
            self.content = ""
            self.children = []

    root = Section("__root__", 1)
    stack = [root]
    pending_lines = []

    def flush_pending():
        if not pending_lines:
            return
        block = "".join(pending_lines)
        pending_lines.clear()
        stack[-1].content += block

    for line in wikitext.splitlines(keepends=True):
        stripped = line.strip()
        match = heading_pattern.match(stripped)
        if match:
            flush_pending()
            marker, title = match.groups()
            title = title.strip()
            original_level = len(marker)
            normalized_level = original_level

            if normalized_level == 1:
                print(f'Encountered H1 heading "{title}"; treating as H2.')
                normalized_level = 2
            if normalized_level > max_heading_level:
                print(f'Encountered heading "{title}" beyond H6; treating as H6.')
                normalized_level = max_heading_level

            while stack and stack[-1].level >= normalized_level:
                stack.pop()

            parent_section = stack[-1]
            if normalized_level > parent_section.level + 1:
                adjusted_level = parent_section.level + 1
                print(
                    f'Adjusted heading "{title}" from H{original_level} to H{adjusted_level} to maintain hierarchy.'
                )
                normalized_level = adjusted_level
                while stack and stack[-1].level >= normalized_level:
                    stack.pop()
                parent_section = stack[-1]

            parent_section = stack[-1]
            new_section = Section(title, normalized_level)
            parent_section.children.append(new_section)
            stack.append(new_section)
        else:
            pending_lines.append(line)

    flush_pending()

    def section_to_nested(section):
        if not section.children:
            return (section.title, section.content)
        nested = []
        if section.content:
            nested.append(("__content__", section.content))
        for child in section.children:
            nested.append(section_to_nested(child))
        return (section.title, nested)

    result = []
    if root.content:
        result.append(("__lead__", root.content))
    for child in root.children:
        result.append(section_to_nested(child))
    return result


_SECTION_SENTINELS = {"__lead__", "__content__"}


def fix_demographics_section_wikitext(
    section_wikitext: str, original_section_wikitext: str = None
) -> str:
    """
    Apply deterministic fixes to a demographics section wikitext block.
    """
    fixes = [
        fix_us_census_population_align,
        fix_census_section_order,
        enforce_ref_citation_template_braces,
        strip_whitespace_before_citation_refs,
        move_heading_refs_to_first_paragraph,
        collapse_extra_newlines,
    ]
    fixed = section_wikitext
    for func in fixes:
        fixed = func(fixed)
    if original_section_wikitext:
        fixed = restore_wikilinks_from_original(original_section_wikitext, fixed)
    return fixed


def fix_demographics_section_in_article(
    article_wikitext: str, original_demographics_wikitext: str = None
) -> str:
    """
    Locate the demographics section in an article wikitext and apply
    deterministic fixes, returning the updated article text.
    """
    parsed_article = ParsedWikitext(wikitext=article_wikitext)

    for index, entry in enumerate(parsed_article.sections):
        heading = entry[0]
        if heading in _SECTION_SENTINELS or heading != "Demographics":
            continue

        section_text = ParsedWikitext(sections=[entry]).to_wikitext()
        fixed_section_text = fix_demographics_section_wikitext(
            section_text, original_section_wikitext=original_demographics_wikitext
        )

        if fixed_section_text == section_text:
            return article_wikitext

        fixed_sections = ParsedWikitext(wikitext=fixed_section_text).sections
        replacement_entry = None
        for fixed_entry in fixed_sections:
            if fixed_entry[0] in _SECTION_SENTINELS:
                continue
            replacement_entry = fixed_entry
            break

        if replacement_entry is None:
            raise ValueError(
                "Fixed demographics text did not include a section heading."
            )

        parsed_article.sections[index] = replacement_entry
        return parsed_article.to_wikitext()

    return article_wikitext

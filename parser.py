import re


def parse_wikitext_sections(wikitext):
    """
    Parse wikitext into nested tuples keyed by headings while preserving order.

    Returns a list such that each item represents an H2 section as a tuple of
    (heading, content). Content is either the raw text for that section or a
    list containing sub-sections in the same format. When both free text and
    sub-sections exist under the same heading, the sub-section list stores an
    initial ("__content__", text) entry to keep leading text in order. Content
    preceding the first H2 is returned as ("__lead__", text).
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


def print_wikitext_section_keys(parsed_sections, level=0):
    """
    Return a newline-delimited string of keys from parse_wikitext_sections output.

    level controls indentation depth; H2 sections start at level 0, H3 at 1, etc.
    """
    lines = []

    def collect(sections, depth):
        indent = "  " * depth
        for heading, content in sections:
            lines.append(f"{indent}{heading}")
            if isinstance(content, list):
                collect(content, depth + 1)

    collect(parsed_sections, level)
    return "\n".join(lines)


def get_article_outline(article_title, parsed_sections):
    """
    Return a formatted outline headed by article_title and indented section keys.
    """
    body = print_wikitext_section_keys(parsed_sections, level=1)
    if body:
        return f"{article_title}\n{body}"
    return article_title

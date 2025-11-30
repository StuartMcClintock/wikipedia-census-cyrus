"""
Parser package exposing ParsedWikitext and deterministic fix helpers.
"""

from .parser import ParsedWikitext, fix_demographics_section_in_article
from .parser_utils import fix_us_census_population_align

__all__ = [
    "ParsedWikitext",
    "fix_demographics_section_in_article",
    "fix_us_census_population_align",
]

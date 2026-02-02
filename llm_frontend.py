"""
Frontend layer that routes LLM requests to the appropriate backend based on the model.
Acts as an interface between poster.py and the actual LLM backends.
"""

import os
from constants import DEFAULT_CODEX_MODEL, codex_models, openai_gpt_models, anthropic_models


def _get_backend_module():
    """
    Determine which backend module to use based on the active model.
    Returns the appropriate backend module.
    """
    active_model = os.getenv("ACTIVE_MODEL", DEFAULT_CODEX_MODEL)

    if active_model in codex_models:
        from llm_backends.openai_codex import openai_codex
        return openai_codex
    elif active_model in openai_gpt_models:
        from llm_backends.openai_gpt_5_mini import openai_gpt_5_mini
        return openai_gpt_5_mini
    elif active_model in anthropic_models:
        from llm_backends.claude_haiku import claude_haiku
        return claude_haiku
    else:
        raise ValueError(
            f"Unknown model '{active_model}'. Must be one of {codex_models + openai_gpt_models + anthropic_models}"
        )


def check_if_update_needed(current_article: str, new_text: str, suppress_out: bool = True) -> bool:
    """
    Check if the proposed text contains information not already in the current article.

    Args:
        current_article: Current Wikipedia article text
        new_text: Proposed new text to add
        suppress_out: Whether to suppress LLM output

    Returns:
        True if update is needed, False otherwise
    """
    backend = _get_backend_module()
    return backend.check_if_update_needed(current_article, new_text, suppress_out)


def update_wp_page(current_article: str, new_text: str, suppress_out: bool = True) -> str:
    """
    Update the full Wikipedia page with new census data.

    Args:
        current_article: Current Wikipedia article text
        new_text: Proposed new text to add
        suppress_out: Whether to suppress LLM output

    Returns:
        Updated article text
    """
    backend = _get_backend_module()
    return backend.update_wp_page(current_article, new_text, suppress_out)


def update_demographics_section(
    current_demographics_section: str, new_text: str, mini: bool = True, suppress_out: bool = True
) -> str:
    """
    Update just the demographics section of a Wikipedia article.

    Args:
        current_demographics_section: Current demographics section text
        new_text: Proposed new text to add
        mini: Whether to use the mini (shorter) prompt
        suppress_out: Whether to suppress LLM output

    Returns:
        Updated demographics section text
    """
    backend = _get_backend_module()
    return backend.update_demographics_section(current_demographics_section, new_text, mini, suppress_out)


def update_lede(current_lede_text: str, population_sentence: str, suppress_out: bool = True) -> str:
    """
    Update the lede/intro text of a Wikipedia article.

    Args:
        current_lede_text: Current lede wikitext
        population_sentence: A sentence containing the 2020 census population + citation
        suppress_out: Whether to suppress LLM output

    Returns:
        Updated lede text
    """
    backend = _get_backend_module()
    return backend.update_lede(current_lede_text, population_sentence, suppress_out)

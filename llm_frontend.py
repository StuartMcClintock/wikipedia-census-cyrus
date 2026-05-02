"""
Frontend layer that routes LLM requests to the appropriate backend based on the model.
Acts as an interface between poster.py and the actual LLM backends.
"""

from contextlib import contextmanager
import os
from constants import (
    DEFAULT_CODEX_MODEL,
    codex_models,
    openai_gpt_models,
    anthropic_models,
    claude_code_models,
)

ENABLE_TASK_MODEL_ROUTING_ENV = "ENABLE_TASK_MODEL_ROUTING"
_LIGHTWEIGHT_OPENAI_MODEL = "gpt-5.4-mini"
_CHECK_TASK = "check_if_update_needed"
_FULL_PAGE_TASK = "update_wp_page"
_DEMOGRAPHICS_TASK = "update_demographics_section"
_LEDE_TASK = "update_lede"


def _get_backend_module_for_model(active_model: str):
    """
    Determine which backend module to use based on the provided model.
    Returns the appropriate backend module.
    """
    if active_model in codex_models:
        from llm_backends.openai_codex import openai_codex
        return openai_codex
    elif active_model in openai_gpt_models:
        from llm_backends.openai_gpt_5_mini import openai_gpt_5_mini
        return openai_gpt_5_mini
    elif active_model in anthropic_models:
        from llm_backends.claude_haiku import claude_haiku
        return claude_haiku
    elif active_model in claude_code_models:
        from llm_backends.claude_code import claude_code
        return claude_code
    else:
        raise ValueError(
            f"Unknown model '{active_model}'. Must be one of "
            f"{codex_models + openai_gpt_models + anthropic_models + claude_code_models}"
        )


def _get_backend_module():
    active_model = os.getenv("ACTIVE_MODEL", DEFAULT_CODEX_MODEL)
    return _get_backend_module_for_model(active_model)


def _task_model_routing_enabled() -> bool:
    return os.getenv(ENABLE_TASK_MODEL_ROUTING_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _openai_chat_models_available() -> bool:
    try:
        from credentials import OPEN_AI_KEY
    except Exception:
        return False
    return bool(OPEN_AI_KEY and str(OPEN_AI_KEY).strip())


def _resolve_model_for_task(task_name: str) -> str:
    active_model = os.getenv("ACTIVE_MODEL", DEFAULT_CODEX_MODEL)
    if not _task_model_routing_enabled():
        return active_model

    if active_model in claude_code_models:
        if task_name in {_CHECK_TASK, _LEDE_TASK}:
            return "haiku"
        return active_model

    if active_model in anthropic_models:
        if task_name in {_CHECK_TASK, _FULL_PAGE_TASK}:
            return DEFAULT_CODEX_MODEL
        return active_model

    if (
        active_model in codex_models or active_model in openai_gpt_models
    ) and task_name in {_CHECK_TASK, _LEDE_TASK}:
        if _openai_chat_models_available():
            return _LIGHTWEIGHT_OPENAI_MODEL
    return active_model


@contextmanager
def _temporary_active_model(model_name: str):
    had_previous = "ACTIVE_MODEL" in os.environ
    previous_model = os.environ.get("ACTIVE_MODEL")
    os.environ["ACTIVE_MODEL"] = model_name
    try:
        yield
    finally:
        if had_previous and previous_model is not None:
            os.environ["ACTIVE_MODEL"] = previous_model
        else:
            os.environ.pop("ACTIVE_MODEL", None)


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
    task_model = _resolve_model_for_task(_CHECK_TASK)
    backend = _get_backend_module_for_model(task_model)
    with _temporary_active_model(task_model):
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
    task_model = _resolve_model_for_task(_FULL_PAGE_TASK)
    backend = _get_backend_module_for_model(task_model)
    with _temporary_active_model(task_model):
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
    task_model = _resolve_model_for_task(_DEMOGRAPHICS_TASK)
    backend = _get_backend_module_for_model(task_model)
    with _temporary_active_model(task_model):
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
    task_model = _resolve_model_for_task(_LEDE_TASK)
    backend = _get_backend_module_for_model(task_model)
    with _temporary_active_model(task_model):
        return backend.update_lede(current_lede_text, population_sentence, suppress_out)

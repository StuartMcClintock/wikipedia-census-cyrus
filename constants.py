codex_models = [
    "gpt-5.3-codex",
]
openai_gpt_models = [
    "gpt-5.2",
    "gpt-5.4",
    "gpt-5.4-mini",
]
FINE_TUNED_GPT_4_1_MINI_WIKI_CENSUS_IOWA = (
    "ft:gpt-4.1-mini-2025-04-14:personal:wiki-census-iowa:DbNjEIZz"
)

# Short aliases for long fine-tuned model ids. Use either side as the value of
# --model or ACTIVE_MODEL; the backend resolves aliases before calling OpenAI.
MODEL_ALIASES = {
    "gpt-4-1-mini-ft": FINE_TUNED_GPT_4_1_MINI_WIKI_CENSUS_IOWA,
}

fine_tuned_models = [
    FINE_TUNED_GPT_4_1_MINI_WIKI_CENSUS_IOWA,
    *MODEL_ALIASES.keys(),
]


def resolve_model_alias(name: str) -> str:
    """Map a friendly alias to its real OpenAI model id, or return name unchanged."""
    return MODEL_ALIASES.get(name, name)
open_ai_models = codex_models + openai_gpt_models + fine_tuned_models

anthropic_models = ['claude-haiku-4-5']

claude_code_models = [
    'haiku',
    'claude-opus-4-7',
    'claude-sonnet-4-6',
]

DEFAULT_CODEX_MODEL = 'gpt-5.3-codex'
DEFAULT_ANTHROPIC_MODEL = 'claude-haiku-4-5'
DEFAULT_CLAUDE_CODE_MODEL = 'claude-opus-4-7'


def is_mini_model(model_name: str) -> bool:
    return model_name.endswith("-mini")


def get_all_model_options():
    return open_ai_models + anthropic_models + claude_code_models

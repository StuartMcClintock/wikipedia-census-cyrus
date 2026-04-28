codex_models = [
    "gpt-5.3-codex",
]
openai_gpt_models = [
    "gpt-5.2",
    "gpt-5.4",
    "gpt-5.4-mini",
]
open_ai_models = codex_models + openai_gpt_models

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

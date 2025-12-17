open_ai_models = ["gpt-5.1-codex-mini", "gpt-5.1-codex-max", "gpt-5.1"]

anthropic_models = ['claude-haiku-4-5']

DEFAULT_CODEX_MODEL = 'gpt-5.1-codex-max'
DEFAULT_ANTHROPIC_MODEL = 'claude-haiku-4-5'

def get_all_model_options():
    return open_ai_models + anthropic_models
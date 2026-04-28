import importlib.util
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "test_codex_model_support.py"
)
SPEC = importlib.util.spec_from_file_location(
    "test_codex_model_support",
    MODULE_PATH,
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_classify_probe_result_marks_supported():
    result = MODULE.classify_probe_result(
        model="gpt-5.4",
        returncode=0,
        stdout="OK",
        stderr="",
    )

    assert result["supported"] is True
    assert result["status"] == "supported"


def test_classify_probe_result_marks_chatgpt_unsupported():
    result = MODULE.classify_probe_result(
        model="gpt-5.1-codex-mini",
        returncode=1,
        stdout="",
        stderr=(
            'ERROR: unexpected status 400 Bad Request: {"detail":"The '
            '\'gpt-5.1-codex-mini\' model is not supported when using Codex '
            'with a ChatGPT account."}'
        ),
    )

    assert result["supported"] is False
    assert result["status"] == "unsupported_for_chatgpt_account"


def test_parse_args_uses_default_model_list():
    args = MODULE.parse_args([])

    assert args.models == MODULE.DEFAULT_MODELS
    assert args.timeout == 45

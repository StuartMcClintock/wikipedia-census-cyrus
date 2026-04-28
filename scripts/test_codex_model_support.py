#!/usr/bin/env python3
"""
Probe which Codex CLI models work in the current authenticated environment.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

DEFAULT_MODELS = [
    "gpt-5.4",
    "gpt-5.2-codex",
    "gpt-5.1-codex-max",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5.2",
    "gpt-5.1-codex-mini",
]
DEFAULT_PROMPT = (
    "Reply with exactly OK and do not run any shell commands or edit any files."
)
CHATGPT_UNSUPPORTED_MARKER = (
    "is not supported when using codex with a chatgpt account"
)
MODEL_NOT_FOUND_MARKER = "model_not_found"
USAGE_LIMIT_MARKERS = (
    "you've hit your usage limit",
    "usage limit",
    "insufficient_quota",
)


def classify_probe_result(
    model: str,
    returncode: int,
    stdout: str,
    stderr: str,
    timed_out: bool = False,
) -> Dict[str, object]:
    combined = "\n".join(part for part in (stdout, stderr) if part).lower()
    if timed_out:
        return {
            "model": model,
            "status": "timeout",
            "supported": False,
            "detail": "Command timed out",
        }
    if returncode == 0:
        return {
            "model": model,
            "status": "supported",
            "supported": True,
            "detail": "Codex accepted the model",
        }
    if CHATGPT_UNSUPPORTED_MARKER in combined:
        return {
            "model": model,
            "status": "unsupported_for_chatgpt_account",
            "supported": False,
            "detail": "Model rejected for current ChatGPT-authenticated Codex account",
        }
    if MODEL_NOT_FOUND_MARKER in combined:
        return {
            "model": model,
            "status": "model_not_found",
            "supported": False,
            "detail": "Model name was not recognized",
        }
    if any(marker in combined for marker in USAGE_LIMIT_MARKERS):
        return {
            "model": model,
            "status": "usage_limited",
            "supported": False,
            "detail": "Probe hit a Codex usage limit before completion",
        }
    return {
        "model": model,
        "status": "error",
        "supported": False,
        "detail": (stderr or stdout or "Unknown error").strip(),
    }


def probe_model(
    model: str,
    prompt: str,
    workdir: Path,
    timeout_seconds: int,
) -> Dict[str, object]:
    cmd = ["codex", "exec", "-m", model, prompt]
    try:
        result = subprocess.run(
            cmd,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        probe = classify_probe_result(
            model=model,
            returncode=-1,
            stdout=stdout,
            stderr=stderr,
            timed_out=True,
        )
        probe["stdout"] = stdout.strip()
        probe["stderr"] = stderr.strip()
        return probe

    probe = classify_probe_result(
        model=model,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )
    probe["returncode"] = result.returncode
    probe["stdout"] = (result.stdout or "").strip()
    probe["stderr"] = (result.stderr or "").strip()
    return probe


def format_results(results: Sequence[Dict[str, object]]) -> str:
    lines = ["Codex model support probe", ""]
    for result in results:
        marker = "OK" if result["supported"] else "NO"
        lines.append(
            f"- {result['model']}: {marker} ({result['status']})"
        )
        detail = str(result.get("detail", "")).strip()
        if detail:
            lines.append(f"  detail: {detail}")
    supported = [result["model"] for result in results if result["supported"]]
    lines.append("")
    lines.append(
        "Supported models: "
        + (", ".join(supported) if supported else "none detected")
    )
    return "\n".join(lines)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test which Codex CLI models work in the current account/session."
    )
    parser.add_argument(
        "--model",
        dest="models",
        action="append",
        help="Model to test. Repeat to override the default list.",
    )
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help="Minimal prompt used for the probe.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=45,
        help="Timeout per model in seconds.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of human-readable text.",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=Path.cwd(),
        help="Working directory to use when invoking codex.",
    )
    args = parser.parse_args(argv)
    args.models = args.models or list(DEFAULT_MODELS)
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    results: List[Dict[str, object]] = []

    for model in args.models:
        print(f"Testing {model}...", file=sys.stderr)
        results.append(
            probe_model(
                model=model,
                prompt=args.prompt,
                workdir=args.workdir,
                timeout_seconds=args.timeout,
            )
        )

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(format_results(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

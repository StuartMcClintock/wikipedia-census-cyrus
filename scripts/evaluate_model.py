#!/usr/bin/env python3
"""
Run held-out eval examples through the base model and (optionally) a fine-tuned
model, score a small set of objective checks, and print a side-by-side summary.

Objective checks (per generated output):
  - non_empty:           output is non-empty
  - starts_with_heading: starts with a wiki heading marker (== or ===)
  - has_2020_subhead:    contains a "===2020 census===" subsection (case-insensitive)
  - keeps_pop_template:  reference output contained {{US Census population...}}
                         and so does the generated output
  - balanced_braces:     number of `{{` matches `}}` and `{|` matches `|}`
  - length_within_2x:    output length is within 0.5x..2x of the reference

The script saves per-example predictions + scores to a JSONL file, then prints
aggregate accuracy per check for each model. Length-sensitive judgment calls
(style, factual fidelity) are deliberately NOT auto-scored — spot-check those
manually using the saved JSONL.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DEFAULT_EVAL_PATH = Path(__file__).resolve().parents[1] / "artifacts" / "fine_tuning" / "eval.jsonl"
DEFAULT_RESULTS_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "fine_tuning" / "eval_results"
BASE_MODEL = "gpt-4.1-mini-2025-04-14"

CHECKS = [
    "non_empty",
    "starts_with_heading",
    "has_2020_subhead",
    "keeps_pop_template",
    "balanced_braces",
    "length_within_2x",
]


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


_HEADING_RE = re.compile(r"^\s*={2,3}[^=]+={2,3}", re.MULTILINE)
_2020_SUBHEAD_RE = re.compile(r"={2,3}\s*2020 census\s*={2,3}", re.IGNORECASE)
_POP_TEMPLATE_RE = re.compile(r"\{\{\s*US Census population", re.IGNORECASE)


def score_output(generated: str, reference: str) -> Dict[str, bool]:
    g = generated or ""
    r = reference or ""

    open_t = g.count("{{")
    close_t = g.count("}}")
    open_tab = len(re.findall(r"\{\|", g))
    close_tab = len(re.findall(r"\|\}", g))

    ref_len = max(1, len(r))
    return {
        "non_empty": bool(g.strip()),
        "starts_with_heading": bool(_HEADING_RE.match(g.lstrip().split("\n", 1)[0]) or g.lstrip().startswith("==")),
        "has_2020_subhead": bool(_2020_SUBHEAD_RE.search(g)),
        # Only require the template in the generated output if the reference had one.
        "keeps_pop_template": (
            (not _POP_TEMPLATE_RE.search(r)) or bool(_POP_TEMPLATE_RE.search(g))
        ),
        "balanced_braces": (abs(open_t - close_t) <= 1) and (abs(open_tab - close_tab) <= 1),
        "length_within_2x": 0.5 <= (len(g) / ref_len) <= 2.0,
    }


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------


def run_one(
    client, model: str, messages: List[Dict], max_output_tokens: int
) -> Tuple[str, Optional[str]]:
    """Return (generated_text, error_or_none)."""
    # Strip the assistant message if present — only system + user go in.
    in_messages = [m for m in messages if m.get("role") in ("system", "developer", "user")]
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=in_messages,
            temperature=0,
            max_completion_tokens=max_output_tokens,
        )
    except Exception as exc:
        return "", f"{type(exc).__name__}: {exc}"
    choice = resp.choices[0] if resp.choices else None
    text = choice.message.content if choice and choice.message else ""
    return text or "", None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def aggregate(results: List[Dict], model_key: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    n = sum(1 for r in results if model_key in r and not r[model_key].get("error"))
    if n == 0:
        return {c: 0.0 for c in CHECKS}
    for c in CHECKS:
        out[c] = sum(1 for r in results if r.get(model_key, {}).get("scores", {}).get(c)) / n
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval", dest="eval_path", type=Path, default=DEFAULT_EVAL_PATH)
    parser.add_argument("--base-model", default=BASE_MODEL)
    parser.add_argument(
        "--fine-tuned-model",
        default=None,
        help="Optional fine-tuned model id (ft:... ). Omit to evaluate the base model only.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only run the first N eval examples (smoke testing).",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.2,
        help="Seconds to sleep between API calls.",
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=3000,
        help="Cap on generated tokens per call (default: %(default)s; lowers eval cost).",
    )
    args = parser.parse_args()

    if not args.eval_path.exists():
        print(f"Eval file not found: {args.eval_path}", file=sys.stderr)
        return 1

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY is not set in the environment.", file=sys.stderr)
        return 2

    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        print("openai package not installed. Run: pip install --upgrade openai", file=sys.stderr)
        return 3

    client = OpenAI(api_key=api_key)
    args.results_dir.mkdir(parents=True, exist_ok=True)

    examples: List[Dict] = []
    with args.eval_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            examples.append(json.loads(line))
    if args.limit is not None:
        examples = examples[: args.limit]
    print(f"Loaded {len(examples)} eval examples")

    models_to_run = [("base", args.base_model)]
    if args.fine_tuned_model:
        models_to_run.append(("fine_tuned", args.fine_tuned_model))

    results: List[Dict] = []
    for index, example in enumerate(examples, start=1):
        messages = example["messages"]
        reference = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "assistant"),
            "",
        )
        record: Dict = {"index": index, "reference_length": len(reference)}
        for label, model_id in models_to_run:
            print(f"[{index}/{len(examples)}] {label} ({model_id})")
            text, err = run_one(client, model_id, messages, args.max_output_tokens)
            scored = score_output(text, reference)
            record[label] = {
                "model": model_id,
                "output": text,
                "scores": scored,
                "error": err,
            }
            if args.sleep > 0:
                time.sleep(args.sleep)
        results.append(record)

    # Persist raw results first, before printing summary.
    suffix = "_with_ft" if args.fine_tuned_model else "_base_only"
    results_path = args.results_dir / f"results{suffix}.jsonl"
    with results_path.open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    summary = {label: aggregate(results, label) for label, _ in models_to_run}

    print("\nResults summary (fraction passing each check):")
    header = f"{'check':<22}" + "".join(f"{label:>14}" for label, _ in models_to_run)
    print(header)
    print("-" * len(header))
    for c in CHECKS:
        row = f"{c:<22}" + "".join(f"{summary[label][c]:>14.2%}" for label, _ in models_to_run)
        print(row)

    print(f"\nWrote per-example results to: {results_path}")
    print("Spot-check the JSONL manually — the auto-checks catch obvious breakage but cannot judge style or factual fidelity.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

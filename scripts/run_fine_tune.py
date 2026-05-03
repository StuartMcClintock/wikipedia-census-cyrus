#!/usr/bin/env python3
"""
Upload a training file and create an OpenAI supervised fine-tuning job for
gpt-4.1-mini-2025-04-14.

Defaults to dry-run: prints exactly what it WOULD do (paths, sizes, model,
estimated tokens) without uploading anything or starting a paid job.

Pass --create-job to actually upload + create the job. The script prints the
file id and job id; use scripts/check_fine_tune.py to monitor progress.

Reads OPENAI_API_KEY from the environment.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

DEFAULT_TRAIN_PATH = Path(__file__).resolve().parents[1] / "artifacts" / "fine_tuning" / "train.jsonl"
DEFAULT_EVAL_PATH = Path(__file__).resolve().parents[1] / "artifacts" / "fine_tuning" / "eval.jsonl"
DEFAULT_MODEL = "gpt-4.1-mini-2025-04-14"


def estimate_token_count(path: Path) -> int:
    """Cheap ~4 chars/token estimate over messages content."""
    total_chars = 0
    n = 0
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            n += 1
            try:
                obj = json.loads(line)
            except Exception:
                continue
            for m in obj.get("messages", []):
                content = m.get("content", "")
                if isinstance(content, str):
                    total_chars += len(content)
    return total_chars // 4


def upload_file(client, path: Path) -> str:
    """Upload a JSONL file with purpose=fine-tune. Return file id."""
    with path.open("rb") as fh:
        result = client.files.create(file=fh, purpose="fine-tune")
    return result.id


def create_job(
    client,
    *,
    training_file_id: str,
    model: str,
    validation_file_id: Optional[str] = None,
    suffix: Optional[str] = None,
    n_epochs: Optional[int] = None,
) -> str:
    """Create the supervised fine-tune job. Returns job id."""
    hyperparameters: dict = {}
    if n_epochs is not None:
        # Set n_epochs explicitly to control training cost. Default ("auto")
        # usually picks ~3 epochs; 1 is enough for an initial sanity-check run.
        hyperparameters["n_epochs"] = n_epochs

    kwargs = {
        "training_file": training_file_id,
        "model": model,
        "method": {"type": "supervised", "supervised": {"hyperparameters": hyperparameters}},
    }
    if validation_file_id:
        kwargs["validation_file"] = validation_file_id
    if suffix:
        kwargs["suffix"] = suffix

    job = client.fine_tuning.jobs.create(**kwargs)
    return job.id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, default=DEFAULT_TRAIN_PATH)
    parser.add_argument(
        "--eval",
        dest="eval_path",
        type=Path,
        default=DEFAULT_EVAL_PATH,
        help="Optional validation file. Pass empty string to skip.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--suffix",
        default="wiki-census-iowa",
        help="Optional model name suffix for easier identification.",
    )
    parser.add_argument(
        "--create-job",
        action="store_true",
        help="Required to actually upload files and start the job (costs $).",
    )
    parser.add_argument(
        "--n-epochs",
        type=int,
        default=None,
        help="Override n_epochs (default: OpenAI auto, usually ~3). Use 1 to keep first-run cost low.",
    )
    parser.add_argument(
        "--no-validation-file",
        action="store_true",
        help="Skip uploading the eval file as a validation file (saves ~10%% on training cost; eval still runs separately via evaluate_model.py).",
    )
    args = parser.parse_args()

    if not args.train.exists():
        print(f"Train file not found: {args.train}", file=sys.stderr)
        return 1

    train_tokens = estimate_token_count(args.train)
    train_lines = sum(1 for _ in args.train.open("r", encoding="utf-8") if _.strip())

    eval_path: Optional[Path] = args.eval_path if (args.eval_path and str(args.eval_path)) else None
    if args.no_validation_file:
        eval_path = None
    eval_lines = 0
    eval_tokens = 0
    if eval_path and eval_path.exists():
        eval_tokens = estimate_token_count(eval_path)
        eval_lines = sum(1 for _ in eval_path.open("r", encoding="utf-8") if _.strip())
    elif eval_path:
        print(f"WARN: eval file not found: {eval_path} — proceeding without validation file.")
        eval_path = None

    print("Fine-tune job plan")
    print(f"  model:           {args.model}")
    print(f"  suffix:          {args.suffix}")
    print(f"  train file:      {args.train}")
    print(f"  train examples:  {train_lines}")
    print(f"  train tokens:    ~{train_tokens:,} (estimate; OpenAI bills exact)")
    if eval_path:
        print(f"  eval file:       {eval_path}")
        print(f"  eval examples:   {eval_lines}")
        print(f"  eval tokens:     ~{eval_tokens:,}")
    else:
        print(f"  eval file:       (none)")
    if args.n_epochs is not None:
        print(f"  n_epochs:        {args.n_epochs} (override)")
    else:
        print(f"  n_epochs:        auto (OpenAI defaults)")

    if not args.create_job:
        print("\nDRY RUN — no files uploaded, no job created.")
        print("Re-run with --create-job to upload and start fine-tuning.")
        return 0

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY is not set in the environment.", file=sys.stderr)
        return 2

    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        print(
            "openai package not installed. Run: pip install --upgrade openai",
            file=sys.stderr,
        )
        return 3

    client = OpenAI(api_key=api_key)

    print("\nUploading training file...")
    train_file_id = upload_file(client, args.train)
    print(f"  training_file_id: {train_file_id}")

    validation_file_id = None
    if eval_path:
        print("Uploading validation file...")
        validation_file_id = upload_file(client, eval_path)
        print(f"  validation_file_id: {validation_file_id}")

    print("Creating fine-tuning job...")
    job_id = create_job(
        client,
        training_file_id=train_file_id,
        model=args.model,
        validation_file_id=validation_file_id,
        suffix=args.suffix,
        n_epochs=args.n_epochs,
    )
    print(f"  job_id: {job_id}")

    print(
        "\nNext steps:\n"
        f"  python scripts/check_fine_tune.py {job_id}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

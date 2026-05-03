#!/usr/bin/env python3
"""
Standalone validator for OpenAI chat fine-tuning JSONL files.

Run on train.jsonl and (optionally) eval.jsonl to confirm:
  - every line is valid JSON
  - no blank lines
  - each object has a `messages` list
  - roles are valid (system/developer/user/assistant)
  - the final message is an assistant message
  - each example has at least one user message and non-empty content
  - there are at least 10 training examples
  - no exact-duplicate examples within a file
  - no train/eval overlap (when both files are passed)

Exits non-zero if any check fails.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

VALID_ROLES = {"system", "developer", "user", "assistant"}
MIN_TRAIN_EXAMPLES = 10


def hash_messages(messages: List[Dict]) -> str:
    return hashlib.sha256(
        json.dumps(messages, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def validate_file(path: Path, *, require_min: bool) -> Tuple[List[str], Set[str]]:
    """Return (errors, set_of_message_hashes)."""
    errors: List[str] = []
    hashes: Set[str] = set()
    seen_hashes: Set[str] = set()
    n = 0

    if not path.exists():
        errors.append(f"{path}: file does not exist")
        return errors, hashes

    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            if raw == "\n" or raw.strip() == "":
                errors.append(f"{path}:{line_no}: blank line not allowed")
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                errors.append(f"{path}:{line_no}: invalid JSON ({exc})")
                continue

            n += 1
            messages = obj.get("messages")
            if not isinstance(messages, list) or len(messages) < 2:
                errors.append(f"{path}:{line_no}: missing or short messages list")
                continue

            roles = [m.get("role") for m in messages]
            bad_roles = [r for r in roles if r not in VALID_ROLES]
            if bad_roles:
                errors.append(f"{path}:{line_no}: invalid roles {bad_roles}")
                continue
            if messages[-1].get("role") != "assistant":
                errors.append(f"{path}:{line_no}: last message role must be assistant")
                continue
            if not any(m.get("role") == "user" for m in messages):
                errors.append(f"{path}:{line_no}: no user message present")
                continue

            empty = [
                m.get("role") for m in messages
                if not isinstance(m.get("content"), str) or not m.get("content").strip()
            ]
            if empty:
                errors.append(f"{path}:{line_no}: empty content in roles {empty}")
                continue

            h = hash_messages(messages)
            if h in seen_hashes:
                errors.append(f"{path}:{line_no}: duplicate of an earlier example in same file")
                continue
            seen_hashes.add(h)
            hashes.add(h)

    if require_min and n < MIN_TRAIN_EXAMPLES:
        errors.append(
            f"{path}: only {n} examples (OpenAI requires >= {MIN_TRAIN_EXAMPLES} for fine-tuning)"
        )

    return errors, hashes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--eval", dest="eval_path", type=Path, default=None)
    args = parser.parse_args()

    all_errors: List[str] = []
    train_errors, train_hashes = validate_file(args.train, require_min=True)
    all_errors.extend(train_errors)

    eval_hashes: Set[str] = set()
    if args.eval_path is not None:
        eval_errors, eval_hashes = validate_file(args.eval_path, require_min=False)
        all_errors.extend(eval_errors)

        overlap = train_hashes & eval_hashes
        if overlap:
            all_errors.append(
                f"train/eval leakage: {len(overlap)} examples appear in both files"
            )

    if all_errors:
        print("VALIDATION FAILED:", file=sys.stderr)
        for e in all_errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"OK  train: {len(train_hashes)} examples")
    if args.eval_path is not None:
        print(f"OK  eval:  {len(eval_hashes)} examples (no overlap with train)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

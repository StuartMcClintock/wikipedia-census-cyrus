#!/usr/bin/env python3
"""
Look up the status of an OpenAI fine-tuning job.

Usage:
  python scripts/check_fine_tune.py ftjob-XXXXXXXXXXXXXXXX

Prints:
  - current job status (queued / running / succeeded / failed / cancelled)
  - the fine-tuned model id once the job has succeeded
  - the most recent fine-tune events (training metrics, errors)
"""

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id", help="Fine-tuning job id (e.g. ftjob-...)")
    parser.add_argument(
        "--events",
        type=int,
        default=10,
        help="Number of recent events to print (default: %(default)s).",
    )
    args = parser.parse_args()

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

    job = client.fine_tuning.jobs.retrieve(args.job_id)
    print(f"job id:            {job.id}")
    print(f"status:            {job.status}")
    print(f"model:             {job.model}")
    print(f"training file:     {job.training_file}")
    if getattr(job, "validation_file", None):
        print(f"validation file:   {job.validation_file}")
    if getattr(job, "trained_tokens", None):
        print(f"trained tokens:    {job.trained_tokens:,}")
    if getattr(job, "fine_tuned_model", None):
        print(f"fine-tuned model:  {job.fine_tuned_model}")
    elif job.status not in ("succeeded",):
        print(f"fine-tuned model:  (not yet available; status={job.status})")

    events = client.fine_tuning.jobs.list_events(args.job_id, limit=args.events)
    print(f"\nLast {args.events} events:")
    # The events list is newest-first; reverse so the printout reads chronologically.
    for ev in reversed(list(events.data)):
        ts = getattr(ev, "created_at", "?")
        level = getattr(ev, "level", "info")
        msg = getattr(ev, "message", "")
        print(f"  [{ts}] {level}: {msg}")

    if job.status == "succeeded" and getattr(job, "fine_tuned_model", None):
        print(
            "\nReady to evaluate:\n"
            f"  python scripts/evaluate_model.py --fine-tuned-model {job.fine_tuned_model}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

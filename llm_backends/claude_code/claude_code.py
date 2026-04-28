import os
import re
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pytz

BASE_DIR = Path(__file__).resolve().parent
RUN_ARTIFACT_DIR_ENV = "LLM_RUN_ARTIFACT_DIR"
_RUNS_DIR = BASE_DIR / ".runs"
_DEFAULT_RUN_TOKEN = f"run-{os.getpid()}-{int(time.time() * 1000)}"
DEFAULT_CLAUDE_CODE_MODEL = "claude-opus-4-7"
CLAUDE_CODE_WAIT_FOR_LIMIT_RESET_ENV = "CLAUDE_CODE_WAIT_FOR_LIMIT_RESET"
USAGE_LIMIT_MARKERS = (
    "you've hit your limit",
    "you’ve hit your limit",
    "usage limit reached",
    "rate limit exceeded",
    "you have exceeded",
)
LIMIT_RESET_PATTERN = re.compile(
    r"you['’]?ve hit your limit.*?resets\s+(\d{1,2}(?::\d{2})?\s*[ap]m)\s*\(([^)]+)\)",
    re.IGNORECASE | re.DOTALL,
)


class ClaudeCodeUsageLimitError(Exception):
    """Raised when the Claude Code CLI reports a usage limit error."""

    def __init__(
        self,
        message: str,
        retry_at: Optional[datetime] = None,
        cli_output: Optional[str] = None,
    ):
        super().__init__(message)
        self.retry_at = retry_at
        self.cli_output = cli_output


def _get_run_work_dir() -> Path:
    override = os.getenv(RUN_ARTIFACT_DIR_ENV)
    if override:
        path = Path(override).expanduser()
    else:
        path = _RUNS_DIR / _DEFAULT_RUN_TOKEN
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_snapshot(filename: str, content: str) -> None:
    """Persist content for inspection/debugging and so the CLI can Read it."""
    (_get_run_work_dir() / filename).write_text(content)


def _resolve_model() -> str:
    active = os.getenv("ACTIVE_MODEL", "")
    if active == "haiku":
        return active
    if active.startswith("claude-") and "haiku-4-5" not in active:
        return active
    env_model = os.getenv("CLAUDE_CODE_MODEL")
    if env_model:
        return env_model
    return DEFAULT_CLAUDE_CODE_MODEL


def _auto_wait_for_limit_reset_enabled() -> bool:
    return os.getenv(CLAUDE_CODE_WAIT_FOR_LIMIT_RESET_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _now_in_zone(tz) -> datetime:
    return datetime.now(tz)


def _extract_limit_reset_retry_at(
    output: str, now: Optional[datetime] = None
) -> Optional[datetime]:
    match = LIMIT_RESET_PATTERN.search(output)
    if not match:
        return None
    time_text, timezone_name = match.groups()
    try:
        timezone = pytz.timezone(timezone_name.strip())
    except pytz.UnknownTimeZoneError:
        return None

    normalized = re.sub(r"\s+", "", time_text).upper()
    fmt = "%I:%M%p" if ":" in normalized else "%I%p"
    reset_time = datetime.strptime(normalized, fmt).time()

    if now is None:
        now_in_zone = _now_in_zone(timezone)
    elif now.tzinfo is None:
        now_in_zone = timezone.localize(now)
    else:
        now_in_zone = now.astimezone(timezone)

    retry_at = now_in_zone.replace(
        hour=reset_time.hour,
        minute=reset_time.minute,
        second=0,
        microsecond=0,
    )
    if retry_at <= now_in_zone:
        retry_at += timedelta(days=1)
    retry_at = timezone.normalize(retry_at)
    return timezone.normalize(retry_at + timedelta(minutes=1))


def _build_usage_limit_error(
    stdout: str, stderr: str
) -> Optional[ClaudeCodeUsageLimitError]:
    combined = "\n".join(part for part in (stdout, stderr) if part)
    lowered = combined.lower()
    retry_at = _extract_limit_reset_retry_at(combined)
    for marker in USAGE_LIMIT_MARKERS:
        if marker in lowered:
            normalized_output = combined.strip()
            if not normalized_output:
                normalized_output = marker
            detail = normalized_output
            if retry_at:
                detail = (
                    f"{normalized_output}\nParsed retry time: {retry_at.isoformat()}"
                )
            return ClaudeCodeUsageLimitError(
                f"Claude Code usage limit reported by CLI:\n{detail}",
                retry_at=retry_at,
                cli_output=normalized_output,
            )
    return None


def _sleep_until(retry_at: datetime) -> None:
    now = _now_in_zone(retry_at.tzinfo)
    wait_seconds = max(0.0, (retry_at - now).total_seconds())
    retry_label = retry_at.strftime("%Y-%m-%d %I:%M%p %Z")
    print(
        f"Claude Code usage limit hit; waiting until {retry_label} before retrying."
    )
    time.sleep(wait_seconds)


def claude_exec(prompt: str, suppress_out: bool = True) -> str:
    model = _resolve_model()
    cmd = [
        "claude",
        "-p", prompt,
        "--model", model,
        "--permission-mode", "bypassPermissions",
    ]
    while True:
        result = subprocess.run(
            cmd,
            cwd=_get_run_work_dir(),
            capture_output=True,
            text=True,
        )
        usage_limit_error = _build_usage_limit_error(
            result.stdout or "", result.stderr or ""
        )
        if usage_limit_error:
            if (
                _auto_wait_for_limit_reset_enabled()
                and usage_limit_error.retry_at is not None
            ):
                _sleep_until(usage_limit_error.retry_at)
                continue
            raise usage_limit_error
        if result.returncode != 0:
            raise RuntimeError(
                f"claude -p failed (model={model}, rc={result.returncode}): "
                f"{result.stderr or result.stdout}"
            )
        if not suppress_out and result.stderr:
            print(result.stderr)
        return (result.stdout or "").strip()


def check_if_update_needed(current_article: str, new_text: str, suppress_out: bool = True) -> bool:
    _write_snapshot("full_current_wp_page.txt", current_article)
    _write_snapshot("new_text.txt", new_text)
    response = claude_exec(
        """
Read full_current_wp_page.txt and new_text.txt from the current working directory.

full_current_wp_page.txt contains the current text for the Wikipedia page for a county or municipality in the United States.

new_text.txt contains proposed new text that I am considering to add to the Wikipedia page. It is composed entirely of data from the 2020 US Census.

Does new_text.txt contain any information that is not already contained in full_current_wp_page.txt? If so, print exactly "YES" as your final output; otherwise print exactly "NO". Print nothing else.

Be sure to not confuse the decade that a particular census fact is from; if there is already data for a field from 2010, the 2020 data for that field is considered different.
""",
        suppress_out=suppress_out,
    )
    return response.strip() == "YES"


def update_wp_page(current_article: str, new_text: str, suppress_out: bool = True) -> str:
    _write_snapshot("full_current_wp_page.txt", current_article)
    _write_snapshot("new_text.txt", new_text)
    return claude_exec(
        """
Read full_current_wp_page.txt and new_text.txt from the current working directory.

full_current_wp_page.txt contains the current text for the Wikipedia page for a county or municipality in the United States.

new_text.txt contains proposed new text that I am going to add to the Wikipedia page. It is composed entirely of data from the 2020 US Census.

Modify the existing Wikipedia page to contain the new section. Make sure it is placed within an appropriate place in the article. If there is not currently a demographics H2 section header you should add one if there is not already a logical place to put the new data.

If the existing article contains any 2020 Census information that is not contained in the new text that I am inserting, insert those sentences into the new text in a logical location.

Make sure that redundant information is removed. If needed, rearrange sentences containing existing demographic information so that it is grouped with related sentences in a logically flowing manner. If it is necessary and it is possible to do without creating confusion or making the article messy, put another H3 header below the new ===2020 census=== section in order to clearly mark where the 2020 census stops. The new header should meaningfully describe the content that comes below it in a way that is consistent with established section-naming precedent in Wikipedia.

DO NOT MODIFY THE FACTUAL CONTENT OF THE ARTICLE beyond simply inserting the given 2020 census section. Besides that you should only be reorganizing sentences/paragraphs and potentially deleting redundant facts.

Be sure to not confuse the decade that a particular census fact is from; if there is already data for a field from 2010, the 2020 data for that field is considered different.

If an article has a 2020 "Vintage" or other pre-census estimate for a specific datapoint, remove that estimate (and its citation) when you also insert an official 2020 decennial census value for the same datapoint; if no official 2020 census replacement exists for that datapoint, leave the estimate as is.

If there are existing chunks of information for the 2000 or 2010 censuses that don't have a H3 header, you should put them under a "2000 census" or "2010 census" header. Any census data that does not come from decennial census results should be labeled "[year] estimates" (eg. "2021 estimates") rather than "census".

If you reformat old census data (from 2000 or 2010), prefer the format "As of the [[2000 United States census|2000 census]]" over the format "As of the [[census]] of 2000" or "As of the 2000 [[census]]". Modify this part of the existing content if necessary but do not modify actual factual information.

Make sure that headings in the Demographics section are in chronological order ("2020 census" should come above "2010 census"; if there is a "2021 estimates" section is should come above "2020 census")

Output only the full text of the updated article as your final response. Do not include commentary, code fences, or any text that should not be in the updated article.
""",
        suppress_out=suppress_out,
    )


def update_demographics_section(
    current_demographics_section: str, new_text: str, mini: bool = True, suppress_out: bool = True
) -> str:
    PROMPT = """
Read current_demographics_section.txt and new_text.txt from the current working directory.

current_demographics_section.txt contains the current text for the demographics section of a Wikipedia article for a county or municipality in the United States.

new_text.txt contains proposed new text you must add to this demographics section. It is composed entirely of data from the 2020 US Census.

If the existing demographics section contains any 2020 Census information that is missing from the new text, insert those sentences into the new text in a logical location. Remove redundant information so each datapoint is stated once.

If an article has a pre-2020 estimate for a specific datapoint and the new text includes the official 2020 decennial value for that same datapoint, remove the estimate and any associated references so only the official 2020 figure remains. If there is no official 2020 replacement for that datapoint, leave the estimate untouched.

Prefer the phrasing "As of the [[2020 United States census|2020 census]]" when referencing official census counts. Ensure every new or modified sentence retains or adds appropriate references.

If a 2020 race table already exists, do not append another one.

If there is a banner in the existing wikitext indicating that demographic/census data is out of date, remove it.

If you modify any tags like </small> or <br>, make sure the outcome is valid (eg. "</small)" is not okay)

You do not need to delete data that does not come from a decennial census as long as it is appropriately cited - but make sure it has an appropriately descriptive H3 header.

DO NOT remove any data or sources from the "US Census population" table. The "US Census population" table should remain as it starts.

DO NOT rename "==Demographics==" or delete the "US Census population" table.

Be careful not to remove any existing sections like "===Religion===" unless you are moving all relevant content elsewhere. THIS IS IMPORTANT, DO NOT JUST DELETE "===Religion===" blocks!

If there is a wikitable on racial/ethnic composition across multiple decades, put it in it's own "===Racial and ethnic composition===" section. Don't generate any new text that explains/describes the table

If you mix with existing content, do not remove the references for the existing data.

If there is a table on race/ethnicity that contains up-to-date 2020 census information, DO NOT DELETE IT!

If there is 2010 or 2000 census data that doesn't have an appropriate H3 heading above it, add "===2010 census===" or "===2000 census===" above it respectively

Be careful to avoid creating wording like "As of the 2000 census of 2000".

Be VERY careful to not delete a "</ref>" tag unless you are sure it will not break a ref. This is important!

If a wikitable ends with "|}", don't remove the "|" and cause it to simply be "}". In general, make sure wikitables are closed properly.

The content of the 2020 census section should be split into topically coherent paragraphs, NOT SMASHED INTO A SINGLE LARGE PARAGRAPH!

Ensure that adequate citation refs from the three census api refs (DP, PL, DHC) are added to backup all the factual claims made in a particular paragraph.

If there is a "Racial and ethnic composition" subsection, put it as the top subsection of the Demographics, below only the lede text. Do not generate new text to add to the lede, you may only modify or reposition existing text

Be careful not to remove query parameters from the census url (eg "?get="), we want to ensure that the url is usable as a source citation. THIS IS IMPORTANT, DO NOT REMOVE QUERY PARAMETERS FROM CENSUS URLS

Tables or paragraphs on racial data for only 2020 or any other specific decade should be in their respective "20xx census" subsection, not the "Racial and ethnic composition" subsection

Put new 2020 census data within "===2020 census===", DO NOT put it in the lede of the demographics section

Output only the updated demographics and related census sections as your final response. Do not include commentary, code fences, or any explanation.
"""
    _write_snapshot("current_demographics_section.txt", current_demographics_section)
    _write_snapshot("new_text.txt", new_text)
    return claude_exec(PROMPT, suppress_out=suppress_out) + "\n"


def update_lede(current_lede_text: str, population_sentence: str, suppress_out: bool = True) -> str:
    prompt = """
Read current_lede_text.txt and population_sentence.txt from the current working directory.

current_lede_text.txt contains the current lede/intro wikitext of a Wikipedia municipality article.

population_sentence.txt contains a single sentence that includes the 2020 census population and a citation.

Integrate the population sentence into the lede so it reads naturally, preserving existing facts and citations.
Do not add or remove headings, and do not add any new facts beyond the population sentence.
If the lede already clearly states the 2020 population, keep it and avoid duplication.

Output only the updated lede text as your final response (no commentary, no code fences).
"""
    _write_snapshot("current_lede_text.txt", current_lede_text)
    _write_snapshot("population_sentence.txt", population_sentence)
    return claude_exec(prompt, suppress_out=suppress_out)

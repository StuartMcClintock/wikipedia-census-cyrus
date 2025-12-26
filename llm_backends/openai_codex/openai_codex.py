#from credentials import OPEN_AI_KEY
import subprocess
import os
from pathlib import Path
from typing import Optional, List, Tuple
from constants import DEFAULT_CODEX_MODEL, codex_models

BASE_DIR = Path(__file__).resolve().parent
CANDIDATE_OUT_PATHS = [BASE_DIR / "codex_out" / "out.txt"]
MIN_NODE_MAJOR = 18


class CodexOutputMissingError(FileNotFoundError):
    """Raised when codex_out/out.txt cannot be located after a Codex run."""
    pass


def _write_snapshot(filename: str, content: str) -> None:
    """Persist content for inspection/debugging."""
    (BASE_DIR / filename).write_text(content)


def _read_codex_output() -> str:
    path = _locate_codex_output(require_nonempty=True)
    if path:
        return path.read_text()
    candidates = ", ".join(str(p) for p in CANDIDATE_OUT_PATHS)
    raise CodexOutputMissingError(
        f"codex_out/out.txt not found in any known location (checked: {candidates})"
    )


def _resolve_model() -> str:
    """
    Return the requested Codex model, falling back to the default if the active
    model is not an OpenAI Codex model (e.g., a Claude model).
    """
    active = os.getenv("ACTIVE_MODEL")
    if active in codex_models:
        return active
    codex_env = os.getenv("CODEX_MODEL")
    if codex_env in codex_models:
        return codex_env
    return DEFAULT_CODEX_MODEL


def _clear_codex_output() -> None:
    """
    Remove any existing Codex output so a failed run cannot reuse stale data.
    """
    for path in CANDIDATE_OUT_PATHS:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                path.unlink()
        except Exception:
            continue


def _locate_codex_output(require_nonempty: bool = False) -> Optional[Path]:
    """Return the first existing codex_out file, or None if missing."""
    for path in CANDIDATE_OUT_PATHS:
        if not path.exists():
            continue
        if require_nonempty and path.stat().st_size == 0:
            continue
        return path
    return None


def _ensure_codex_out_placeholder() -> Path:
    """
    Create an empty codex_out/out.txt placeholder to unblock a retry attempt.
    """
    target = CANDIDATE_OUT_PATHS[0]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("")
    return target


def _find_node_bin_dir(min_major: int = MIN_NODE_MAJOR) -> Optional[Path]:
    """
    Prefer a modern Node version (>= min_major) so the Codex CLI ESM entrypoint
    does not get executed by an old default nvm version.
    """
    override = os.getenv("CODEX_NODE_BIN")
    if override:
        override_path = Path(override).expanduser()
        if override_path.is_file():
            return override_path.parent
        if (override_path / "node").is_file():
            return override_path

    nvm_root = Path.home() / ".nvm" / "versions" / "node"
    if nvm_root.is_dir():
        versions: List[Tuple[int, Path]] = []
        for version_dir in nvm_root.iterdir():
            node_path = version_dir / "bin" / "node"
            if not node_path.is_file():
                continue
            try:
                major = int(version_dir.name.lstrip("v").split(".")[0])
            except (ValueError, IndexError):
                continue
            versions.append((major, node_path.parent))
        sorted_versions = sorted(versions, key=lambda item: item[0], reverse=True)
        for major, bin_dir in sorted_versions:
            if major >= min_major:
                return bin_dir
        if sorted_versions:
            return sorted_versions[0][1]
    return None


def _build_codex_env() -> dict:
    env = os.environ.copy()
    node_bin_dir = _find_node_bin_dir()
    if node_bin_dir:
        env["PATH"] = f"{node_bin_dir}{os.pathsep}{env.get('PATH', '')}"
    return env


def codex_exec(text: str, suppress_out=True) -> None:
    # Check ACTIVE_MODEL first (new architecture), fall back to CODEX_MODEL (backward compatibility)
    model = _resolve_model()
    cmd = ["codex", "exec", "-m", model]
    cmd.append(text)
    attempt_details = []
    _clear_codex_output()
    for attempt in (1, 2):
        result = subprocess.run(
            cmd,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            env=_build_codex_env(),
        )
        attempt_details.append(
            f"attempt {attempt} stdout: {result.stdout.strip() if result.stdout else '<empty>'}; "
            f"stderr: {result.stderr.strip() if result.stderr else '<empty>'}"
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"codex exec failed (model={model}, rc={result.returncode}): {result.stderr or result.stdout}"
            )
        if _locate_codex_output(require_nonempty=True):
            break
        if attempt == 1:
            _ensure_codex_out_placeholder()
            continue
        candidates = ", ".join(str(p) for p in CANDIDATE_OUT_PATHS)
        raise CodexOutputMissingError(
            f"codex exec succeeded but codex_out/out.txt is missing or empty after 2 attempts "
            f"(checked: {candidates}; {attempt_details[0]} | {attempt_details[1]})"
        )
    if not suppress_out:
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)


def check_if_update_needed(current_article: str, new_text: str, suppress_out: bool = True) -> bool:
    _write_snapshot("full_current_wp_page.txt", current_article)
    _write_snapshot("new_text.txt", new_text)
    codex_exec(
        """
full_current_wp_page.txt contains the current text for the Wikipedia page for a county or municipality in the United States.

new_text.txt contains proposed new text that I am considering to add to the Wikipedia page. It is composed entirely of data from the 2020 US Census.

Does new_text.txt contain any information that is not already contained in full_current_wp_page.txt? If so, write "YES" to codex_out/out.txt; otherwise write "NO" to the same file.

Be sure to not confuse the decade that a particular census fact is from; if there is already data for a field from 2010, the 2020 data for that field is considered different.
"""
    , suppress_out=suppress_out)
    try:
        return _read_codex_output().strip() == "YES"
    except FileNotFoundError:
        return False


def update_wp_page(current_article: str, new_text: str, suppress_out: bool = True) -> str:
    _write_snapshot("full_current_wp_page.txt", current_article)
    _write_snapshot("new_text.txt", new_text)
    codex_exec(
        """
full_current_wp_page.txt contains the current text for the Wikipedia page for a county or municipality in the United States.

new_text.txt contains proposed new text that I am going to add to the Wikipedia page. It is composed entirely of data from the 2020 US Census.

Modify the existing Wikipedia page to contain the new section. Make sure it is placed within an appropriate place in the article. If there is not currently a demographics H2 section header you should add one if there is not already a logical place to put the new data.

If the existing article contains any 2020 Census information that is not contained in the new text that I am inserting, insert those sentences into the new text in a logical location.

Make sure that redundant information is removed. If needed, rearrange sentences containing existing demographic information so that it is grouped with related sentences in a logically flowing manner. If it is necessary and it is possible to do without creating confusion or making the article messy, put another H3 header below the new ===2020 census=== section in order to clearly mark where the 2020 census stops. The new header should meaningfully describe the content that comes below it in a way that is consistent with established section-naming precedent in Wikipedia.

DO NOT MODIFY THE FACTUAL CONTENT OF THE ARTICLE beyond simply inserting the given 2020 census section. Besides that you should only be reorganizing sentences/paragraphs and potentially deleting redundant facts.

Be sure to not confuse the decade that a particular census fact is from; if there is already data for a field from 2010, the 2020 data for that field is considered different.

If an article has a 2020 “Vintage” or other pre-census estimate for a specific datapoint, remove that estimate (and its citation) when you also insert an official 2020 decennial census value for the same datapoint; if no official 2020 census replacement exists for that datapoint, leave the estimate as is.

If there are existing chunks of information for the 2000 or 2010 censuses that don't have a H3 header, you should put them under a "2000 census" or "2010 census" header. Any census data that does not come from decennial census results should be labeled "[year] estimates" (eg. "2021 estimates") rather than "census".

If you reformat old census data (from 2000 or 2010), prefer the format "As of the [[2000 United States census|2000 census]]" over the format "As of the [[census]] of 2000" or "As of the 2000 [[census]]". Modify this part of the existing content if necessary but do not modify actual factual information.

Make sure that headings in the Demographics section are in chronological order ("2020 census" should come above "2010 census"; if there is a "2021 estimates" section is should come above "2020 census")

Write the output to codex_out/out.txt. The output should contain the full text of the updated article and nothing that should not be in the updated article.
"""
    , suppress_out=suppress_out)
    return _read_codex_output()


def update_demographics_section(
    current_demographics_section: str, new_text: str, mini=True, suppress_out: bool = True
) -> str:
    MAX_PROMPT = """
current_demographics_section.txt contains the current text for the demographics section of a Wikipedia article for a county or municipality in the United States.

new_text.txt contains proposed new text you must add to this demographics section. It is composed entirely of data from the 2020 US Census.

If the existing demographics section contains any 2020 Census information that is missing from the new text, insert those sentences into the new text in a logical location. Remove redundant information so each datapoint is stated once. If needed, reorganize or reheader census-era content (e.g., add ===2000 census=== or ===2010 census===) so the chronology is clear, but do not alter the factual content of older census sections.

If an article has a pre-2020 estimate for a specific datapoint and the new text includes the official 2020 decennial value for that same datapoint, remove the estimate and any associated references so only the official 2020 figure remains. If there is no official 2020 replacement for that datapoint, leave the estimate untouched.

Prefer the phrasing "As of the [[2020 United States census|2020 census]]" when referencing official census counts. Ensure every new or modified sentence retains or adds appropriate references.

Make sure that headings in the Demographics section are in chronological order ("2020 census" should come above "2010 census"; if there is a "2021 estimates" section is should come above "2020 census")

If you mix with existing content, do not remove the references for the existing data.

If an article has a 2020 “Vintage” or other pre-census estimate for a specific datapoint, remove that estimate (and its citation) when you also insert an official 2020 decennial census value for the same datapoint; if no official 2020 census replacement exists for that datapoint, leave the estimate as is.

Write only the updated demographics and related census sections to codex_out/out.txt (no commentary).
"""
    MINI_PROMPT = """
current_demographics_section.txt contains the current text for the demographics section of a Wikipedia article for a county or municipality in the United States.

new_text.txt contains proposed new text you must add to this demographics section. It is composed entirely of data from the 2020 US Census.

If the existing demographics section contains any 2020 Census information that is missing from the new text, insert those sentences into the new text in a logical location. Remove redundant information so each datapoint is stated once.

If an article has a pre-2020 estimate for a specific datapoint and the new text includes the official 2020 decennial value for that same datapoint, remove the estimate and any associated references so only the official 2020 figure remains. If there is no official 2020 replacement for that datapoint, leave the estimate untouched.

Prefer the phrasing "As of the [[2020 United States census|2020 census]]" when referencing official census counts. Ensure every new or modified sentence retains or adds appropriate references.

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

If a wikitable ends with "|}", don't remove the "|" and cause it to simply be "}"

The content of the 2020 census section should be split into topically coherent paragraphs, NOT SMASHED INTO A SINGLE LARGE PARAGRAPH!

Ensure that adequate citation refs from the three census api refs (DP, PL, DHC) are added to backup all the factual claims made in a particular paragraph. 

Write only the updated demographics and related census sections to codex_out/out.txt (no commentary).
"""
    prompt = MINI_PROMPT if mini else MAX_PROMPT

    _write_snapshot("current_demographics_section.txt", current_demographics_section)
    _write_snapshot("new_text.txt", new_text)
    codex_exec(prompt, suppress_out=suppress_out)
    return _read_codex_output()

if __name__ == '__main__':
    codex_exec("add a file within openai_codex called 'new_text.txt'")

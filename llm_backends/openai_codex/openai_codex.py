#from credentials import OPEN_AI_KEY
import subprocess
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CANDIDATE_OUT_PATHS = [BASE_DIR / "codex_out" / "out.txt"]
DEFAULT_CODEX_MODEL = "gpt-5.1-codex-max"


def _write_snapshot(filename: str, content: str) -> None:
    """Persist content for inspection/debugging."""
    (BASE_DIR / filename).write_text(content)


def _read_codex_output() -> str:
    for path in CANDIDATE_OUT_PATHS:
        if path.exists():
            return path.read_text()
    raise FileNotFoundError("codex_out/out.txt not found in any known location")


def codex_exec(text: str, suppress_out=True) -> None:
    model = os.getenv("CODEX_MODEL", DEFAULT_CODEX_MODEL)
    cmd = ["codex", "exec", "-m", model]
    cmd.append(text)
    if suppress_out:
        subprocess.run(
            cmd,
            cwd=BASE_DIR,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        subprocess.run(cmd, cwd=BASE_DIR, check=True)


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

Do not remove any data or sources from the "US Census population" table.

DO NOT rename "==Demographics==" or delete the "US Census population" table.

If you mix with existing content, do not remove the references for the existing data.

If there is a table on race/ethnicity that contains up-to-date 2020 census information, DO NOT DELETE IT!

If there is 2010 or 2000 census data that doesn't have an appropriate H3 heading above it, add "===2010 census===" or "===2000 census===" above it respectively

When you insert the new text, please make sure the original tags that give the actual api source are not dropped. DO NOT USE <ref name="Census2020DP"/> OR <ref name="Census2020PL"/> WITHOUT ACTUALLY DEFINING IT FIRST!!

BEFORE SAYING THAT THE TASK IS COMPLETE, PLEASE VALIDATE THAT THE ABOVE REFERENCE CHECK IS VALID. This is needed to avoid this type of error: "Cite error: The named reference Census2020DP was invoked but never defined"

Write only the updated demographics and related census sections to codex_out/out.txt (no commentary).
"""
    prompt = MINI_PROMPT if mini else MAX_PROMPT

    _write_snapshot("current_demographics_section.txt", current_demographics_section)
    _write_snapshot("new_text.txt", new_text)
    codex_exec(prompt, suppress_out=suppress_out)
    return _read_codex_output()

if __name__ == '__main__':
    codex_exec("add a file within openai_codex called 'new_text.txt'")

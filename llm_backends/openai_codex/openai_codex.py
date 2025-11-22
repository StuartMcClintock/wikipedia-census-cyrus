#from credentials import OPEN_AI_KEY
from os import system
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CANDIDATE_OUT_PATHS = [BASE_DIR / "codex_out" / "out.txt"]


def _write_snapshot(filename: str, content: str) -> None:
    """Persist content for inspection/debugging."""
    (BASE_DIR / filename).write_text(content)


def _read_codex_output() -> str:
    for path in CANDIDATE_OUT_PATHS:
        if path.exists():
            return path.read_text()
    raise FileNotFoundError("codex_out/out.txt not found in any known location")


def codex_exec(text: str) -> None:
    system('codex exec "' + text + '"')


def check_if_update_needed(current_article: str, new_text: str) -> bool:
    _write_snapshot("full_current_wp_page.txt", current_article)
    _write_snapshot("new_text.txt", new_text)
    codex_exec(
        """
full_current_wp_page.txt contains the current text for the Wikipedia page for a county or municipality in the United States.

new_text.txt contains proposed new text that I am considering to add to the Wikipedia page. It is composed entirely of data from the 2020 US Census.

Does new_text.txt contain any information that is not already contained in full_current_wp_page.txt? If so, write "YES" to codex_out/out.txt; otherwise write "NO" to the same file.

Be sure to not confuse the decade that a particular census fact is from; if there is already data for a field from 2010, the 2020 data for that field is considered different.
"""
    )
    try:
        return _read_codex_output().strip() == "YES"
    except FileNotFoundError:
        return False


def update_wp_page(current_article: str, new_text: str) -> str:
    _write_snapshot("full_current_wp_page.txt", current_article)
    _write_snapshot("new_text.txt", new_text)
    codex_exec(
        """
full_current_wp_page.txt contains the current text for the Wikipedia page for a county or municipality in the United States.

new_text.txt contains proposed new text that I am going to add to the Wikipedia page. It is composed entirely of data from the 2020 US Census.

Modify the existing Wikipedia page to contain the new section. Make sure it is placed within an appropriate place in the article. If there is not currently a demographics H2 section header you may want to add one if there is not already a logical place to put the new data.

If the existing article contains any 2020 Census information that is not contained in the new text that I am inserting, insert those sentences into the new text in a logical location.

Make sure that redundant information is removed. If needed, rearrange sentences containing existing demographic information so that it is grouped with related sentences in a logically flowing manner. If it is necessary and it is possible to do without creating confusion or making the article messy, put another H3 header below the new ===2020 census=== section in order to clearly mark where the 2020 census stops. The new header should meaningfully describe the content that comes below it in a way that is consistent with established section-naming precedent in Wikipedia.

DO NOT MODIFY THE FACTUAL CONTENT OF THE ARTICLE beyond simply inserting the given 2020 census section. Besides that you should only be reorganizing sentences/paragraphs and potentially deleting redundant facts.

Write the output to codex_out/out.txt. The output should contain the full text of the updated article and nothing that should not be in the updated article.

Be sure to not confuse the decade that a particular census fact is from; if there is already data for a field from 2010, the 2020 data for that field is considered different.
"""
    )
    return _read_codex_output()

if __name__ == '__main__':
    codex_exec("add a file within openai_codex called 'new_text.txt'")

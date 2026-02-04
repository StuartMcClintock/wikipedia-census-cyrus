from typing import Optional
import os

from openai import OpenAI
from credentials import OPEN_AI_KEY

MODEL_NAME = "gpt-5-mini"

SYSTEM_PROMPT = """You are an expert Wikipedia editor focused on demographics sections. Follow the instructions precisely and return only valid wikitext."""


def _chat_complete(prompt: str, *, max_tokens: int = 25000) -> str:
    client = OpenAI(api_key=OPEN_AI_KEY)
    resp = client.chat.completions.create(
        model=os.getenv("ACTIVE_MODEL", MODEL_NAME),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=1, # I wish I could set this to 0, but I can't with the mini model :(
        max_completion_tokens=max_tokens,
        service_tier="flex",
    )
    choice = resp.choices[0] if resp.choices else None
    content = choice.message.content if choice and choice.message else None
    if not content or not content.strip():
        raise RuntimeError(f"OpenAI response missing content: {resp}")
    return content.strip()


def update_demographics_section(
    current_demographics_section: str, new_text: str, mini: bool = True, suppress_out: bool = True
) -> str:
    prompt = f"""
In the message you will be provided with "current_demographics_section", which contains the current text for the demographics section of a Wikipedia article for a county or municipality in the United States.

You will also be provided with "new_text", which contains proposed new text you must add to this demographics section. It is composed entirely of data from the 2020 US Census.

Modify the existing demographics section to contain the new 2020 census data, adding a new "===2020 census===" section or integrating with a pre-existing one as needed.

Keep references intact, and do not change factual content beyond inserting the 2020 census data. Be careful with headings, tables and refs to ensure that you don't break the wikitext.

Remove information made redundant by the new data. If needed, rearrange sentences containing existing demographic information so that it is grouped with related sentences in a logically flowing manner. If appropriate, put another H3 header below the new ===2020 census=== section in order to clearly mark where the 2020 census stops. The new header should meaningfully describe the content that comes below it in a way that is consistent with established section-naming precedent in Wikipedia.

If there is a wikitable on racial/ethnic composition across multiple decades, put it in it's own "===Racial and ethnic composition===" section. Keep in mind that sometimes the racial and ethnic composition section is called something like "Demographic Profile".

Do not remove old data (eg 2000 or 2010 census data), just move it into its own properly labeled subsection (eg "===2010 census===" or "===2000 census===")

Do not delete large chunks of existing content even if it seems irrelevant to demographics (eg a "===Crime===" section). You may move, modify, and add headings - but never just delete a bunch of content.

Output only the updated demographics and related census sections (no commentary).

current_demographics_section:
{current_demographics_section}

new_text:
{new_text}
"""
    return _chat_complete(prompt)+'\n'


def update_lede(current_lede_text: str, population_sentence: str, suppress_out: bool = True) -> str:
    prompt = f"""
You will be given the current lede text (wikitext) of a Wikipedia municipality article.

You will also be given a population_sentence that includes the 2020 census population and a citation.

Integrate the population_sentence into the lede so it reads naturally. Preserve existing facts and citations - except for population counts from 2010 or earlier (eg from 2010 or 2000), which may be removed.
Do not add new facts beyond the population sentence, and do not add or remove headings.
If the lede already clearly states the 2020 population, keep it and avoid duplication.

Output only the updated lede text (no commentary).

current_lede_text:
{current_lede_text}

population_sentence:
{population_sentence}
"""
    return _chat_complete(prompt, max_tokens=4000) + "\n"


def check_if_update_needed(current_article: str, new_text: str, suppress_out: bool = True) -> bool:
    prompt = f"""
You will be given two blocks of text.

current_article:
{current_article}

proposed_text:
{new_text}

Does proposed_text contain any information that is not already contained in current_article? If yes, answer YES. If no, answer NO. Reply with exactly YES or NO."""
    if new_text and new_text.strip() and new_text.strip() in current_article:
        return False
    try:
        response = _chat_complete(prompt, max_tokens=256).strip().upper()
    except RuntimeError:
        return True
    return response.startswith("Y")


def update_wp_page(current_article: str, new_text: str, suppress_out: bool = True) -> str:
    prompt = f"""
The variable "current_article" contains the full text for the Wikipedia page for a county or municipality in the United States.

"new_text" contains proposed new text you must add to the demographics section. It is composed entirely of data from the 2020 US Census.

Modify the existing Wikipedia page to contain the new section in the appropriate place (or create a Demographics section if absent). Remove redundant information, keep references intact, and do not change factual content beyond inserting the 2020 census data. Be careful with headings and tables as described for the demographics-only update.

Return ONLY the full updated article text (no commentary).

current_article:
{current_article}

new_text:
{new_text}
"""
    return _chat_complete(prompt, max_tokens=12000)+'\n'

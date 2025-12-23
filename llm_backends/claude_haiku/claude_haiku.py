import anthropic
from credentials import ANTHROPIC_API_KEY

"""
Claude backend for LLM operations.
Implements the same interface as the OpenAI Codex backend.
"""


def check_if_update_needed(current_article: str, new_text: str, suppress_out: bool = True) -> bool:
    """
    Check if the proposed text contains information not already in the current article.

    Args:
        current_article: Current Wikipedia article text
        new_text: Proposed new text to add
        suppress_out: Whether to suppress LLM output

    Returns:
        True if update is needed, False otherwise

    TODO: Implement using Claude Haiku API
    """
    raise NotImplementedError("Claude Haiku check_if_update_needed not yet implemented")


def update_wp_page(current_article: str, new_text: str, suppress_out: bool = True) -> str:
    """
    Update the full Wikipedia page with new census data.

    Args:
        current_article: Current Wikipedia article text
        new_text: Proposed new text to add
        suppress_out: Whether to suppress LLM output

    Returns:
        Updated article text

    TODO: Implement using Claude Haiku API
    """
    raise NotImplementedError("Claude Haiku update_wp_page not yet implemented")


def update_demographics_section(
    current_demographics_section: str, new_text: str, _unused1, _unused2, model = 'claude-haiku-4-5-20251001'
) -> str:
    """
    Update just the demographics section of a Wikipedia article.

    Args:
        current_demographics_section: Current demographics section text
        new_text: Proposed new text to add
        mini: Whether to use the mini (shorter) prompt
        suppress_out: Whether to suppress LLM output

    Returns:
        Updated demographics section text
    """

    PROMPT = ("""In the message you will be provided with "current_demographics_section", which contains the current text for the demographics section of a Wikipedia article for a county or municipality in the United States.

You will also be provided with "new_text", which contains proposed new text you must add to this demographics section. It is composed entirely of data from the 2020 US Census.

Modify the existing demographics section to contain the new 2020 census data, adding a new "===2020 census===" section or integrating with a pre-existing one as needed.

Keep references intact, and do not change factual content beyond inserting the 2020 census data. Be careful with headings, tables and refs to ensure that you don't break the wikitext.

Remove information made redundant by the new data. If needed, rearrange sentences containing existing demographic information so that it is grouped with related sentences in a logically flowing manner. If appropriate, put another H3 header below the new ===2020 census=== section in order to clearly mark where the 2020 census stops (eg. "===2000 census===", "===2010 census==="). The new header should meaningfully describe the content that comes below it in a way that is consistent with established section-naming precedent in Wikipedia.

Don't delete old census data or existing data tables

Output only the updated demographics and related census sections (no commentary).

"""
# Haiku, specific instruction
"""
Not every sentence needs a citation. As long as all appropriate sources are included at the end of the paragraph, it is fine.





current_demographics_section:
    """+current_demographics_section+"""





new_text:
    """+new_text)
    
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    message = client.messages.create(
        model=model,
        max_tokens=4096,
        system=("Output should be valid wikitext."),
        messages=[ { "role": "user", "content": PROMPT } ]
    )

    return message.content[0].text+'\n'

    

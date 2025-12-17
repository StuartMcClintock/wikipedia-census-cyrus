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
    # print('current_demographics_section:\n\n', current_demographics_section)
    # print('\n\n\n\n\n new_text:\n\n', new_text)
    # gljhgjh
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

    PROMPT = ("""
The following text contains the current text for the demographics section of a Wikipedia article for a county or municipality in the United States:
    """+current_demographics_section+"""



















This text is proposed new text you must add to this demographics section. It is composed entirely of data from the 2020 US Census:
    """+new_text+"""

















If the existing demographics section contains any 2020 Census information that is missing from the new text, insert those sentences into the new text in a logical location. Remove redundant information so each datapoint is stated once.

If an article has a pre-2020 estimate for a specific datapoint and the new text includes the official 2020 decennial value for that same datapoint, remove the estimate and any associated references so only the official 2020 figure remains. If there is no official 2020 replacement for that datapoint, leave the estimate untouched.

Prefer the phrasing "As of the [[2020 United States census|2020 census]]" when referencing official census counts. Ensure every new or modified sentence retains or adds appropriate references.

If you modify any tags like </small> or <br>, make sure the outcome is valid (eg. "</small)" is not okay)

You do not need to delete data that does not come from a decennial census as long as it is appropriately cited - but make sure it has an appropriately descriptive H3 header.

DO NOT remove any data or sources from the "US Census population" table. The "US Census population" table should remain as it starts.

DO NOT rename "==Demographics==" or delete the "US Census population" table.

If you mix with existing content, do not remove the references for the existing data.

If there is a table on race/ethnicity that contains up-to-date 2020 census information, DO NOT DELETE IT!

If there is 2010 or 2000 census data that doesn't have an appropriate H3 heading above it, add "===2010 census===" or "===2000 census===" above it respectively

The content of the 2020 census section should be split into topically coherent paragraphs, NOT SMASHED INTO A SINGLE LARGE PARAGRAPH!

Ensure that adequate citation refs from the three census api refs (DP, PL, DHC) are added to backup all the factual claims made in a particular paragraph."""
# the following are additional instructions specific to haiuku
"""Not every sentence needs a citation. As long as all appropriate sources are included at the end of the paragraph, it is fine.

Output only the updated demographics section (no commentary).
    """)
    
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    message = client.messages.create(
        model=model,
        max_tokens=4096,
        system=("Output should be valid wikitext."),
        messages=[ { "role": "user", "content": PROMPT } ]
    )

    return message.content[0].text

    

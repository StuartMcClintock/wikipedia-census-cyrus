# Fine-tuning dataset report

**Target model:** `gpt-4.1-mini-2025-04-14`
**Output directory:** `artifacts/fine_tuning`

## Counts

| | count |
|---|---|
| Source pairs (`pairs.jsonl`) | 50 |
| Quarantined (validation failed) | 0 |
| Skipped (could not regenerate `new_text`) | 0 |
| Duplicates dropped | 0 |
| **Train examples** | **45** |
| **Eval examples** | **5** |

## Distribution by state FIPS
- state FIPS `19`: 50

## Token estimates (per example, ~4 chars/token)
- Average user-prompt tokens: ~2408
- Average assistant-output tokens: ~1565
- Estimated total training tokens (train set, 1 epoch): ~178,854

## Quarantined examples (first 10)
- (none)

## Skipped — Census API regeneration failed (first 10)
- (none)

## Duplicates dropped (first 10)
- (none)

## Sample examples (truncated)
```
USER (truncated):
In the message you will be provided with "current_demographics_section", which contains the current text for the demographics section of a Wikipedia article for a county or municipality in the United States.

You will also be provided with "new_text", which contains proposed new text you must add to this demographics section. It is composed entirely of data from the 2020 US Census.

Modify the existing demographics section to contain the new 2020 census data, adding a new "===2020 census===" section or integrating with a pre-existing one as needed.

Keep references intact, and do not change fa...

ASSISTANT (truncated):
=== Demographics ===
{{Historical populations
|title= Historical populations
|type= USA
|align= left
|1900|149
|1910|130
|1920|135
|1930|149
|1940|147
|1950|125
|1960|130
|1970|152
|1980|128
|1990|74
|2000|74
|2010|66
|2020|45
|source={{center|U.S. Decennial Census<ref name="DecennialCensus">{{cite web|url=https://www.census.gov/programs-surveys/decennial-census.html|title=Census of Population and Housing|publisher=Census.gov|accessdate=June 4, 2015}}</ref><ref name=cen2020/>}}|footnote=Source:{{cite web|url=https://www.census.gov|publisher=[[United States Census Bureau]]|title=U.S. Census web...
```

```
USER (truncated):
In the message you will be provided with "current_demographics_section", which contains the current text for the demographics section of a Wikipedia article for a county or municipality in the United States.

You will also be provided with "new_text", which contains proposed new text you must add to this demographics section. It is composed entirely of data from the 2020 US Census.

Modify the existing demographics section to contain the new 2020 census data, adding a new "===2020 census===" section or integrating with a pre-existing one as needed.

Keep references intact, and do not change fa...

ASSISTANT (truncated):
=== Demographics ===
{{US Census population
|align= right
|2010= 33
|2020= 32
|footnote=U.S. Decennial Census<ref name="DecennialCensus">{{cite web|url=http://www.census.gov/prod/www/decennial.html|title=Census of Population and Housing|publisher=Census.gov|accessdate=June 4, 2016}}</ref>
| align-fn = center
}}

===2020 census===
As of the [[2020 United States census|2020 census]], there were 32 people, 5 households, and 3 families residing in the community. The [[population density]] was 11.1 inhabitants per square mile (4.3/km<sup>2</sup>). There were 12 housing units at an average density o...
```


## Data quality concerns
- All source examples come from a single state (Iowa, FIPS 19) and a single
  generator model (`gpt-5.3-codex`). The fine-tuned model will be fit to that
  output style — if it differs noticeably from what you want, expand the corpus
  before scaling up.
- The `new_text` field is regenerated *now* from the Census API, while the
  outputs were produced earlier with whatever `new_text` the generator emitted
  at precompute time. Small drifts are possible if `generate_municipality_paragraphs`
  has changed since.
- All examples are full-page wikitext rewrites, which makes evaluation expensive
  and noisy. Plan to spot-check a handful of generated outputs by hand.

## Recommended first run
- Start with this corpus as-is for a single fine-tune run.
- Default OpenAI hyperparameters (auto) are fine; do not hand-tune until you
  have a baseline metric to compare against.
- Estimated training cost (very rough): ~0 M tokens
  at default 3 epochs. Check current `gpt-4.1-mini` fine-tuning pricing before
  starting the job.

## Next data improvements
1. Add a second state (e.g. Texas, Ohio) to test geographic generalization.
2. Add county-level examples (currently municipality only).
3. Manually spot-check 10 outputs and quarantine any that drop refs, mangle
   tables, or hallucinate numbers.
4. Capture the *exact* `new_text` used at generation time during precompute,
   so you don't have to regenerate.

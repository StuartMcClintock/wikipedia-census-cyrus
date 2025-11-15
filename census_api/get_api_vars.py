import json
from typing import Dict

import pandas as pd

DATASET_URLS = {
    "pl": "https://api.census.gov/data/2020/dec/pl/variables.html",
    "dp": "https://api.census.gov/data/2020/dec/dp/variables.html",
}


def fetch_vars(url: str) -> Dict[str, str]:
    """Return Name -> Label mapping from the census metadata table at url."""
    tables = pd.read_html(url)
    df = tables[0][["Name", "Label"]]  # only keep relevant columns
    return {
        row["Name"]: row["Label"]
        for _, row in df.iterrows()
    }


all_vars = {
    dataset: fetch_vars(url)
    for dataset, url in DATASET_URLS.items()
}

# Dump as JSON keyed by dataset (pl/dp)
print(json.dumps(all_vars, indent=2, ensure_ascii=False))

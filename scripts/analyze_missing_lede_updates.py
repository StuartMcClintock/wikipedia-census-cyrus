#!/usr/bin/env python3
"""
Analyze lede edit logs to find which (municipality type, state) combinations
have not been updated yet.
"""

import json
from pathlib import Path
from collections import defaultdict
from typing import Set, Dict

BASE_DIR = Path(__file__).resolve().parent.parent
LEDE_LOG_PATH = BASE_DIR / "app_logging" / "logs" / "lede_edits.log"
MUNICIPALITY_FIPS_DIR = BASE_DIR / "census_api" / "fips_mappings" / "municipality_to_fips"

# Only these muni types (lowercase for comparison)
TARGET_MUNI_TYPES = {"city", "town", "village", "borough", "cdp"}


def get_edited_articles() -> Set[str]:
    """Get set of all article titles that have been edited."""
    edited = set()

    if not LEDE_LOG_PATH.exists():
        print(f"Warning: Log file not found: {LEDE_LOG_PATH}")
        return edited

    with open(LEDE_LOG_PATH, 'r') as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                result = entry.get("result", {})
                edit_info = result.get("edit", {})

                if edit_info.get("result") == "Success":
                    # Get article name from either the entry or the edit result
                    article = entry.get("article") or edit_info.get("title", "")
                    if article:
                        # Normalize: convert spaces to underscores
                        edited.add(article.replace(" ", "_"))
            except json.JSONDecodeError:
                continue
            except Exception:
                continue

    return edited


def get_all_municipalities_by_type_and_state() -> Dict[str, Dict[str, Set[str]]]:
    """
    Get all municipalities organized by type and state.

    Returns:
        Dict mapping muni_type -> state_postal -> set of article titles
    """
    muni_data = defaultdict(lambda: defaultdict(set))

    if not MUNICIPALITY_FIPS_DIR.exists():
        print(f"Warning: Municipality FIPS directory not found: {MUNICIPALITY_FIPS_DIR}")
        return dict(muni_data)

    # Iterate through each state directory
    for state_dir in MUNICIPALITY_FIPS_DIR.iterdir():
        if not state_dir.is_dir():
            continue

        state_postal = state_dir.name  # e.g., "AL", "AK"

        # Iterate through each municipality type directory
        for type_dir in state_dir.iterdir():
            if not type_dir.is_dir():
                continue

            muni_type = type_dir.name.lower()

            # Only track target muni types
            if muni_type not in TARGET_MUNI_TYPES:
                continue

            # Read the places.json file
            places_file = type_dir / "places.json"
            if not places_file.exists():
                continue

            try:
                places_data = json.loads(places_file.read_text())

                # Add all article titles for this type/state combo
                for article_title in places_data.keys():
                    # Normalize: convert spaces to underscores
                    normalized_title = article_title.replace(" ", "_")
                    muni_data[muni_type][state_postal].add(normalized_title)
            except Exception as e:
                print(f"Warning: Could not read {places_file}: {e}")
                continue

    return dict(muni_data)


def find_missing_combinations():
    """Find and report municipality type/state combinations with no lede updates."""
    print("=" * 70)
    print("Missing Lede Updates by Municipality Type and State")
    print("=" * 70)
    print()

    print("Loading edited articles from log...")
    edited_articles = get_edited_articles()
    print(f"Found {len(edited_articles)} successfully edited articles")
    print()

    print("Loading all municipalities from FIPS mappings...")
    all_munis = get_all_municipalities_by_type_and_state()
    print(f"Found {len(all_munis)} municipality types")
    print()

    # For each muni type, find states with no edits
    results = {}

    # Sort muni types, but put CDP last and capitalize it for display
    display_order = ["borough", "city", "town", "village", "cdp"]

    for muni_type in display_order:
        if muni_type not in all_munis:
            continue

        missing_states = []

        for state in sorted(all_munis[muni_type].keys()):
            articles_in_state = all_munis[muni_type][state]

            # Check if ANY article in this state/type has been edited
            has_any_edits = any(article in edited_articles for article in articles_in_state)

            if not has_any_edits:
                missing_states.append(state)

        if missing_states:
            results[muni_type] = missing_states

    # Print results
    print("=" * 70)
    print("RESULTS: (Municipality Type, States) with NO lede updates")
    print("=" * 70)
    print()

    if not results:
        print("All municipality type/state combinations have at least one lede update!")
    else:
        for muni_type in display_order:
            if muni_type not in results:
                continue
            # Display CDP in uppercase
            display_name = "CDP" if muni_type == "cdp" else muni_type
            states_str = ",".join(results[muni_type])
            count = len(results[muni_type])
            print(f"{display_name:12} ({count:2} states): {states_str}")

    print()
    print("=" * 70)

    # Additional stats
    print("\nAdditional Statistics:")
    for muni_type in display_order:
        if muni_type not in all_munis:
            continue

        display_name = "CDP" if muni_type == "cdp" else muni_type
        total_states = len(all_munis[muni_type])
        missing_count = len(results.get(muni_type, []))
        updated_count = total_states - missing_count

        print(f"  {display_name:12}: {updated_count}/{total_states} states have updates")


if __name__ == "__main__":
    find_missing_combinations()

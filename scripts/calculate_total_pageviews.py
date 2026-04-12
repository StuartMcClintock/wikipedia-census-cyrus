#!/usr/bin/env python3
"""
Calculate total Wikipedia pageviews for all articles edited by the bot.

This script reads the edit logs (demographics and lede edits), finds the earliest
edit date for each article, and calculates total pageviews from that date to today
across all articles to demonstrate the bot's impact.
"""

import json
import requests
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path
from typing import Dict, Optional
import time
import sys
import math
from urllib.parse import quote, unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from credentials import WP_BOT_USER_AGENT

EDIT_LOG_PATH = BASE_DIR / "app_logging" / "logs" / "edit.log"
LEDE_LOG_PATH = BASE_DIR / "app_logging" / "logs" / "lede_edits.log"

# Wikipedia Pageviews API
# Docs: https://wikitech.wikimedia.org/wiki/Analytics/AQS/Pageviews
PAGEVIEWS_API = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/{article}/daily/{start}/{end}"
MEDIAWIKI_API = "https://en.wikipedia.org/w/api.php"

# Manual backfill for Oklahoma county pages updated at 8:03pm PST on Nov 23, 2025.
# These edits were missing from logging and must be counted in total pageviews.
MISSING_OKLAHOMA_COUNTY_EDIT_TIMESTAMP_PST = datetime(2025, 11, 23, 20, 3, 0)
MISSING_OKLAHOMA_COUNTY_PAGES = (
    "Adair County, Oklahoma",
    "Alfalfa County, Oklahoma",
    "Atoka County, Oklahoma",
    "Beaver County, Oklahoma",
    "Beckham County, Oklahoma",
    "Blaine County, Oklahoma",
    "Bryan County, Oklahoma",
    "Caddo County, Oklahoma",
    "Canadian County, Oklahoma",
    "Carter County, Oklahoma",
    "Cherokee County, Oklahoma",
    "Choctaw County, Oklahoma",
    "Cimarron County, Oklahoma",
    "Cleveland County, Oklahoma",
    "Coal County, Oklahoma",
    "Comanche County, Oklahoma",
    "Cotton County, Oklahoma",
    "Craig County, Oklahoma",
    "Creek County, Oklahoma",
    "Custer County, Oklahoma",
    "Delaware County, Oklahoma",
    "Dewey County, Oklahoma",
    "Ellis County, Oklahoma",
    "Garfield County, Oklahoma",
    "Garvin County, Oklahoma",
    "Grady County, Oklahoma",
    "Grant County, Oklahoma",
    "Greer County, Oklahoma",
    "Harmon County, Oklahoma",
    "Harper County, Oklahoma",
    "Haskell County, Oklahoma",
    "Hughes County, Oklahoma",
    "Jackson County, Oklahoma",
    "Jefferson County, Oklahoma",
    "Johnston County, Oklahoma",
    "Kay County, Oklahoma",
    "Kingfisher County, Oklahoma",
    "Kiowa County, Oklahoma",
    "Latimer County, Oklahoma",
    "LeFlore County, Oklahoma",
    "Lincoln County, Oklahoma",
    "Logan County, Oklahoma",
    "Love County, Oklahoma",
    "McClain County, Oklahoma",
    "McCurtain County, Oklahoma",
    "McIntosh County, Oklahoma",
    "Major County, Oklahoma",
    "Marshall County, Oklahoma",
    "Mayes County, Oklahoma",
    "Murray County, Oklahoma",
    "Muskogee County, Oklahoma",
    "Noble County, Oklahoma",
    "Nowata County, Oklahoma",
    "Okfuskee County, Oklahoma",
    "Oklahoma County, Oklahoma",
    "Okmulgee County, Oklahoma",
    "Osage County, Oklahoma",
    "Ottawa County, Oklahoma",
    "Pawnee County, Oklahoma",
    "Payne County, Oklahoma",
    "Pittsburg County, Oklahoma",
    "Pontotoc County, Oklahoma",
    "Pottawatomie County, Oklahoma",
    "Pushmataha County, Oklahoma",
    "Roger Mills County, Oklahoma",
    "Rogers County, Oklahoma",
    "Seminole County, Oklahoma",
    "Sequoyah County, Oklahoma",
    "Stephens County, Oklahoma",
    "Texas County, Oklahoma",
    "Tillman County, Oklahoma",
    "Tulsa County, Oklahoma",
    "Wagoner County, Oklahoma",
    "Washington County, Oklahoma",
    "Washita County, Oklahoma",
    "Woods County, Oklahoma",
    "Woodward County, Oklahoma",
)


def parse_log_file(log_path: Path) -> Dict[str, datetime]:
    """
    Parse a log file and return a dict of article names to edit timestamps.

    Args:
        log_path: Path to the log file

    Returns:
        Dict mapping article names to their edit datetime
    """
    article_edits = {}

    if not log_path.exists():
        print(f"Warning: Log file not found: {log_path}")
        return article_edits

    with open(log_path, 'r') as f:
        for line_num, line in enumerate(f, 1):
            try:
                entry = json.loads(line.strip())
                article = entry.get("article")

                # Get the Wikipedia edit timestamp (newtimestamp)
                result = entry.get("result", {})
                edit_info = result.get("edit", {})
                timestamp_str = edit_info.get("newtimestamp")

                if article and timestamp_str:
                    # Parse timestamp: "2025-11-30T05:31:15Z"
                    timestamp = datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%SZ")
                    article_edits[article] = timestamp

            except json.JSONDecodeError:
                print(f"Warning: Could not parse line {line_num} in {log_path.name}")
            except Exception as e:
                print(f"Warning: Error processing line {line_num} in {log_path.name}: {e}")

    return article_edits


def get_earliest_edit_dates() -> Dict[str, datetime]:
    """
    Get the earliest edit date for each article across both log files.

    Returns:
        Dict mapping article names to their earliest edit datetime
    """
    print("Parsing demographics edit log...")
    demographics_edits = parse_log_file(EDIT_LOG_PATH)
    print(f"Found {len(demographics_edits)} demographics edits")

    print("Parsing lede edit log...")
    lede_edits = parse_log_file(LEDE_LOG_PATH)
    print(f"Found {len(lede_edits)} lede edits")

    # Combine and take earliest date for each article
    earliest_edits = {}
    all_articles = set(demographics_edits.keys()) | set(lede_edits.keys())

    for article in all_articles:
        demo_date = demographics_edits.get(article)
        lede_date = lede_edits.get(article)

        if demo_date and lede_date:
            earliest_edits[article] = min(demo_date, lede_date)
        elif demo_date:
            earliest_edits[article] = demo_date
        else:
            earliest_edits[article] = lede_date

    # Backfill county pages that were edited but missing from logs.
    backfilled_new = 0
    backfilled_earlier = 0
    for page in MISSING_OKLAHOMA_COUNTY_PAGES:
        article = page.replace(" ", "_")
        existing_date = earliest_edits.get(article)
        if existing_date is None:
            earliest_edits[article] = MISSING_OKLAHOMA_COUNTY_EDIT_TIMESTAMP_PST
            backfilled_new += 1
            continue

        earlier_date = min(existing_date, MISSING_OKLAHOMA_COUNTY_EDIT_TIMESTAMP_PST)
        if earlier_date != existing_date:
            earliest_edits[article] = earlier_date
            backfilled_earlier += 1

    print(
        "Backfilled Oklahoma county pages from missing logs: "
        f"{backfilled_new} added, {backfilled_earlier} updated to earlier date"
    )

    print(f"\nTotal unique articles edited: {len(earliest_edits)}")
    return earliest_edits


def format_date_for_api(dt: datetime) -> str:
    """Format datetime for Wikipedia API: YYYYMMDD"""
    return dt.strftime("%Y%m%d")


def normalize_article_title(article: str) -> str:
    """
    Normalize an article identifier into a canonical Wikipedia page title.

    Handles percent-encoded titles like ``Kellogg%2C_Idaho`` and full wiki URLs.
    """
    normalized = article.strip()

    parsed = urlparse(normalized)
    if parsed.scheme and parsed.netloc and "/wiki/" in parsed.path:
        normalized = parsed.path.split("/wiki/", 1)[1]

    previous = None
    while normalized != previous:
        previous = normalized
        normalized = unquote(normalized)

    return normalized.replace(" ", "_")


def resolve_canonical_article_title(article: str) -> Optional[str]:
    """
    Resolve redirects and canonical capitalization/title spelling via MediaWiki.
    """
    normalized_article = normalize_article_title(article)
    headers = {
        'User-Agent': WP_BOT_USER_AGENT
    }

    try:
        response = requests.get(
            MEDIAWIKI_API,
            headers=headers,
            params={
                "action": "query",
                "format": "json",
                "redirects": 1,
                "titles": normalized_article.replace("_", " "),
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            if "missing" in page:
                return None
            title = page.get("title")
            if title:
                return title.replace(" ", "_")
    except requests.exceptions.RequestException:
        return None
    except Exception:
        return None

    return None


def fetch_pageviews_for_article(article: str, start_str: str, end_str: str, headers: Dict[str, str]) -> int:
    """Fetch pageviews for a single normalized article title."""
    url = PAGEVIEWS_API.format(
        article=quote(article, safe=""),
        start=start_str,
        end=end_str
    )
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    data = response.json()
    items = data.get("items", [])
    return sum(item.get("views", 0) for item in items)


def get_pageviews(article: str, start_date: datetime, end_date: datetime) -> Optional[int]:
    """
    Get total pageviews for an article between start and end dates.

    Args:
        article: Wikipedia article title (with underscores)
        start_date: Start date for pageview counting
        end_date: End date for pageview counting

    Returns:
        Total pageviews or None if request fails
    """
    start_str = format_date_for_api(start_date)
    end_str = format_date_for_api(end_date)
    normalized_article = normalize_article_title(article)
    headers = {
        'User-Agent': WP_BOT_USER_AGENT
    }

    try:
        return fetch_pageviews_for_article(normalized_article, start_str, end_str, headers)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            resolved_article = resolve_canonical_article_title(normalized_article)
            if resolved_article:
                try:
                    return fetch_pageviews_for_article(resolved_article, start_str, end_str, headers)
                except requests.exceptions.HTTPError as retry_error:
                    if retry_error.response.status_code != 404:
                        print(f"  HTTP error for {resolved_article}: {retry_error}")
                        return None
                except requests.exceptions.RequestException as retry_error:
                    print(f"  Request error for {resolved_article}: {retry_error}")
                    return None
                except Exception as retry_error:
                    print(f"  Unexpected error for {resolved_article}: {retry_error}")
                    return None

            if normalized_article != article:
                print(f"  404 - Article not found: {article} (normalized to {normalized_article})")
            else:
                print(f"  404 - Article not found: {article}")
        else:
            print(f"  HTTP error for {normalized_article}: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"  Request error for {normalized_article}: {e}")
        return None
    except Exception as e:
        print(f"  Unexpected error for {normalized_article}: {e}")
        return None


def calculate_total_pageviews():
    """Calculate total pageviews across all edited articles."""
    print("=" * 70)
    print("Wikipedia Bot Impact: Total Pageviews Calculator")
    print("=" * 70)
    print()

    # Get earliest edit date for each article
    article_edits = get_earliest_edit_dates()

    if not article_edits:
        print("No articles found in edit logs!")
        return

    # Calculate views
    today = datetime.now()
    total_views = 0
    successful_articles = 0
    failed_articles = 0
    article_view_totals = []

    print(f"\nCalculating pageviews from edit dates to today ({today.strftime('%Y-%m-%d')})...")
    print("This may take a while...\n")

    for i, (article, edit_date) in enumerate(article_edits.items(), 1):
        days_since_edit = (today - edit_date).days

        # Get pageviews
        views = get_pageviews(article, edit_date, today)

        if views is not None:
            total_views += views
            successful_articles += 1
            article_view_totals.append((article, views))
            if i <= 5:  # Show details for first few articles
                print(f"  {article}: {views:,} views ({days_since_edit} days)")
        else:
            failed_articles += 1

        # Show progress with running totals every 10 articles
        if i % 10 == 0:
            print(f"Progress: {i}/{len(article_edits)} articles processed... Total views so far: {total_views:,}")

        # Rate limiting: be nice to the API
        time.sleep(0.1)

    # Print results
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"Total articles analyzed: {len(article_edits)}")
    print(f"Successfully retrieved: {successful_articles}")
    print(f"Failed/Not found: {failed_articles}")
    print()
    print(f"TOTAL PAGEVIEWS SINCE EDITS: {total_views:,}")
    print("=" * 70)

    # Calculate date range
    earliest_edit = min(article_edits.values())
    latest_edit = max(article_edits.values())
    print(f"\nEdit date range: {earliest_edit.strftime('%Y-%m-%d')} to {latest_edit.strftime('%Y-%m-%d')}")
    print(f"Average views per article: {total_views // successful_articles:,}" if successful_articles > 0 else "N/A")

    if successful_articles == 0:
        return

    sorted_articles = sorted(article_view_totals, key=lambda x: x[1], reverse=True)

    print("\nView concentration (share of total views)")
    print("-" * 70)

    def print_bucket_summary(label: str, count: int) -> None:
        count = min(count, successful_articles)
        if count <= 0:
            return

        bucket_views = sum(views for _, views in sorted_articles[:count])
        bucket_share = (bucket_views / total_views * 100) if total_views > 0 else 0.0
        print(
            f"{label:<18} {bucket_views:>15,} views  "
            f"({bucket_share:>6.2f}% of total, {count} articles)"
        )

    print_bucket_summary("Top 10 articles", 10)

    percentile_buckets = (
        ("Top 1%", 0.01),
        ("Top 5%", 0.05),
        ("Top 10%", 0.10),
        ("Top 25%", 0.25),
        ("Top 50%", 0.50),
    )

    for label, pct in percentile_buckets:
        bucket_count = max(1, math.ceil(successful_articles * pct))
        print_bucket_summary(label, bucket_count)


if __name__ == "__main__":
    calculate_total_pageviews()

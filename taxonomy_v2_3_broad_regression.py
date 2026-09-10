"""Broad regression check for WhatNextTV Taxonomy V2.3 concept-affinity shadow mode.

Run:
    python taxonomy_v2_3_broad_regression.py

Optional:
    python taxonomy_v2_3_broad_regression.py severance bridgerton shogun

Backend default:
    http://localhost:8000

Override:
    set WHATNEXT_BACKEND_URL=http://localhost:8000
"""

from __future__ import annotations

import os
import sys
from typing import Any

import httpx

BASE_URL = os.getenv("WHATNEXT_BACKEND_URL", "http://localhost:8000").rstrip("/")
TOP_N = 12

# Deliberately spread across multiple taxonomy families and styles.
DEFAULT_SLUGS = [
    # Sci-fi / speculative
    "severance",
    "foundation",
    "stranger-things",
    "the-last-of-us",

    # Crime / mystery / thriller
    "mindhunter",
    "yellowjackets",
    "only-murders-in-the-building",
    "slow-horses",

    # Politics / power
    "succession",
    "the-diplomat",

    # Historical / period
    "bridgerton",
    "shogun",
    "the-crown",

    # Workplace / professional
    "the-bear",
    "greys-anatomy",
    "abbott-elementary",

    # Comedy / character
    "ted-lasso",
    "the-white-lotus",

    # Fantasy
    "house-of-the-dragon",

    # Historical disaster / grounded drama control
    "chernobyl",
]


def title_of(item: dict[str, Any]) -> str:
    return str(
        item.get("title")
        or item.get("name")
        or item.get("show_title")
        or "?"
    )


def score_of(item: dict[str, Any]) -> str:
    value = item.get("score")
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "-"


def get_page(client: httpx.Client, slug: str, shadow: bool) -> dict[str, Any]:
    url = f"{BASE_URL}/api/seo/shows-like/{slug}"
    params = {"taxonomy_shadow": "true"} if shadow else None
    response = client.get(url, params=params)
    response.raise_for_status()
    return response.json()


def compare_slug(client: httpx.Client, slug: str) -> None:
    old = get_page(client, slug, False)
    new = get_page(client, slug, True)

    anchor = (new.get("anchor") or {}).get("title") or slug
    shadow = new.get("_taxonomy_shadow") or {}

    old_items = list(old.get("recommendations") or [])[:TOP_N]
    new_items = list(new.get("recommendations") or [])[:TOP_N]

    old_titles = [title_of(x) for x in old_items]
    new_titles = [title_of(x) for x in new_items]
    overlap = len(set(old_titles) & set(new_titles))

    print("\n" + "=" * 100)
    print(f"ANCHOR: {anchor}")
    print(
        f"OLD={shadow.get('old_concept', '?')}  |  "
        f"NEW={shadow.get('taxonomy_concept', '?')}  |  "
        f"FAMILY={shadow.get('family', '?')}  |  "
        f"CONF={shadow.get('confidence', '?')}  |  "
        f"STATE={shadow.get('state', '?')}  |  "
        f"OVERLAP={overlap}/{TOP_N}"
    )

    print("TAXONOMY TOP 12:")
    for i, item in enumerate(new_items, start=1):
        print(f"  {i:>2}. {title_of(item):<46} score={score_of(item)}")

    if len(new_items) < TOP_N:
        print(f"  !! ONLY {len(new_items)} RESULTS")

    entered = [x for x in new_titles if x not in old_titles]
    if entered:
        print("ENTERED:", ", ".join(entered))


def main() -> None:
    slugs = sys.argv[1:] or DEFAULT_SLUGS

    print(f"Backend: {BASE_URL}")
    print("Mode: Taxonomy V2.3 concept-affinity broad regression")
    print(f"Testing {len(slugs)} anchors")

    failures: list[str] = []

    with httpx.Client(timeout=120.0) as client:
        for slug in slugs:
            try:
                compare_slug(client, slug)
            except Exception as exc:
                failures.append(slug)
                print(f"\nERROR for {slug}: {exc!r}")

    print("\n" + "=" * 100)
    print(f"COMPLETE: {len(slugs) - len(failures)}/{len(slugs)} anchors returned successfully")
    if failures:
        print("FAILED:", ", ".join(failures))


if __name__ == "__main__":
    main()

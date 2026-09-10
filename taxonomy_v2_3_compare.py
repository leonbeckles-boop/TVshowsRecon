"""Compare current WhatNextTV SEO recommendations with Taxonomy V2.2 shadow mode.

Usage:
    python taxonomy_shadow_compare.py
    python taxonomy_shadow_compare.py severance fallout the-witcher

Backend default: http://localhost:8000
Override with WHATNEXT_BACKEND_URL if required.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import httpx

BASE_URL = os.getenv("WHATNEXT_BACKEND_URL", "http://localhost:8000").rstrip("/")
TOP_N = 12

DEFAULT_SLUGS = [
    "severance",
    "fallout",
    "the-witcher",
    "better-call-saul",
    "hannibal",
    "the-night-manager",
    "abbott-elementary",
    "only-murders-in-the-building",
    "succession",
    "stranger-things",
    "the-100",
]


def title_of(item: dict[str, Any]) -> str:
    return str(item.get("title") or item.get("name") or item.get("show_title") or "?")


def score_of(item: dict[str, Any]) -> str:
    value = item.get("score")
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "-"


def get_page(client: httpx.Client, slug: str, shadow: bool) -> dict[str, Any]:
    url = f"{BASE_URL}/api/seo/shows-like/{slug}"
    response = client.get(url, params={"taxonomy_shadow": "true"} if shadow else None)
    response.raise_for_status()
    return response.json()


def print_list(label: str, items: list[dict[str, Any]]) -> None:
    print(label)
    for i, item in enumerate(items[:TOP_N], start=1):
        print(f"  {i:>2}. {title_of(item):<42} score={score_of(item)}")


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

    print("\n" + "=" * 88)
    print(f"ANCHOR: {anchor}")
    print(f"OLD CONCEPT:      {shadow.get('old_concept', '?')}")
    print(f"TAXONOMY CONCEPT: {shadow.get('taxonomy_concept', '?')}")
    print(
        f"FAMILY: {shadow.get('family', '?')} | "
        f"CONFIDENCE: {shadow.get('confidence', '?')} | "
        f"STATE: {shadow.get('state', '?')}"
    )
    print(f"TOP-{TOP_N} OVERLAP: {overlap}/{TOP_N}")
    print()
    print_list("OLD TOP 12", old_items)
    print()
    print_list("TAXONOMY TOP 12", new_items)

    entered = [x for x in new_titles if x not in old_titles]
    dropped = [x for x in old_titles if x not in new_titles]
    if entered:
        print("\nENTERED TAXONOMY LIST:", ", ".join(entered))
    if dropped:
        print("DROPPED FROM OLD LIST:", ", ".join(dropped))


def main() -> None:
    slugs = sys.argv[1:] or DEFAULT_SLUGS
    print(f"Backend: {BASE_URL}")
    print("Mode: Taxonomy V2.3 downstream shadow")
    print(f"Testing {len(slugs)} anchors")

    with httpx.Client(timeout=120.0) as client:
        for slug in slugs:
            try:
                compare_slug(client, slug)
            except Exception as exc:
                print(f"\nERROR for {slug}: {exc!r}")


if __name__ == "__main__":
    main()

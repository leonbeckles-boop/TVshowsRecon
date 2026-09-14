#!/usr/bin/env python3

import argparse
import asyncio
import time
import os
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import httpx


DEFAULT_API_BASE = "http://localhost:8000/api/seo/shows-like"
DEFAULT_SITEMAP = "http://localhost/sitemap.xml"


def extract_slug(url: str) -> str | None:
    path = urlparse(url).path.strip("/")
    marker = "shows-like/"

    if marker not in path:
        return None

    slug = path.split(marker, 1)[1].strip("/")
    return slug or None


async def fetch_sitemap_urls(
    client: httpx.AsyncClient,
    sitemap_url: str,
) -> list[str]:
    response = await client.get(sitemap_url, timeout=60.0)
    response.raise_for_status()

    root = ET.fromstring(response.text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    sitemap_nodes = root.findall("sm:sitemap", ns)

    if sitemap_nodes:
        urls: list[str] = []

        for node in sitemap_nodes:
            loc = node.find("sm:loc", ns)

            if loc is not None and loc.text:
                urls.extend(
                    await fetch_sitemap_urls(
                        client,
                        loc.text.strip(),
                    )
                )

        return urls

    urls: list[str] = []

    for node in root.findall("sm:url", ns):
        loc = node.find("sm:loc", ns)

        if loc is not None and loc.text:
            urls.append(loc.text.strip())

    return urls


async def warm_one(
    client: httpx.AsyncClient,
    api_base: str,
    slug: str,
    semaphore: asyncio.Semaphore,
    retries: int,
    refresh: bool,
):
    url = f"{api_base.rstrip('/')}/{slug}"

    if refresh:
        url += "?refresh=true"

    async with semaphore:
        last_error = ""
        elapsed = 0.0

        for attempt in range(retries + 1):
            started = time.perf_counter()

            try:
                headers = {}

                if refresh:
                    refresh_key = os.getenv("SEO_REFRESH_KEY")

                    if not refresh_key:
                        raise RuntimeError(
                            "SEO_REFRESH_KEY environment variable is required when using --refresh"
                        )

                    headers["X-SEO-Refresh-Key"] = refresh_key

                response = await client.get(
                    url,
                    headers=headers,
                    timeout=180.0,
                )

                elapsed = time.perf_counter() - started

                if response.status_code == 200:
                    state = (
                        "HIT/FAST"
                        if elapsed < 1.0
                        else "BUILT"
                    )

                    return (
                        slug,
                        True,
                        elapsed,
                        state,
                    )

                last_error = (
                    f"HTTP {response.status_code}: "
                    f"{response.text[:160]}"
                )

            except Exception as exc:
                elapsed = time.perf_counter() - started
                last_error = repr(exc)

            if attempt < retries:
                await asyncio.sleep(1.0)

        return (
            slug,
            False,
            elapsed,
            last_error,
        )


async def main_async(args):
    async with httpx.AsyncClient(
        follow_redirects=True
    ) as client:

        if args.slug:
            slugs = args.slug

        else:
            print(
                f"Reading sitemap: {args.sitemap}"
            )

            urls = await fetch_sitemap_urls(
                client,
                args.sitemap,
            )

            slugs = []
            seen = set()

            for url in urls:
                slug = extract_slug(url)

                if slug and slug not in seen:
                    seen.add(slug)
                    slugs.append(slug)

        if args.limit:
            slugs = slugs[: args.limit]

        if not slugs:
            print(
                "No /shows-like/ URLs found."
            )
            return 1

        print(
            f"Found {len(slugs)} Shows Like pages"
        )

        print(
            f"API base: {args.api_base}"
        )

        print(
            f"Concurrency: {args.concurrency}"
        )

        print()

        semaphore = asyncio.Semaphore(
            args.concurrency
        )

        tasks = [
        warm_one(
            client,
            args.api_base,
            slug,
            semaphore,
            args.retries,
            args.refresh,
        )
        for slug in slugs
    ]

        success = 0
        failed = 0

        for future in asyncio.as_completed(
            tasks
        ):
            (
                slug,
                ok,
                elapsed,
                detail,
            ) = await future

            if ok:
                success += 1

                print(
                    f"[OK]   "
                    f"{slug:<45} "
                    f"{elapsed:7.2f}s  "
                    f"{detail}"
                )

            else:
                failed += 1

                print(
                    f"[FAIL] "
                    f"{slug:<45} "
                    f"{elapsed:7.2f}s  "
                    f"{detail}"
                )

        print()
        print("Summary")
        print(f"  Success: {success}")
        print(f"  Failed:  {failed}")
        print(f"  Pages:   {len(slugs)}")

        return 0 if failed == 0 else 2


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Warm Redis-backed WhatNextTV "
            "Shows Like SEO pages."
        )
    )

    parser.add_argument(
        "--api-base",
        default=DEFAULT_API_BASE,
    )

    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force every Shows Like page to rebuild and replace its Redis cache entry.",
    )

    parser.add_argument(
        "--sitemap",
        default=DEFAULT_SITEMAP,
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=0,
    )

    parser.add_argument(
        "--concurrency",
        type=int,
        default=2,
    )

    parser.add_argument(
        "--retries",
        type=int,
        default=1,
    )

    parser.add_argument(
        "--slug",
        action="append",
        default=[],
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.concurrency < 1:
        parser.error(
            "--concurrency must be at least 1"
        )

    raise SystemExit(
        asyncio.run(
            main_async(args)
        )
    )


if __name__ == "__main__":
    main()
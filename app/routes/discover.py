# app/routes/discover.py

from __future__ import annotations

import asyncio
import os
import random
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/discover", tags=["discover"])

TMDB_API_KEY = os.getenv("TMDB_API_KEY")
TMDB_BASE_URL = "https://api.themoviedb.org/3"

# ---- simple in-process cache for discover payload ----
# You can later replace this with Redis if you like.

DISCOVER_CACHE_TTL_SECONDS = 300  # 5 minutes
_DISCOVER_CACHE: Dict[str, tuple[float, "DiscoverResponse"]] = {}
_DISCOVER_CACHE_KEY = "discover_v1"


class DiscoverShow(BaseModel):
    tmdb_id: int
    title: str
    name: Optional[str] = None
    overview: Optional[str] = None
    poster_path: Optional[str] = None
    first_air_date: Optional[str] = None
    vote_average: Optional[float] = None
    vote_count: Optional[int] = None
    reason: Optional[str] = None


class DiscoverResponse(BaseModel):
    featured: List[DiscoverShow]
    top_decade: List[DiscoverShow]
    trending: List[DiscoverShow]

    drama: List[DiscoverShow]
    crime: List[DiscoverShow]
    documentary: List[DiscoverShow]
    scifi_fantasy: List[DiscoverShow]
    thriller: List[DiscoverShow]
    comedy: List[DiscoverShow]
    action_adventure: List[DiscoverShow]
    animation: List[DiscoverShow]
    family: List[DiscoverShow]


async def _tmdb_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not TMDB_API_KEY:
        raise HTTPException(status_code=500, detail="TMDB_API_KEY is not configured")

    q: Dict[str, Any] = dict(params or {})
    q.setdefault("language", "en-GB")
    q["api_key"] = TMDB_API_KEY

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{TMDB_BASE_URL}{path}", params=q)

        if resp.status_code == 404:
            return {}

        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=502, detail=f"TMDb error: {exc.response.text}"
            ) from exc

        return resp.json()


def _map_tmdb_show(item: Dict[str, Any], *, reason: Optional[str] = None) -> DiscoverShow:
    return DiscoverShow(
        tmdb_id=item.get("id"),
        title=item.get("name") or item.get("original_name") or "",
        name=item.get("name") or item.get("original_name"),
        overview=item.get("overview"),
        poster_path=item.get("poster_path"),
        first_air_date=item.get("first_air_date") or item.get("release_date"),
        vote_average=item.get("vote_average"),
        vote_count=item.get("vote_count"),
        reason=reason,
    )


# --- ChatGPT-style curated titles (static list, TMDb data is live) ---
# Note: this list is GLOBAL, not based on user favourites; it's just a
# cross-genre set of strong, widely loved shows.

FEATURED_TITLES: list[str] = [
    "Breaking Bad",
    "Game of Thrones",
    "Chernobyl",
    "The Sopranos",
    "Band of Brothers",
    "The Wire",
    "Better Call Saul",
    "Stranger Things",
    "Sherlock",
    "Peaky Blinders",
    "The Twilight Zone",
    "Fleabag",
    "Fargo",
    "House M.D.",
    "Friends",
    "Dark",
    "The Office",
    "Succession",
    "Battlestar Galactica",
    "Freaks and Geeks",
    "Mad Men",
    "Narcos",
    "Mindhunter",
    "Mr. Robot",
    "Black Mirror",
    "Heartstopper",
    "Severance",
    "It’s Always Sunny in Philadelphia",
    "The Boys",
    "Seinfeld",
    "Peep Show",
    "The Last of Us",
    "When They See Us",
    "The Mandalorian",
    "Lost",
    "Line of Duty",
    "Deadwood",
    "Mare of Easttown",
    "Hannibal",
    "The Bear",
    "Boardwalk Empire",
    "Atlanta",
    "Vikings",
    "Twin Peaks",
    "The Shield",
    "Happy Valley",
    "True Detective",
    "The Haunting of Hill House",
    "The Americans",
    "Justified",
    # IMDB-only additions:
    "The Walking Dead",
    "The Big Bang Theory",
    "Dexter",
    "How I Met Your Mother",
    "Squid Game",
    "Rick and Morty",
    "Attack on Titan",
    "Prison Break",
    "The Witcher",
    "Money Heist",
    "House of Cards",
    "Westworld",
    "Modern Family",
    "Suits",
    "Supernatural",
    "Daredevil",
    "House of the Dragon",
    "Wednesday",
    "The Simpsons",
    "Loki",
    "Arrow",
    "Death Note",
    "South Park",
    "The Lord of the Rings: The Rings of Power",
    "Avatar: The Last Airbender",
    "Ted Lasso",
    "Arcane",
    "Brooklyn Nine-Nine",
]

# limit how many featured titles we actually query each time
FEATURED_MAX_RESULTS = 24


async def _fetch_featured() -> List[DiscoverShow]:
    """
    Fetch a curated slice of FEATURED_TITLES.

    - Randomly samples up to FEATURED_MAX_RESULTS titles from the big list
    - Fetches them from TMDb IN PARALLEL (asyncio.gather)
    """
    if not FEATURED_TITLES:
        return []

    # sample a subset so we aren't doing 70+ HTTP calls per request
    titles = FEATURED_TITLES
    if len(titles) > FEATURED_MAX_RESULTS:
        titles = random.sample(titles, FEATURED_MAX_RESULTS)

    tasks = [
        _tmdb_get("/search/tv", {"query": title})
        for title in titles
    ]

    results: List[DiscoverShow] = []
    # gather with return_exceptions so one failure doesn't blow up the whole list
    data_list = await asyncio.gather(*tasks, return_exceptions=True)

    for title, data in zip(titles, data_list):
        if isinstance(data, Exception):
            # you could log this if you have a logger
            continue
        items = (data or {}).get("results") or []
        if items:
            results.append(_map_tmdb_show(items[0], reason="Curated highlight"))

    return results


async def _fetch_top_decade() -> List[DiscoverShow]:
    params = {
        "sort_by": "vote_average.desc",
        "vote_count.gte": 300,
        "first_air_date.gte": "2015-01-01",
        "include_adult": "false",
        "page": 1,
    }
    data = await _tmdb_get("/discover/tv", params)
    items = data.get("results") or []
    return [_map_tmdb_show(i, reason="Top rated 2015–2025") for i in items]


async def _fetch_trending() -> List[DiscoverShow]:
    data = await _tmdb_get("/trending/tv/week")
    items = data.get("results") or []
    filtered = [
        i
        for i in items
        if (i.get("vote_average") or 0) >= 7.0 and (i.get("vote_count") or 0) >= 100
    ]
    return [_map_tmdb_show(i, reason="Trending now") for i in filtered]


GENRES = {
    "drama": 18,
    "crime": 80,
    "documentary": 99,
    "scifi_fantasy": 10765,
    "thriller": 9648,
    "comedy": 35,
    "action_adventure": 10759,
    "animation": 16,
    "family": 10751,
}


async def _fetch_by_genre(genre_id: int, label: str) -> List[DiscoverShow]:
    params = {
        "sort_by": "vote_average.desc",
        "vote_count.gte": 200,
        "first_air_date.gte": "2015-01-01",
        "include_adult": "false",
        "with_genres": str(genre_id),
        "page": 1,
    }
    data = await _tmdb_get("/discover/tv", params)
    items = data.get("results") or []
    return [_map_tmdb_show(i, reason=f"Top {label}") for i in items]


@router.get("", response_model=DiscoverResponse)
async def get_discover() -> DiscoverResponse:
    """
    Main Discover endpoint.

    - Returns cached payload if it's still fresh (fast path)
    - Otherwise fetches all sections from TMDb, then caches the result
    """

    # ---- FAST PATH: return cached if fresh ----
    now = time.monotonic()
    cached = _DISCOVER_CACHE.get(_DISCOVER_CACHE_KEY)
    if cached is not None:
        ts, payload = cached
        if now - ts < DISCOVER_CACHE_TTL_SECONDS:
            return payload

    # ---- SLOW PATH: build the payload once ----
    (
        featured,
        top_decade,
        trending,
        drama,
        crime,
        documentary,
        scifi_fantasy,
        thriller,
        comedy,
        action_adventure,
        animation,
        family,
    ) = await asyncio.gather(
        _fetch_featured(),
        _fetch_top_decade(),
        _fetch_trending(),
        _fetch_by_genre(GENRES["drama"], "Drama"),
        _fetch_by_genre(GENRES["crime"], "Crime"),
        _fetch_by_genre(GENRES["documentary"], "Documentary"),
        _fetch_by_genre(GENRES["scifi_fantasy"], "Sci-Fi & Fantasy"),
        _fetch_by_genre(GENRES["thriller"], "Thriller"),
        _fetch_by_genre(GENRES["comedy"], "Comedy"),
        _fetch_by_genre(GENRES["action_adventure"], "Action & Adventure"),
        _fetch_by_genre(GENRES["animation"], "Animation"),
        _fetch_by_genre(GENRES["family"], "Family"),
    )

    payload = DiscoverResponse(
        featured=featured,
        top_decade=top_decade,
        trending=trending,
        drama=drama,
        crime=crime,
        documentary=documentary,
        scifi_fantasy=scifi_fantasy,
        thriller=thriller,
        comedy=comedy,
        action_adventure=action_adventure,
        animation=animation,
        family=family,
    )

    # store in cache
    _DISCOVER_CACHE[_DISCOVER_CACHE_KEY] = (now, payload)

    return payload

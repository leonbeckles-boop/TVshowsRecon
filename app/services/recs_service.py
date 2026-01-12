# app/reddit_service.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Set, Tuple
import os
import re
import asyncio
import httpx

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_models import Show

# Optional title resolver (TMDb); if missing, we still work with local titles
try:
    from app.services.title_to_tmdb import title_to_tmdb
except Exception:
    title_to_tmdb = None  # type: ignore

load_dotenv()

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_UA = os.getenv("REDDIT_USER_AGENT", "tvrecon/1.0 (by u/yourbot)")

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
OAUTH = httpx.BasicAuth(REDDIT_CLIENT_ID or "", REDDIT_SECRET or "")

SUBS_DEFAULT = ["television", "tvrecommendations", "netflix", "HBO", "Hulu"]
LIMIT_PER_SUB = 20


async def _get_access_token(client: httpx.AsyncClient) -> Optional[str]:
    if not (REDDIT_CLIENT_ID and REDDIT_SECRET):
        return None
    try:
        resp = await client.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=OAUTH,
            headers={"User-Agent": REDDIT_UA},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("access_token")
    except Exception:
        return None


async def _fetch_top_posts(client: httpx.AsyncClient, sub: str, token: Optional[str]) -> List[Dict[str, Any]]:
    headers = {"User-Agent": REDDIT_UA}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://oauth.reddit.com/r/{sub}/top"
    try:
        r = await client.get(url, params={"t": "month", "limit": LIMIT_PER_SUB}, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        children = data.get("data", {}).get("children", [])
        out = []
        for ch in children:
            d = ch.get("data", {})
            out.append({
                "id": d.get("id"),
                "title": d.get("title"),
                "selftext": d.get("selftext"),
                "score": d.get("score"),
                "subreddit": d.get("subreddit"),
            })
        return out
    except Exception:
        return []


async def _fetch_comments_for_post(client: httpx.AsyncClient, post_id: str, token: Optional[str]) -> List[Dict[str, Any]]:
    headers = {"User-Agent": REDDIT_UA}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://oauth.reddit.com/comments/{post_id}"
    try:
        r = await client.get(url, params={"limit": 100, "depth": 1}, headers=headers, timeout=20)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list) or len(data) < 2:
            return []
        comments_listing = data[1]  # second listing is comments
        children = comments_listing.get("data", {}).get("children", [])
        out = []
        for ch in children:
            kind = ch.get("kind")
            d = ch.get("data", {})
            if kind != "t1":  # comment
                continue
            out.append({
                "body": d.get("body") or "",
                "score": int(d.get("score") or 0),
            })
        return out
    except Exception:
        return []


async def fetch_posts_with_comments(subs: Optional[List[str]] = None, *, limit_total: int = 60) -> List[Dict[str, Any]]:
    subs = subs or SUBS_DEFAULT
    async with httpx.AsyncClient() as client:
        token = await _get_access_token(client)
        posts: List[Dict[str, Any]] = []
        for sub in subs:
            posts.extend(await _fetch_top_posts(client, sub, token))
            if len(posts) >= limit_total:
                break
        posts = posts[:limit_total]

        # fetch comments concurrently
        tasks = [
            _fetch_comments_for_post(client, p["id"], token)
            for p in posts
            if p.get("id")
        ]
        comments_list = await asyncio.gather(*tasks, return_exceptions=True)
        for p, comments in zip(posts, comments_list):
            p["comments"] = comments if isinstance(comments, list) else []
        return posts


def _normalize(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s


async def _local_title_map(db: AsyncSession) -> Dict[str, int]:
    rows = (await db.execute(select(Show.title, Show.external_id))).all()
    out: Dict[str, int] = {}
    for title, ext in rows:
        if not title:
            continue
        try:
            tm = int(ext)
        except Exception:
            continue
        out[_normalize(title)] = tm
    return out


def extract_titles_from_text(text: str, local_map: Dict[str, int]) -> List[int]:
    """
    Extract candidate titles from free text, resolve to TMDb ids using:
      1) exact/substring over local_map (normalized)
      2) optional TMDb title_to_tmdb() for top spans
    """
    tmdbs: List[int] = []
    t = text or ""
    if not t:
        return tmdbs

    norm_text = _normalize(t)

    # 1) cheap contains over local titles
    hits: Set[int] = set()
    for lt_norm, tm in local_map.items():
        if lt_norm and lt_norm in norm_text:
            hits.add(tm)

    # 2) try TMDb lookup on a few long spans if available
    if title_to_tmdb:
        # crude spans: quoted titles or long alpha blocks
        spans = re.findall(r"\"([^\"]{3,80})\"", t) or re.findall(r"[A-Za-z0-9][A-Za-z0-9\s:'!-]{4,80}[A-Za-z0-9]", t)
        spans = sorted({s.strip() for s in spans}, key=len, reverse=True)[:3]
        for sp in spans:
            tm = title_to_tmdb(sp)
            if tm:
                hits.add(tm)

    tmdbs.extend(sorted(hits))
    return tmdbs


async def reddit_trending_candidates(
    subs: Optional[List[str]] = None, *, limit_total: int = 60
) -> List[Dict[str, Any]]:
    # kept for backwards compatibility with your earlier code
    return await fetch_posts_with_comments(subs=subs, limit_total=limit_total)


async def reddit_mention_counts(
    db: AsyncSession, *, subs: Optional[List[str]] = None, limit_total: int = 60
) -> Dict[int, int]:
    posts = await fetch_posts_with_comments(subs=subs, limit_total=limit_total)
    local_map = await _local_title_map(db)
    counts: Dict[int, int] = {}

    def bump(tm: int, w: int):
        counts[tm] = counts.get(tm, 0) + w

    for p in posts:
        # count titles in post title & selftext (weight lightly)
        for tm in extract_titles_from_text((p.get("title") or "") + " " + (p.get("selftext") or ""), local_map):
            bump(tm, 1)
        # count titles in comments (weight by comment score)
        for c in p.get("comments", []):
            weight = max(int(c.get("score") or 0), 0) + 1
            for tm in extract_titles_from_text(c.get("body") or "", local_map):
                bump(tm, weight)

    return counts


async def reddit_recs_by_overlap(
    db: AsyncSession,
    seeds_tmdb: Set[int],
    *,
    subs: Optional[List[str]] = None,
    limit_total: int = 60,
    min_overlap: int = 1,
) -> Dict[int, float]:
    """
    Personalized Reddit signal:
      - find posts where OP lists overlap with user's seed shows (favorites/high ratings)
      - aggregate comment suggestions as recs, weighted by comment score
      - normalize 0..1
    """
    posts = await fetch_posts_with_comments(subs=subs, limit_total=limit_total)
    local_map = await _local_title_map(db)

    # Build OP-liked set for each post from title + selftext
    out_counts: Dict[int, int] = {}

    def bump(tm: int, w: int):
        out_counts[tm] = out_counts.get(tm, 0) + w

    for p in posts:
        op_likes: Set[int] = set(extract_titles_from_text((p.get("title") or "") + " " + (p.get("selftext") or ""), local_map))
        overlap = len(op_likes & seeds_tmdb)
        if overlap < min_overlap:
            continue

        # Mine comments for suggestions, weight by score
        for c in p.get("comments", []):
            weight = max(int(c.get("score") or 0), 0) + 1
            c_titles = extract_titles_from_text(c.get("body") or "", local_map)
            for tm in c_titles:
                # skip if user already likes it (seed)
                if tm in seeds_tmdb:
                    continue
                bump(tm, weight)

    if not out_counts:
        return {}

    mx = max(out_counts.values())
    return {tm: (cnt / mx) for tm, cnt in out_counts.items() if cnt > 0}

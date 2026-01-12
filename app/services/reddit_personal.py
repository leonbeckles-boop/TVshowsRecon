# app/services/reddit_personal.py
from __future__ import annotations

import json
import os
import re
import time
from functools import lru_cache
from typing import Dict, Iterable, List, Optional, Set
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

# Prefer the sync alias to avoid event-loop issues
try:
    from app.services.title_to_tmdb import resolve_title as _resolve_sync  # returns dict or None
except Exception:
    _resolve_sync = None  # type: ignore

DEBUG_REDDIT_PERSONAL = os.getenv("DEBUG_REDDIT_PERSONAL", "").lower() in ("1", "true", "yes")

# ---------- HTTP helper (stdlib) ----------
def _http_get_json(url: str, ua: str = "tvshowsrecon/0.1") -> dict:
    req = Request(url, headers={"User-Agent": ua})
    with urlopen(req, timeout=14) as r:
        return json.loads(r.read().decode("utf-8"))

# ---------- Extract candidate titles ----------
# Split on list separators (bullets, commas, pipes, slashes, newlines)
_SPLIT_RE = re.compile(r"[•\*\-\u2022,\n\r;|/]+")
# Title-ish runs (permissive)
_TITLE_RUN_RE = re.compile(r'\b[A-Za-z][A-Za-z0-9&\'!:.\-\s]{2,}\b')

# Markdown link: [Title Here](...)
_MD_LINK_RE = re.compile(r"\[([^\]]{2,})\]\([^)]+\)")

_STOPWORDS = {
    "season","seasons","episode","episodes","show","shows","series",
    "recommendation","recommendations","thanks","please","list","tv",
    "movie","movies","film","films",
}

_LIST_ANCHORS = (
    "liked", "favourites", "favorites", "faves",
    "seen", "watched", "my list", "shows i like", "liked shows",
    "i enjoyed", "i love", "top shows", "recommend me based on",
)

def _pull_markdown_link_titles(text: str) -> List[str]:
    out: List[str] = []
    for m in _MD_LINK_RE.finditer(text or ""):
        t = (m.group(1) or "").strip(" \"'()[]")
        if 2 <= len(t) <= 80:
            out.append(t)
    return out

def _extract_titles_freeform(text: str) -> List[str]:
    """
    Robustly pull plausible show titles from OP/comment text:
    - First harvest Markdown link titles [Title](url)
    - Then split lines and harvest short segments + title-like runs
    - De-dup and drop trivial stopwords
    """
    if not text:
        return []

    cand: List[str] = []

    # 1) Markdown link titles first (they’re often accurate)
    md_titles = _pull_markdown_link_titles(text)
    cand.extend(md_titles)

    # 2) Split and harvest
    for part in _SPLIT_RE.split(text):
        s = (part or "").strip(" \t-–—•*·0123456789.)(")
        if len(s) < 2:
            continue
        words = s.split()
        if 1 <= len(words) <= 9:
            cand.append(s)
        else:
            for m in _TITLE_RUN_RE.finditer(s):
                frag = (m.group(0) or "").strip(" \"'")
                if 2 <= len(frag) <= 80:
                    cand.append(frag)

    # Dedup & filter
    out: List[str] = []
    seen: Set[str] = set()
    for t in cand:
        k = t.casefold().strip()
        if not k or k in seen:
            continue
        if k in _STOPWORDS:
            continue
        if len(k.split()) == 1 and k in _STOPWORDS:
            continue
        seen.add(k)
        out.append(t.strip())
    return out

# ---------- Title normalization & mapping ----------
_PARENS_BRACKETS_RE = re.compile(r"(\([^)]*\)|\[[^\]]*\])")
_YEAR_TOKEN_RE = re.compile(r"\b(19|20)\d{2}\b")
_SEASON_RE = re.compile(r"\bseason\s+\d+\b", flags=re.IGNORECASE)
_QUOTES_EDGE_RE = re.compile(r'^[\"\'“”‘’]|[\"\'“”‘’]$')
_WS_MULTI = re.compile(r"\s{2,}")

def _clean_title_once(title: str) -> str:
    s = (title or "").strip()
    s = _PARENS_BRACKETS_RE.sub("", s)        # remove (...) and [...]
    s = _YEAR_TOKEN_RE.sub("", s)              # remove years
    s = _SEASON_RE.sub("", s)                  # remove "Season N"
    s = s.replace("&", "and")                  # & -> and
    s = _QUOTES_EDGE_RE.sub("", s)             # trim quotes at edges
    s = _WS_MULTI.sub(" ", s)                  # collapse spaces
    s = s.strip(" .,:;–—-").strip()
    return s

def _title_variants(raw: str) -> List[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    variants = [raw]
    for sep in (" - ", " — ", ": "):
        if sep in raw:
            variants.append(raw.split(sep, 1)[0].strip())
    cleaned = _clean_title_once(raw)
    if cleaned and cleaned != raw:
        variants.append(cleaned)
    if ", The" in cleaned:
        variants.append(cleaned.replace(", The", ""))
    if cleaned.lower().startswith("the "):
        variants.append(cleaned[4:])
    # de-dup preserve order
    seen = set()
    out: List[str] = []
    for v in variants:
        k = v.casefold()
        if k and k not in seen:
            seen.add(k)
            out.append(v)
    return out

@lru_cache(maxsize=4096)
def _resolve_title_to_tmdb_id(title: str) -> Optional[int]:
    """
    Map a free-text title to a TMDb TV id using your sync resolver (which calls /api/tmdb/search).
    Tries several normalized variants until one maps.
    """
    if not _resolve_sync or not title:
        return None
    try:
        for v in _title_variants(title):
            res = _resolve_sync(v)  # dict or None
            if res and isinstance(res, dict):
                tmdb_id = res.get("tmdb_id") or res.get("id")
                if tmdb_id is not None:
                    try:
                        return int(tmdb_id)
                    except Exception:
                        pass
    except Exception:
        return None
    return None

def _map_titles_to_tmdb(titles: Iterable[str]) -> Dict[int, str]:
    out: Dict[int, str] = {}
    for t in titles:
        tid = _resolve_title_to_tmdb_id(t)
        if tid:
            out[tid] = t
    return out

# ---------- OP list helpers ----------
def _op_lines_from_text(selftext: str) -> List[str]:
    """
    Try to find the section of the OP that enumerates liked shows.
    Looks for anchor phrases and collects the remainder of the line (and nearby lines).
    """
    if not selftext:
        return []
    lines = [ln.strip() for ln in selftext.splitlines()]
    out: List[str] = []

    for i, ln in enumerate(lines):
        lcl = ln.lower()
        if any(anchor in lcl for anchor in _LIST_ANCHORS):
            # take this line (after ':' if present) and next 4 lines as possible list
            tail = ln.split(":", 1)[-1] if ":" in ln else ln
            parts = [tail] + lines[i+1:i+5]
            out.extend([p for p in parts if p and len(p) > 1])

    # fallback: if nothing matched anchors, just return original lines (some posts are pure bullet lists)
    return out or lines

# ---------- Score one thread ----------
def _score_from_thread_json(thread_json: list, min_overlap: int) -> Dict[int, float]:
    """
    Return { tmdb_id: score } for a single thread:
      - Build OP list (mapped to TMDb); prefer >= min_overlap hits.
      - Parse top-level comments, map titles, exclude those already in OP.
      - Score = (1 + upvotes/50) * (1 + 0.2 * OP_size/10)
      - Fallback: if OP list maps to < min_overlap, still mine comments (reduced weight)
    """
    scores: Dict[int, float] = {}

    if not isinstance(thread_json, list) or len(thread_json) < 2:
        return scores

    try:
        post_wrappers = thread_json[0]["data"]["children"]
        post = post_wrappers[0]["data"] if post_wrappers else {}
        comments_wrappers = thread_json[1]["data"].get("children", [])
    except Exception:
        return scores

    title = (post.get("title") or "").strip()
    selftext = (post.get("selftext") or "").strip()

    # 1) OP list mapping (look for explicit "liked/favorites" blocks; else harvest markdown + freeform)
    op_titles: List[str] = []
    for seg in _op_lines_from_text(selftext):
        op_titles.extend(_pull_markdown_link_titles(seg))
        op_titles.extend(_extract_titles_freeform(seg))
    if not op_titles and title:
        op_titles.extend(_pull_markdown_link_titles(title))
        op_titles.extend(_extract_titles_freeform(title))

    # normalize + map
    op_map = _map_titles_to_tmdb(op_titles)
    op_tmdb = set(op_map.keys())
    op_ok = len(op_tmdb) >= max(min_overlap, 1)
    op_bonus = 1.0 + 0.2 * min(len(op_tmdb), 10) / 10.0  # 1.0..1.2

    if DEBUG_REDDIT_PERSONAL:
        print(f"[reddit_personal] OP titles raw={len(op_titles)} mapped={len(op_tmdb)} ok={op_ok} :: {title[:90]}")

    # 2) Parse top-level comments
    for c in comments_wrappers:
        kind = c.get("kind")
        if kind == "more":
            continue
        data = c.get("data") or {}
        body = data.get("body") or ""
        if not body:
            continue
        ups = int(data.get("ups") or 0)

        # comment titles
        cm_titles: List[str] = []
        cm_titles.extend(_pull_markdown_link_titles(body))
        cm_titles.extend(_extract_titles_freeform(body))
        if not cm_titles:
            continue
        cm_map = _map_titles_to_tmdb(cm_titles)
        cm_tmdb = set(cm_map.keys())
        if not cm_tmdb:
            continue

        # suggestions: exclude OP’s listed shows when OP list is usable
        suggestions = cm_tmdb - op_tmdb if op_ok else cm_tmdb
        if not suggestions:
            continue

        base_weight = 1.0 + min(ups, 50) / 50.0  # 1..2
        weight = base_weight * (op_bonus if op_ok else 0.85)  # slight dampening if OP not mapped

        for tmdb_id in suggestions:
            scores[tmdb_id] = scores.get(tmdb_id, 0.0) + float(weight)

    return scores

# ---------- Aggregate recent threads ----------
def reddit_personal_candidates(limit_threads: int = 10, min_overlap: int = 1) -> Dict[int, float]:
    """
    Read recent r/televisionsuggestions threads (public JSON) and
    aggregate suggestions into { tmdb_id: score }.
    """
    base = "https://www.reddit.com/r/televisionsuggestions"
    # raw_json=1 ensures we get unescaped Markdown for better parsing
    listing = f"{base}/new.json?limit={int(max(1, min(limit_threads, 25)))}&raw_json=1"

    try:
        js = _http_get_json(listing)
    except Exception:
        return {}

    items = js.get("data", {}).get("children", [])
    totals: Dict[int, float] = {}

    if DEBUG_REDDIT_PERSONAL:
        print(f"[reddit_personal] fetched threads: {len(items)}")

    for it in items:
        d = it.get("data") or {}
        permalink = d.get("permalink") or ""
        if not permalink:
            q = quote_plus(d.get("title") or "")
            permalink = f"/r/televisionsuggestions/search?q={q}"

        url = permalink
        if not url.startswith("http"):
            url = f"https://www.reddit.com{url}"
        if not url.endswith(".json"):
            url = url + ".json"
        # include raw_json here too
        url = url + ("&" if "?" in url else "?") + "raw_json=1"

        try:
            tj = _http_get_json(url)
        except Exception:
            continue

        s = _score_from_thread_json(tj, min_overlap=min_overlap)
        if s:
            if DEBUG_REDDIT_PERSONAL:
                try:
                    post_title = tj[0]["data"]["children"][0]["data"].get("title")
                    print(f"[reddit_personal] +{len(s)} suggestions from: {post_title}")
                except Exception:
                    pass
            for k, v in s.items():
                totals[k] = totals.get(k, 0.0) + float(v)

        time.sleep(0.35)  # be polite to Reddit

    if DEBUG_REDDIT_PERSONAL:
        print(f"[reddit_personal] total candidates: {len(totals)}")

    return totals

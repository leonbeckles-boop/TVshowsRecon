from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.routes.recs_v3 import (
    _tmdb_api_key,
    _tmdb_details,
    _tmdb_recommendations_for_fav,
    _fetch_tmdb_trending_candidates,
)

import asyncio
import json
import math
import re
import os
import hmac

from fastapi import Header, HTTPException
from collections import Counter
from datetime import datetime
from app.services.seo_profiles import get_or_create_profile, apply_profile_scoring
from app.services.seo_taxonomy import (
    classify_anchor,
    candidate_fit as taxonomy_candidate_fit,
    concept_affinity as taxonomy_concept_affinity,
    discovery_terms_for as taxonomy_discovery_terms_for,
    discovery_genres_for as taxonomy_discovery_genres_for,
    fingerprint_term_role_weight as taxonomy_fingerprint_term_role_weight,
)
import httpx
from fastapi_cache import FastAPICache

SEO_DEBUG = True

SEO_CACHE_VERSION = "v274a"
SEO_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60


async def _get_cached_shows_like_payload(slug: str) -> dict | None:
    try:
        backend = FastAPICache.get_backend()
        redis = getattr(backend, "redis", None)
        if redis is None:
            return None
        key = f"seo:shows-like:{SEO_CACHE_VERSION}:{slug}"
        cached = await redis.get(key)
        if not cached:
            return None
        if isinstance(cached, bytes):
            cached = cached.decode("utf-8")
        payload = json.loads(cached)
        if isinstance(payload, dict):
            if SEO_DEBUG:
                print("SEO CACHE HIT:", key)
            return payload
    except Exception as exc:
        if SEO_DEBUG:
            print("SEO CACHE READ ERROR:", slug, repr(exc))
    return None


async def _cache_shows_like_payload(slug: str, payload: dict) -> None:
    try:
        backend = FastAPICache.get_backend()
        redis = getattr(backend, "redis", None)
        if redis is None:
            return
        key = f"seo:shows-like:{SEO_CACHE_VERSION}:{slug}"
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        await redis.setex(key, SEO_CACHE_TTL_SECONDS, encoded)
        if SEO_DEBUG:
            print("SEO CACHE STORE:", key, f"ttl={SEO_CACHE_TTL_SECONDS}s")
    except Exception as exc:
        if SEO_DEBUG:
            print("SEO CACHE WRITE ERROR:", slug, repr(exc))



router = APIRouter(prefix="/api/seo", tags=["seo"])

MIN_RESULTS = 12
MAX_RESULTS = 24

# Public SEO pages need stricter thresholds than in-app recs.
ABS_MIN_VOTE_COUNT = 10
ABS_MIN_POPULARITY = 2.0

SEO_MIN_VOTE_COUNT = 50
SEO_MIN_VOTE_AVERAGE = 6.8
SEO_MIN_POPULARITY = 8.0

STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "from", "into", "their",
    "they", "them", "have", "has", "had", "was", "were", "are", "but",
    "about", "after", "before", "over", "under", "when", "while", "where",
    "what", "who", "why", "how", "you", "your", "our", "his", "her", "its",
    "she", "him", "his", "hers", "than", "then", "out", "off", "too", "very",
    "series", "show", "story", "stories", "season", "seasons", "episode",
    "episodes", "drama", "comedy", "family", "kids", "reality", "television",
    "life", "new", "old", "young", "set", "one", "two", "three", "four",
    "five", "their", "often", "next", "people", "watch", "watching", "viewer",
    "viewers", "about", "through", "across", "around", "within", "without",
    "love", "like", "more", "most", "some", "many", "each", "other",
}

BAD_GENRES = {
    10751,  # Family
    10762,  # Kids
    10764,  # Reality
}


CURRENT_YEAR = datetime.utcnow().year
SEO_FRESH_MIN_VOTE_COUNT = 150

SCI_FI_CLASSICS = {
    "the expanse",
    "battlestar galactica",
    "firefly",
    "for all mankind",
    "andor",
    "halo",
    "stargate universe",
    "star trek: picard",
    "star trek: discovery",
    "the 100",
    "12 monkeys",
    "colony",
    "snowpiercer",
}

ANCHOR_CONCEPTS = {
    "finance_power": {
        "must_have": [
            "wealth", "company", "business", "corporate", "money",
            "finance", "bank", "banking", "executive", "ceo",
            "dynasty", "inheritance", "media empire"
        ],
        "prefer": [
            "boardroom", "elite", "rivalry", "ambition",
            "shareholder", "merger", "acquisition"
        ],
        "reject": [
            "motorcycle club", "serial killer",
            "hospital", "heist", "superhero"
        ],
    },
    "small_town_mystery": {
        "must_have": ["murder", "investigation", "detective", "community", "family", "secrets"],
        "prefer": ["small town", "grief", "local", "coastal", "personal life"],
        "reject": ["superhero", "monster", "sci-fi", "fantasy", "procedural"],
    },
    "medical_family": {
        "must_have": ["doctor", "nurse", "hospital", "family", "community"],
        "prefer": ["care", "patients", "relationships", "compassion"],
        "reject": ["serial killer", "war crime", "gang"],
    },
}

# Emergency overrides only.
# Normal anchors should be classified automatically from metadata.
ANCHOR_TO_CONCEPT: dict[str, str] = {}


# Broad fallback pools for SEO pages when live signals are sparse.
# These are concept-level guardrails, not single-title overrides.
SEO_CONCEPT_FALLBACK_IDS: dict[str, list[int]] = {
    "space_franchise_adventure": [
        115036,  # The Book of Boba Fett
        114461,  # Ahsoka
        83867,   # Andor
        60554,   # Star Wars Rebels
        202879,  # Star Wars: Skeleton Crew
        4194,    # Star Wars: The Clone Wars
        105971,  # Star Wars: The Bad Batch
        1437,    # Firefly
        1972,    # Battlestar Galactica
        63639,   # The Expanse
        2290,    # Stargate Atlantis
    ],

    "space_epic": [83867, 63639, 71365, 1437, 87917, 5148, 580, 4271, 48866, 9156, 82856],
    "contained_dystopia": [
    106379,  # Fallout
    245927,  # Paradise
    79680,   # Snowpiercer
    125988,  # Silo
    70523,   # Dark
    60948,   # 12 Monkeys
    66732,   # Stranger Things
    48866,   # The 100
    46331,   # Under the Dome
    14956,   # Dollhouse
],
    "mystery_box_survival": [
        124364,  # FROM
        1705,    # Fringe
        70523,   # Dark
        60948,   # 12 Monkeys
        79696,   # Manifest
        117488,  # Yellowjackets
        66732,   # Stranger Things
        125988,  # Silo
        48866,   # The 100
        46331,   # Under the Dome
        53425,   # Wayward Pines
        54344,   # The Leftovers
    ],
    "prestige_existential_mystery": [
        54344,   # The Leftovers
        1575,    # Lost
        124364,  # FROM
        70523,   # Dark
        1705,    # Fringe
        79696,   # Manifest
        117488,  # Yellowjackets
        66732,   # Stranger Things
        60948,   # 12 Monkeys
        125988,  # Silo
        42009,   # Black Mirror
        53425,   # Wayward Pines
    ],
    
    "time_mystery": [70523, 60948, 42009, 95396, 66732, 14956],
    "corporate_mystery": [95396, 62560, 42009, 14956, 70523],
    "general_scifi": [42009, 70523, 66732, 60948, 83867, 87917, 63639, 125988],
}

def passes_concept_guardrail(concept: str, blob: str, genres: list[str]) -> bool:
    profile = ANCHOR_CONCEPTS.get(concept)
    if not profile:
        return True

    blob_l = blob.lower()

    # Reject hard mismatches
    if any(term in blob_l for term in profile["reject"]):
        return False

    # Must-have: require at least one strong signal
    if profile["must_have"]:
        if not any(term in blob_l for term in profile["must_have"]):
            return False

    return True

def _fallback_ids_for_concept(anchor_concept: str) -> list[int]:
    """
    Return optional emergency candidates for a concept.

    Fallbacks are a safety net only. They do not define the recommendation
    list and still have to pass the normal candidate filters/ranking.
    """
    extra_pools = {
        "finance_power": [
            # Existing finance fallback pool can remain temporarily.
        ],
        "medical_family": [
            39793, 18856, 95386, 61241, 62084, 5021, 1457,
        ],
        "small_town_mystery": [
            1427, 70453, 61244, 34415, 45016, 46648, 115004,
        ],
    }

    ids: list[int] = []

    for tid in extra_pools.get(anchor_concept, []):
        if tid not in ids:
            ids.append(tid)

    for tid in SEO_CONCEPT_FALLBACK_IDS.get(anchor_concept, []):
        if tid not in ids:
            ids.append(tid)

    # Only sci-fi concepts may borrow the broad sci-fi emergency pool.
    sci_fi_concepts = {
        "general_scifi",
        "space_epic",
        "space_franchise_adventure",
        "contained_dystopia",
        "mystery_box_survival",
        "prestige_existential_mystery",
        "time_mystery",
        "corporate_mystery",
    }

    if anchor_concept in sci_fi_concepts:
        for tid in SEO_CONCEPT_FALLBACK_IDS.get("general_scifi", []):
            if tid not in ids:
                ids.append(tid)

    return ids

def _tokenise(text_val: str | None) -> list[str]:
    if not text_val:
        return []
    words = re.findall(r"[a-zA-Z]{3,}", text_val.lower())
    return [w for w in words if w not in STOPWORDS]


def _extract_anchor_keywords(*parts: str | None, top_n: int = 14) -> list[str]:
    counts: Counter[str] = Counter()
    for part in parts:
        counts.update(_tokenise(part))
    boosts = {
        "spy": 3, "spies": 3, "espionage": 4, "cia": 4, "kgb": 4, "agent": 2,
        "agents": 2, "undercover": 3, "intelligence": 3, "mystery": 2,
        "crime": 2, "thriller": 2, "murder": 2, "political": 2, "war": 2,
        "survival": 2, "dystopian": 3, "time": 1, "travel": 1, "sci": 1,
        "period": 3, "historical": 3, "victorian": 3, "midwife": 5,
        "nurse": 4, "nurses": 4, "medical": 4, "hospital": 4, "doctor": 3,
        "family": 3, "community": 3, "romance": 2, "british": 2,
        "finance": 5, "billionaire": 4, "hedge": 4, "fund": 4, "wall": 3,
        "street": 3, "power": 3, "wealth": 3, "corporate": 4, "ambition": 3,
        "deal": 2, "deals": 2, "business": 3, "money": 3, "elite": 2,
        "rivalry": 3, "law": 2, "attorney": 2, "lawyer": 2,
        "cartel": 3, "drug": 3, "criminal": 2, "antihero": 3,
        "women": 2, "village": 2, "postwar": 2, "post-war": 2,
        "company": 3, "shareholder": 3, "merger": 3, "acquisition": 3,
        "tycoon": 3, "ceo": 3, "boardroom": 3, "dynasty": 2,
    }
    for token, boost in boosts.items():
        if token in counts:
            counts[token] += boost
    return [w for w, _ in counts.most_common(top_n)]


def _semantic_text_score(anchor_keywords: list[str], *candidate_parts: str | None) -> float:
    if not anchor_keywords:
        return 0.0
    candidate_tokens = set()
    for part in candidate_parts:
        candidate_tokens.update(_tokenise(part))
    if not candidate_tokens:
        return 0.0

    overlap = 0.0
    for kw in anchor_keywords:
        if kw in candidate_tokens:
            overlap += 1.0

    score = overlap / max(1.0, len(anchor_keywords))
    joined = " ".join(candidate_tokens)

    if any(k in joined for k in ("spy", "espionage", "cia", "kgb", "undercover", "agent", "intelligence")):
        score += 0.08
    if any(k in joined for k in ("crime", "thriller", "mystery", "murder", "political", "cartel", "drug", "criminal", "antihero")):
        score += 0.06
    if any(k in joined for k in ("period", "historical", "medical", "hospital", "nurse", "family", "community", "romance", "midwife", "women", "village")):
        score += 0.07
    if any(k in joined for k in ("finance", "billionaire", "hedge", "fund", "wealth", "corporate", "ambition", "business", "money", "deal", "elite", "lawyer", "attorney", "company", "ceo", "boardroom", "shareholder", "merger", "acquisition", "tycoon")):
        score += 0.12

    return float(min(score, 1.0))


def _genre_overlap_score(anchor_genre_ids: set[int], candidate_genre_ids: set[int]) -> float:
    if not anchor_genre_ids or not candidate_genre_ids:
        return 0.0
    overlap = len(anchor_genre_ids & candidate_genre_ids)
    union = len(anchor_genre_ids | candidate_genre_ids) or 1
    base = overlap / union
    if overlap >= 2:
        base += 0.10
    return float(min(base, 1.0))


def _bayesian_quality_score(vote_average: float, vote_count: int, global_mean: float = 6.8, m: int = 150) -> float:
    """
    IMDb-style smoothing to avoid tiny-vote shows floating too high.
    Returns roughly 0..1.
    """
    v = max(0, int(vote_count or 0))
    r = max(0.0, float(vote_average or 0.0))
    weighted = ((v / (v + m)) * r) + ((m / (v + m)) * global_mean) if (v + m) > 0 else global_mean
    return max(0.0, min(1.0, weighted / 10.0))


def _quality_bonus(vote_average: float, vote_count: int, popularity: float) -> float:
    bonus = 0.0
    if vote_average >= 8.4 and vote_count >= 400:
        bonus += 0.18
    elif vote_average >= 8.0 and vote_count >= 200:
        bonus += 0.13
    elif vote_average >= 7.6 and vote_count >= 100:
        bonus += 0.08

    if popularity >= 25:
        bonus += 0.06
    elif popularity >= 15:
        bonus += 0.03

    return bonus


def _confidence_factor(vote_count: int, popularity: float) -> float:
    vote_conf = min(1.0, math.log10(max(1, vote_count) + 1) / 2.2)
    pop_conf = min(1.0, math.log10(max(1.0, popularity) + 1.0) / 1.5)
    return 0.55 + (0.30 * vote_conf) + (0.15 * pop_conf)


def _passes_seo_quality_floor(
    *,
    vote_average: float,
    vote_count: int,
    popularity: float,
    semantic_score: float,
    genre_score: float,
    is_reddit: bool,
    is_tmdb: bool,
    is_trending: bool,
) -> bool:
    if vote_count < ABS_MIN_VOTE_COUNT:
        return False
    if popularity < ABS_MIN_POPULARITY:
        return False
    if vote_average < 6.3:
        return False

    if (
        vote_count >= SEO_MIN_VOTE_COUNT
        and vote_average >= SEO_MIN_VOTE_AVERAGE
        and popularity >= SEO_MIN_POPULARITY
    ):
        return True

    strong_match = semantic_score >= 0.24 or genre_score >= 0.22
    elite_quality = vote_average >= 7.6 and popularity >= 12.0
    decent_volume = vote_count >= 25

    if strong_match and elite_quality and decent_volume:
        if is_reddit and not (is_tmdb or is_trending):
            return vote_count >= 60
        if is_tmdb and not is_reddit:
            return semantic_score >= 0.20 or genre_score >= 0.20
        return True

    return False


def _natural_join(items: list[str]) -> str:
    vals = [str(x).strip() for x in items if str(x).strip()]
    if not vals:
        return ""
    if len(vals) == 1:
        return vals[0]
    if len(vals) == 2:
        return f"{vals[0]} and {vals[1]}"
    return f"{', '.join(vals[:-1])}, and {vals[-1]}"


def _top_titles(results: list[dict], max_n: int = 3) -> list[str]:
    out: list[str] = []
    for item in results[:max_n]:
        title = str(item.get("title") or "").strip()
        if title:
            out.append(title)
    return out


def _top_genres(results: list[dict], max_n: int = 2) -> list[str]:
    counts: Counter[str] = Counter()
    for item in results:
        genres = item.get("genres") or []
        if not isinstance(genres, list):
            continue
        for g in genres:
            name = str(g or "").strip()
            if name:
                counts[name] += 1
    return [name for name, _ in counts.most_common(max_n)]


def _genre_name_set(details: dict) -> set[str]:
    vals = set()
    for g in details.get("genres") or []:
        name = str(g or "").strip().lower()
        if name:
            vals.add(name)
    return vals


def _anchor_profile(anchor_details: dict) -> dict[str, bool]:
    genre_names = _genre_name_set(anchor_details)
    text_blob = " ".join(
        [
            str(anchor_details.get("title") or anchor_details.get("name") or ""),
            str(anchor_details.get("overview") or ""),
            " ".join(anchor_details.get("genres") or []),
            " ".join(anchor_details.get("seo_keywords") or []),
        ]
    ).lower()

    has = lambda *terms: any(t in text_blob for t in terms)

    is_actionish = bool(
        {"action & adventure", "crime", "sci-fi & fantasy", "animation"} & genre_names
    )
    is_grounded_drama = "drama" in genre_names and not is_actionish
    is_period = (
        "war & politics" in genre_names
        or has("period", "historical", "victorian", "georgian", "post-war", "postwar", "1950", "1960", "1940", "18th", "19th")
    )
    medical_terms = (
        "midwife",
        "nurse",
        "nurses",
        "hospital",
        "medical",
        "doctor",
        "maternity",
        "clinic",
        "patient",
        "patients",
    )

    community_family_terms = (
        "community",
        "village",
        "mother",
        "women",
        "relationships",
    )

    romance_terms = (
        "romance",
        "romantic",
        "love story",
        "courtship",
    )

    is_medical_family = has(*medical_terms) or (
        is_grounded_drama
        and has(*community_family_terms)
        and has("care", "health", "maternity", "midwife", "nurse", "doctor")
    )

    prefers_romance_family = (
        is_period
        or has(*romance_terms)
        or (
            is_grounded_drama
            and has("community", "village")
            and has("relationships", "marriage", "romance", "love")
        )
    )
    
    avoids_action_crime = is_grounded_drama and not has("crime", "murder", "detective", "police", "gang", "spy", "espionage")
    avoids_speculative = is_grounded_drama and not has("supernatural", "fantasy", "alien", "future", "post-apocalyptic", "superhero")

    return {
        "grounded_drama": is_grounded_drama,
        "period": is_period,
        "medical_family": is_medical_family,
        "prefers_romance_family": prefers_romance_family,
        "avoids_action_crime": avoids_action_crime,
        "avoids_speculative": avoids_speculative,
        "is_scifi": 10765 in set(anchor_details.get("genre_ids") or []),
        "is_animation": 16 in set(anchor_details.get("genre_ids") or []),
    }

def _anchor_theme_flags(anchor_title: str, anchor_details: dict) -> dict[str, bool]:
    title_lower = str(anchor_title or "").lower()
    overview = str(anchor_details.get("overview") or "").lower()
    genre_names = _genre_name_set(anchor_details)
    blob = f"{title_lower} {overview}"

    def has(*terms: str) -> bool:
        return any(term in blob for term in terms)

    epic_scifi = (
        title_lower in {"foundation", "the expanse", "for all mankind"}
        or has("empire", "civilization", "civilisation", "galaxy", "planet", "space program", "psychohistory", "dynasty", "interplanetary")
    ) and "sci-fi & fantasy" in genre_names

    dystopian_survival_scifi = (
        title_lower in {"silo", "snowpiercer"}
        or has("dystopian", "bunker", "underground", "sealed", "silo", "vault", "survival", "authoritarian", "controlled society")
    ) and "sci-fi & fantasy" in genre_names

    return {
        "finance_power": has(
            "finance", "hedge fund", "wall street", "billionaire", "wealth",
            "corporate", "business", "money", "elite", "attorney",
            "lawyer", "prosecutor", "empire", "conglomerate", "media empire",
            "company", "shareholder", "merger", "acquisition", "tycoon"
        ) or title_lower in {"billions", "succession", "industry"},
        "period_community": has(
            "period", "historical", "post-war", "postwar", "1950", "1960",
            "community", "village", "women", "midwife", "maternity"
        ),
        "warm_medical": has(
            "midwife", "maternity", "nurse", "nurses", "community care"
        ),
        "crime_antihero": (
            "crime" in genre_names
            or has("cartel", "drug", "criminal", "lawyer", "murder", "gang", "antihero", "mob")
        ),
        "epic_scifi": epic_scifi,
        "space_opera": epic_scifi or has("space", "galaxy", "fleet", "ship", "starship", "interplanetary"),
        "hard_scifi": has("nasa", "science", "experiment", "time travel", "technology", "future", "colony", "asteroid", "space program"),
        "dystopian_survival_scifi": dystopian_survival_scifi,
        "contained_society_scifi": dystopian_survival_scifi or has("contained", "sealed", "bunker", "vault", "underground", "enclosed"),
    }

def _candidate_theme_flags(details: dict) -> dict[str, bool]:
    overview = str(details.get("overview") or "").lower()
    title = str(details.get("title") or details.get("name") or "").lower()
    genre_names = _genre_name_set(details)
    blob = f"{title} {overview}"

    def has(*terms: str) -> bool:
        return any(term in blob for term in terms)

    return {
        "finance_power": has(
            "finance", "hedge fund", "wall street", "billionaire", "wealth",
            "corporate", "business", "money", "elite", "executive",
            "ceo", "boardroom", "empire", "conglomerate", "media", "attorney",
            "lawyer", "prosecutor", "firm", "broker", "trading", "investment",
            "company", "dynasty", "inheritance", "shareholder",
            "merger", "acquisition", "owner", "tycoon"
        ),
        "corporate_drama": has(
            "executive", "ceo", "company", "boardroom", "conglomerate", "media",
            "shareholder", "merger", "acquisition", "dynasty", "owner", "tycoon",
            "family empire", "business empire", "inheritance", "corporate", "empire"
        ),
        "period_community": has(
            "period", "historical", "post-war", "postwar", "1950", "1960",
            "community", "village", "women", "family", "rural", "small town"
        ),
        "warm_medical": has(
            "midwife", "maternity", "nurse", "nurses", "community care", "district nurse"
        ),
        "modern_hospital": has(
            "hospital", "trauma", "emergency department", "resident", "surgery",
            "frontlines", "medical center", "senior resident", "doctor"
        ),
        "crime_antihero": (
            "crime" in genre_names
            or has("cartel", "drug", "criminal", "lawyer", "murder", "gang", "antihero", "mob", "underworld")
        ),
        "teen_chaos": has("high school", "teen", "teenager", "social media", "party"),
        "epic_scifi": has("empire", "civilization", "civilisation", "galaxy", "planet", "fleet", "interplanetary", "space program") or title in {"for all mankind", "foundation", "the expanse"},
        "space_opera": has("space", "ship", "starship", "galaxy", "fleet", "planet", "interplanetary", "colony"),
        "hard_scifi": has("nasa", "science", "experiment", "technology", "future", "time travel", "asteroid", "space program"),
        "dystopian_survival_scifi": has("dystopian", "survival", "post-apocalyptic", "authoritarian", "controlled society", "wasteland", "frozen wasteland"),
        "contained_society_scifi": has("contained", "sealed", "bunker", "vault", "underground", "silo", "enclosed"),
        "fantasy_magic": has("magic", "wizard", "dragon", "prophecy", "kingdom", "sorcer", "dream", "angel"),
        "franchise_space_action": title in {"the mandalorian", "ahsoka", "star wars: maul - shadow lord"} or has("jedi", "empire", "rebel hero"),
        "animated": 16 in set(details.get("genre_ids") or []),
    }

def _candidate_fit_adjustment(anchor_profile: dict[str, bool], details: dict) -> tuple[bool, float]:
    genre_names = _genre_name_set(details)
    text_blob = " ".join(
        [
            str(details.get("title") or details.get("name") or ""),
            str(details.get("overview") or ""),
            " ".join(details.get("genres") or []),
        ]
    ).lower()

    has = lambda *terms: any(t in text_blob for t in terms)

    bonus = 0.0

    is_action = "action & adventure" in genre_names
    is_crime = "crime" in genre_names
    is_speculative = bool({"sci-fi & fantasy", "animation"} & genre_names) or has(
        "superhero", "vigilante", "marvel", "comic", "alien", "fantasy", "supernatural", "post-apocalyptic"
    )
    is_period = "war & politics" in genre_names or has(
        "period", "historical", "victorian", "georgian", "18th", "19th", "1940", "1950", "1960", "post-war", "postwar"
    )
    is_medical = has("midwife", "nurse", "nurses", "hospital", "medical", "doctor", "ward", "clinic", "maternity")
    is_family_community = has("family", "community", "village", "small town", "mother", "marriage", "women") or "family" in genre_names
    is_romance = has("romance", "romantic", "love", "marriage", "courtship")
    is_finance_power = has(
        "finance", "billionaire", "hedge fund", "hedge", "wall street", "corporate",
        "wealth", "money", "ambition", "deal", "power struggle", "power broker",
        "ceo", "executive", "boardroom", "empire", "elite", "attorney", "lawyer",
        "company", "shareholder", "merger", "acquisition", "tycoon"
    )
    

    if anchor_profile["avoids_speculative"] and is_speculative:
        return False, 0.0

    if anchor_profile["avoids_action_crime"] and (is_action or is_crime):
        if not (is_period or is_medical or is_family_community):
            return False, 0.0

    if anchor_profile["period"]:
        if is_period:
            bonus += 0.18
        elif not (is_medical or is_family_community or is_romance):
            return False, 0.0

    if anchor_profile["medical_family"]:
        if is_medical:
            bonus += 0.18
        elif is_family_community:
            bonus += 0.10
        elif not (is_period or is_romance):
            return False, 0.0

    if anchor_profile["prefers_romance_family"]:
        if is_family_community:
            bonus += 0.08
        if is_romance:
            bonus += 0.06

    if anchor_profile["grounded_drama"] and "drama" in genre_names:
        bonus += 0.05

    if is_finance_power:
        bonus += 0.10

    return True, bonus


def _anchor_descriptor(anchor_title: str, anchor_details: dict) -> dict[str, str | list[str]]:
    title_lower = str(anchor_title or "").lower()
    genre_names = _genre_name_set(anchor_details)
    overview = str(anchor_details.get("overview") or "").lower()
    blob = f"{title_lower} {overview}"

    def has(*terms: str) -> bool:
        return any(term in blob for term in terms)

    themes: list[str] = []
    mood = "character-driven"
    angle = "storytelling"
    audience_hook = "a similar overall feel"

    if title_lower in {"foundation", "the expanse", "for all mankind"} or ("sci-fi & fantasy" in genre_names and has("empire", "civilization", "galaxy", "planet", "space", "fleet", "interplanetary", "space program")):
        themes = ["world-building", "large-scale conflict", "big-idea sci-fi"]
        mood = "sweeping"
        angle = "epic sci-fi storytelling"
        audience_hook = "scale, politics and long-form sci-fi payoff"
    elif title_lower in {"silo", "snowpiercer"} or ("sci-fi & fantasy" in genre_names and has("dystopian", "bunker", "vault", "underground", "survival", "authoritarian", "controlled society")):
        themes = ["survival pressure", "contained mystery", "dystopian tension"]
        mood = "claustrophobic"
        angle = "closed-world sci-fi storytelling"
        audience_hook = "mystery, pressure and a controlled-world atmosphere"
    elif has("finance", "billionaire", "hedge fund", "wall street", "corporate", "wealth", "money", "power", "ambition", "media conglomerate", "empire") or title_lower in {"billions", "succession", "industry"}:
        themes = ["power plays", "elite rivalry", "high-stakes ambition"]
        mood = "sharp and intense"
        angle = "status-driven drama"
        audience_hook = "power, money and strategic conflict"
    elif has("time travel", "parallel", "dystopian", "future", "alien") or "sci-fi & fantasy" in genre_names:
        themes = ["big ideas", "mystery", "long-form payoff"]
        mood = "atmospheric"
        angle = "concept-heavy storytelling"
        audience_hook = "mystery, world-building and payoff over time"
    elif "crime" in genre_names or has("cartel", "criminal", "drug", "lawyer", "detective", "murder", "gang", "antihero", "mob"):
        themes = ["moral pressure", "high-stakes choices", "tense character drama"]
        mood = "tense"
        angle = "pressure-cooker plotting"
        audience_hook = "the same mix of tension and character consequences"
    elif has("midwife", "hospital", "doctor", "nurse", "maternity"):
        themes = ["community", "compassion", "emotionally grounded stories"]
        mood = "warm but emotional"
        angle = "human stories"
        audience_hook = "heart, warmth and a strong sense of place"
    elif has("historical", "period", "victorian", "post-war", "postwar", "1950", "1960") or "war & politics" in genre_names:
        themes = ["period detail", "social change", "strong ensemble drama"]
        mood = "richly textured"
        angle = "period storytelling"
        audience_hook = "setting, relationships and social texture"
    elif has("spy", "espionage", "agent", "intelligence", "undercover"):
        themes = ["double lives", "secrecy", "slow-burn suspense"]
        mood = "suspenseful"
        angle = "cloak-and-dagger tension"
        audience_hook = "carefully built suspense and competing loyalties"
    
    elif has("family", "marriage", "community", "small town", "village"):
        themes = ["community", "relationships", "emotional connection"]
        mood = "warm"
        angle = "character-led storytelling"
        audience_hook = "relationships, atmosphere and character connection"
    else:
        themes = ["tone", "memorable characters", "story momentum"]

    return {
        "themes": themes[:3],
        "mood": mood,
        "angle": angle,
        "audience_hook": audience_hook,
    }

def _pick_faq_variant(anchor_title: str, anchor_details: dict, top_titles_text: str, genre_text: str, descriptor: dict[str, str | list[str]]) -> list[dict]:
    title_lower = str(anchor_title or "").lower()
    overview = str(anchor_details.get("overview") or "").lower()
    genre_names = _genre_name_set(anchor_details)
    blob = f"{title_lower} {overview}"
    themes = descriptor.get("themes") or []
    if not isinstance(themes, list):
        themes = []
    theme_text = _natural_join([str(t) for t in themes[:3]])

    def has(*terms: str) -> bool:
        return any(term in blob for term in terms)

    if has("midwife", "hospital", "doctor", "nurse", "maternity"):
        return [
            {
                "question": f"Which shows capture the same warmth as {anchor_title}?",
                "answer": f"Series like {top_titles_text or 'these picks'} work well because they balance emotion, community and ongoing personal stories in a way fans of {anchor_title} often respond to.",
            },
            {
                "question": f"Are these recommendations as gentle as {anchor_title}?",
                "answer": f"Not every show here has exactly the same tone, but they were chosen because they share some combination of compassion, character focus and emotionally grounded storytelling rather than relying on spectacle alone.",
            },
            {
                "question": f"What should I watch after {anchor_title} for more character-led drama?",
                "answer": f"Start with {top_titles_text or 'the highest-ranked titles'} if you want more relationship-driven storytelling, a strong sense of place and characters you can settle in with over time.",
            },
            {
                "question": f"Where can I find more shows tailored to my taste?",
                "answer": "WhatNext lets you save favourites, build a watchlist and rate what you have seen so future recommendations become more personalised over time.",
            },
        ]

    if has("historical", "period", "victorian", "post-war", "postwar", "1950", "1960") or "war & politics" in genre_names:
        return [
            {
                "question": f"Which shows offer a similar period feel to {anchor_title}?",
                "answer": f"These recommendations lean toward dramas that pair strong character work with a vivid setting, so they feel close to {anchor_title} in atmosphere as well as subject matter.",
            },
            {
                "question": f"What makes a good follow-up to {anchor_title}?",
                "answer": f"For most viewers it is not just the historical backdrop. It is the mix of relationships, social pressure and slow-building drama, which is why {top_titles_text or 'these shows'} rose to the top.",
            },
            {
                "question": f"Are these shows similar to {anchor_title} because of genre alone?",
                "answer": f"No. The list is filtered for tone and story shape too, so it prioritises shows that share {theme_text or 'character depth and atmosphere'} rather than matching on a broad genre label only.",
            },
            {
                "question": f"How can I get even better recommendations after {anchor_title}?",
                "answer": "Add a few favourites to WhatNext, rate anything you have already watched and the recommendation mix will sharpen around your own taste rather than a single title.",
            },
        ]

    if has("finance", "billionaire", "hedge fund", "wall street", "corporate", "wealth", "money", "power", "ambition") or title_lower in {"billions", "succession", "industry"}:
        return [
            {
                "question": f"What should I watch after {anchor_title} for more power and money drama?",
                "answer": f"Start with {top_titles_text or 'the top-ranked series here'} if you want more ambition, strategic rivalry and high-status drama built around power plays rather than action spectacle.",
            },
            {
                "question": f"Are these shows similar to {anchor_title} because of finance alone?",
                "answer": f"No. The ranking looks beyond a business setting and favours series that share the same mix of pressure, status, ego and long-running conflict.",
            },
            {
                "question": f"Why do fans of {anchor_title} often end up watching these next?",
                "answer": f"They usually respond to {theme_text or 'power, rivalry and elite conflict'}, so the page prioritises series that recreate that feeling instead of just matching on industry keywords.",
            },
            {
                "question": f"How can I get more recommendations like {anchor_title}?",
                "answer": "Save a few favourites in WhatNext, add shows to your watchlist and rate what you have already seen so future recommendations line up more closely with your taste.",
            },
        ]

    if "sci-fi & fantasy" in genre_names or has("future", "alien", "time travel", "parallel", "dystopian"):
        return [
            {
                "question": f"Which shows scratch the same itch as {anchor_title}?",
                "answer": f"These are not just similar on genre. They were chosen because they offer a related mix of mystery, world-building and long-form payoff for viewers who connected with {anchor_title}.",
            },
            {
                "question": f"What should I watch after {anchor_title} for more big-idea storytelling?",
                "answer": f"{top_titles_text or 'The top picks on this page'} are a good place to start if you want another series that unfolds gradually and rewards attention over time.",
            },
            {
                "question": f"Are these recommendations more about mood or plot?",
                "answer": f"Usually both. The strongest matches tend to share atmosphere as well as structure, so the page does not just chase shows with similar premises.",
            },
            {
                "question": f"How do I find more shows once I finish these?",
                "answer": "Build up your favourites and ratings in WhatNext and the app can keep narrowing in on the sci-fi and fantasy shows that suit your taste best.",
            },
        ]

    if "crime" in genre_names or has("crime", "murder", "detective", "cartel", "lawyer", "drug", "criminal"):
        return [
            {
                "question": f"What should I watch after {anchor_title} if I want the same tension?",
                "answer": f"Start with {top_titles_text or 'the strongest picks here'} because they keep the pressure high and stay focused on character consequences instead of feeling like generic crime TV.",
            },
            {
                "question": f"Do these shows match the tone of {anchor_title}?",
                "answer": f"That is the aim. The ranking favours series with a similar blend of atmosphere, conflict and long-form payoff, not just surface-level plot similarities.",
            },
            {
                "question": f"Why are fans of {anchor_title} often drawn to these series?",
                "answer": f"Because they tap into {theme_text or 'tension, escalation and memorable characters'}, which is usually what keeps viewers hooked once they finish {anchor_title}.",
            },
            {
                "question": f"Where can I keep track of crime dramas I want to watch next?",
                "answer": "Use WhatNext to save favourites, keep a watchlist and improve future recommendations based on what you actually enjoy.",
            },
        ]

    return [
        {
            "question": f"Why do fans of {anchor_title} often like these shows too?",
            "answer": f"They tend to share {theme_text or 'tone, character depth and story momentum'}, which is often a better guide than genre alone when you are deciding what to watch next.",
        },
        {
            "question": f"What should I watch after {anchor_title}?",
            "answer": f"{top_titles_text or 'The top-ranked titles here'} are a strong place to start because they echo the overall feel of {anchor_title} without being carbon copies of it.",
        },
        {
            "question": f"How were these shows chosen?",
            "answer": f"The ranking blends audience behaviour with similarity signals, then filters for stronger tonal fit so the final list feels closer to what fans of {anchor_title} usually want.",
        },
        {
            "question": f"Where can I get more personalised recommendations?",
            "answer": "WhatNext improves as you add favourites, build a watchlist and rate shows you have already seen.",
        },
    ]



def _score_to_match_percent(score: float | int | None) -> int:
    """Convert the internal recommendation score into a user-facing match %.

    Internal recommendation scores are not probabilities. This mapping keeps
    the displayed percentage meaningful while preserving visible differences
    between exceptional, strong and secondary recommendations.
    """
    try:
        val = float(score or 0.0)
    except Exception:
        val = 0.0

    if val >= 2.70:
        return 96
    if val >= 2.40:
        return 93
    if val >= 2.10:
        return 90
    if val >= 1.80:
        return 86
    if val >= 1.55:
        return 82
    if val >= 1.30:
        return 78
    if val >= 1.05:
        return 74
    if val >= 0.80:
        return 70

    return 66


def _short_overview(text_val: str | None, max_chars: int = 210) -> str:
    text_clean = re.sub(r"\s+", " ", str(text_val or "")).strip()
    if len(text_clean) <= max_chars:
        return text_clean
    return text_clean[: max_chars - 1].rsplit(" ", 1)[0].strip() + "…"


def _genre_overlap_names(anchor_details: dict, item: dict, max_n: int = 3) -> list[str]:
    anchor_genres = {str(g).strip().lower() for g in (anchor_details.get("genres") or []) if str(g).strip()}
    item_genres = [str(g).strip() for g in (item.get("genres") or []) if str(g).strip()]
    return [g for g in item_genres if g.lower() in anchor_genres][:max_n]


def _source_reason_label(source: str) -> str:
    source = str(source or "").strip()
    if source == "multi_signal":
        return "Multiple signals agree: audience behaviour and recommendation similarity both point to this title."
    if source == "reddit_pairs":
        return "Audience behaviour signal: viewers discussing similar shows often move toward this title."
    if source == "tmdb_recs":
        return "Recommendation graph signal: this title appears close to the anchor show in recommendation data."
    if source == "semantic_fallback":
        return "Story-shape signal: this title was selected because its themes and tone are a close fit."
    return "Quality fallback: this title survived the same relevance and quality filters as the main recommendations."


def _recommendation_match_reasons(anchor_title: str, anchor_details: dict, item: dict) -> list[str]:
    """Build concise, visible reasons Google and users can understand."""
    reasons: list[str] = []
    overlap = _genre_overlap_names(anchor_details, item)
    if overlap:
        reasons.append(f"Shared genre fit: {_natural_join(overlap)}")

    source_label = _source_reason_label(str(item.get("source") or ""))
    if source_label:
        reasons.append(source_label)

    vote_average = float(item.get("vote_average") or 0.0)
    vote_count = int(item.get("vote_count") or 0)
    if vote_average >= 8.0 and vote_count >= 200:
        reasons.append(f"Strong audience quality signal: {vote_average:.1f}/10 from {vote_count:,} votes")
    elif vote_average >= 7.2 and vote_count >= 100:
        reasons.append(f"Solid audience quality signal: {vote_average:.1f}/10 from {vote_count:,} votes")

    anchor_descriptor = _anchor_descriptor(anchor_title, anchor_details)
    themes = anchor_descriptor.get("themes") or []
    if isinstance(themes, list) and themes:
        item_blob = _blob_for(item)
        matched_themes = [str(t) for t in themes if str(t).lower() in item_blob]
        if matched_themes:
            reasons.append(f"Theme overlap: {_natural_join(matched_themes[:2])}")
        else:
            reasons.append(f"Chosen for a similar {anchor_descriptor.get('angle') or 'storytelling'} feel")

    # Keep cards readable. The expanded explanation below carries the longer copy.
    clean: list[str] = []
    for reason in reasons:
        if reason and reason not in clean:
            clean.append(reason)
    return clean[:5]


def _why_recommended(anchor_title: str, anchor_details: dict, item: dict) -> str:
    title = str(item.get("title") or "this show").strip()
    descriptor = _anchor_descriptor(anchor_title, anchor_details)
    audience_hook = str(descriptor.get("audience_hook") or "a similar overall feel")
    angle = str(descriptor.get("angle") or "storytelling")
    overview = _short_overview(str(item.get("overview") or ""), 220)
    reasons = _recommendation_match_reasons(anchor_title, anchor_details, item)

    reason_sentence = " ".join(reasons[:2]) if reasons else f"It shares {audience_hook}."
    if overview:
        return (
            f"{title} is a strong follow-up to {anchor_title} because it offers {audience_hook} and a comparable sense of {angle}. "
            f"{reason_sentence} In practical terms, {overview}"
        )
    return (
        f"{title} is a strong follow-up to {anchor_title} because it offers {audience_hook} and a comparable sense of {angle}. "
        f"{reason_sentence}"
    )


def _enrich_recommendations_for_seo(anchor_title: str, anchor_details: dict, results: list[dict]) -> list[dict]:
    """Expose the recommendation engine's reasoning in the API response.

    This is deliberately additive: existing frontend fields are preserved, while
    new fields can be used to create richer indexable content on the SEO pages.
    """
    enriched: list[dict] = []
    for idx, item in enumerate(results, start=1):
        enriched_item = dict(item)
        enriched_item["rank"] = idx
        enriched_item["match_percent"] = _score_to_match_percent(item.get("score"))
        enriched_item["match_reasons"] = _recommendation_match_reasons(anchor_title, anchor_details, item)
        enriched_item["why_recommended"] = _why_recommended(anchor_title, anchor_details, item)
        enriched_item["source_explanation"] = _source_reason_label(str(item.get("source") or ""))
        enriched.append(enriched_item)
    return enriched


def _build_page_copy(anchor_title: str, anchor_details: dict, results: list[dict]) -> dict:
    titles = _top_titles(results, 3)
    top_titles_text = _natural_join(titles)

    genres = _top_genres(results, 2)
    genre_text = ""
    if len(genres) == 1:
        genre_text = genres[0].lower()
    elif len(genres) >= 2:
        genre_text = f"{genres[0].lower()} and {genres[1].lower()}"

    sources = {str(r.get("source") or "").strip() for r in results}
    has_reddit = "reddit_pairs" in sources or "multi_signal" in sources
    has_tmdb = "tmdb_recs" in sources or "multi_signal" in sources
    has_semantic = "semantic_fallback" in sources

    descriptor = _anchor_descriptor(anchor_title, anchor_details)
    themes = descriptor.get("themes") or []
    if not isinstance(themes, list):
        themes = []
    theme_text = _natural_join([str(t) for t in themes[:3]])
    mood = str(descriptor.get("mood") or "character-driven")
    angle = str(descriptor.get("angle") or "storytelling")
    audience_hook = str(descriptor.get("audience_hook") or "a similar overall feel")

    intro_parts: list[str] = []
    if top_titles_text:
        intro_parts.append(
            f"If {anchor_title} worked for you because of its {theme_text or mood}, start with {top_titles_text}."
        )
    else:
        intro_parts.append(
            f"If you are looking for shows like {anchor_title}, this page focuses on series that echo its {theme_text or mood}."
        )

    if genre_text:
        intro_parts.append(
            f"The list leans toward {genre_text} stories with a similar sense of {angle}."
        )

    if has_reddit and has_tmdb:
        intro_parts.append(
            "It is built from both audience viewing patterns and close-match recommendation signals, then filtered more aggressively for relevance and title quality."
        )
    elif has_reddit:
        intro_parts.append(
            f"It gives extra weight to the shows viewers most often move to after finishing {anchor_title}, but only after stronger quality and fit checks."
        )
    elif has_semantic:
        intro_parts.append(
            "It prioritises shared tone and story shape rather than relying on broad genre matching alone."
        )
    else:
        intro_parts.append(
            f"The goal is to surface shows that recreate {audience_hook}."
        )

    intro = " ".join(intro_parts)

    seo_blurb = (
        f"Fans of {anchor_title} usually respond to some combination of {theme_text or mood}. "
        f"That is why this list highlights {top_titles_text or 'closely matched series'} instead of simply pulling in every {genre_text or 'related'} title."
    )
    if genre_text and top_titles_text:
        seo_blurb = (
            f"If you enjoyed {anchor_title}, try {top_titles_text}. These recommendations focus on {genre_text} shows that share {audience_hook} and a similar storytelling rhythm."
        )

    what_makes_good_match = (
        f"A good replacement for {anchor_title} is not just another show in the same broad genre. "
        f"The best matches keep the parts viewers remember most: {theme_text or mood}, a {mood} atmosphere and {angle}. "
        "That is why the ranking combines several signals before a title reaches the final list."
    )

    how_chosen = [
        "Audience behaviour: Reddit-style co-mentions and pair signals help identify shows viewers naturally compare or recommend together.",
        "Recommendation graph: TMDB recommendation data helps identify titles that sit close to the anchor show.",
        "Story fit: genre overlap, semantic keywords and concept-specific guardrails reduce lazy matches that share only a surface-level category.",
        "Quality control: vote average, vote count, popularity and freshness checks help remove weak or low-confidence titles from public SEO pages.",
    ]

    best_for: list[dict] = []
    for item in results[:6]:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        reasons = _recommendation_match_reasons(anchor_title, anchor_details, item)
        best_for.append(
            {
                "title": title,
                "match_percent": _score_to_match_percent(item.get("score")),
                "best_for": reasons[0] if reasons else f"Viewers who want {audience_hook}.",
                "why": _why_recommended(anchor_title, anchor_details, item),
            }
        )

    related_page_links = []
    for item in results[:10]:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        if slug:
            related_page_links.append(
                {
                    "title": f"Shows like {title}",
                    "href": f"/shows-like/{slug}",
                }
            )

    faq_items = _pick_faq_variant(anchor_title, anchor_details, top_titles_text, genre_text, descriptor)

    return {
        "intro": intro,
        "seo_blurb": seo_blurb,
        "top_titles_text": top_titles_text,
        "top_genres": genres,
        "audience_profile": {
            "headline": f"Why {anchor_title} fans may like these shows",
            "themes": themes[:3],
            "mood": mood,
            "storytelling_angle": angle,
            "hook": audience_hook,
            "summary": (
                f"This page is tuned for viewers who want {audience_hook}. "
                f"It favours shows with {theme_text or mood}, not just titles that happen to share a genre label."
            ),
        },
        "content_sections": [
            {
                "heading": f"What makes a good show like {anchor_title}?",
                "body": what_makes_good_match,
            },
            {
                "heading": "How these recommendations are chosen",
                "body": " ".join(how_chosen),
                "bullets": how_chosen,
            },
            {
                "heading": "Editor's verdict",
                "body": (
                    f"The strongest starting point is {top_titles_text or 'the top-ranked titles'} because the list balances similarity, quality and viewer behaviour. "
                    f"For best results, choose the recommendation that matches the part of {anchor_title} you liked most: tone, characters, setting, mystery, tension or long-form payoff."
                ),
            },
        ],
        "best_for": best_for,
        "related_page_links": related_page_links,
        "faq_items": faq_items,
    }

def _is_future_or_too_fresh_for_seo(first_air_date: str | None, vote_count: int) -> bool:
    if vote_count < SEO_FRESH_MIN_VOTE_COUNT and first_air_date:
        try:
            year = int(str(first_air_date)[:4])
            if year >= CURRENT_YEAR:
                return True
        except Exception:
            pass
    return False


def _is_weak_scifi(details: dict) -> bool:
    overview = (details.get("overview") or "").lower()
    genres = set(details.get("genre_ids") or [])

    if 10765 not in genres:
        return True

    strong_terms = (
        "space", "future", "alien", "technology", "experiment", "time", "dystopian",
        "post-apocalyptic", "planet", "galaxy", "empire", "robot", "android",
        "survival", "nasa", "asteroid", "colony", "bunker", "vault", "underground",
        "fleet", "interplanetary"
    )
    return not any(k in overview for k in strong_terms)


def _anchor_fill_bucket(anchor_title: str, anchor_details: dict) -> str:
    flags = _anchor_theme_flags(anchor_title, anchor_details)
    if flags["dystopian_survival_scifi"] or flags["contained_society_scifi"]:
        return "dystopian"
    if flags["space_opera"] or flags["epic_scifi"]:
        return "space"
    return "general_scifi"



def _fill_fit_score(bucket: str, details: dict) -> float:
    title = str(details.get("title") or details.get("name") or "").lower()
    overview = str(details.get("overview") or "").lower()
    genres = set(details.get("genre_ids") or [])
    score = 0.0

    if 10765 in genres:
        score += 0.25
    if 18 in genres:
        score += 0.05
    if title in SCI_FI_CLASSICS:
        score += 0.22

    if bucket == "space":
        terms = (
            "space", "galaxy", "planet", "fleet", "ship", "starship",
            "interplanetary", "nasa", "colony", "empire", "asteroid", "station"
        )
        score += 0.28 * sum(t in overview for t in terms)
        if any(t in title for t in ("star trek", "stargate", "firefly", "andor", "halo", "expanse", "farscape", "battlestar")):
            score += 0.18
    elif bucket == "dystopian":
        contained_terms = (
            "bunker", "underground", "sealed", "silo", "vault", "quarantine",
            "containment", "contained", "enclosed", "isolated", "restricted",
            "authoritarian", "regime", "surveillance", "controlled society", "facility"
        )
        collapse_terms = (
            "collapse", "post-apocalyptic", "post apocalyptic", "survival", "wasteland"
        )
        wrong_vibe_terms = (
            "alien attack", "battlefield", "invasion", "soldiers", "war against",
            "supernatural", "vampire", "witch", "magic", "superhero"
        )

        contained_hits = sum(t in overview for t in contained_terms)
        collapse_hits = sum(t in overview for t in collapse_terms)

        score += 0.38 * contained_hits
        score += 0.10 * collapse_hits

        if contained_hits >= 2:
            score += 0.18
        elif contained_hits == 1:
            score += 0.08

        if any(t in title for t in ("silo", "snowpiercer", "12 monkeys", "colony")):
            score += 0.12

        if any(t in overview for t in wrong_vibe_terms):
            score -= 0.30
    else:
        terms = ("future", "technology", "experiment", "time", "alien", "parallel")
        score += 0.18 * sum(t in overview for t in terms)

    if 16 in genres:
        score -= 0.18
    if any(t in overview for t in ("wizard", "dragon", "magic", "sorcer", "angel")):
        score -= 0.25

    return score

def _passes_anchor_filter(item: dict, anchor_type: str) -> bool:
    overview = (item.get("overview") or "").lower()
    genres = set(item.get("genre_ids") or [])

    if anchor_type == "dystopian":
        strong = any(k in overview for k in [
            "bunker", "underground", "sealed", "silo", "vault",
            "quarantine", "containment", "contained", "enclosed",
            "authoritarian", "regime", "surveillance",
            "collapse", "post-apocalyptic", "post apocalyptic", "survival"
        ])

        if not strong:
            return False

        if any(k in overview for k in [
            "alien attack", "battlefield", "invasion", "soldiers",
            "supernatural", "vampire", "witch", "magic", "superhero"
        ]):
            return False

    elif anchor_type == "space_epic":
        if not any(k in overview for k in [
            "space", "planet", "galaxy", "ship", "colony",
            "station", "empire", "fleet"
        ]):
            return False

    return True


def _fill_score_boost(show: dict, anchor_type: str) -> float:
    genres = set(show.get("genre_ids") or [])
    title = (show.get("title") or "").lower()
    overview = (show.get("overview") or "").lower()

    score = 0.0

    if anchor_type == "space_epic":
        if any(k in overview for k in [
            "empire", "galaxy", "interstellar", "colony", "rebellion",
            "fleet", "station", "starship", "space"
        ]):
            score += 0.25
        if any(k in title for k in [
            "star", "galactica", "trek", "dune", "stargate", "farscape"
        ]):
            score += 0.25
        if 10759 in genres:
            score += 0.10

    elif anchor_type == "dystopian":
        contained_terms = [
            "bunker", "underground", "sealed", "silo", "vault",
            "containment", "contained", "quarantine", "enclosed",
            "authoritarian", "regime", "surveillance", "restricted", "facility"
        ]
        collapse_terms = ["collapse", "post-apocalyptic", "post apocalyptic", "survival"]

        contained_hits = sum(k in overview for k in contained_terms)
        collapse_hits = sum(k in overview for k in collapse_terms)

        score += 0.12 * contained_hits
        score += 0.04 * collapse_hits

        if contained_hits >= 2:
            score += 0.18
        elif contained_hits == 1:
            score += 0.08

        if 9648 in genres:
            score += 0.05

    elif anchor_type == "crime":
        if any(k in overview for k in ["cartel", "detective", "police", "crime", "murder"]):
            score += 0.30

    else:
        if 10765 in genres:
            score += 0.10

    return score



# ---------------------------------------------------------------------------
# Refactored SEO recommendation engine
# ---------------------------------------------------------------------------
# The old version had several overlapping gates: theme flags, concept gates,
# fill-only blocks and final post-filters. This version keeps the response shape
# the same, but moves concept fit into one reusable scoring path.

CONCEPT_RULES: dict[str, dict[str, object]] = {
    "space_franchise_adventure": {
        "required_any": [
            "star wars",
            "space",
            "galaxy",
            "planet",
            "ship",
            "starship",
            "jedi",
            "mandalorian",
            "bounty hunter",
            "rebel",
            "rebellion",
            "empire",
            "imperial",
            "new republic",
            "clone",
            "fleet",
            "colony",
            "colonies",
            "cylon",
            "space western",
        ],
        "boost_any": [
            "star wars",
            "jedi",
            "mandalorian",
            "bounty hunter",
            "rebel",
            "rebellion",
            "empire",
            "imperial",
            "new republic",
            "galaxy",
            "space western",
            "outlaw",
            "mercenary",
            "adventure",
            "planet",
            "ship",
            "fleet",
            "colony",
            "colonies",
            "cylon",
            "space western",
        ],
        "reject_any": [
            "superhero",
            "marvel",
            "dc comics",
            "vampire",
            "witch",
            "high school",
            "sitcom",
            "reality",
            "talk show",
        ],
        "preferred_genres": {10765, 10759, 16, 18},
        "strict": True,
    },

    "post_apocalyptic_survival": {
        "required_any": [
            "post-apocalyptic",
            "post apocalyptic",
            "apocalypse",
            "apocalyptic",
            "collapse",
            "survival",
            "survivors",
            "infection",
            "epidemic",
            "pandemic",
            "virus",
            "outbreak",
            "zombie",
        ],
        "boost_any": [
            "survival",
            "survivors",
            "infection",
            "epidemic",
            "pandemic",
            "virus",
            "outbreak",
            "zombie",
            "collapse",
            "dystopia",
            "dystopian",
            "humanity",
            "society",
            "journey",
        ],
        "avoid_any": [
            "workplace",
            "legal drama",
            "political drama",
            "royal family",
        ],
    },
    "space_epic": {
        "required_any": [
            "space", "planet", "galaxy", "ship", "starship", "fleet", "station",
            "colony", "interplanetary", "empire", "civilization", "civilisation",
            "nasa", "space program",
        ],
        "boost_any": [
            "space", "planet", "galaxy", "ship", "starship", "fleet", "station",
            "colony", "empire", "interplanetary", "civilization", "civilisation",
            "rebellion", "dynasty", "nasa", "space program",
        ],
        "reject_any": [
            "witch", "wizard", "magic", "dragon", "vampire", "high school",
            "superhero", "marvel", "dc comics",
        ],
        "preferred_genres": {10765, 10759, 18},
        "strict": True,
    },
    "contained_dystopia": {
        "required_any": [
            "bunker", "underground", "sealed", "silo", "vault", "contained",
            "containment", "enclosed", "isolated", "quarantine", "authoritarian",
            "regime", "restricted", "surveillance", "controlled", "facility",
            "experiment", "collapse", "post-apocalyptic", "post apocalyptic", "survival",
        ],
        "boost_any": [
            "bunker", "underground", "sealed", "silo", "vault", "contained",
            "containment", "enclosed", "isolated", "quarantine", "authoritarian",
            "regime", "restricted", "surveillance", "controlled", "facility",
            "experiment", "system", "mystery",
        ],
        "reject_any": [
            "alien attack", "battlefield", "invasion force", "war against",
            "soldiers", "vampire", "witch", "magic", "superhero", "high school",
        ],
        "preferred_genres": {10765, 9648, 18},
        "strict": True,
    },
    "mystery_box_survival": {
        "required_any": [
            "mystery", "missing", "disappearance", "survival", "survivors",
            "island", "stranded", "supernatural", "unexplained", "secret",
            "secrets", "time", "timeline", "alternate", "plane crash",
            "community", "experiment", "paranormal", "conspiracy", "unknown",
        ],
        "boost_any": [
            "mystery", "survival", "survivors", "island", "stranded",
            "supernatural", "unexplained", "secrets", "time travel",
            "timeline", "alternate reality", "ensemble", "community",
            "disappearance", "paranormal", "conspiracy", "plane crash",
            "unknown", "experiment",
        ],
        "reject_any": [
            "sitcom", "stand-up", "reality", "talk show", "sketch comedy",
            "cooking competition", "talent competition",
        ],
        "preferred_genres": {10765, 9648, 18},
        "strict": False,
    },
    "prestige_existential_mystery": {
        "required_any": [
            "disappear", "disappears", "disappearance", "vanish", "vanished",
            "missing", "unexplained", "mystery", "grief", "loss", "trauma",
            "faith", "spiritual", "cult", "apocalypse", "apocalyptic",
            "survivors", "community", "strange", "supernatural", "paranormal",
            "alternate", "reality", "identity", "consciousness",
        ],
        "boost_any": [
            "grief", "loss", "trauma", "faith", "spiritual", "cult",
            "disappearance", "vanished", "unexplained", "mystery",
            "supernatural", "paranormal", "apocalypse", "apocalyptic",
            "survivors", "community", "identity", "consciousness",
            "psychological", "existential",
        ],
        "reject_any": [
            "sitcom", "stand-up", "reality", "talk show", "talent competition",
            "medical center", "emergency department", "trauma center",
            "assassin", "procedural", "solve crimes", "case of the week",
            "superhero", "high school superhero",
        ],
        "preferred_genres": {18, 9648, 10765},
        "strict": False,
    },
    "time_mystery": {
        "required_any": [
            "time", "timeline", "time travel", "loop", "paradox", "parallel",
            "alternate", "generation", "generations", "missing", "mystery",
            "secret", "secrets", "past", "future",
        ],
        "boost_any": [
            "time travel", "timeline", "loop", "paradox", "parallel", "alternate",
            "generation", "generations", "missing", "mystery", "secret", "secrets",
        ],
        "reject_any": ["sitcom", "stand-up", "reality", "talk show"],
        "preferred_genres": {10765, 9648, 18, 80},
        "strict": False,
    },
    "corporate_mystery": {
        "required_any": [
            "office", "workplace", "corporate", "company", "memory", "identity",
            "experiment", "consciousness", "surveillance", "controlled", "facility",
            "secret", "mystery",
        ],
        "boost_any": [
            "office", "workplace", "corporate", "company", "memory", "identity",
            "experiment", "consciousness", "surveillance", "controlled", "facility",
            "secret", "mystery",
        ],
        "reject_any": ["wizard", "dragon", "vampire", "reality", "talk show"],
        "preferred_genres": {10765, 9648, 18},
        "strict": False,
    },
        "small_town_mystery": {
        "required_any": [
            "small town", "community", "local murder", "murder", "detective",
            "investigation", "missing", "secrets", "family", "personal life",
        ],
        "boost_any": [
            "small town", "community", "local murder", "detective",
            "investigation", "family", "secrets", "grief", "personal life",
        ],
        "reject_any": [
            "elite team", "fbi profilers", "procedural", "cases", "solve new cases",
            "unusual partnership", "superhero", "magic", "reality",
        ],
        "preferred_genres": {80, 18, 9648},
        "strict": False,
    },
    "crime_pressure": {
        "required_any": [
            "crime", "criminal", "murder", "detective", "police", "cartel", "drug",
            "gang", "mob", "mafia", "lawyer", "attorney", "corruption", "killer",
            "investigation", "heist", "prison", "underworld",
        ],
        "boost_any": [
            "crime", "criminal", "murder", "detective", "police", "cartel", "drug",
            "gang", "mob", "mafia", "lawyer", "attorney", "corruption", "killer",
            "investigation", "heist", "prison", "underworld", "moral", "dark",
        ],
        "reject_any": ["high school musical", "reality", "talk show"],
        "preferred_genres": {80, 18, 9648},
        "strict": False,
    },
    "detective_mystery": {
        "required_any": [
            "detective", "investigation", "murder", "killer", "case", "crime",
            "police", "fbi", "mystery", "missing", "secrets",
        ],
        "boost_any": [
            "detective", "investigation", "murder", "killer", "case", "crime",
            "police", "fbi", "mystery", "missing", "secrets", "serial",
        ],
        "reject_any": ["superhero", "magic", "wizard", "reality"],
        "preferred_genres": {80, 18, 9648},
        "strict": False,
    },
    "finance_power": {
        "required_any": [
            "finance", "hedge fund", "wall street", "bank", "banking",
            "billionaire", "wealth", "corporate", "business",
            "company", "ceo", "executive", "boardroom",
            "shareholder", "merger", "acquisition",
            "media empire", "conglomerate", "dynasty",
            "inheritance", "investment", "trading",
            "family empire", "business empire",
        ],
        "boost_any": [
            "finance", "hedge fund", "wall street", "bank", "banking",
            "billionaire", "wealth", "corporate", "business",
            "company", "ceo", "executive", "boardroom",
            "shareholder", "merger", "acquisition",
            "media empire", "conglomerate", "dynasty",
            "inheritance", "investment", "trading",
            "family empire", "business empire",
            "power", "ambition", "rivalry", "elite",
        ],
        "reject_any": [
            "high school", "teen", "supernatural",
            "vampire", "wizard", "superhero",
        ],
        "preferred_genres": {18, 80},
        "strict": False,
    },
    "political_diplomatic_drama": {
        "required_any": [
            "diplomat", "diplomacy", "diplomatic", "embassy",
            "ambassador", "foreign policy", "international relations",
            "state department", "foreign affairs",
            "politics", "political", "government",
            "political thriller", "political drama",
        ],
        "boost_any": [
            "president", "prime minister", "white house",
            "government", "politics", "political",
            "political thriller", "political drama",
            "crisis", "geopolitics", "negotiation",
            "national security", "international",
        ],
        "avoid_any": [
            "sitcom", "superhero", "supernatural", "space",
        ],
    },

    "period_power_drama": {
        "required_any": [
            "samurai", "feudal", "feudal japan", "warlord",
            "empire", "emperor", "shogun", "historical epic",
            "historical drama",
        ],
        "boost_any": [
            "political", "politics", "power", "war", "dynasty",
            "court", "intrigue", "history", "historical",
            "succession", "rivalry", "clan",
        ],
        "avoid_any": [
            "modern corporation", "startup", "superhero",
            "space", "police procedural",
        ],
    },

    "period_professional_drama": {
        "required_any": [
            "advertising", "advertising agency", "workplace",
            "business", "office", "professional", "career",
            "journalism", "media",
        ],
        "boost_any": [
            "1960s", "1950s", "1970s", "period",
            "ambition", "career", "marriage", "relationships",
            "businessman", "executive", "corporate",
        ],
        "avoid_any": [
            "superhero", "space", "supernatural",
        ],
    },

    "speculative_anthology": {
        "required_any": [
            "anthology", "technology", "dystopia", "dystopian",
            "future", "futuristic", "artificial intelligence",
            "virtual reality", "science fiction", "speculative",
        ],
        "boost_any": [
            "social commentary", "satire", "dark satire",
            "technology", "society", "surveillance",
            "artificial intelligence", "digital",
            "psychological", "twist",
        ],
        "avoid_any": [
            "historical drama", "period drama", "royal family",
        ],
    },

    "comedy_mystery": {
        "required_any": [
            "comedy mystery", "murder mystery", "amateur detective",
            "amateur sleuth", "podcast", "true crime podcast",
            "whodunit", "sleuth",
        ],
        "boost_any": [
            "comedy", "murder", "mystery", "investigation",
            "detective", "crime", "neighbors", "apartment",
            "eccentric", "dark comedy",
        ],
        "avoid_any": [
            "serial killer", "police procedural",
            "war", "space",
        ],
    },

    "period_community": {
        "required_any": [
            "period", "historical", "victorian", "post-war", "postwar", "1950",
            "1960", "community", "village", "family", "women", "rural", "small town",
            "war", "estate",
        ],
        "boost_any": [
            "period", "historical", "victorian", "post-war", "postwar", "1950",
            "1960", "community", "village", "family", "women", "rural", "small town",
            "war", "estate", "relationships",
        ],
        "reject_any": ["superhero", "alien", "vampire", "zombie", "wizard"],
        "preferred_genres": {18, 10768},
        "strict": False,
    },
    "medical_family": {
        "required_any": [
            "midwife", "maternity", "nurse", "nurses", "hospital", "doctor",
            "medical", "clinic", "community", "family", "women", "village",
        ],
        "boost_any": [
            "midwife", "maternity", "nurse", "nurses", "hospital", "doctor",
            "medical", "clinic", "community", "family", "women", "village", "compassion",
        ],
        "reject_any": ["superhero", "alien", "vampire", "wizard", "cartel", "mafia"],
        "preferred_genres": {18},
        "strict": False,
    },
    "general_scifi": {
        "required_any": [
            "future", "alien", "technology", "experiment", "time", "parallel",
            "dystopian", "space", "mystery", "secret", "world", "survival",
        ],
        "boost_any": [
            "future", "alien", "technology", "experiment", "time", "parallel",
            "dystopian", "space", "mystery", "secret", "world", "survival",
        ],
        "reject_any": ["reality", "talk show"],
        "preferred_genres": {10765, 9648, 18},
        "strict": False,
    },
    "general_drama": {
        "required_any": [],
        "boost_any": ["family", "relationships", "community", "secrets", "ambition", "conflict"],
        "reject_any": ["reality", "talk show"],
        "preferred_genres": {18},
        "strict": False,
    },
    "social_satire": {
        "required_any": [
            "satire",
            "social satire",
            "class conflict",
            "social class",
            "social elite",
            "wealthy",
            "privilege",
            "privileged",
            "exploitation",
            "status",
        ],
        "boost_any": [
            "vacation",
            "resort",
            "hotel",
            "elite",
            "wealth",
            "family",
            "anthology",
            "sardonic",
            "scathing",
        ],
        "avoid_any": [
            "space",
            "time travel",
            "superhero",
        ],
    },

    "royal_historical_drama": {
        "required_any": [
            "royal family",
            "royalty",
            "monarchy",
            "king",
            "queen",
            "prince",
            "princess",
            "palace",
            "historical drama",
            "british monarchy",
            "british royal family",
        ],
        "boost_any": [
            "dynasty",
            "history",
            "historical",
            "political",
            "politics",
            "palace intrigue",
            "aristocracy",
            "aristocratic",
            "period",
            "power",
        ],
        "avoid_any": [
            "corporation",
            "hedge fund",
            "wall street",
            "startup",
        ],
    },

    "espionage_thriller": {
        "required_any": [
            "spy",
            "spies",
            "espionage",
            "secret agent",
            "intelligence agency",
            "intelligence officer",
            "mi5",
            "mi6",
            "cia",
            "british intelligence",
        ],
        "boost_any": [
            "terrorism",
            "agent",
            "operative",
            "government",
            "conspiracy",
            "surveillance",
            "undercover",
            "political thriller",
            "national security",
        ],
        "avoid_any": [
            "superhero",
            "supernatural",
            "fantasy",
        ],
    },

    "workplace_character_drama": {
        "required_any": [
            "workplace",
            "restaurant",
            "chef",
            "kitchen",
            "office",
            "career",
            "professional",
            "business",
        ],
        "boost_any": [
            "family",
            "grief",
            "trauma",
            "ambition",
            "relationships",
            "colleagues",
            "coworkers",
            "pressure",
            "work",
        ],
        "avoid_any": [
            "time travel",
            "superhero",
            "space war",
        ],
    },

    "warm_workplace_comedy": {
        "required_any": [
            "workplace comedy",
            "workplace",
            "team",
            "teammate",
            "colleagues",
            "coworkers",
            "coach",
            "coaching",
            "office",
            "school",
            "restaurant",
        ],
        "boost_any": [
            "friendship",
            "male friendship",
            "female friendship",
            "optimist",
            "optimistic",
            "joyful",
            "nice guy",
            "community",
            "teamwork",
            "mentor",
            "mentorship",
            "fish out of water",
            "found family",
            "heartwarming",
            "uplifting",
            "workplace comedy",
        ],
        "avoid_any": [
            "serial killer",
            "murder investigation",
            "organized crime",
            "gangster",
            "war",
            "supernatural",
        ],
    },
}


def _blob_for(details: dict, extra_title: str | None = None) -> str:
    return " ".join(
        [
            str(
                extra_title
                or details.get("title")
                or details.get("name")
                or ""
            ),
            str(details.get("overview") or ""),
            " ".join(
                str(g)
                for g in (details.get("genres") or [])
            ),
            " ".join(
                str(k)
                for k in (details.get("seo_keywords") or [])
            ),
        ]
    ).lower()


def _contains_any(blob: str, terms: list[str] | tuple[str, ...]) -> bool:
    return any(term in blob for term in terms)


def _count_hits(blob: str, terms: list[str] | tuple[str, ...]) -> int:
    return sum(1 for term in terms if term in blob)


def _classify_anchor_concept_v2(anchor_title: str, anchor_details: dict) -> str:
    """
    Automatically classify an anchor show from its metadata.

    Titles are deliberately NOT used as direct concept mappings.
    Classification is based on genres and semantic/theme signals so
    unseen shows can be handled without manual configuration.
    """
    blob = _blob_for(anchor_details, anchor_title)
    genres = set(anchor_details.get("genre_ids") or [])
    genre_names = _genre_name_set(anchor_details)

    def hits(*terms: str) -> int:
        return _count_hits(blob, list(terms))

    scores: dict[str, float] = {
        "space_franchise_adventure": 0.0,
        "space_epic": 0.0,
        "contained_dystopia": 0.0,
        "mystery_box_survival": 0.0,
        "post_apocalyptic_survival": 0.0,
        "prestige_existential_mystery": 0.0,
        "time_mystery": 0.0,
        "corporate_mystery": 0.0,
        "finance_power": 0.0,
        "medical_family": 0.0,
        "period_community": 0.0,
        "small_town_mystery": 0.0,
        "detective_mystery": 0.0,
        "crime_pressure": 0.0,
        "general_scifi": 0.0,
        "general_drama": 0.10,
        "social_satire": 0.0,
        "political_diplomatic_drama": 0.0,
        "period_power_drama": 0.0,
        "period_professional_drama": 0.0,
        "speculative_anthology": 0.0,
        "comedy_mystery": 0.0,
        "royal_historical_drama": 0.0,
        "espionage_thriller": 0.0,
        "workplace_character_drama": 0.0,
        "warm_workplace_comedy": 0.0,
    }

    is_scifi = 10765 in genres or "sci-fi & fantasy" in genre_names
    is_action = 10759 in genres or "action & adventure" in genre_names
    is_drama = 18 in genres or "drama" in genre_names
    is_mystery = 9648 in genres or "mystery" in genre_names
    is_crime = 80 in genres or "crime" in genre_names

    # ---------------------------------------------------------
    # SPACE / FRANCHISE ADVENTURE
    # ---------------------------------------------------------
    if is_scifi:
        scores["space_franchise_adventure"] += 0.40

    if is_action:
        scores["space_franchise_adventure"] += 0.20

    scores["space_franchise_adventure"] += min(
        1.25,
        0.23 * hits(
            "galaxy",
            "galactic",
            "empire",
            "imperial",
            "rebel",
            "rebellion",
            "republic",
            "jedi",
            "bounty hunter",
            "spacecraft",
            "spaceship",
            "starship",
            "planet",
            "outer rim",
            "space western",
            "interstellar",
        ),
    )

    # ---------------------------------------------------------
    # SPACE EPIC
    # ---------------------------------------------------------
    if is_scifi:
        scores["space_epic"] += 0.35

    scores["space_epic"] += min(
        1.0,
        0.20 * hits(
            "space",
            "galaxy",
            "galactic",
            "planet",
            "colony",
            "colonies",
            "fleet",
            "starship",
            "spaceship",
            "interstellar",
            "civilization",
            "civilisation",
            "empire",
            "war",
        ),
    )

    # Franchise/adventure wins over generic space when there are
    # strong rebellion / galactic-action signals.
    franchise_specific_hits = hits(
        "rebel",
        "rebellion",
        "imperial",
        "republic",
        "jedi",
        "bounty hunter",
        "space western",
    )

    if franchise_specific_hits >= 1:
        scores["space_franchise_adventure"] += 0.35

    # ---------------------------------------------------------
    # CONTAINED DYSTOPIA
    # ---------------------------------------------------------
    if is_scifi:
        scores["contained_dystopia"] += 0.25

    scores["contained_dystopia"] += min(
        1.4,
        0.28 * hits(
            "bunker",
            "underground",
            "sealed",
            "vault",
            "silo",
            "facility",
            "enclosed",
            "contained",
            "containment",
            "controlled society",
            "authoritarian",
            "surveillance",
            "restricted",
            "dystopian",
        ),
    )

    # ---------------------------------------------------------
    # POST-APOCALYPTIC SURVIVAL
    # ---------------------------------------------------------
    if is_drama:
        scores["post_apocalyptic_survival"] += 0.12

    if is_scifi:
        scores["post_apocalyptic_survival"] += 0.10

    scores["post_apocalyptic_survival"] += min(
        1.80,
        0.34 * hits(
            "post-apocalyptic",
            "post apocalyptic",
            "post-apocalyptic future",
            "apocalypse",
            "apocalyptic",
            "collapse",
            "end of the world",
            "survival",
            "survivors",
            "infection",
            "epidemic",
            "pandemic",
            "virus",
            "outbreak",
            "zombie",
        ),
    )

    # ---------------------------------------------------------
    # MYSTERY BOX / SURVIVAL
    # ---------------------------------------------------------
    if is_mystery:
        scores["mystery_box_survival"] += 0.25

    if is_scifi:
        scores["mystery_box_survival"] += 0.15

    scores["mystery_box_survival"] += min(
        1.25,
        0.25 * hits(
            "stranded",
            "survivors",
            "survival",
            "disappearance",
            "missing",
            "unexplained",
            "paranormal",
            "alternate reality",
            "mystery",
            "supernatural",
            "island",
        ),
    )

    # ---------------------------------------------------------
    # PRESTIGE / EXISTENTIAL MYSTERY
    # ---------------------------------------------------------
    if is_drama:
        scores["prestige_existential_mystery"] += 0.20

    if is_mystery or is_scifi:
        scores["prestige_existential_mystery"] += 0.20

    scores["prestige_existential_mystery"] += min(
        1.20,
        0.22 * hits(
            "grief",
            "loss",
            "faith",
            "identity",
            "consciousness",
            "cult",
            "spiritual",
            "unexplained",
            "disappearance",
            "paranormal",
            "existence",
            "reality",
        ),
    )

    # ---------------------------------------------------------
    # TIME MYSTERY
    # ---------------------------------------------------------
    scores["time_mystery"] += min(
        1.5,
        0.35 * hits(
            "time travel",
            "timeline",
            "time loop",
            "paradox",
            "parallel world",
            "alternate timeline",
            "past",
            "future",
        ),
    )

    # ---------------------------------------------------------
    # CORPORATE MYSTERY
    # ---------------------------------------------------------
    if is_drama:
        scores["corporate_mystery"] += 0.15

    if is_scifi or is_mystery:
        scores["corporate_mystery"] += 0.20

    scores["corporate_mystery"] += min(
        1.3,
        0.28 * hits(
            "workplace",
            "office",
            "corporation",
            "corporate",
            "employee",
            "memory",
            "identity",
            "experiment",
            "company",
        ),
    )

    # ---------------------------------------------------------
    # FINANCE / CORPORATE POWER
    # ---------------------------------------------------------
    if is_drama:
        scores["finance_power"] += 0.30

    scores["finance_power"] += min(
        1.5,
        0.30 * hits(
            "finance",
            "financial",
            "hedge fund",
            "wall street",
            "investment",
            "trading",
            "billionaire",
            "wealth",
            "wealthy",
            "corporate",
            "corporation",
            "company",
            "ceo",
            "executive",
            "boardroom",
            "shareholder",
            "merger",
            "acquisition",
            "conglomerate",
            "media empire",
            "business empire",
            "family business",
            "inheritance",
            "dynasty",
        ),
    )

    # Generic "power" language should support the concept,
    # but must not define it by itself.
    scores["finance_power"] += min(
        0.35,
        0.07 * hits(
            "power",
            "ambition",
            "rivalry",
            "elite",
            "influence",
            "scandal",
            "corruption",
        ),
    )

    # ---------------------------------------------------------
    # MEDICAL / FAMILY
    # ---------------------------------------------------------
    scores["medical_family"] += min(
        1.5,
        0.30 * hits(
            "midwife",
            "maternity",
            "nurse",
            "nurses",
            "hospital",
            "doctor",
            "medical",
            "clinic",
            "patient",
            "patients",
            "community care",
        ),
    )

    # ---------------------------------------------------------
    # PERIOD COMMUNITY
    # ---------------------------------------------------------
    if is_drama:
        scores["period_community"] += 0.15

    scores["period_community"] += min(
        1.3,
        0.24 * hits(
            "victorian",
            "georgian",
            "historical",
            "period",
            "post-war",
            "postwar",
            "19th century",
            "18th century",
            "1950",
            "1960",
            "estate",
            "aristocratic",
            "village",
            "rural",
        ),
    )

    # ---------------------------------------------------------
    # SMALL-TOWN MYSTERY
    # ---------------------------------------------------------
    if is_mystery or is_crime:
        scores["small_town_mystery"] += 0.25

    scores["small_town_mystery"] += min(
        1.2,
        0.28 * hits(
            "small town",
            "small-town",
            "local murder",
            "local detective",
            "community",
            "town",
            "village",
            "close-knit",
        ),
    )

    # ---------------------------------------------------------
    # DETECTIVE MYSTERY
    # ---------------------------------------------------------
    if is_mystery:
        scores["detective_mystery"] += 0.30
    if is_crime:
        scores["detective_mystery"] += 0.20

    scores["detective_mystery"] += min(
        1.3,
        0.25 * hits(
            "detective",
            "investigation",
            "investigator",
            "murder",
            "murder case",
            "serial killer",
            "fbi",
            "police",
            "case",
        ),
    )

    # ---------------------------------------------------------
    # CRIME PRESSURE
    # ---------------------------------------------------------
    if is_crime:
        scores["crime_pressure"] += 0.50

    scores["crime_pressure"] += min(
        1.15,
        0.22 * hits(
            "crime",
            "criminal",
            "cartel",
            "drug",
            "gang",
            "mafia",
            "mob",
            "underworld",
            "lawyer",
            "attorney",
            "corruption",
        ),
    )
    # POLITICAL / DIPLOMATIC DRAMA
    if is_drama:
        scores["political_diplomatic_drama"] += 0.15

    scores["political_diplomatic_drama"] += min(
        1.8,
        0.38 * hits(
            "diplomat", "diplomacy", "diplomatic",
            "embassy", "ambassador", "foreign policy",
            "international relations", "state department",
            "foreign affairs",
        ),
    )

    scores["political_diplomatic_drama"] += min(
        0.50,
        0.10 * hits(
            "politics", "political", "government",
            "president", "prime minister", "geopolitics",
            "national security", "international",
        ),
    )


    # PERIOD POWER / HISTORICAL EPIC
    if is_drama:
        scores["period_power_drama"] += 0.12

    scores["period_power_drama"] += min(
        1.8,
        0.36 * hits(
            "samurai", "feudal", "feudal japan",
            "warlord", "shogun", "historical epic",
            "empire", "emperor",
        ),
    )

    scores["period_power_drama"] += min(
        0.65,
        0.11 * hits(
            "political", "politics", "power", "war",
            "dynasty", "court", "intrigue",
            "historical", "history", "clan",
        ),
    )


    if is_drama:
        scores["period_professional_drama"] += 0.08

    professional_hits = hits(
        "advertising",
        "advertising agency",
        "journalism",
        "media",
        "workplace",
        "professional",
        "career",
        "executive",
        "businessman",
        "corporate",
        "office",
    )

    period_hits = hits(
        "1940s",
        "1950s",
        "1960s",
        "1970s",
        "1980s",
        "1940",
        "1950",
        "1960",
        "1970",
        "1980",
        "period drama",
        "historical",
        "period",
    )

    # Professional setting contributes, but this concept should not
    # classify a modern workplace/professional drama without period evidence.
    scores["period_professional_drama"] += min(
        1.40,
        0.30 * professional_hits,
    )

    scores["period_professional_drama"] += min(
        0.90,
        0.22 * period_hits,
    )

    if period_hits == 0:
        scores["period_professional_drama"] *= 0.20


    # SPECULATIVE / TECHNOLOGY ANTHOLOGY
    if is_scifi:
        scores["speculative_anthology"] += 0.30

    scores["speculative_anthology"] += min(
        1.9,
        0.34 * hits(
            "anthology", "technology", "dystopia",
            "dystopian", "future", "futuristic",
            "artificial intelligence", "virtual reality",
            "science fiction", "speculative",
        ),
    )

    scores["speculative_anthology"] += min(
        0.65,
        0.11 * hits(
            "social commentary", "satire",
            "surveillance", "digital",
            "psychological", "society", "twist",
        ),
    )


    # COMEDY MYSTERY
    scores["comedy_mystery"] += min(
        1.8,
        0.38 * hits(
            "comedy mystery", "murder mystery",
            "amateur detective", "amateur sleuth",
            "true crime podcast", "podcast",
            "whodunit", "sleuth",
        ),
    )

    comedy_hits = hits(
        "comedy", "dark comedy", "humor",
        "humour", "funny",
    )

    mystery_hits = hits(
        "murder", "mystery", "investigation",
        "detective", "crime",
    )

    # Combination evidence is especially important here.
    if comedy_hits > 0 and mystery_hits > 0:
        scores["comedy_mystery"] += 0.75

    scores["comedy_mystery"] += min(
        0.35,
        0.07 * (comedy_hits + mystery_hits),
    )

    # ---------------------------------------------------------
    # SOCIAL SATIRE / CLASS
    # ---------------------------------------------------------
    if is_drama:
        scores["social_satire"] += 0.15

    scores["social_satire"] += min(
        1.5,
        0.30 * hits(
            "satire",
            "social satire",
            "class conflict",
            "social class",
            "social elite",
            "privilege",
            "privileged",
            "exploitation",
            "sardonic",
            "scathing",
        ),
    )

    # ---------------------------------------------------------
    # ROYAL / HISTORICAL DRAMA
    # ---------------------------------------------------------
    if is_drama:
        scores["royal_historical_drama"] += 0.15

    scores["royal_historical_drama"] += min(
        1.6,
        0.32 * hits(
            "royal family",
            "royalty",
            "monarchy",
            "british monarchy",
            "british royal family",
            "queen",
            "king",
            "prince",
            "princess",
            "palace intrigue",
            "historical drama",
        ),
    )

    # ---------------------------------------------------------
    # ESPIONAGE THRILLER
    # ---------------------------------------------------------
    scores["espionage_thriller"] += min(
        1.6,
        0.34 * hits(
            "spy",
            "spies",
            "espionage",
            "secret agent",
            "mi5",
            "mi6",
            "cia",
            "british intelligence",
            "intelligence agency",
            "intelligence officer",
        ),
    )

    # ---------------------------------------------------------
    # WARM WORKPLACE COMEDY
    # ---------------------------------------------------------
    if is_drama:
        scores["warm_workplace_comedy"] += 0.08

    warm_workplace_hits = hits(
        "workplace comedy",
        "workplace",
        "team",
        "teammate",
        "colleagues",
        "coworkers",
        "coach",
        "coaching",
        "office",
        "school",
        "restaurant",
    )

    warm_tone_hits = hits(
        "friendship",
        "male friendship",
        "female friendship",
        "optimist",
        "optimistic",
        "joyful",
        "nice guy",
        "community",
        "teamwork",
        "mentor",
        "mentorship",
        "fish out of water",
        "found family",
        "heartwarming",
        "uplifting",
    )

    scores["warm_workplace_comedy"] += min(
        1.40,
        0.28 * warm_workplace_hits,
    )

    scores["warm_workplace_comedy"] += min(
        1.20,
        0.24 * warm_tone_hits,
    )

    # This concept requires both a communal/workplace setting
    # and positive/comedic relationship evidence.
    if warm_workplace_hits == 0 or warm_tone_hits == 0:
        scores["warm_workplace_comedy"] *= 0.30

    # ---------------------------------------------------------
    # WORKPLACE CHARACTER DRAMA
    # ---------------------------------------------------------
    if is_drama:
        scores["workplace_character_drama"] += 0.15

    scores["workplace_character_drama"] += min(
        1.3,
        0.26 * hits(
            "workplace",
            "restaurant",
            "chef",
            "kitchen",
            "career",
            "colleagues",
            "coworkers",
            "professional",
        ),
    )

    # ---------------------------------------------------------
    # GENERIC FALLBACKS
    # ---------------------------------------------------------
    if is_scifi:
        scores["general_scifi"] += 0.60

    if is_drama:
        scores["general_drama"] += 0.25

    best_concept, best_score = max(
        scores.items(),
        key=lambda pair: pair[1],
    )

    # Avoid over-classifying weak metadata.
    if best_score < 0.55:
        return "general_scifi" if is_scifi else "general_drama"

    return best_concept

def _concept_fit_score(anchor_concept: str, details: dict, *, semantic_score: float, genre_score: float) -> tuple[bool, float, float]:
    """Return (passes, additive_bonus, multiplier)."""
    rule = CONCEPT_RULES.get(anchor_concept) or CONCEPT_RULES["general_drama"]
    blob = _blob_for(details)
    genres = set(details.get("genre_ids") or [])
    title = str(details.get("title") or details.get("name") or "").lower()

    if anchor_concept == "warm_workplace_comedy":
        title_debug = str(details.get("title") or details.get("name") or "")

        if title_debug.lower() in {
            "2 broke girls",
            "the bear",
            "shrinking",
            "parks and recreation",
            "abbott elementary",
            "brooklyn nine-nine",
        }:
            print(
                "SEO WARM FIT DEBUG:",
                {
                    "title": title_debug,
                    "genres": list(details.get("genre_ids") or []),
                    "keywords": list(details.get("seo_keywords") or []),
                    "semantic": round(float(semantic_score), 4),
                },
                flush=True,
            )

    first_air_date = str(details.get("first_air_date") or "")
    year = 0
    try:
        year = int(first_air_date[:4])
    except Exception:
        year = 0

    # Avoid anime/animation drift on non-animation SEO pages.
    if 16 in genres and anchor_concept not in {
    "general_scifi",
    "space_epic",
    "space_franchise_adventure",
    }:        
        return False, 0.0, 1.0

    required_any = list(rule.get("required_any") or [])
    boost_any = list(rule.get("boost_any") or [])
    reject_any = list(rule.get("reject_any") or [])
    preferred_genres = set(rule.get("preferred_genres") or set())
    strict = bool(rule.get("strict"))

    if reject_any and _contains_any(blob, reject_any):
        return False, 0.0, 1.0

    required_hits = _count_hits(blob, required_any)
    boost_hits = _count_hits(blob, boost_any)
    genre_hits = len(genres & preferred_genres)

    bonus = 0.0
    bonus += min(0.42, 0.07 * boost_hits)
    bonus += min(0.18, 0.06 * genre_hits)

    multiplier = 1.0

    # Very old shows often make SEO pages look low quality unless they are classics.
    classic_allowlist = {
        "the twilight zone",
        "star trek",
        "star trek: deep space nine",
        "the sopranos",
        "the wire",
    }

    if year and year < 1990 and title not in classic_allowlist:
        multiplier *= 0.45

    if required_any and required_hits == 0:
        if strict:
            return False, 0.0, 1.0
        if semantic_score < 0.20 and genre_score < 0.22 and genre_hits == 0:
            return False, 0.0, 1.0

    
    if title in SCI_FI_CLASSICS and anchor_concept in {
        "space_epic",
        "general_scifi",
        "space_franchise_adventure",
    }:
        bonus += 0.16


    if anchor_concept == "space_franchise_adventure":
        # Must fundamentally belong in sci-fi/fantasy or action/adventure.
        if not ({10765, 10759, 16} & genres):
            return False, 0.0, 1.0

        # Closest Star Wars / Mandalorian viewing companions.
        if title == "the book of boba fett":
            bonus += 0.60

        elif title == "ahsoka":
            bonus += 0.56

        elif title == "andor":
            bonus += 0.52

        elif title == "star wars rebels":
            bonus += 0.50

        elif title == "obi-wan kenobi":
            bonus += 0.48

        elif title == "star wars: skeleton crew":
            bonus += 0.46

        elif title == "star wars: the clone wars":
            bonus += 0.42

        elif title == "star wars: the bad batch":
            bonus += 0.40

        # Strong non-Star-Wars tonal matches.
        elif title == "firefly":
            bonus += 0.30

        elif title in {
            "battlestar galactica",
            "the expanse",
        }:
            bonus += 0.18

        elif title in {
            "stargate sg-1",
            "stargate atlantis",
        }:
            bonus += 0.14

        # General franchise/space-western signals.
        if _contains_any(blob, [
            "star wars",
            "jedi",
            "mandalorian",
            "bounty hunter",
            "new republic",
            "galactic empire",
            "space western",
        ]):
            bonus += 0.16

        elif _contains_any(blob, [
            "rebellion",
            "rebel",
            "empire",
            "galaxy",
            "outlaw",
            "mercenary",
            "space adventure",
        ]):
            bonus += 0.08


    elif anchor_concept == "space_epic":
        if 10765 not in genres:
            return False, 0.0, 1.0

        if _contains_any(blob, [
            "star trek",
            "stargate",
            "battlestar",
            "farscape",
            "firefly",
            "andor",
        ]):
            bonus += 0.12

        if _contains_any(blob, [
            "jedi",
            "mandalorian",
            "ahsoka",
        ]):
            multiplier *= 0.88
    elif anchor_concept == "contained_dystopia":
        contained_terms = [
            "bunker",
            "underground",
            "sealed",
            "silo",
            "vault",
            "contained",
            "containment",
            "surveillance",
            "authoritarian",
            "controlled society",
            "restricted",
            "facility",
            "enclosed",
            "isolated",
            "quarantine",
            "shelter",
        ]

        dystopia_terms = [
            "dystopia",
            "dystopian",
            "post-apocalyptic",
            "post apocalyptic",
            "apocalypse",
            "apocalyptic",
            "collapse",
            "wasteland",
            "regime",
            "oppressive",
            "totalitarian",
            "class warfare",
            "corruption",
        ]

        survival_terms = [
            "survival",
            "survive",
            "survivor",
            "survivors",
            "pandemic",
            "plague",
            "disaster",
            "catastrophe",
            "devastated",
            "civilization",
            "humanity",
        ]

        social_control_terms = [
            "government",
            "authority",
            "authoritarian",
            "regime",
            "surveillance",
            "controlled",
            "restricted",
            "secret",
            "conspiracy",
            "corruption",
            "society",
        ]

        wrong_context_terms = [
            "jedi",
            "starship",
            "galactic empire",
            "space battle",
            "superhero",
            "sitcom",
            "talent competition",
            "police procedural",
        ]

        contained_hits = _count_hits(blob, contained_terms)
        dystopia_hits = _count_hits(blob, dystopia_terms)
        survival_hits = _count_hits(blob, survival_terms)
        control_hits = _count_hits(blob, social_control_terms)

        concept_hits = (
            contained_hits
            + dystopia_hits
            + survival_hits
            + control_hits
        )

        # A contained/dystopian recommendation should have actual thematic
        # evidence. Sci-fi genre membership helps, but is not mandatory.
        if concept_hits == 0:
            if semantic_score < 0.20 and genre_score < 0.30:
                return False, 0.0, 1.0

            multiplier *= 0.72

        # Reward the strongest characteristics of this concept.
        bonus += min(0.36, 0.12 * contained_hits)
        bonus += min(0.30, 0.10 * dystopia_hits)
        bonus += min(0.24, 0.08 * survival_hits)
        bonus += min(0.18, 0.06 * control_hits)

        # Sci-fi is supporting evidence rather than an admission requirement.
        if 10765 in genres:
            bonus += 0.08

        if 18 in genres:
            bonus += 0.04

        # Multiple independent thematic signals are especially valuable.
        signal_groups = sum([
            contained_hits > 0,
            dystopia_hits > 0,
            survival_hits > 0,
            control_hits > 0,
        ])

        if signal_groups >= 3:
            bonus += 0.18
        elif signal_groups >= 2:
            bonus += 0.10

        # Strong mismatches should be suppressed rather than relying on
        # individual title exclusions.
        if _contains_any(blob, wrong_context_terms):
            if concept_hits < 2:
                multiplier *= 0.50
            else:
                multiplier *= 0.75

    elif anchor_concept == "post_apocalyptic_survival":
        apocalypse_terms = [
            "post-apocalyptic",
            "post apocalyptic",
            "apocalypse",
            "apocalyptic",
            "collapse",
            "end of the world",
            "dystopia",
            "dystopian",
        ]

        survival_terms = [
            "survival",
            "survivors",
            "infection",
            "epidemic",
            "pandemic",
            "virus",
            "outbreak",
            "zombie",
        ]

        human_drama_terms = [
            "family",
            "relationship",
            "relationships",
            "community",
            "humanity",
            "society",
            "journey",
            "protect",
            "loss",
        ]

        apocalypse_hits = _count_hits(blob, apocalypse_terms)
        survival_hits = _count_hits(blob, survival_terms)
        human_hits = _count_hits(blob, human_drama_terms)

        core_hits = apocalypse_hits + survival_hits

        if core_hits == 0:
            return False, 0.0, 1.0

        if core_hits >= 3:
            bonus += 0.48
        elif core_hits == 2:
            bonus += 0.36
        else:
            bonus += 0.22

        bonus += min(0.15, 0.03 * human_hits)

        if apocalypse_hits == 0 and survival_hits < 2:
            multiplier *= 0.72
                
    elif anchor_concept == "mystery_box_survival":
        close_titles = {
            "from",
            "fringe",
            "dark",
            "12 monkeys",
            "manifest",
            "yellowjackets",
            "wayward pines",
            "the leftovers",
            "silo",
            "stranger things",
            "the 100",
            "under the dome",
        }
        core_terms = [
            "mystery", "missing", "disappearance", "survival", "survivors",
            "stranded", "island", "supernatural", "unexplained", "secret",
            "secrets", "time travel", "timeline", "alternate", "paranormal",
            "experiment", "conspiracy", "community",
        ]
        core_hits = _count_hits(blob, core_terms)

        if title in close_titles:
            bonus += 0.42

        if 9648 in genres:
            bonus += 0.12
        if 10765 in genres:
            bonus += 0.10
        if 18 in genres:
            bonus += 0.06

        if core_hits >= 3:
            bonus += 0.26
        elif core_hits >= 2:
            bonus += 0.18
        elif core_hits == 1:
            bonus += 0.08

        if _contains_any(blob, ["procedural", "solve crimes", "case of the week", "talent competition", "sitcom"]):
            multiplier *= 0.55

        # Do not kill shows that are strongly genre-aligned but sparse in overview text;
        # Lost-style pages need enough mystery-box candidates to avoid empty SEO pages.
        if required_hits == 0 and semantic_score < 0.16 and genre_score < 0.20 and title not in close_titles:
            multiplier *= 0.72

    elif anchor_concept == "prestige_existential_mystery":
        existential_terms = [
            "disappear", "disappears", "disappearance", "vanish", "vanished",
            "missing", "unexplained", "grief", "loss", "faith", "spiritual",
            "cult", "apocalypse", "apocalyptic", "supernatural", "paranormal",
            "identity", "consciousness", "psychological", "community",
        ]
        procedural_terms = [
            "procedural", "solve crimes", "case of the week", "nypd", "lapd",
            "homicide unit", "detective partnership", "elite team",
        ]
        generic_family_terms = [
            "family drama", "family", "relationships", "marriage", "home town",
            "returns home", "personal and professional life",
        ]
        core_hits = _count_hits(blob, existential_terms)

        if 18 not in genres and 9648 not in genres and 10765 not in genres:
            return False, 0.0, 1.0

        if 80 in genres and core_hits < 2 and semantic_score < 0.26:
            multiplier *= 0.45

        if 10759 in genres and core_hits < 2:
            multiplier *= 0.55

        if _contains_any(blob, procedural_terms):
            multiplier *= 0.35

        if _contains_any(blob, generic_family_terms) and core_hits == 0 and semantic_score < 0.24:
            return False, 0.0, 1.0

        if core_hits >= 4:
            bonus += 0.38
        elif core_hits >= 2:
            bonus += 0.26
        elif core_hits == 1:
            bonus += 0.12

        if 9648 in genres:
            bonus += 0.14
        if 10765 in genres:
            bonus += 0.10
        if 18 in genres:
            bonus += 0.08

        # Keep this bucket broad: it rewards tone/shape rather than one exact title.
        if required_hits == 0 and semantic_score < 0.20 and genre_score < 0.22:
            return False, 0.0, 1.0

    elif anchor_concept == "time_mystery":
        time_core_terms = [
            "time travel",
            "time traveller",
            "time traveler",
            "time machine",
            "timeline",
            "alternate timeline",
            "alternate reality",
            "parallel universe",
            "parallel world",
            "time loop",
            "temporal",
            "paradox",
        ]

        mystery_support_terms = [
            "mystery",
            "missing",
            "disappearance",
            "secret",
            "secrets",
            "unexplained",
            "past",
            "future",
            "generation",
            "generations",
        ]

        time_hits = _count_hits(
            blob,
            time_core_terms,
        )

        mystery_hits = _count_hits(
            blob,
            mystery_support_terms,
        )

        is_mystery_or_scifi = bool(
            {9648, 10765} & genres
        )

        # Direct temporal evidence is the strongest reason for belonging
        # to this concept.
        if time_hits >= 2:
            bonus += 0.42
        elif time_hits == 1:
            bonus += 0.28

        # Mystery atmosphere supports a temporal match but cannot define
        # time_mystery by itself.
        if time_hits > 0:
            bonus += min(
                0.18,
                0.05 * mystery_hits,
            )

        # Candidates without explicit temporal metadata can still belong
        # when they are genuine mystery/speculative shows with meaningful
        # semantic similarity to the anchor.
        if time_hits == 0:
            if not is_mystery_or_scifi:
                return False, 0.0, 1.0

            if mystery_hits == 0:
                return False, 0.0, 1.0

            if semantic_score < 0.18:
                return False, 0.0, 1.0

            multiplier *= 0.72

        # Crime alone should not masquerade as a temporal mystery.
        if (
            80 in genres
            and 9648 not in genres
            and 10765 not in genres
            and time_hits == 0
        ):
            return False, 0.0, 1.0

    elif anchor_concept == "corporate_mystery":
        if _contains_any(blob, ["memory", "identity", "consciousness", "experiment", "office", "workplace", "corporate"]):
            bonus += 0.22
        elif required_hits == 0 and semantic_score < 0.24:
            multiplier *= 0.72

        if 10759 in genres:
            multiplier *= 0.72

        if _contains_any(blob, ["supernatural forces", "young boy", "small town", "monster"]):
            multiplier *= 0.65

        if _contains_any(blob, ["office", "workplace", "memory", "identity", "corporate", "experiment", "consciousness"]):
            bonus += 0.12
        if title in {"the pretender", "taken", "nancy drew"}:
            multiplier *= 0.65

    elif anchor_concept == "small_town_mystery":
        if _contains_any(blob, ["small town", "community", "local murder", "murder", "grief", "family", "secrets"]):
            bonus += 0.28

        if _contains_any(blob, ["elite team", "profilers", "solve new cases", "nypd", "fbi"]):
            multiplier *= 0.55

        procedural_terms = [
            "case", "cases", "solve crimes", "solving crimes", "homicide unit",
            "nypd", "fbi", "precinct", "partnership", "detective inspector",
            "murder mysteries", "each episode"
        ]

        grounded_terms = [
            "small town", "community", "family", "grief", "secrets",
            "local", "coastal", "personal life", "missing"
        ]

        procedural_hits = _count_hits(blob, procedural_terms)
        grounded_hits = _count_hits(blob, grounded_terms)

        if procedural_hits >= 1 and grounded_hits == 0:
            multiplier *= 0.50

        if 10765 in genres or 10759 in genres:
            multiplier *= 0.55

    elif anchor_concept == "detective_mystery":
        # Detective/mystery recommendations need genuine investigative evidence.
        # Drama tone or Reddit similarity alone should not qualify a candidate.

        core_investigation_terms = [
            "detective",
            "police detective",
            "detective inspector",
            "investigation",
            "police investigation",
            "murder investigation",
            "homicide",
            "murder case",
            "cold case",
            "missing person",
            "missing persons",
            "investigator",
            "investigates",
            "investigate",
        ]

        crime_mystery_terms = [
            "murder",
            "murder mystery",
            "serial killer",
            "killer",
            "crime",
            "criminal",
            "missing",
            "disappearance",
            "case",
            "cases",
            "police",
            "fbi",
            "corruption",
            "unsolved",
        ]

        tone_terms = [
            "neo-noir",
            "noir",
            "grim",
            "psychological",
            "philosophical",
            "introspective",
            "dark",
            "brooding",
            "atmospheric",
            "morally complex",
        ]

        wrong_context_terms = [
            "superhero",
            "vampire",
            "monster",
            "supernatural",
            "wizard",
            "magic",
            "high school students",
            "hospital",
            "trauma medical center",
            "restaurant",
            "chef",
            "workplace comedy",
            "sitcom",
        ]

        core_hits = _count_hits(
            blob,
            core_investigation_terms,
        )

        crime_hits = _count_hits(
            blob,
            crime_mystery_terms,
        )

        tone_hits = _count_hits(
            blob,
            tone_terms,
        )

        is_crime = 80 in genres
        is_mystery = 9648 in genres

        # Strong investigative metadata is the clearest fit.
        if core_hits >= 2:
            bonus += 0.42
        elif core_hits == 1:
            bonus += 0.28

        # Crime/mystery evidence supports the investigative signal.
        if core_hits > 0:
            bonus += min(
                0.20,
                0.05 * crime_hits,
            )

        # Tone is useful for distinguishing prestige mystery from generic
        # procedural crime, but tone alone cannot qualify a show.
        if core_hits > 0:
            bonus += min(
                0.12,
                0.04 * tone_hits,
            )

        # Candidates without explicit investigation evidence need very strong
        # crime/mystery and semantic evidence to survive.
        if core_hits == 0:
            if not (is_crime or is_mystery):
                return False, 0.0, 1.0

            if crime_hits < 2:
                return False, 0.0, 1.0

            if semantic_score < 0.18:
                return False, 0.0, 1.0

            multiplier *= 0.72

        # Obvious tonal/context mismatches should not survive weak evidence.
        if _contains_any(blob, wrong_context_terms):
            if core_hits == 0:
                return False, 0.0, 1.0
            multiplier *= 0.55

        # Sci-fi/fantasy needs unusually strong investigative evidence to belong.
        if 10765 in genres and core_hits < 2:
            multiplier *= 0.35

        # Action-heavy candidates should not dominate a grounded detective page.
        if 10759 in genres and core_hits == 0:
            multiplier *= 0.45

        # Comedy without crime/mystery grounding is not a detective match.
        if 35 in genres and not (is_crime or is_mystery):
            return False, 0.0, 1.0


    elif anchor_concept == "crime_pressure":
        if 80 in genres:
            bonus += 0.12

        if 10765 in genres:
            multiplier *= 0.35

        if 10759 in genres and semantic_score < 0.35:
            multiplier *= 0.45

        if _contains_any(
            blob,
            [
                "superhero",
                "vampire",
                "monster",
                "supernatural",
                "high school students",
                "trauma medical center",
            ],
        ):
            multiplier *= 0.35

        generic_procedural_terms = [
            "nypd",
            "lapd",
            "fbi",
            "elite agents",
            "homicide unit",
            "police procedural",
            "solve crimes",
            "solving crimes",
            "cases",
            "case-of-the-week",
            "precinct",
            "rookie",
        ]

        prestige_crime_terms = [
            "corruption",
            "institution",
            "bureaucracy",
            "drug",
            "cartel",
            "underworld",
            "organized crime",
            "moral",
            "political",
            "system",
            "city",
            "criminal organization",
        ]

        procedural_hits = _count_hits(
            blob,
            generic_procedural_terms,
        )

        prestige_hits = _count_hits(
            blob,
            prestige_crime_terms,
        )

        if procedural_hits >= 1 and prestige_hits == 0:
            multiplier *= 0.35

        if 35 in genres and 80 not in genres and semantic_score < 0.24:
            multiplier *= 0.75

    elif anchor_concept == "finance_power":
            # finance_power needs stronger evidence than simply being a drama
            # about a family or workplace.
            #
            # Reset the generic CONCEPT_RULES bonus so this concept is scored
            # from finance/power evidence rather than broad Drama overlap.
            bonus = 0.0

            # Tier 1: unmistakable finance / capital-market signals.
            finance_specific_terms = [
                "finance",
                "financial",
                "hedge fund",
                "wall street",
                "investment",
                "investment bank",
                "investment banking",
                "trading",
                "trader",
                "banking",
                "banker",
                "private equity",
                "venture capital",
                "stock market",
                "shareholder",
                "merger",
                "acquisition",
                "broker",
            ]

            # Tier 2: corporate control / executive-power signals.
            corporate_power_terms = [
                "corporate",
                "corporation",
                "ceo",
                "executive",
                "boardroom",
                "board of directors",
                "conglomerate",
                "media empire",
                "business empire",
                "family empire",
                "media tycoon",
                "tycoon",
                "company owner",
                "business owner",
            ]

            # Tier 3: wealth / dynasty signals.
            wealth_status_terms = [
                "billionaire",
                "wealth",
                "wealthy",
                "elite",
                "dynasty",
                "inheritance",
                "family business",
                "media mogul",
                "mogul",
            ]

            # Useful supporting signals, but these must NOT define the concept
            # on their own.
            power_terms = [
                "power",
                "power struggle",
                "ambition",
                "rivalry",
                "influence",
                "corruption",
                "scandal",
                "succession",
            ]

            # Very broad business words. These get only weak credit because
            # almost any workplace drama can contain them.
            generic_business_terms = [
                "business",
                "company",
                "money",
                "firm",
                "owner",
            ]

            finance_hits = _count_hits(blob, finance_specific_terms)
            corporate_hits = _count_hits(blob, corporate_power_terms)
            wealth_hits = _count_hits(blob, wealth_status_terms)
            power_hits = _count_hits(blob, power_terms)
            generic_business_hits = _count_hits(blob, generic_business_terms)

            strong_hits = (
                finance_hits
                + corporate_hits
                + wealth_hits
            )

            # Clear genre/context mismatches.
            wrong_context_terms = [
                "superhero",
                "monster",
                "alien",
                "godzilla",
                "hospital",
                "medical center",
                "emergency department",
                "restaurant",
                "sandwich shop",
                "chef",
                "high school",
            ]

            if _contains_any(blob, wrong_context_terms) and strong_hits == 0:
                return False, 0.0, 1.0

            # A generic family/workplace drama should NOT become finance_power
            # merely because its description contains "business", "company",
            # "family", "money" or "power".
            if strong_hits == 0:
                if generic_business_hits == 0:
                    return False, 0.0, 1.0

                # Weak business language needs substantial power/status support
                # or unusually strong semantic similarity.
                if power_hits < 2 and semantic_score < 0.24:
                    return False, 0.0, 1.0

                multiplier *= 0.72

            # Strong, specific evidence carries most of the score.
            bonus += min(
                0.75,
                0.22 * finance_hits,
            )

            bonus += min(
                0.60,
                0.20 * corporate_hits,
            )

            bonus += min(
                0.45,
                0.15 * wealth_hits,
            )

            # Power/status helps only when business/finance evidence exists.
            if strong_hits >= 1:
                bonus += min(
                    0.24,
                    0.06 * power_hits,
                )

            # Generic business terminology contributes only a small amount.
            bonus += min(
                0.10,
                0.025 * generic_business_hits,
            )

            # Drama is appropriate but should never be a major reason by itself.
            if 18 in genres:
                bonus += 0.05

            # Crime can coexist with finance/power drama, but if the title is
            # overwhelmingly crime/action with little corporate evidence,
            # reduce its relevance.
            if 80 in genres and strong_hits < 2:
                multiplier *= 0.82

            if 10759 in genres or 10768 in genres:
                multiplier *= 0.55
                
    elif anchor_concept == "period_community":
        if 10765 in genres or 10759 in genres or 80 in genres:
            multiplier *= 0.55
        if _contains_any(blob, ["high school", "drugs", "sex", "social media", "trauma medical center", "emergency department", "overcrowded"]):
            multiplier *= 0.45
        if required_hits == 0 and semantic_score < 0.18:
            return False, 0.0, 1.0

    elif anchor_concept == "political_diplomatic_drama":
        diplomatic_terms = [
            "diplomat",
            "diplomacy",
            "diplomatic",
            "embassy",
            "ambassador",
            "foreign policy",
            "foreign affairs",
            "international relations",
            "state department",
            "geopolitics",
        ]

        political_terms = [
            "politics",
            "political",
            "government",
            "president",
            "prime minister",
            "national security",
            "international crisis",
            "negotiation",
            "intelligence",
            "foreign",
        ]

        wrong_context_terms = [
            "sitcom",
            "family comedy",
            "romantic comedy",
            "superhero",
            "supernatural",
            "teen comedy",
        ]

        diplomatic_hits = _count_hits(blob, diplomatic_terms)
        political_hits = _count_hits(blob, political_terms)

        if SEO_DEBUG:
            matched_diplomatic = [
                term for term in diplomatic_terms
                if term in blob
            ]

            matched_political = [
                term for term in political_terms
                if term in blob
            ]

            print(
                "SEO POLITICAL FIT DEBUG:",
                {
                    "title": str(details.get("title") or details.get("name") or ""),
                    "diplomatic_hits": diplomatic_hits,
                    "political_hits": political_hits,
                    "matched_diplomatic": matched_diplomatic,
                    "matched_political": matched_political,
                    "semantic": round(float(semantic_score), 4),
                }
            )

        if diplomatic_hits >= 2:
            bonus += 0.48
        elif diplomatic_hits == 1:
            bonus += 0.32

        bonus += min(0.22, 0.05 * political_hits)

       # Candidates must contain genuine diplomatic or political evidence.
        if diplomatic_hits == 0:
            if political_hits < 3:
                return False, 0.0, 1.0

            multiplier *= 0.90

        if _contains_any(blob, wrong_context_terms):
            multiplier *= 0.35


    elif anchor_concept == "period_professional_drama":
        professional_terms = [
            "advertising",
            "advertising agency",
            "workplace",
            "office",
            "career",
            "professional",
            "business",
            "executive",
            "journalism",
            "media",
        ]

        period_terms = [
            "1940s",
            "1950s",
            "1960s",
            "1970s",
            "1980s",
            "1940",
            "1950",
            "1960",
            "1970",
            "1980",
            "period drama",
            "historical",
            "period",
        ]

        character_terms = [
            "ambition",
            "marriage",
            "relationships",
            "identity",
            "career",
            "business",
            "power",
            "family",
        ]

        wrong_context_terms = [
            "superhero",
            "supernatural",
            "post-apocalyptic",
            "space",
            "fantasy",
        ]

        professional_hits = _count_hits(blob, professional_terms)
        period_hits = _count_hits(blob, period_terms)
        character_hits = _count_hits(blob, character_terms)

        if SEO_DEBUG:
            print(
                "SEO PERIOD PROFESSIONAL FIT DEBUG:",
                {
                    "title": str(details.get("title") or details.get("name") or ""),
                    "professional_hits": professional_hits,
                    "period_hits": period_hits,
                    "character_hits": character_hits,
                    "semantic": round(float(semantic_score), 4),
                    "matched_professional": [
                        t for t in professional_terms if t in blob
                    ],
                    "matched_period": [
                        t for t in period_terms if t in blob
                    ],
                },
            )

        if professional_hits >= 2:
            bonus += 0.42
        elif professional_hits == 1:
            bonus += 0.27

        if period_hits > 0:
            bonus += min(0.20, 0.06 * period_hits)

        bonus += min(0.12, 0.03 * character_hits)

        # A period-professional drama should normally contain actual
        # period evidence. Modern workplace/professional dramas should
        # not qualify simply because they share an office/career setting.
        if period_hits == 0:
            if semantic_score < 0.30:
                return False, 0.0, 1.0
            multiplier *= 0.55

        # Professional evidence strengthens the match, but period dramas
        # can still qualify when the occupation is poorly represented in
        # TMDb metadata.
        if professional_hits == 0:
            if semantic_score < 0.18:
                multiplier *= 0.72
            else:
                multiplier *= 0.88

        if _contains_any(blob, wrong_context_terms):
            multiplier *= 0.45


    elif anchor_concept == "comedy_mystery":
        mystery_terms = [
            "murder mystery",
            "mystery",
            "murder",
            "whodunit",
            "investigation",
            "detective",
            "sleuth",
            "amateur detective",
            "amateur sleuth",
            "true crime",
            "podcast",
        ]

        comedy_terms = [
            "comedy",
            "dark comedy",
            "comedic",
            "humor",
            "humour",
            "funny",
            "satire",
        ]

        wrong_context_terms = [
            "serial killer",
            "police procedural",
            "horror",
            "supernatural horror",
            "war",
            "post-apocalyptic",
        ]

        mystery_hits = _count_hits(blob, mystery_terms)
        comedy_hits = _count_hits(blob, comedy_terms)

        # The combination is what defines this concept.
        if mystery_hits > 0 and comedy_hits > 0:
            bonus += 0.52
            bonus += min(0.16, 0.04 * (mystery_hits + comedy_hits))

        elif mystery_hits > 0:
            bonus += 0.16
            multiplier *= 0.68

        elif comedy_hits > 0:
            bonus += 0.10
            multiplier *= 0.62

        else:
            if semantic_score < 0.22:
                return False, 0.0, 1.0
            multiplier *= 0.50

        # Straight crime should not dominate a comedy-mystery page.
        if 80 in genres and comedy_hits == 0:
            multiplier *= 0.55

        if _contains_any(blob, wrong_context_terms):
            if comedy_hits == 0:
                multiplier *= 0.40
            else:
                multiplier *= 0.70

    elif anchor_concept == "social_satire":
        satire_terms = [
            "satire",
            "social satire",
            "sardonic",
            "scathing",
            "class conflict",
            "social class",
            "social elite",
            "privilege",
            "privileged",
            "wealth",
            "wealthy",
            "elite",
            "status",
            "exploitation",
        ]

        social_drama_terms = [
            "family",
            "relationships",
            "marriage",
            "vacation",
            "resort",
            "hotel",
            "society",
            "anthology",
            "ambition",
            "power",
        ]

        wrong_context_terms = [
            "post-apocalyptic",
            "apocalypse",
            "zombie",
            "serial killer",
            "police investigation",
            "murder investigation",
            "space",
            "time travel",
            "superhero",
        ]

        satire_hits = _count_hits(blob, satire_terms)
        social_hits = _count_hits(blob, social_drama_terms)

        if satire_hits >= 2:
            bonus += 0.40
        elif satire_hits == 1:
            bonus += 0.26

        bonus += min(0.16, 0.04 * social_hits)

        if satire_hits == 0:
            if semantic_score < 0.20:
                multiplier *= 0.55
            else:
                multiplier *= 0.75

        if _contains_any(blob, wrong_context_terms):
            if satire_hits == 0:
                multiplier *= 0.40
            else:
                multiplier *= 0.70

    elif anchor_concept == "warm_workplace_comedy":
        workplace_terms = [
            "workplace comedy",
            "workplace",
            "team",
            "teammate",
            "colleagues",
            "coworkers",
            "coach",
            "coaching",
            "office",
            "school",
            "restaurant",
        ]

        warmth_terms = [
            "friendship",
            "male friendship",
            "female friendship",
            "optimist",
            "optimistic",
            "joyful",
            "nice guy",
            "community",
            "teamwork",
            "mentor",
            "mentorship",
            "found family",
            "heartwarming",
            "uplifting",
            "fish out of water",
            "relationships",
        ]

        dark_terms = [
            "serial killer",
            "gangster",
            "organized crime",
            "murder investigation",
            "murder",
            "drug addiction",
            "drug dealer",
            "violent crime",
            "horror",
        ]

        workplace_hits = _count_hits(blob, workplace_terms)
        warmth_hits = _count_hits(blob, warmth_terms)
        dark_hits = _count_hits(blob, dark_terms)

        is_comedy_candidate = 35 in genres
        has_workplace_comedy = "workplace comedy" in blob
        has_sitcom = "sitcom" in blob

        # The concept needs comedy plus some kind of workplace/team setting.
        # "Workplace comedy" itself is the strongest reusable metadata signal.
        if not is_comedy_candidate:
            return False, 0.0, 1.0

        if not has_workplace_comedy and workplace_hits == 0:
            return False, 0.0, 1.0

        # Strong structural match.
        if has_workplace_comedy:
            bonus += 0.42
        elif workplace_hits >= 2:
            bonus += 0.28
        else:
            bonus += 0.16

        # Sitcom/comedy tone is useful supporting evidence.
        if has_sitcom:
            bonus += 0.16

        # Warm relationship/community metadata improves the match,
        # but sparse TMDb keywords no longer cause rejection.
        if warmth_hits >= 3:
            bonus += 0.24
        elif warmth_hits == 2:
            bonus += 0.18
        elif warmth_hits == 1:
            bonus += 0.10

        # Extra workplace evidence gets only a small reward.
        # This prevents keyword-rich shows dominating purely through metadata density.
        bonus += min(0.10, 0.025 * workplace_hits)

        # Dark subject matter is allowed in a comedy-drama, but increasingly
        # weakens the tonal fit.
        if dark_hits >= 2:
            multiplier *= 0.45
        elif dark_hits == 1:
            multiplier *= 0.68
    elif anchor_concept == "royal_historical_drama":
        royal_terms = [
            "royal family",
            "royalty",
            "monarchy",
            "british monarchy",
            "british royal family",
            "king",
            "queen",
            "prince",
            "princess",
            "palace",
            "palace intrigue",
            "dynasty",
            "aristocracy",
            "aristocratic",
        ]

        historical_terms = [
            "historical",
            "historical drama",
            "period",
            "history",
            "court",
            "empire",
            "nobility",
            "political",
            "politics",
        ]

        wrong_context_terms = [
            "modern corporation",
            "hedge fund",
            "wall street",
            "startup",
            "serial killer",
            "police procedural",
            "post-apocalyptic",
            "superhero",
        ]

        royal_hits = _count_hits(blob, royal_terms)
        historical_hits = _count_hits(blob, historical_terms)

        if royal_hits >= 2:
            bonus += 0.44
        elif royal_hits == 1:
            bonus += 0.30

        bonus += min(0.22, 0.05 * historical_hits)

        # Historical dramas without explicit royalty can still be good neighbours.
        if royal_hits == 0:
            if historical_hits == 0:
                if semantic_score < 0.20:
                    return False, 0.0, 1.0
                multiplier *= 0.60
            else:
                multiplier *= 0.82

        if _contains_any(blob, wrong_context_terms):
            multiplier *= 0.50


    elif anchor_concept == "espionage_thriller":
        spy_terms = [
            "spy",
            "spies",
            "espionage",
            "secret agent",
            "intelligence agency",
            "intelligence officer",
            "mi5",
            "mi6",
            "cia",
            "british intelligence",
            "operative",
            "undercover agent",
        ]

        thriller_terms = [
            "terrorism",
            "national security",
            "government",
            "conspiracy",
            "surveillance",
            "undercover",
            "political thriller",
            "agent",
            "intelligence",
        ]

        wrong_context_terms = [
            "serial killer",
            "police procedural",
            "homicide",
            "superhero",
            "supernatural",
            "post-apocalyptic",
            "zombie",
        ]

        spy_hits = _count_hits(blob, spy_terms)
        thriller_hits = _count_hits(blob, thriller_terms)

        if spy_hits >= 2:
            bonus += 0.46
        elif spy_hits == 1:
            bonus += 0.30

        if spy_hits > 0:
            bonus += min(0.18, 0.05 * thriller_hits)

        # A generic crime/thriller shouldn't qualify just because Reddit
        # associates it with the anchor.
        if spy_hits == 0:
            if thriller_hits == 0:
                if semantic_score < 0.22:
                    return False, 0.0, 1.0
                multiplier *= 0.55
            else:
                multiplier *= 0.70

        if 80 in genres and spy_hits == 0:
            multiplier *= 0.55

        if _contains_any(blob, wrong_context_terms):
            if spy_hits == 0:
                multiplier *= 0.40
            else:
                multiplier *= 0.75

    elif anchor_concept == "medical_family":
        is_period = _contains_any(blob, ["period", "post-war", "postwar", "1950", "1960", "historical"])
        is_community = _contains_any(blob, ["community", "village", "family", "women", "rural"])
        is_midwife = _contains_any(blob, ["midwife", "maternity", "district nurse", "community nurse", "nurse", "nurses"])
        is_medical = _contains_any(blob, ["hospital", "doctor", "medical", "clinic", "patient", "ward"])
        is_modern_hospital = _contains_any(blob, ["emergency department", "trauma", "resident", "medical center"])

        if 10765 in genres or 10759 in genres:
            return False, 0.0, 1.0

        if _contains_any(blob, ["monster", "godzilla", "alien", "superhero", "secret organization"]):
            return False, 0.0, 1.0

        # Hard reject only if it has no useful signal at all.
        if not (is_midwife or is_medical or is_community or is_period):
            if semantic_score < 0.22 and genre_score < 0.20:
                return False, 0.0, 1.0
            multiplier *= 0.75

        # Penalise modern hospital shows, but do not automatically kill them.
        if is_modern_hospital:
            multiplier *= 0.55

        # Boost close matches.
        if is_midwife:
            bonus += 0.25
        if is_period and is_community:
            bonus += 0.22
        elif is_community:
            bonus += 0.12
        if is_medical:
            bonus += 0.10
        if is_period or is_community:
            bonus += 0.16

        if is_modern_hospital and not is_community:
            multiplier *= 0.72
        

                # Global sanity filter
    if semantic_score < 0.15 and genre_score < 0.15 and bonus < 0.05:
        return False, 0.0, 1.0

    return True, float(bonus), float(multiplier)


def _source_label(is_reddit: bool, is_tmdb: bool, is_trending: bool, semantic_score: float) -> str:
    if is_reddit and (is_tmdb or is_trending):
        return "multi_signal"
    if is_reddit:
        return "reddit_pairs"
    if is_tmdb:
        return "tmdb_recs"
    if semantic_score >= 0.18:
        return "semantic_fallback"
    return "fill"


def _normalise_result_score(item: dict) -> dict:
    item["score"] = round(float(item.get("score") or 0.0), 4)
    return item



def _weak_future_for_seo(details: dict) -> bool:
    """Avoid unreleased/current-year filler unless it is an unmistakable concept match."""
    first_air_date = str(details.get("first_air_date") or "")
    try:
        year = int(first_air_date[:4])
    except Exception:
        return False
    if not year or year < CURRENT_YEAR:
        return False
    vote_count = int(details.get("vote_count") or 0)
    # Current/future titles can be useful, but only with enough audience signal.
    return vote_count < 300


def _concept_required_blob_terms(anchor_concept: str) -> tuple[list[str], list[str]]:
    """Return (positive_terms, hard_reject_terms) for the final/fill sanity layer."""
    if anchor_concept == "finance_power":
        return [
            "finance", "hedge fund", "wall street", "billionaire", "wealth",
            "corporate", "business empire", "media empire", "conglomerate",
            "company", "ceo", "executive", "boardroom", "shareholder",
            "merger", "acquisition", "dynasty", "inheritance", "elite",
            "power", "ambition", "rivalry", "political", "corruption",
            "law firm", "attorney", "lawyer", "investment", "trading",
        ], [
            "marshals", "navy seal", "range justice", "cowboy", "superhero",
            "high school", "teen", "restaurant", "sandwich shop", "chef",
            "hospital", "nurse", "doctor",
        ]

    if anchor_concept == "medical_family":
        return [
            "midwife", "maternity", "nurse", "nurses", "hospital", "doctor",
            "medical", "clinic", "patients", "community care", "district nurse",
            "period", "historical", "post-war", "postwar", "1950", "1960",
            "village", "rural", "women", "family home", "cornwall", "estate",
        ], [
            "marshals", "navy seal", "range justice", "murder", "killer",
            "assassin", "cartel", "mafia", "gang", "superhero", "sci-fi",
            "science fiction", "alien", "restaurant", "sandwich shop", "chef",
        ]

    if anchor_concept == "period_community":
        return [
            "period", "historical", "victorian", "georgian", "post-war",
            "postwar", "1950", "1960", "18th century", "19th century",
            "estate", "village", "rural", "community", "family", "marriage",
            "cornwall", "aristocratic", "women", "social class",
        ], [
            "marshals", "navy seal", "range justice", "superhero", "alien",
            "sci-fi", "science fiction", "cartel", "mafia", "serial killer",
        ]

    return [], []


def _passes_grounded_concept_sanity(anchor_concept: str, details: dict, *, source: str, score: float) -> bool:
    """Final guardrail for grounded SEO pages so high-popularity generic dramas do not leak in."""
    positive_terms, reject_terms = _concept_required_blob_terms(anchor_concept)
    if not positive_terms and not reject_terms:
        return True

    blob = _blob_for(details)
    title = str(details.get("title") or details.get("name") or "").strip().lower()
    genres = set(details.get("genre_ids") or [])

    if reject_terms and _contains_any(blob, reject_terms):
        return False

    hits = _count_hits(blob, positive_terms)

    # Hard genre drift blocks for grounded pages.
    if anchor_concept in {"medical_family", "period_community", "finance_power"}:
        if 10765 in genres or 10759 in genres or 16 in genres or 10764 in genres or 10762 in genres:
            return False

    if anchor_concept == "finance_power":
        # Allow a few prestige power/crime dramas even if the overview wording is sparse.
        allow_titles = {"the good wife",
        "the good fight",
        "billions",
        "industry",
        "mad men",
        "the sopranos",
        "the white lotus",
        "house of cards",
        "the newsroom",
        "the morning show",}

        if title in allow_titles:
            return True
        if hits == 0:
            return False
        if source == "fill" and hits < 2:
            return False
        return True

    if anchor_concept == "medical_family":
        allow_titles = {"poldark", "all creatures great and small", "downton abbey", "the durrells", "nurses"}
        if title in allow_titles:
            return True
        if hits == 0:
            return False
        # For filler, require more than a generic family mention.
        if source == "fill" and hits < 2 and not _contains_any(blob, ["midwife", "nurse", "hospital", "doctor", "medical", "period", "village", "community care"]):
            return False
        return True

    if anchor_concept == "period_community":
        if hits == 0:
            return False
        if source == "fill" and hits < 2:
            return False
        return True

    return True

def _seo_ranking_layer(
    ranked: list[dict],
    *,
    anchor_concept: str,
    limit: int,
    anchor_tmdb_id: int | None = None,
    taxonomy_mode: bool = False,
) -> list[dict]:
    """
    Final SEO polish layer:
    - removes obvious low-quality drift
    - demotes generic filler/procedurals
    - keeps result diversity
    - avoids cheap-looking old/dated results
    """

    HARD_EXCLUDE_TITLES = {
        # Generic procedurals that make SEO pages look low quality
        "castle",
        "blue bloods",
        "major crimes",
        "elementary",
        "the rookie",
        "fbi: international",
        "hill street blues",
        "the untouchables",
        "in the heat of the night",

        # Weak sci-fi / tone breakers for concept pages
        "the outer limits",
        "the pretender",
        "taken",
    }

    CONCEPT_TITLE_BOOSTS = {
        "contained_dystopia": {
            "fallout": 0.55,
            "paradise": 0.50,
            "station eleven": 0.42,
            "the last of us": 0.42,
            "snowpiercer": 0.30,
            "silo": 0.30,
        },
        "mystery_box_survival": {
            "from": 0.60,
            "fringe": 0.46,
            "dark": 0.42,
            "12 monkeys": 0.40,
            "manifest": 0.38,
            "yellowjackets": 0.36,
            "the leftovers": 0.34,
            "wayward pines": 0.32,
            "silo": 0.28,
            "stranger things": 0.24,
            "the 100": 0.20,
            "under the dome": 0.18,
        },
        "prestige_existential_mystery": {
            "the leftovers": 0.55,
            "lost": 0.38,
            "from": 0.34,
            "dark": 0.32,
            "fringe": 0.26,
            "manifest": 0.24,
            "yellowjackets": 0.24,
            "black mirror": 0.20,
            "silo": 0.18,
        },
        "corporate_mystery": {
            "black mirror": 0.35,
            "severance": 0.35,
            "silo": 0.25,
            "dark": 0.25,
            "3 body problem": 0.20,
        },
        "crime_pressure": {
            "better call saul": 0.35,
            "the sopranos": 0.30,
            "fargo": 0.28,
            "the wire": 0.28,
            "mr. robot": 0.22,
            "the night of": 0.22,
            "true detective": 0.22,
        },

        "finance_power": {
        "industry": 0.50,
        "billions": 0.46,
        "mad men": 0.36,
        "the good wife": 0.30,
        "the good fight": 0.30,
        "the white lotus": 0.28,
        "house of cards": 0.28,
        "the sopranos": 0.24,
        "the newsroom": 0.22,
        "the morning show": 0.20,
        },

        "space_franchise_adventure": {
        "the book of boba fett": 0.60,
        "ahsoka": 0.56,
        "andor": 0.52,
        "star wars rebels": 0.50,
        "obi-wan kenobi": 0.48,
        "star wars: skeleton crew": 0.46,
        "star wars: the clone wars": 0.42,
        "star wars: the bad batch": 0.40,
        "firefly": 0.30,
        "battlestar galactica": 0.18,
        "the expanse": 0.18,
        "stargate atlantis": 0.14,
        "stargate sg-1": 0.14,
        },
    }

    def title_of(item: dict) -> str:
        return str(item.get("title") or item.get("name") or "").strip().lower()

    def year_of(item: dict) -> int:
        try:
            return int(str(item.get("first_air_date") or "")[:4])
        except Exception:
            return 0

    def bucket_for(item: dict) -> str:
        title = title_of(item)
        genres = set(item.get("genre_ids") or [])
        blob = " ".join([
            title,
            str(item.get("overview") or "").lower(),
            " ".join(str(g).lower() for g in item.get("genres") or []),
        ])

        if title in {"fallout", "silo", "snowpiercer", "station eleven", "the last of us"}:
            return "dystopia"

        if 10765 in genres:
            return "scifi"

        if "lawyer" in blob or "legal" in blob or "attorney" in blob:
            return "legal"

        if "cartel" in blob or "drug" in blob or "mafia" in blob or "mob" in blob:
            return "crime_underworld"

        if "detective" in blob or "murder" in blob or "investigation" in blob:
            return "crime_mystery"

        if 80 in genres:
            return "crime"

        if 18 in genres:
            return "drama"

        return "other"

    polished: list[dict] = []

    for item in ranked:
        title = title_of(item)
        genres = set(item.get("genre_ids") or [])
        source = str(item.get("source") or "")
        year = year_of(item)

        if not title:
            continue

        if anchor_tmdb_id is not None and int(item.get("tmdb_id") or 0) == int(anchor_tmdb_id):
            continue

        if title in HARD_EXCLUDE_TITLES:
            continue

        score = float(item.get("score") or 0.0)

        if source == "fill" and _weak_future_for_seo(item):
            continue

        taxonomy_exact_specialist = bool(
            taxonomy_mode
            and str(item.get("_seo_taxonomy_relationship_concept") or "") == anchor_concept
            and str(item.get("_seo_taxonomy_fit_tier") or "") in {"strong", "good"}
            and float(item.get("_seo_taxonomy_fit_score") or 0.0) >= 0.24
        )

        # V2.7.1: exact taxonomy specialist matches have already passed the
        # structural classifier + candidate-fit checks. Do not make them pass
        # the old concept-specific keyword sanity layer a second time.
        #
        # Non-exact and broad candidates still use the legacy safety check.
        if (
            not taxonomy_exact_specialist
            and not _passes_grounded_concept_sanity(
                anchor_concept,
                item,
                source=source,
                score=score,
            )
        ):
            continue

        if taxonomy_exact_specialist:
            # V2.7.1: niche exact-specialist matches may have lower popularity
            # after the generic fill/quality penalties. Keep a conservative
            # floor rather than discarding them purely for being less popular.
            min_polished_score = 0.42
        elif anchor_concept in {
            "period_community",
            "medical_family",
            "political_diplomatic_drama",
        }:
            min_polished_score = 0.42
        else:
            min_polished_score = 0.55

        if score < min_polished_score:
            continue

        if anchor_concept == "period_community":
            period_terms = [
                "period", "historical", "victorian", "georgian", "estate",
                "aristocratic", "19th century", "early 19th century",
                "18th century", "post-war", "postwar", "war", "cornwall"
            ]

            community_terms = [
                "family", "community", "village", "rural", "marriage",
                "inheritance", "social", "class", "relationships"
            ]

            blob = " ".join([
                title,
                str(item.get("overview") or "").lower(),
                " ".join(str(g).lower() for g in item.get("genres") or []),
            ])

            has_period = any(t in blob for t in period_terms)
            has_community = any(t in blob for t in community_terms)

            if 10765 in genres or 10759 in genres or 80 in genres:
                continue

            if not (has_period or has_community):
                if source != "tmdb_recs":
                    continue
                score *= 0.75

            if title in {"pride and prejudice", "the gilded age", "belgravia", "the crown", "upstairs downstairs"}:
                score += 0.45

            if has_period:
                score += 0.35
            elif has_community:
                score += 0.12

            if source == "fill":
                score *= 0.70

        if anchor_concept == "prestige_existential_mystery":
            blob = " ".join([
                title,
                str(item.get("overview") or "").lower(),
                " ".join(str(g).lower() for g in item.get("genres") or []),
            ])
            existential_terms = [
                "disappear", "disappears", "disappearance", "vanish", "vanished",
                "missing", "unexplained", "grief", "loss", "faith", "spiritual",
                "cult", "apocalypse", "apocalyptic", "supernatural", "paranormal",
                "identity", "consciousness", "psychological", "community",
            ]
            core_hits = _count_hits(blob, existential_terms)

            if 16 in genres:
                continue

            if 35 in genres or 10751 in genres or 10762 in genres or 10764 in genres:
                continue

            if "assassin" in blob or "medical center" in blob or "emergency department" in blob:
                continue

            if 80 in genres and core_hits < 2:
                score *= 0.48

            if 10759 in genres and core_hits < 2:
                score *= 0.60

            if core_hits >= 3:
                score += 0.32
            elif core_hits >= 1:
                score += 0.14
            else:
                score *= 0.70

            if 9648 in genres:
                score += 0.14
            if 10765 in genres:
                score += 0.10

            if source == "fill":
                score *= 0.90

        if anchor_concept == "prestige_existential_mystery":
            blob = " ".join([
                title,
                str(item.get("overview") or "").lower(),
                " ".join(str(g).lower() for g in item.get("genres") or []),
            ])
            existential_terms = [
                "disappear", "disappears", "disappearance", "vanish", "vanished",
                "missing", "unexplained", "grief", "loss", "faith", "spiritual",
                "cult", "apocalypse", "apocalyptic", "supernatural", "paranormal",
                "identity", "consciousness", "psychological", "community",
            ]
            core_hits = _count_hits(blob, existential_terms)

            if 16 in genres:
                continue

            if 35 in genres or 10751 in genres or 10762 in genres or 10764 in genres:
                continue

            if "assassin" in blob or "medical center" in blob or "emergency department" in blob:
                continue

            if 80 in genres and core_hits < 2:
                score *= 0.48

            if 10759 in genres and core_hits < 2:
                score *= 0.60

            if core_hits >= 3:
                score += 0.32
            elif core_hits >= 1:
                score += 0.14
            else:
                score *= 0.70

            if 9648 in genres:
                score += 0.14
            if 10765 in genres:
                score += 0.10

            if source == "fill":
                score *= 0.90

        if year >= 2020:
            score += 0.12
        elif year >= 2015:
            score += 0.06

        # Avoid anime/animation drift unless the concept supports it.
        if 16 in genres and anchor_concept not in {"general_scifi", "space_epic", "space_franchise_adventure",}:
            continue

        # Generic sci-fi/fantasy should not leak into grounded crime.
        if anchor_concept in {"crime_pressure", "detective_mystery", "small_town_mystery"}:
            if 10765 in genres:
                continue
            if 10759 in genres and title not in {"peaky blinders"}:
                score *= 0.55

        # Old shows often look bad on SEO pages unless they are prestige classics.
        classic_allowlist = {
            "the sopranos",
            "the wire",
            "star trek: deep space nine",
            "twin peaks",
            "the twilight zone",
        }

        if year and year < 1995 and title not in classic_allowlist:
            score *= 0.55

        # Fill results should not dominate top SEO slots.
        if source == "fill":
            score *= 0.82

        # Penalise low-confidence titles unless they are very relevant.
        vote_average = float(item.get("vote_average") or 0.0)
        vote_count = int(item.get("vote_count") or 0)
        popularity = float(item.get("popularity") or 0.0)

        is_prestige = vote_average >= 7.8 and vote_count >= 500
        is_decent = vote_average >= 7.2 and vote_count >= 150 and popularity >= 8

        if not is_prestige and not is_decent:
            score *= 0.78

        # Concept-specific title boosts.
        boost_map = CONCEPT_TITLE_BOOSTS.get(anchor_concept, {})
        if title in boost_map:
            score += boost_map[title]

        # Silo / contained dystopia specific cleanup.
        if anchor_concept == "contained_dystopia":
            if title in {"under the dome", "dollhouse", "the pretender", "the 100"}:
                score *= 0.70
            if title in {"fallout", "paradise", "station eleven", "the last of us"}:
                score += 0.45


        if taxonomy_exact_specialist:
            # V2.7.1: niche exact-specialist matches may have lower popularity
            # after the generic fill/quality penalties. Keep a conservative
            # floor rather than discarding them purely for being less popular.
            min_polished_score = 0.42
        elif anchor_concept in {
            "period_community",
            "medical_family",
            "political_diplomatic_drama",
        }:
            min_polished_score = 0.42
        else:
            min_polished_score = 0.55

        if score < min_polished_score:
            continue

        item = dict(item)
        item["score"] = round(score, 4)
        polished.append(item)

    polished.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)

    # Diversity cap: avoid one page becoming all procedurals / all legal / all sci-fi.
    bucket_counts: dict[str, int] = {}
    final: list[dict] = []
    seen_final_titles: set[str] = set()

    for item in polished:
        title = title_of(item)

        # Do not allow multiple TMDb records for the same TV series
        # to occupy separate recommendation slots.
        if title in seen_final_titles:
            continue

        bucket = bucket_for(item)
        max_per_bucket = 4

        if anchor_concept in {"crime_pressure", "detective_mystery"}:
            max_per_bucket = 5

        if anchor_concept == "political_diplomatic_drama":
            max_per_bucket = 12

        if anchor_concept == "period_professional_drama":
            max_per_bucket = 6  

        if anchor_concept == "warm_workplace_comedy":
            max_per_bucket = 6

        if anchor_concept == "contained_dystopia":
            max_per_bucket = 8

        if anchor_concept in {"mystery_box_survival", "prestige_existential_mystery"}:
            max_per_bucket = 5

        if anchor_concept == "time_mystery":
            if bucket == "scifi":
                max_per_bucket = 12
            elif bucket in {"crime", "crime_mystery"}:
                max_per_bucket = 2
            else:
                max_per_bucket = 4

        if anchor_concept == "space_franchise_adventure" and bucket == "scifi":
            max_per_bucket = 12

        # V2.3 taxonomy shadow mode already performs concept/family relevance
        # filtering upstream. Do not let the legacy diversity buckets truncate
        # a valid specialist list (for example, fantasy being grouped into the
        # old "scifi" bucket and capped at four).
        #
        # We still keep title de-duplication and the overall `limit`; only the
        # legacy per-bucket cap is bypassed.
        if taxonomy_mode:
            max_per_bucket = limit

        if bucket_counts.get(bucket, 0) >= max_per_bucket:
            if SEO_DEBUG:
                print(
                    "SEO DIVERSITY REJECT DEBUG:",
                    {
                        "title": title,
                        "score": round(float(item.get("score") or 0.0), 4),
                        "bucket": bucket,
                        "bucket_count": bucket_counts.get(bucket, 0),
                        "max_per_bucket": max_per_bucket,
                        "anchor_concept": anchor_concept,
                    },
                )
            continue

        if SEO_DEBUG:
            print(
                "SEO FINAL ACCEPT DEBUG:",
                {
                    "title": title,
                    "score": round(float(item.get("score") or 0.0), 4),
                    "bucket": bucket,
                    "bucket_count_before": bucket_counts.get(bucket, 0),
                    "max_per_bucket": max_per_bucket,
                    "anchor_concept": anchor_concept,
                },
    )

        final.append(item)
        seen_final_titles.add(title)
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1

        if len(final) >= limit:
            break

    for item in final:
        item.pop("_seo_taxonomy_relationship_concept", None)
        item.pop("_seo_taxonomy_fit_tier", None)
        item.pop("_seo_taxonomy_fit_score", None)

    return final

async def _tmdb_keywords(tv_id: int) -> list[dict]:
    """
    Fetch TMDb semantic keywords for a TV show.

    Keep both keyword ID and name:
    - name is used for semantic text scoring/classification
    - id is used for TMDb /discover/tv candidate generation
    """
    api_key = _tmdb_api_key()
    if not api_key or not tv_id:
        return []

    url = f"https://api.themoviedb.org/3/tv/{tv_id}/keywords"

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                url,
                params={"api_key": api_key},
            )

            if response.status_code != 200:
                return []

            data = response.json()

    except Exception:
        return []

    keywords = data.get("results") or []

    out: list[dict] = []

    for item in keywords:
        try:
            keyword_id = int(item.get("id") or 0)
        except Exception:
            keyword_id = 0

        name = str(item.get("name") or "").strip().lower()

        if keyword_id and name:
            out.append(
                {
                    "id": keyword_id,
                    "name": name,
                }
            )

    return out


async def _enrich_seo_details(details: dict) -> dict:
    if not details:
        return details

    enriched = dict(details)

    try:
        tmdb_id = int(
            enriched.get("tmdb_id")
            or enriched.get("id")
            or 0
        )
    except Exception:
        tmdb_id = 0

    if tmdb_id:
        keyword_items = await _tmdb_keywords(tmdb_id)

        enriched["seo_keywords"] = [
            str(item.get("name") or "").strip().lower()
            for item in keyword_items
            if str(item.get("name") or "").strip()
        ]

        enriched["seo_keyword_ids"] = [
            int(item.get("id"))
            for item in keyword_items
            if item.get("id")
        ]

        enriched["seo_keyword_items"] = [
            {
                "id": int(item.get("id")),
                "name": str(item.get("name") or "").strip().lower(),
            }
            for item in keyword_items
            if item.get("id")
            and str(item.get("name") or "").strip()
        ]
    else:
        enriched["seo_keywords"] = []
        enriched["seo_keyword_ids"] = []
        enriched["seo_keyword_items"] = []

    return enriched

def _active_concept_fit_score(
    anchor_concept: str,
    details: dict,
    *,
    semantic_score: float,
    genre_score: float,
    taxonomy_mode: bool = False,
) -> tuple[bool, float, float]:
    """Use taxonomy candidate-fit only for explicit taxonomy shadow requests."""
    if not taxonomy_mode:
        return _concept_fit_score(
            anchor_concept,
            details,
            semantic_score=semantic_score,
            genre_score=genre_score,
        )

    fit = taxonomy_candidate_fit(
        details,
        anchor_concept,
        strict=False,
        semantic_score=semantic_score,
        genre_score=genre_score,
    )

    # V2.5.1 relationship-gated fingerprint ------------------------------
    # Independently classify the candidate even when candidate_fit() took
    # the direct "strong" path. This gives us a real structural relationship
    # between the anchor concept and what the candidate itself appears to be.
    relationship_concept = None
    relationship_family = None
    relationship_state = None
    relationship_compatibility = 0.0

    if fit.passed:
        candidate_class = classify_anchor(details)
        relationship_concept = candidate_class.concept
        relationship_family = candidate_class.family
        relationship_state = candidate_class.state

        if relationship_concept == anchor_concept:
            relationship_compatibility = 1.0
        elif candidate_class.state == "general_fallback":
            # Sparse candidate metadata is uncertain rather than definitively
            # unrelated, so retain a neutral-low floor instead of zeroing it.
            relationship_compatibility = 0.42
        else:
            relationship_compatibility = taxonomy_concept_affinity(
                anchor_concept,
                relationship_concept,
            )

            # A different-family specialist should not receive a useful
            # fingerprint boost merely because of one literal shared keyword.
            if relationship_family != fit.candidate_family and relationship_compatibility <= 0:
                relationship_compatibility = 0.05

        relationship_compatibility = max(
            0.05,
            min(1.0, float(relationship_compatibility)),
        )

        details["_seo_taxonomy_relationship_concept"] = relationship_concept
        details["_seo_taxonomy_relationship_family"] = relationship_family
        details["_seo_taxonomy_relationship_state"] = relationship_state
        details["_seo_taxonomy_relationship_compatibility"] = (
            relationship_compatibility
        )

    if SEO_DEBUG and fit.passed and fit.tier in {"strong", "good", "broad"}:
        print(
            "SEO TAXONOMY GRADED FIT DEBUG:",
            {
                "title": details.get("title") or details.get("name"),
                "anchor_concept": anchor_concept,
                "tier": fit.tier,
                "candidate_concept": fit.candidate_concept,
                "candidate_family": fit.candidate_family,
                "semantic": round(float(semantic_score), 4),
                "genre": round(float(genre_score), 4),
                "fit_score": round(float(fit.score), 4),
                "affinity": round(float(fit.affinity), 4),
                "relationship_concept": relationship_concept,
                "relationship_family": relationship_family,
                "relationship_state": relationship_state,
                "relationship_compatibility": round(
                    float(relationship_compatibility), 4
                ),
                "admission_softened": bool(
                    fit.tier == "broad"
                    and fit.gate_reason not in {None, "", "ok"}
                ),
                "gate_reason": fit.gate_reason,
                "candidate_eligible_families": (
                    classify_anchor(details).eligible_families
                    if fit.passed and fit.tier == "broad"
                    else None
                ),
            },
        )

    if fit.passed:
        details["_seo_taxonomy_fit_tier"] = fit.tier
        details["_seo_taxonomy_fit_score"] = float(fit.score)
        details["_seo_taxonomy_fit_candidate_concept"] = fit.candidate_concept
        details["_seo_taxonomy_fit_candidate_family"] = fit.candidate_family

    return (bool(fit.passed), float(fit.score), float(fit.multiplier))


def _select_semantic_keyword_items(
    anchor_details: dict,
    anchor_concept: str,
    max_n: int = 8,
    taxonomy_mode: bool = False,
) -> list[dict]:
    """
    Rank the anchor's own TMDb keywords by relevance to its automatically
    detected concept.

    This avoids letting generic metadata such as location, age or family
    relationships dominate semantic candidate discovery.
    """
    keyword_items = list(
        anchor_details.get("seo_keyword_items") or []
    )

    if not keyword_items:
        return []

    concept_terms: list[str] = []

    if taxonomy_mode:
        for term in taxonomy_discovery_terms_for(anchor_concept, max_n=18):
            value = str(term or "").strip().lower()
            if value and value not in concept_terms:
                concept_terms.append(value)
    else:
        concept_profile = ANCHOR_CONCEPTS.get(
            anchor_concept,
            {},
        )

        concept_rule = CONCEPT_RULES.get(
            anchor_concept,
            {},
        )

        for term in (
            list(concept_profile.get("must_have") or [])
            + list(concept_profile.get("prefer") or [])
            + list(concept_rule.get("required_any") or [])
            + list(concept_rule.get("boost_any") or [])
        ):
            value = str(term or "").strip().lower()

            if value and value not in concept_terms:
                concept_terms.append(value)

    generic_terms = {
        "new york city",
        "los angeles",
        "sibling",
        "sibling relationship",
        "father",
        "mother",
        "son",
        "daughter",
        "brother",
        "sister",
        "marriage",
        "failed marriage",
        "friendship",
        "based on novel or book",
        "based on true story",
    }

    scored: list[tuple[float, dict]] = []

    for item in keyword_items:
        name = str(item.get("name") or "").strip().lower()

        if not name:
            continue

        score = 0.0

        # Exact or partial concept vocabulary match.
        for term in concept_terms:
            if term == name:
                score += 4.0
            elif term in name or name in term:
                score += 2.5

        # Compound keywords are generally more descriptive than a
        # single generic noun.
        if len(name.split()) >= 2:
            score += 0.35

        if name in generic_terms:
            score -= 2.5

        scored.append(
            (
                score,
                item,
            )
        )

    scored.sort(
        key=lambda pair: pair[0],
        reverse=True,
    )

    strong = [
        item
        for score, item in scored
        if score > 0
    ]

    # If concept matching produced too few keywords, supplement with the
    # highest-ranked non-generic anchor keywords.
    if len(strong) < min(4, max_n):
        for score, item in scored:
            name = str(
                item.get("name") or ""
            ).strip().lower()

            if (
                item not in strong
                and name not in generic_terms
            ):
                strong.append(item)

            if len(strong) >= max_n:
                break

    return strong[:max_n]

def _semantic_concept_terms(
    anchor_concept: str,
    *,
    max_n: int = 8,
    taxonomy_mode: bool = False,
) -> list[str]:
    """
    Return reusable semantic discovery vocabulary for an automatically
    detected concept.

    Prefer ANCHOR_CONCEPTS when available, otherwise reuse CONCEPT_RULES.
    """
    if taxonomy_mode:
        return [
            str(term).strip().lower()
            for term in taxonomy_discovery_terms_for(anchor_concept, max_n=max_n)
            if str(term or "").strip()
        ][:max_n]

    terms: list[str] = []

    profile = ANCHOR_CONCEPTS.get(anchor_concept) or {}

    profile_terms = (
        list(profile.get("must_have") or [])
        + list(profile.get("prefer") or [])
    )

    for term in profile_terms:
        value = str(term or "").strip().lower()

        if value and value not in terms:
            terms.append(value)

    # Most concepts currently live in CONCEPT_RULES rather than
    # ANCHOR_CONCEPTS, so use that vocabulary as the generic fallback.
    if len(terms) < max_n:
        rule = CONCEPT_RULES.get(anchor_concept) or {}

        rule_terms = (
            list(rule.get("required_any") or [])
            + list(rule.get("boost_any") or [])
        )

        for term in rule_terms:
            value = str(term or "").strip().lower()

            if value and value not in terms:
                terms.append(value)

            if len(terms) >= max_n:
                break

    return terms[:max_n]

async def _tmdb_keyword_ids_for_terms(
    terms: list[str],
    *,
    max_terms: int = 6,
) -> list[dict]:
    """
    Resolve semantic concept vocabulary into TMDb keyword IDs.

    This lets candidate discovery expand beyond the exact keywords attached
    to the anchor while remaining completely title-agnostic.
    """
    api_key = _tmdb_api_key()

    if not api_key:
        return []

    clean_terms: list[str] = []

    for term in terms:
        value = str(term or "").strip().lower()

        if not value:
            continue

        if value not in clean_terms:
            clean_terms.append(value)

        if len(clean_terms) >= max_terms:
            break

    if not clean_terms:
        return []

    url = "https://api.themoviedb.org/3/search/keyword"

    async def resolve_term(term: str) -> dict | None:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(
                    url,
                    params={
                        "api_key": api_key,
                        "query": term,
                        "page": 1,
                    },
                )

            if response.status_code != 200:
                return None

            data = response.json()
            results = list(data.get("results") or [])

        except Exception:
            return None

        if not results:
            return None

        # Exact keyword-name matches are much safer than accepting an
        # unrelated first search result.
        exact = next(
            (
                item
                for item in results
                if str(item.get("name") or "").strip().lower() == term
            ),
            None,
        )

        # Do not guess when TMDb does not have an exact keyword.
        if exact is None:
            return None

        try:
            keyword_id = int(exact.get("id") or 0)
        except Exception:
            return None

        name = str(
            exact.get("name") or ""
        ).strip().lower()

        if not keyword_id or not name:
            return None

        return {
            "id": keyword_id,
            "name": name,
            "source": "concept",
        }

    resolved = await asyncio.gather(
        *[
            resolve_term(term)
            for term in clean_terms
        ]
    )

    output: list[dict] = []
    seen_ids: set[int] = set()

    for item in resolved:
        if not item:
            continue

        try:
            keyword_id = int(item.get("id") or 0)
        except Exception:
            continue

        if not keyword_id or keyword_id in seen_ids:
            continue

        seen_ids.add(keyword_id)
        output.append(item)

    return output

async def _fetch_tmdb_semantic_candidates(
    *,
    anchor_tmdb_id: int,
    anchor_details: dict,
    anchor_concept: str,
    limit: int = 60,
    taxonomy_mode: bool = False,
) -> list[dict]:
    """
    Discover additional TV candidates by querying TMDb separately for the
    anchor's strongest semantic keywords.

    A candidate becomes stronger when it is independently discovered through
    several meaningful anchor keywords. This is more useful than one giant OR
    query where matching a single generic keyword is enough.

    Completely title-agnostic.
    """
    api_key = _tmdb_api_key()

    if not api_key:
        return []

    genre_ids: list[int] = []

    for value in anchor_details.get("genre_ids") or []:
        try:
            genre_id = int(value)
        except Exception:
            continue

        if genre_id > 0 and genre_id not in genre_ids:
            genre_ids.append(genre_id)

   # For grounded finance/power dramas, Comedy is often a secondary
    # classification rather than a useful discovery constraint.
    if anchor_concept == "finance_power":
        if 18 in genre_ids:
            genre_ids = [18]

    # Some TMDb genre profiles are too broad or misleading for semantic
    # discovery. When we have a strong concept classification, use genres
    # that better represent that concept instead of allowing an incidental
    # genre to dominate discovery.
    CONCEPT_DISCOVERY_GENRES = {
        "political_diplomatic_drama": [18, 10768],
        "period_power_drama": [18, 10768],
        "period_professional_drama": [18],
        "speculative_anthology": [18, 10765],
        "comedy_mystery": [35, 9648],
    }

    if taxonomy_mode:
        concept_genres = taxonomy_discovery_genres_for(anchor_concept, max_n=3)
    else:
        concept_genres = CONCEPT_DISCOVERY_GENRES.get(anchor_concept)

    if concept_genres:
        genre_ids = concept_genres

    original_language = str(
        anchor_details.get("original_language") or ""
    ).strip()

    # Strong keywords that TMDb explicitly assigned to this anchor.
    anchor_keyword_items = _select_semantic_keyword_items(
        anchor_details,
        anchor_concept,
        max_n=6,
        taxonomy_mode=taxonomy_mode,
    )

    # Expand discovery using vocabulary from the automatically detected concept.
    concept_terms = _semantic_concept_terms(
        anchor_concept,
        max_n=14,
        taxonomy_mode=taxonomy_mode,
    )

    concept_keyword_items = await _tmdb_keyword_ids_for_terms(
        concept_terms,
        max_terms=14,
    )

    # Tag anchor keywords as their own evidence source.
    anchor_keyword_items = [
        {
            "id": int(item["id"]),
            "name": str(item["name"]).strip().lower(),
            "source": "anchor",
        }
        for item in anchor_keyword_items
        if item.get("id")
        and str(item.get("name") or "").strip()
    ]

    # Combine the two sources without querying the same TMDb keyword twice.
    selected_keyword_items: list[dict] = []
    seen_keyword_ids: set[int] = set()

    for item in anchor_keyword_items + concept_keyword_items:
        try:
            keyword_id = int(item.get("id") or 0)
        except Exception:
            continue

        if not keyword_id or keyword_id in seen_keyword_ids:
            continue

        seen_keyword_ids.add(keyword_id)
        selected_keyword_items.append(item)

    # Keep network usage bounded.
    selected_keyword_items = selected_keyword_items[:14]

    if not selected_keyword_items:
        return []

    url = "https://api.themoviedb.org/3/discover/tv"

    # Store independent evidence for every candidate.
    candidate_evidence: dict[int, dict] = {}

    async def fetch_keyword(
        keyword_item: dict,
        keyword_rank: int,
    ) -> tuple[dict, list[dict]]:
        try:
            keyword_id = int(keyword_item.get("id") or 0)
        except Exception:
            return keyword_item, []

        if not keyword_id:
            return keyword_item, []

        params = {
            "api_key": api_key,
            "include_adult": "false",
            "sort_by": "popularity.desc",
            "vote_count.gte": 40,
            "vote_average.gte": 6.3,
            "with_keywords": str(keyword_id),
            "page": 1,
        }

        # Anchor genres are OR-based. A candidate only needs to share
        # one useful genre rather than every genre assigned to the anchor.
        if genre_ids:
            params["with_genres"] = "|".join(
                str(genre_id)
                for genre_id in genre_ids[:3]
            )

        

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    url,
                    params=params,
                )

            if response.status_code != 200:
                return keyword_item, []

            data = response.json()
            results = list(data.get("results") or [])
            total_results = int(data.get("total_results") or len(results))

            # V2.5 fingerprint: preserve how common this keyword is across the
            # TMDb discover result set. This is a generic rarity signal.
            enriched_keyword_item = dict(keyword_item)
            enriched_keyword_item["result_count"] = max(1, total_results)

            if SEO_DEBUG:
                print(
                    "SEO KEYWORD QUERY DEBUG:",
                    {
                        "keyword": str(
                            keyword_item.get("name") or ""
                        ),
                        "source": str(
                            keyword_item.get("source") or "anchor"
                        ),
                        "count": len(results),
                        "total_results": total_results,
                        "titles": [
                            str(item.get("name") or "")
                            for item in results[:20]
                        ],
                    },
                )

            return (
                enriched_keyword_item,
                results,
            )

        except Exception:
            return keyword_item, []

    # Run each meaningful keyword independently.
    keyword_results = await asyncio.gather(
        *[
            fetch_keyword(
                keyword_item,
                rank,
            )
            for rank, keyword_item in enumerate(
                selected_keyword_items
            )
        ]
    )

    # V2.5 anchor fingerprint -------------------------------------------------
    # Fingerprint terms are the *actual TMDb keywords selected from this anchor*.
    # Importance is automatic:
    #   1) rarer TMDb keywords are more discriminating,
    #   2) multi-word phrases are more specific,
    #   3) taxonomy role says whether the term is defining or merely contextual.
    #
    # No title mappings or per-show rules.
    anchor_fingerprint_weights: dict[str, float] = {}

    if taxonomy_mode:
        import math

        for keyword_item, _items in keyword_results:
            if str(keyword_item.get("source") or "") != "anchor":
                continue

            name = str(keyword_item.get("name") or "").strip().lower()
            if not name:
                continue

            result_count = max(
                1,
                int(keyword_item.get("result_count") or 1),
            )

            # Smooth IDF-like rarity. Very rare terms approach 1.0; very common
            # terms retain a small floor rather than disappearing entirely.
            rarity = max(
                0.16,
                min(
                    1.0,
                    1.10 - (0.12 * math.log2(1.0 + result_count)),
                ),
            )

            word_count = len([part for part in name.split() if part])
            if word_count >= 3:
                specificity = 1.22
            elif word_count == 2:
                specificity = 1.10
            else:
                specificity = 1.0

            role_weight = taxonomy_fingerprint_term_role_weight(
                anchor_concept,
                name,
            )

            weight = rarity * specificity * role_weight
            anchor_fingerprint_weights[name] = round(
                max(anchor_fingerprint_weights.get(name, 0.0), weight),
                4,
            )

    fingerprint_total_weight = sum(anchor_fingerprint_weights.values())
    fingerprint_max_weight = max(
        anchor_fingerprint_weights.values(),
        default=0.0,
    )

    for keyword_rank, (keyword_item, items) in enumerate(
        keyword_results
    ):
        keyword_source = str(
            keyword_item.get("source") or "anchor"
        )

        # Anchor keywords are direct evidence from the programme itself.
        # Concept keywords broaden recall, but should carry slightly less
        # weight individually.
        source_weight = (
            1.0
            if keyword_source == "anchor"
            else 0.78
        )

        rank_weight = max(
            0.60,
            1.0 - (0.06 * keyword_rank),
        )

        keyword_weight = (
            source_weight
            * rank_weight
        )

        keyword_name = str(
            keyword_item.get("name") or ""
        ).strip().lower()

        for item in items:
            try:
                rid = int(item.get("id") or 0)
            except Exception:
                continue

            if not rid or rid == anchor_tmdb_id:
                continue

            evidence = candidate_evidence.setdefault(
                rid,
                {
                    "tmdb_id": rid,
                    "keyword_hits": 0,
                    "anchor_keyword_hits": 0,
                    "concept_keyword_hits": 0,
                    "weighted_hits": 0.0,
                    "matched_keywords": [],
                    "vote_average": 0.0,
                    "vote_count": 0,
                    "popularity": 0.0,
                },
            )

            evidence["keyword_hits"] += 1
            evidence["weighted_hits"] += keyword_weight
            if keyword_source == "anchor":
                evidence["anchor_keyword_hits"] += 1
            else:
                evidence["concept_keyword_hits"] += 1

            if (
                keyword_name
                and keyword_name not in evidence["matched_keywords"]
            ):
                matched_keyword = {
                    "name": keyword_name,
                    "source": keyword_source,
                }

                if taxonomy_mode and keyword_source == "anchor":
                    matched_keyword["fingerprint_weight"] = float(
                        anchor_fingerprint_weights.get(keyword_name, 0.0)
                    )
                    matched_keyword["result_count"] = int(
                        keyword_item.get("result_count") or 0
                    )

                evidence["matched_keywords"].append(matched_keyword)

            evidence["vote_average"] = max(
                float(evidence.get("vote_average") or 0.0),
                float(item.get("vote_average") or 0.0),
            )

            evidence["vote_count"] = max(
                int(evidence.get("vote_count") or 0),
                int(item.get("vote_count") or 0),
            )

            evidence["popularity"] = max(
                float(evidence.get("popularity") or 0.0),
                float(item.get("popularity") or 0.0),
            )

    # V2.3 candidate-breadth pass.
    #
    # Keyword discovery is intentionally precise, but some concepts can have
    # only a handful of TMDb titles carrying the exact taxonomy keywords.
    # In taxonomy shadow mode, always add a bounded genre-driven candidate
    # pool and let taxonomy candidate_fit() decide relevance downstream.
    #
    # This is generic: no title-specific rules and only three extra TMDb calls.
    # Production retains the old single-page sparse fallback.
    breadth_pages = 3 if taxonomy_mode else (1 if len(candidate_evidence) < 20 else 0)

    if breadth_pages and genre_ids:
        async def fetch_breadth_page(page: int) -> list[dict]:
            try:
                params = {
                    "api_key": api_key,
                    "include_adult": "false",
                    "sort_by": "popularity.desc",
                    "vote_count.gte": 40,
                    "vote_average.gte": 6.3,
                    "with_genres": "|".join(str(gid) for gid in genre_ids[:3]),
                    "page": page,
                }

                async with httpx.AsyncClient(timeout=8.0) as client:
                    response = await client.get(url, params=params)

                if response.status_code != 200:
                    return []

                return list((response.json() or {}).get("results") or [])

            except Exception:
                return []

        breadth_results = await asyncio.gather(
            *[
                fetch_breadth_page(page)
                for page in range(1, breadth_pages + 1)
            ]
        )

        breadth_added = 0

        for page_items in breadth_results:
            for item in page_items:
                try:
                    rid = int(item.get("id") or 0)
                except Exception:
                    continue

                if not rid or rid == anchor_tmdb_id:
                    continue

                was_new = rid not in candidate_evidence

                evidence = candidate_evidence.setdefault(
                    rid,
                    {
                        "tmdb_id": rid,
                        "keyword_hits": 0,
                        "anchor_keyword_hits": 0,
                        "concept_keyword_hits": 0,
                        "weighted_hits": 0.0,
                        "matched_keywords": [],
                        "vote_average": 0.0,
                        "vote_count": 0,
                        "popularity": 0.0,
                        "breadth_hits": 0,
                    },
                )

                # Existing keyword-discovered candidates may not have this
                # field because they were created earlier.
                evidence["breadth_hits"] = int(
                    evidence.get("breadth_hits") or 0
                ) + 1

                evidence["vote_average"] = max(
                    float(evidence.get("vote_average") or 0.0),
                    float(item.get("vote_average") or 0.0),
                )

                evidence["vote_count"] = max(
                    int(evidence.get("vote_count") or 0),
                    int(item.get("vote_count") or 0),
                )

                evidence["popularity"] = max(
                    float(evidence.get("popularity") or 0.0),
                    float(item.get("popularity") or 0.0),
                )

                if was_new:
                    breadth_added += 1

        if SEO_DEBUG:
            print(
                "SEO TAXONOMY BREADTH DEBUG:",
                {
                    "anchor_concept": anchor_concept,
                    "genre_ids": genre_ids[:3],
                    "pages": breadth_pages,
                    "breadth_added": breadth_added,
                    "candidate_pool": len(candidate_evidence),
                },
            )

    candidates: list[dict] = []

    for evidence in candidate_evidence.values():
        keyword_hits = int(
            evidence.get("keyword_hits") or 0
        )

        weighted_hits = float(
            evidence.get("weighted_hits") or 0.0
        )

        vote_average = float(
            evidence.get("vote_average") or 0.0
        )

        # Repeated discovery is the strongest signal.
        #
        # One keyword match is useful.
        # Two independent matches are substantially stronger.
        # Three or more indicates very strong semantic overlap.
        overlap_component = min(
            1.0,
            weighted_hits / 2.5,
        )

        repeat_component = min(
            1.0,
            keyword_hits / 3.0,
        )

        quality_component = min(
            1.0,
            vote_average / 10.0,
        )

        breadth_hits = int(
            evidence.get("breadth_hits") or 0
        )

        breadth_component = (
            0.08
            if taxonomy_mode and breadth_hits > 0
            else 0.0
        )

        # V2.5 actual-anchor fingerprint match.
        fingerprint_terms: list[str] = []
        fingerprint_matched_weight = 0.0
        fingerprint_peak_weight = 0.0

        if taxonomy_mode and anchor_fingerprint_weights:
            for kw in evidence.get("matched_keywords") or []:
                if not isinstance(kw, dict):
                    continue
                if str(kw.get("source") or "") != "anchor":
                    continue

                name = str(kw.get("name") or "").strip().lower()
                weight = float(
                    kw.get("fingerprint_weight")
                    or anchor_fingerprint_weights.get(name, 0.0)
                    or 0.0
                )
                if not name or weight <= 0:
                    continue

                if name not in fingerprint_terms:
                    fingerprint_terms.append(name)
                    fingerprint_matched_weight += weight
                    fingerprint_peak_weight = max(
                        fingerprint_peak_weight,
                        weight,
                    )

        if fingerprint_total_weight > 0 and fingerprint_max_weight > 0:
            fingerprint_coverage = min(
                1.0,
                fingerprint_matched_weight / fingerprint_total_weight,
            )
            fingerprint_peak = min(
                1.0,
                fingerprint_peak_weight / fingerprint_max_weight,
            )
            fingerprint_score = (
                (0.62 * fingerprint_peak)
                + (0.38 * fingerprint_coverage)
            )

            if len(fingerprint_terms) >= 2:
                fingerprint_score += min(
                    0.10,
                    0.035 * (len(fingerprint_terms) - 1),
                )

            fingerprint_score = min(1.0, fingerprint_score)
        else:
            # Neutral for sparse anchors / unavailable keyword evidence.
            fingerprint_score = 0.50 if taxonomy_mode else 0.0

        score_raw = (
            (0.50 * overlap_component)
            + (0.25 * repeat_component)
            + (0.25 * quality_component)
            + breadth_component
        )

        candidates.append(
                {
                    "tmdb_id": int(evidence["tmdb_id"]),
                    "score_raw": float(
                        min(1.0, score_raw)
                    ),
                    "keyword_hits": keyword_hits,
                    "anchor_keyword_hits": int(
                        evidence.get("anchor_keyword_hits") or 0
                    ),
                    "concept_keyword_hits": int(
                        evidence.get("concept_keyword_hits") or 0
                    ),
                    "breadth_hits": int(
                        evidence.get("breadth_hits") or 0
                    ),
                    "matched_keywords": list(
                        evidence.get("matched_keywords") or []
                    ),
                    "fingerprint_score": float(
                        fingerprint_score if taxonomy_mode else 0.0
                    ),
                    "fingerprint_terms": list(fingerprint_terms),
                }
            )

    # Most semantically-supported candidates first.
    candidates.sort(
        key=lambda item: (
            float(item.get("score_raw") or 0.0),
            int(item.get("keyword_hits") or 0),
        ),
        reverse=True,
    )

    candidates = candidates[:limit]

    if SEO_DEBUG:
        print(
            "SEO SEMANTIC DISCOVERY DEBUG:",
            {
                "keywords": [
                    {
                        "id": int(item["id"]),
                        "name": str(item["name"]),
                    }
                    for item in selected_keyword_items
                ],
                "genre_ids": genre_ids[:3],
                "anchor_fingerprint": (
                    [
                        {
                            "name": name,
                            "weight": round(weight, 4),
                        }
                        for name, weight in sorted(
                            anchor_fingerprint_weights.items(),
                            key=lambda item: item[1],
                            reverse=True,
                        )
                    ]
                    if taxonomy_mode
                    else []
                ),
                "count": len(candidates),
                "top_candidates": [
                    {
                        "tmdb_id": int(item["tmdb_id"]),
                        "keyword_hits": int(
                            item.get("keyword_hits") or 0
                        ),
                        "anchor_keyword_hits": int(
                            item.get("anchor_keyword_hits") or 0
                        ),
                        "concept_keyword_hits": int(
                            item.get("concept_keyword_hits") or 0
                        ),
                        "matched_keywords": item.get(
                            "matched_keywords"
                        ) or [],
                        "score_raw": round(
                            float(item.get("score_raw") or 0.0),
                            4,
                        ),
                    }
                    for item in candidates[:15]
                ],
            },
        )

    return candidates

@router.get("/shows-like/{slug}")
async def shows_like(
    slug: str,
    taxonomy_shadow: bool = True,
    refresh: bool = False,
    x_seo_refresh_key: str | None = Header(
        default=None,
        alias="X-SEO-Refresh-Key",
    ),
    db: AsyncSession = Depends(get_async_session),
):
    if refresh:
        expected_refresh_key = os.getenv("SEO_REFRESH_KEY")

        if (
            not expected_refresh_key
            or not x_seo_refresh_key
            or not hmac.compare_digest(
                x_seo_refresh_key,
                expected_refresh_key,
            )
        ):
            raise HTTPException(
                status_code=403,
                detail="Invalid SEO refresh key",
            )

    # Keep the cache key aligned with the actual route slug. Do not ASCII-normalise
    # here: accented/non-Latin slugs must remain distinct.
    cache_slug = slug.strip().lower()

    if taxonomy_shadow and not refresh:
        cached_payload = await _get_cached_shows_like_payload(cache_slug)
        if cached_payload is not None:
            return cached_payload
    
    # Keep the cache key aligned with the actual route slug. Do not ASCII-normalise
    # here: accented/non-Latin slugs must remain distinct.
    cache_slug = slug.strip().lower()
    if taxonomy_shadow and not refresh:
        cached_payload = await _get_cached_shows_like_payload(cache_slug)
        if cached_payload is not None:
            return cached_payload

    title = slug.replace("-", " ")

    # Resolve the anchor deterministically.
    #
    # Some titles exist more than once in the local shows table. Previously this
    # query used LIMIT 1 without ordering, so a weak duplicate could win. That is
    # exactly what happened for /shows-like/the-leftovers: the page anchored on a
    # posterless duplicate instead of the real populated TMDB record.
    show_res = await db.execute(
        text(
            """
            SELECT
                show_id,
                title,
                poster_path
            FROM shows
            WHERE lower(title) = lower(:title)
            ORDER BY
                CASE WHEN poster_path IS NULL OR poster_path = '' THEN 1 ELSE 0 END ASC,
                show_id ASC
            LIMIT 1
            """
        ),
        {"title": title},
    )

    row = show_res.mappings().first()

    from app.routes.recs_v3 import _tmdb_search_tv

    async def _tmdb_search_anchor() -> dict | None:
        tmdb_match = await _tmdb_search_tv(title)
        if not tmdb_match:
            return None

        tmdb_id_candidate = tmdb_match.get("id")
        if not isinstance(tmdb_id_candidate, int):
            return None

        details = await _tmdb_details(tmdb_id_candidate)
        return {
            "show_id": tmdb_id_candidate,
            "title": details.get("title") or details.get("name") or title.title(),
            "poster_path": details.get("poster_path"),
            "details": details,
        }

    tmdb_anchor_details: dict | None = None

    if not row:
        tmdb_row = await _tmdb_search_anchor()
        if not tmdb_row:
            raise HTTPException(status_code=404, detail="Show not found")
        tmdb_anchor_details = dict(tmdb_row.pop("details") or {})
        row = tmdb_row

    tmdb_id = int(row["show_id"])
    anchor_title = str(row["title"])
    print("SEO anchor:", anchor_title, tmdb_id)

    anchor_details = tmdb_anchor_details or await _tmdb_details(tmdb_id)

    anchor_details = await _enrich_seo_details(anchor_details)
    print(
    "SEO KEYWORD DEBUG:",
    anchor_title,
    tmdb_id,
    anchor_details.get("seo_keywords"),
    )

    # If the DB row is present but weak/stale, compare it with TMDB search. This
    # prevents duplicate or imported rows with the same title from poisoning the
    # SEO page. Only switch when the TMDB result has the same title and better
    # core metadata, so remakes / unrelated same-name shows are not blindly
    # overwritten.
    if not row.get("poster_path") or not anchor_details.get("poster_path"):
        tmdb_row = await _tmdb_search_anchor()
        if tmdb_row:
            candidate_details = dict(tmdb_row.get("details") or {})
            candidate_title = str(tmdb_row.get("title") or "").strip().lower()
            current_title = str(anchor_title or "").strip().lower()
            if candidate_title == current_title and candidate_details.get("poster_path"):
                candidate_details = await _enrich_seo_details(candidate_details)
                tmdb_anchor_details = candidate_details
                tmdb_row.pop("details", None)
                row = tmdb_row
                tmdb_id = int(row["show_id"])
                anchor_title = str(row["title"])
                anchor_details = tmdb_anchor_details
                print("SEO anchor corrected from TMDB search:", anchor_title, tmdb_id)

    # V2.7.3 shadow-only identity verification. Exact-title DB rows can still
    # point at an unrelated same-name TMDB show. Compare against TMDB search
    # even when the stored row has a poster, and prefer the same-title result
    # when it carries materially richer semantic metadata. Production remains
    # untouched until the shadow regression proves this behaviour.
    if taxonomy_shadow:
        tmdb_verify = await _tmdb_search_anchor()
        if tmdb_verify:
            verify_title = str(tmdb_verify.get("title") or "").strip().lower()
            current_title = str(anchor_title or "").strip().lower()
            verify_details = dict(tmdb_verify.get("details") or {})
            verify_id = tmdb_verify.get("show_id")
            if verify_title == current_title and isinstance(verify_id, int):
                verify_details = await _enrich_seo_details(verify_details)

                def _anchor_richness(details: dict) -> float:
                    kw = len(details.get("seo_keywords") or [])
                    genres_n = len(details.get("genre_ids") or details.get("genres") or [])
                    overview_n = len(str(details.get("overview") or "").strip())
                    return (0.65 * min(12, kw)) + (0.55 * min(4, genres_n)) + (1.0 if overview_n >= 80 else 0.0)

                current_richness = _anchor_richness(anchor_details)
                verify_richness = _anchor_richness(verify_details)

                # V2.7.4a ambiguity guard:
                # TMDB search can return a newer/remade show with the exact same
                # title. Richer metadata alone is not enough reason to replace a
                # DB anchor that already has a meaningful semantic fingerprint.
                #
                # Only allow same-title replacement when the current anchor is
                # genuinely sparse. This still repairs bad duplicate/import rows
                # such as an entry with only one or two generic keywords, while
                # preserving established same-name shows that already have
                # several coherent keywords.
                current_kw_n = len(anchor_details.get("seo_keywords") or [])
                current_genre_n = len(anchor_details.get("genre_ids") or anchor_details.get("genres") or [])
                current_overview_n = len(str(anchor_details.get("overview") or "").strip())
                current_is_sparse = bool(
                    current_kw_n <= 2
                    or current_genre_n == 0
                    or current_overview_n < 40
                    or current_richness < 4.25
                )

                should_verify_replace = bool(
                    verify_id != tmdb_id
                    and current_is_sparse
                    and verify_richness >= current_richness + 1.5
                )

                if should_verify_replace:
                    previous_id = tmdb_id
                    tmdb_id = int(verify_id)
                    anchor_title = str(tmdb_verify.get("title") or anchor_title)
                    anchor_details = verify_details
                    row = {
                        "show_id": tmdb_id,
                        "title": anchor_title,
                        "poster_path": verify_details.get("poster_path"),
                    }
                    print(
                        "SEO TAXONOMY ANCHOR VERIFY:",
                        {
                            "title": anchor_title,
                            "previous_tmdb_id": previous_id,
                            "tmdb_id": tmdb_id,
                            "previous_richness": round(current_richness, 3),
                            "verified_richness": round(verify_richness, 3),
                            "reason": "current_anchor_sparse",
                        },
                    )
                elif verify_id != tmdb_id and verify_richness >= current_richness + 1.5:
                    print(
                        "SEO TAXONOMY ANCHOR VERIFY SKIP:",
                        {
                            "title": anchor_title,
                            "current_tmdb_id": tmdb_id,
                            "search_tmdb_id": int(verify_id),
                            "current_keyword_count": current_kw_n,
                            "current_richness": round(current_richness, 3),
                            "verified_richness": round(verify_richness, 3),
                            "reason": "current_anchor_not_sparse",
                        },
                    )
    anchor_genre_ids = set(anchor_details.get("genre_ids") or [])
    anchor_lang = anchor_details.get("original_language")
    anchor_keywords = _extract_anchor_keywords(
        anchor_details.get("title") or anchor_details.get("name") or anchor_title,
        anchor_details.get("overview"),
        " ".join(anchor_details.get("genres") or []),
        " ".join(anchor_details.get("seo_keywords") or []),
    )
    anchor_profile = _anchor_profile(anchor_details)

    # V2.7.4a production cutover: taxonomy is now the default path. Set taxonomy_shadow=false only for temporary legacy comparison/rollback diagnostics.
    # This lets us run the exact same recommendation pipeline with Taxonomy V2.3
    # without changing the live /shows-like behaviour.
    old_anchor_concept = _classify_anchor_concept_v2(anchor_title, anchor_details)
    old_anchor_concept = ANCHOR_TO_CONCEPT.get(anchor_title.lower(), old_anchor_concept)

    taxonomy_result = None
    if taxonomy_shadow:
        taxonomy_result = classify_anchor(anchor_details)
        anchor_concept = taxonomy_result.concept
    else:
        anchor_concept = old_anchor_concept

    print(
        "SEO CONCEPT DEBUG:",
        anchor_title,
        anchor_concept,
        "mode=taxonomy_v2_7_4a_production" if taxonomy_shadow else "mode=legacy_diagnostic",
    )

    if taxonomy_shadow and taxonomy_result is not None:
        print(
            "SEO TAXONOMY SHADOW:",
            {
                "title": anchor_title,
                "old_concept": old_anchor_concept,
                "taxonomy_concept": taxonomy_result.concept,
                "family": taxonomy_result.family,
                "confidence": round(taxonomy_result.confidence, 4),
                "state": taxonomy_result.state,
                "changed": old_anchor_concept != taxonomy_result.concept,
            },
        )
    print(
        "SEO ANCHOR PROFILE DEBUG:",
        anchor_title,
        anchor_details.get("seo_keywords"),
        anchor_profile,
    )
    anchor_is_scifi = bool(10765 in anchor_genre_ids or anchor_profile.get("is_scifi", False))

    api_key = _tmdb_api_key()
    if not api_key:
        raise HTTPException(status_code=500, detail="TMDB API key not configured")

    reddit_sql = text(
        """
        SELECT
            CASE
                WHEN tmdb_id_a = :tid THEN tmdb_id_b
                ELSE tmdb_id_a
            END AS other_id,
            pair_weight
        FROM reddit_pairs
        WHERE tmdb_id_a = :tid OR tmdb_id_b = :tid
        ORDER BY pair_weight DESC NULLS LAST
        LIMIT :lim
        """
    )

    async def _fetch_reddit_similar() -> dict[int, float]:
        try:
            res = await db.execute(reddit_sql, {"tid": tmdb_id, "lim": MAX_RESULTS * 5})
            rows = res.mappings().all()
        except Exception:
            return {}

        out: dict[int, float] = {}
        for r in rows:
            try:
                oid = int(r.get("other_id"))
                weight = float(r.get("pair_weight") or 0.0)
            except Exception:
                continue
            if oid and oid != tmdb_id:
                out[oid] = max(out.get(oid, 0.0), weight)
        return out

    tmdb_task = _tmdb_recommendations_for_fav(
        tmdb_id,
        api_key,
        max_n=MAX_RESULTS * 4,
    )

    trending_task = _fetch_tmdb_trending_candidates(
        allowed_langs={anchor_lang} if anchor_lang else set(),
        fav_genres=anchor_genre_ids,
        block_ids={tmdb_id},
        limit=MAX_RESULTS * 3,
    )

    semantic_task = _fetch_tmdb_semantic_candidates(
        anchor_tmdb_id=tmdb_id,
        anchor_details=anchor_details,
        anchor_concept=anchor_concept,
        limit=MAX_RESULTS * 3,
        taxonomy_mode=taxonomy_shadow,
    )

    (
        tmdb_ids_raw,
        reddit_scores,
        trending_items,
        semantic_items,
    ) = await asyncio.gather(
        tmdb_task,
        _fetch_reddit_similar(),
        trending_task,
        semantic_task,
    )

    tmdb_ids_raw = [rid for rid in (tmdb_ids_raw or []) if isinstance(rid, int) and rid != tmdb_id]
    reddit_scores = reddit_scores or {}

    semantic_scores: dict[int, float] = {}
    semantic_matched_terms: dict[int, list[str]] = {}
    semantic_fingerprint_scores: dict[int, float] = {}
    semantic_fingerprint_terms: dict[int, list[str]] = {}

    for item in semantic_items or []:
        try:
            rid = int(item.get("tmdb_id") or 0)
            raw = float(
                item.get("score_raw")
                or item.get("score")
                or 0.0
            )
        except Exception:
            continue

        if rid and rid != tmdb_id:
            semantic_scores[rid] = max(
                semantic_scores.get(rid, 0.0),
                raw,
            )

            if taxonomy_shadow:
                try:
                    fp_score = float(item.get("fingerprint_score") or 0.0)
                except Exception:
                    fp_score = 0.0

                semantic_fingerprint_scores[rid] = max(
                    semantic_fingerprint_scores.get(rid, 0.0),
                    fp_score,
                )

                fp_terms = [
                    str(v).strip().lower()
                    for v in (item.get("fingerprint_terms") or [])
                    if str(v).strip()
                ]
                if fp_terms:
                    existing_fp = semantic_fingerprint_terms.setdefault(rid, [])
                    for term in fp_terms:
                        if term not in existing_fp:
                            existing_fp.append(term)

            matched_names: list[str] = []
            for kw in item.get("matched_keywords") or []:
                if isinstance(kw, dict):
                    name = str(kw.get("name") or "").strip().lower()
                else:
                    name = str(kw or "").strip().lower()
                if name and name not in matched_names:
                    matched_names.append(name)

            if matched_names:
                existing = semantic_matched_terms.setdefault(rid, [])
                for name in matched_names:
                    if name not in existing:
                        existing.append(name)

    trending_scores: dict[int, float] = {}
    for item in trending_items or []:
        try:
            rid = int(item.get("tmdb_id") or 0)
            raw = float(item.get("score_raw") or item.get("score") or 0.0)
        except Exception:
            continue
        if rid and rid != tmdb_id:
            trending_scores[rid] = max(trending_scores.get(rid, 0.0), raw)

    merged_scores: dict[int, float] = {}

    for rid in tmdb_ids_raw:
        if rid == tmdb_id:
            continue

        merged_scores[rid] = merged_scores.get(rid, 0.0) + 0.18

    for rid, raw in semantic_scores.items():
        merged_scores[rid] = (
            merged_scores.get(rid, 0.0)
            + min(
                0.20,
                0.10 + (0.10 * raw),
            )
        )

    for rid, raw in trending_scores.items():
        merged_scores[rid] = merged_scores.get(rid, 0.0) + min(0.12, 0.04 + 0.06 * raw)

    for rid, weight in reddit_scores.items():
        if rid == tmdb_id:
            continue
        merged_scores[rid] = merged_scores.get(rid, 0.0) + 0.62 * math.log10(1.0 + max(float(weight), 0.0))

    sorted_ids = sorted(
        merged_scores.keys(),
        key=lambda x: merged_scores[x],
        reverse=True
    )

    # Main pool from all recommendation sources.
    base_fetch_ids = sorted_ids[: MAX_RESULTS * 5]

    # Reserve some candidate capacity specifically for the strongest semantic
    # discoveries. Otherwise Reddit/TMDb graph volume can push good semantic
    # matches out before the concept scorer ever gets to inspect them.
    semantic_reserved_ids = sorted(
        semantic_scores.keys(),
        key=lambda rid: semantic_scores.get(rid, 0.0),
        reverse=True,
    )[: MAX_RESULTS * 2]

    fetch_ids = list(
        dict.fromkeys(
            base_fetch_ids
            + semantic_reserved_ids
        )
    )[: MAX_RESULTS * 7]


    # Fetch the normal candidate details first
    details_list = (
        await asyncio.gather(
            *[_tmdb_details(rid) for rid in fetch_ids]
        )
        if fetch_ids
        else []
    )

    details_list = [d for d in details_list if d]


    # Add concept-level fallback candidates when available.
    # These candidates still pass through the normal relevance, quality,
    # concept and ranking filters below.
    extra_ids = [
        rid
        for rid in _fallback_ids_for_concept(anchor_concept)
        if rid != tmdb_id and rid not in fetch_ids
    ]

    if extra_ids:
        extra_details = await asyncio.gather(
            *[_tmdb_details(rid) for rid in extra_ids[:24]]
        )

        details_list.extend(
            [d for d in extra_details if d]
        )


    # Enrich every candidate with TMDb semantic keywords
    details_list = await asyncio.gather(
        *[
            _enrich_seo_details(details)
            for details in details_list
            if details
        ]
    )

    # Attach semantic-discovery evidence to each enriched candidate so the
    # taxonomy fit layer can distinguish "metadata is sparse" from
    # "there is no concept evidence". Internal key only; it is not part of the
    # public response schema.
    if taxonomy_shadow:
        for details in details_list:
            try:
                rid = int(details.get("tmdb_id") or 0)
            except Exception:
                rid = 0
            if rid:
                details["_seo_taxonomy_matched_terms"] = list(
                    semantic_matched_terms.get(rid, [])
                )
                details["_seo_anchor_fingerprint_score"] = float(
                    semantic_fingerprint_scores.get(rid, 0.0)
                )
                details["_seo_anchor_fingerprint_terms"] = list(
                    semantic_fingerprint_terms.get(rid, [])
                )

    if SEO_DEBUG:
        print(
            "SEO DETAILS LIST DEBUG:",
            {
                "count": len(details_list),
                "titles": [
                    str(d.get("title") or d.get("name") or "")
                    for d in details_list
                ],
            }
        )

    results: list[dict] = []
    seen_ids = {tmdb_id}
    tmdb_set = set(tmdb_ids_raw)
    reddit_set = set(reddit_scores.keys())
    trending_set = set(trending_scores.keys())
    semantic_set = set(semantic_scores.keys())

    def _seo_debug_candidate(
        *,
        title: str,
        stage: str,
        rid: int = 0,
        semantic_score: float | None = None,
        genre_score: float | None = None,
        concept_bonus: float | None = None,
        total_score: float | None = None,
        is_reddit: bool | None = None,
        is_tmdb: bool | None = None,
        is_trending: bool | None = None,
    ) -> None:
        if not SEO_DEBUG:
            return

        print(
            "SEO CANDIDATE DEBUG:",
            {
                "title": title,
                "tmdb_id": rid,
                "stage": stage,
                "semantic": None if semantic_score is None else round(semantic_score, 4),
                "genre": None if genre_score is None else round(genre_score, 4),
                "concept_bonus": None if concept_bonus is None else round(concept_bonus, 4),
                "total": None if total_score is None else round(total_score, 4),
                "reddit": is_reddit,
                "tmdb": is_tmdb,
                "trending": is_trending,
            }
        )

    def _passes_basic_candidate_checks(details: dict) -> tuple[bool, int, str, set[int], float, int, float, str, str]:
        try:
            rid = int(details.get("tmdb_id") or 0)
        except Exception:
            return False, 0, "", set(), 0.0, 0, 0.0, "", "BAD_ID"

        title_val = str(details.get("title") or details.get("name") or "").strip()
        if not rid or rid in seen_ids or not title_val:
            return False, rid, title_val, set(), 0.0, 0, 0.0, "", "MISSING_TITLE_OR_DUPLICATE"
        if not details.get("poster_path"):
            return False, rid, title_val, set(), 0.0, 0, 0.0, "", "NO_POSTER"

        genre_ids = set(details.get("genre_ids") or [])

        bad_genres_found = genre_ids & BAD_GENRES

        if bad_genres_found:
            # Family is acceptable for franchise-led space adventure pages
            # when the candidate is also genuinely sci-fi/action.
            allow_family_scifi = (
                anchor_concept == "space_franchise_adventure"
                and 10751 in bad_genres_found
                and bool({10765, 10759} & genre_ids)
                and not ({10762, 10764} & genre_ids)
            )

            if not allow_family_scifi:
                return False, rid, title_val, genre_ids, 0.0, 0, 0.0, "", "BAD_GENRE"

        if 10767 in genre_ids or 10766 in genre_ids:
            return False, rid, title_val, genre_ids, 0.0, 0, 0.0, "", "BAD_GENRE"

        if 99 in genre_ids and len(genre_ids) == 1:
            return False, rid, title_val, genre_ids, 0.0, 0, 0.0, "", "BAD_GENRE"

        if anchor_concept == "finance_power" and 35 in genre_ids and 18 not in genre_ids:
            return False, rid, title_val, genre_ids, 0.0, 0, 0.0, "", "BAD_GENRE"

        vote_average = float(details.get("vote_average") or 0.0)
        vote_count = int(details.get("vote_count") or 0)
        popularity = float(details.get("popularity") or 0.0)
        first_air_date = str(details.get("first_air_date") or "")

        if vote_count < ABS_MIN_VOTE_COUNT or popularity < ABS_MIN_POPULARITY:
            return False, rid, title_val, genre_ids, vote_average, vote_count, popularity, first_air_date, "LOW_VOTES_OR_POPULARITY"
        if _is_future_or_too_fresh_for_seo(first_air_date, vote_count):
            return False, rid, title_val, genre_ids, vote_average, vote_count, popularity, first_air_date, "FUTURE_OR_TOO_FRESH"
        
        if (
        anchor_is_scifi
        and not anchor_profile.get("is_animation")
        and 16 in genre_ids
        and anchor_concept != "space_franchise_adventure"
        ):            
         return False, rid, title_val, genre_ids, vote_average, vote_count, popularity, first_air_date, "ANIME"

        return True, rid, title_val, genre_ids, vote_average, vote_count, popularity, first_air_date, "OK"

    for details in details_list:
        ok, rid, title_val, genre_ids, vote_average, vote_count, popularity, first_air_date, reject_reason = _passes_basic_candidate_checks(details)
        if not ok or rid in seen_ids:
            _seo_debug_candidate(
                title=title_val or str(details.get("title") or details.get("name") or ""),
                rid=rid,
                stage=f"REJECT_BASIC_{reject_reason}",
            )
            continue

        genre_score = _genre_overlap_score(anchor_genre_ids, genre_ids)
        semantic_score = _semantic_text_score(
            anchor_keywords,
            title_val,
            details.get("overview"),
            " ".join(details.get("genres") or []),
            " ".join(details.get("seo_keywords") or []),
        )

        is_tmdb = rid in tmdb_set
        is_reddit = rid in reddit_set
        is_trending = rid in trending_set

        concept_controls_fit = taxonomy_shadow or anchor_concept in {
            "period_professional_drama",
            "post_apocalyptic_survival",
            "warm_workplace_comedy",
        }

        if concept_controls_fit:
            fits_anchor = True
            fit_bonus = 0.0
        else:
            fits_anchor, fit_bonus = _candidate_fit_adjustment(anchor_profile, details)

        if not fits_anchor:
            _seo_debug_candidate(
                title=title_val,
                rid=rid,
                stage="REJECT_ANCHOR_FIT",
                semantic_score=semantic_score,
                genre_score=genre_score,
                is_reddit=is_reddit,
                is_tmdb=is_tmdb,
                is_trending=is_trending,
            )
            continue

        concept_pass, concept_bonus, concept_multiplier = _active_concept_fit_score(
            anchor_concept,
            details,
            semantic_score=semantic_score,
            genre_score=genre_score,
            taxonomy_mode=taxonomy_shadow,
        )
        if not concept_pass:
            _seo_debug_candidate(
                title=title_val,
                rid=rid,
                stage="REJECT_CONCEPT_FIT",
                semantic_score=semantic_score,
                genre_score=genre_score,
                concept_bonus=concept_bonus,
                is_reddit=is_reddit,
                is_tmdb=is_tmdb,
                is_trending=is_trending,
            )
            continue

        candidate_blob = _blob_for(details)

        # Legacy concept guardrail is only needed for the older concept profiles.
        # finance_power now uses CONCEPT_RULES + grounded sanity checks below.
        if (
            not taxonomy_shadow
            and anchor_concept
            and anchor_concept != "finance_power"
        ):
            if not passes_concept_guardrail(
                anchor_concept,
                candidate_blob,
                list(details.get("genres") or [])
            ):
                continue

        if anchor_is_scifi and _is_weak_scifi(details) and semantic_score < 0.22 and concept_bonus < 0.16:
            continue

       
        
        if anchor_concept in {"medical_family", "period_community"}:
            if (
                not is_reddit
                and not is_tmdb
                and semantic_score < 0.08
                and genre_score < 0.05
                and concept_bonus < 0.08
            ):
                continue

        elif anchor_concept == "finance_power":
            if (
                not is_reddit
                and not is_tmdb
                and semantic_score < 0.06
                and genre_score < 0.05
                and concept_bonus < 0.07
            ):
                _seo_debug_candidate(
                    title=title_val,
                    rid=rid,
                    stage="REJECT_FINANCE_SIGNAL",
                    semantic_score=semantic_score,
                    genre_score=genre_score,
                    concept_bonus=concept_bonus,
                    is_reddit=is_reddit,
                    is_tmdb=is_tmdb,
                    is_trending=is_trending,
                )
                continue

        else:
            if (
                not is_reddit
                and not is_tmdb
                and semantic_score < 0.10
                and genre_score < 0.08
                and concept_bonus < 0.12
            ):
                continue
        passes_quality = _passes_seo_quality_floor(
            vote_average=vote_average,
            vote_count=vote_count,
            popularity=popularity,
            semantic_score=semantic_score + min(0.20, concept_bonus),
            genre_score=genre_score,
            is_reddit=is_reddit,
            is_tmdb=is_tmdb,
            is_trending=is_trending,
        )

        # V2.7 taxonomy-aware quality rescue
        # ----------------------------------
        # The generic quality floor is useful for suppressing weak/popularity
        # noise, but it can discard structurally excellent specialist matches.
        # In taxonomy shadow mode only, rescue a candidate when:
        #   * its independent taxonomy classification exactly matches the
        #     anchor specialist concept;
        #   * candidate-fit itself is meaningfully strong;
        #   * the absolute safety/quality floors still hold; and
        #   * there is at least some semantic or genre evidence.
        #
        # This is deliberately NOT a generic semantic rescue and does not apply
        # to broad/secondary-family candidates. It therefore recovers genuine
        # niche specialist matches such as low-popularity finance dramas without
        # weakening concept precision globally.
        taxonomy_quality_rescue = False
        if not passes_quality and taxonomy_shadow:
            relationship_concept = str(
                details.get("_seo_taxonomy_relationship_concept") or ""
            )
            fit_tier = str(details.get("_seo_taxonomy_fit_tier") or "")
            fit_score = float(details.get("_seo_taxonomy_fit_score") or 0.0)

            taxonomy_quality_rescue = bool(
                relationship_concept == anchor_concept
                and fit_tier in {"strong", "good"}
                and fit_score >= 0.24
                and vote_average >= 6.3
                and vote_count >= ABS_MIN_VOTE_COUNT
                and popularity >= ABS_MIN_POPULARITY
                and (
                    semantic_score >= 0.06
                    or genre_score >= 0.33
                )
            )

            if taxonomy_quality_rescue and SEO_DEBUG:
                print(
                    "SEO TAXONOMY QUALITY RESCUE DEBUG:",
                    {
                        "title": title_val,
                        "anchor_concept": anchor_concept,
                        "relationship_concept": relationship_concept,
                        "fit_tier": fit_tier,
                        "fit_score": round(fit_score, 4),
                        "semantic": round(float(semantic_score), 4),
                        "genre": round(float(genre_score), 4),
                        "vote_average": round(float(vote_average), 3),
                        "vote_count": int(vote_count),
                        "popularity": round(float(popularity), 3),
                    },
                )

        if not passes_quality and not taxonomy_quality_rescue:
            _seo_debug_candidate(
                title=title_val,
                rid=rid,
                stage="REJECT_QUALITY",
                semantic_score=semantic_score,
                genre_score=genre_score,
                concept_bonus=concept_bonus,
                is_reddit=is_reddit,
                is_tmdb=is_tmdb,
                is_trending=is_trending,
            )
            continue

        bayes_quality = _bayesian_quality_score(vote_average, vote_count)
        qual_bonus = _quality_bonus(vote_average, vote_count, popularity)
        conf_factor = _confidence_factor(vote_count, popularity)

        source_score = float(merged_scores.get(rid, 0.0))

        # Source evidence (especially Reddit) is useful for discovering candidates,
        # but it should not overpower the actual similarity evidence.
        #
        # Strong semantic/concept/genre agreement preserves most of the source score.
        # Weakly related candidates receive much less benefit simply because they are
        # frequently co-mentioned with the anchor.
        relevance_strength = min(
            1.0,
            (1.20 * semantic_score)
            + (0.75 * concept_bonus)
            + (0.25 * genre_score),
        )

        source_multiplier = 0.35 + (0.65 * relevance_strength)

        weighted_source_score = source_score * source_multiplier

        total_score = weighted_source_score
        total_score += 0.62 * semantic_score
        total_score += 0.42 * genre_score
        total_score += 0.32 * bayes_quality
        total_score += qual_bonus
        total_score += fit_bonus
        total_score += concept_bonus

        # V2.5.1 relationship-gated anchor fingerprint.
        #
        # Fingerprint overlap is useful only in proportion to structural
        # taxonomy compatibility. Literal overlap such as "satire", "monster",
        # or "miniseries" cannot independently overpower the candidate's actual
        # archetype. This remains ranking-only; it never rejects a candidate.
        if taxonomy_shadow:
            fingerprint_score = max(
                0.0,
                min(
                    1.0,
                    float(
                        details.get("_seo_anchor_fingerprint_score", 0.0)
                        or 0.0
                    ),
                ),
            )

            relationship_compatibility = max(
                0.05,
                min(
                    1.0,
                    float(
                        details.get(
                            "_seo_taxonomy_relationship_compatibility",
                            0.42,
                        )
                        or 0.42
                    ),
                ),
            )

            # Relationship gating:
            #   exact specialist        -> full fingerprint value
            #   close same-family       -> proportionate value
            #   weak/different concept  -> fingerprint heavily damped
            gated_fingerprint = (
                fingerprint_score
                * (relationship_compatibility ** 1.25)
            )

            # Keep the contribution bounded. The fingerprint refines the
            # existing concept/semantic/source ranking; it does not replace it.
            total_score += 0.30 * gated_fingerprint

            # Only a very small dampener is retained for candidates with no
            # anchor fingerprint evidence. Absence is not a rejection signal.
            if fingerprint_score <= 0.0:
                total_score *= 0.96
            elif gated_fingerprint < 0.08:
                total_score *= 0.985

            if SEO_DEBUG and fingerprint_score > 0:
                print(
                    "SEO TAXONOMY FINGERPRINT DEBUG:",
                    {
                        "title": details.get("title") or details.get("name"),
                        "anchor_concept": anchor_concept,
                        "fingerprint": round(fingerprint_score, 4),
                        "relationship_compatibility": round(
                            relationship_compatibility, 4
                        ),
                        "gated_fingerprint": round(gated_fingerprint, 4),
                        "fingerprint_terms": list(
                            details.get("_seo_anchor_fingerprint_terms", [])
                        ),
                        "relationship_concept": details.get(
                            "_seo_taxonomy_relationship_concept"
                        ),
                    },
                )

        # Penalise crime-heavy shows for non-crime anchors
        if anchor_concept not in {
            "crime_pressure",
            "detective_mystery",
            "finance_power",
        }:
            if 80 in genre_ids:
                total_score *= 0.75

        if is_tmdb and not is_reddit:
            total_score *= 0.94
        if is_reddit and not is_tmdb and vote_count < 100:
            total_score *= 0.84
        if is_trending and not is_reddit and semantic_score >= 0.18:
            total_score += 0.04

        total_score *= concept_multiplier
        total_score *= conf_factor

        min_total_score = 0.38

        if anchor_concept == "small_town_mystery":
            min_total_score = 0.65

        if total_score < min_total_score:
            _seo_debug_candidate(
                title=title_val,
                rid=rid,
                stage="REJECT_TOTAL_SCORE",
                semantic_score=semantic_score,
                genre_score=genre_score,
                concept_bonus=concept_bonus,
                total_score=total_score,
                is_reddit=is_reddit,
                is_tmdb=is_tmdb,
                is_trending=is_trending,
            )
            continue

        source = _source_label(is_reddit, is_tmdb, is_trending, semantic_score)
        result = {
            "tmdb_id": rid,
            "title": title_val,
            "poster_path": details.get("poster_path"),
            "poster_url": details.get("poster_url"),
            "overview": details.get("overview"),
            "first_air_date": details.get("first_air_date"),
            "vote_average": vote_average,
            "vote_count": vote_count,
            "popularity": popularity,
            "genres": details.get("genres"),
            "genre_ids": details.get("genre_ids"),
            "source": source,
            "score": total_score,
        }

        if taxonomy_shadow:
            result["_seo_taxonomy_relationship_concept"] = str(
                details.get("_seo_taxonomy_relationship_concept") or ""
            )
            result["_seo_taxonomy_fit_tier"] = str(
                details.get("_seo_taxonomy_fit_tier") or ""
            )
            result["_seo_taxonomy_fit_score"] = float(
                details.get("_seo_taxonomy_fit_score") or 0.0
            )

        _seo_debug_candidate(
            title=title_val,
            rid=rid,
            stage="ACCEPT",
            semantic_score=semantic_score,
            genre_score=genre_score,
            concept_bonus=concept_bonus,
            total_score=total_score,
            is_reddit=is_reddit,
            is_tmdb=is_tmdb,
            is_trending=is_trending,
        )

        results.append(_normalise_result_score(result))
        seen_ids.add(rid)

    results.sort(
        key=lambda x: (
            float(x.get("score") or 0.0),
            float(x.get("vote_average") or 0.0),
            float(x.get("popularity") or 0.0),
        ),
        reverse=True,
    )

    fill_target = (
        MAX_RESULTS
        if anchor_concept == "space_franchise_adventure"
        else MIN_RESULTS
    )

    if len(results) < fill_target:
        fill_candidates: list[dict] = []
        for details in details_list:
            ok, rid, title_val, genre_ids, vote_average, vote_count, popularity, first_air_date, reject_reason = _passes_basic_candidate_checks(details)
            if not ok or rid in seen_ids:
                continue

            genre_score = _genre_overlap_score(anchor_genre_ids, genre_ids)
            semantic_score = _semantic_text_score(
                anchor_keywords,
                title_val,
                details.get("overview"),
                " ".join(details.get("genres") or []),
                " ".join(details.get("seo_keywords") or []),
            )
            concept_pass, concept_bonus, concept_multiplier = _active_concept_fit_score(
                anchor_concept,
                details,
                semantic_score=semantic_score,
                genre_score=genre_score,
                taxonomy_mode=taxonomy_shadow,
            )
            if not concept_pass:
                continue

            candidate_blob = _blob_for(details)

            # Legacy concept guardrail is only needed for the older concept profiles.
            # finance_power now uses CONCEPT_RULES + grounded sanity checks below.
            if (
                not taxonomy_shadow
                and anchor_concept
                and anchor_concept != "finance_power"
            ):
                if not passes_concept_guardrail(
                    anchor_concept,
                    candidate_blob,
                    list(details.get("genres") or [])
                ):
                    continue

            if _weak_future_for_seo(details):
                continue

            if (
                not taxonomy_shadow
                and not _passes_grounded_concept_sanity(
                    anchor_concept,
                    details,
                    source="fill",
                    score=0.0,
                )
            ):
                continue

            fit = (
                0.0
                if taxonomy_shadow
                else _fill_fit_score(_anchor_fill_bucket(anchor_title, anchor_details), details)
            )
            if taxonomy_shadow:
                if concept_bonus < 0.12 and semantic_score < 0.14:
                    continue
            elif fit < 0.10 and concept_bonus < 0.12 and semantic_score < 0.14:
                continue

            bayes_quality = _bayesian_quality_score(vote_average, vote_count)
            raw_score = (
                0.18
                + 0.40 * semantic_score
                + 0.34 * genre_score
                + 0.28 * bayes_quality
                + concept_bonus
                + min(0.18, fit / 4.0)
                + _quality_bonus(vote_average, vote_count, popularity)
            )
            raw_score *= concept_multiplier
            raw_score *= _confidence_factor(vote_count, popularity)
            raw_score *= 0.82

            min_fill_score = 0.34 if anchor_concept in {"medical_family", "period_community"} else 0.40

            if raw_score < min_fill_score:
                continue

            fill_candidates.append(
                _normalise_result_score(
                    {
                        "tmdb_id": rid,
                        "title": title_val,
                        "poster_path": details.get("poster_path"),
                        "poster_url": details.get("poster_url"),
                        "overview": details.get("overview"),
                        "first_air_date": details.get("first_air_date"),
                        "vote_average": vote_average,
                        "vote_count": vote_count,
                        "popularity": popularity,
                        "genres": details.get("genres"),
                        "genre_ids": details.get("genre_ids"),
                        "source": "fill",
                        "score": raw_score,
                    }
                )
            )

        fill_candidates.sort(
            key=lambda x: (
                float(x.get("score") or 0.0),
                float(x.get("vote_average") or 0.0),
                float(x.get("popularity") or 0.0),
            ),
            reverse=True,
        )

        for item in fill_candidates:
            if len(results) >= fill_target:
                break
            if item["tmdb_id"] in seen_ids:
                continue
            results.append(item)
            seen_ids.add(item["tmdb_id"])

    results.sort(
        key=lambda x: (
            float(x.get("score") or 0.0),
            float(x.get("vote_average") or 0.0),
            math.log10(int(x.get("vote_count") or 0) + 1),
            float(x.get("popularity") or 0.0),
        ),
        reverse=True,
    )

    final_limit = (
        MIN_RESULTS
        if anchor_concept == "space_franchise_adventure"
        else MAX_RESULTS
    )

    results = _seo_ranking_layer(
        results,
        anchor_concept=anchor_concept,
        limit=final_limit,
        anchor_tmdb_id=tmdb_id,
        taxonomy_mode=taxonomy_shadow,
    )

    # SEO safety net: never leave a valid sci-fi / mystery-box anchor with an empty page
    # just because the live TMDB/Reddit signals were sparse or a strict filter removed too much.
    if anchor_concept in {
        "mystery_box_survival",
        "prestige_existential_mystery",
    } and len(results) < 6:
        existing_ids = {int(x.get("tmdb_id") or 0) for x in results}

        rescue_ids = [
            rid
            for rid in SEO_CONCEPT_FALLBACK_IDS.get(anchor_concept, [])
            if rid != tmdb_id and rid not in existing_ids
        ]
        rescue_details = await asyncio.gather(*[_tmdb_details(rid) for rid in rescue_ids[:18]]) if rescue_ids else []
        rescue_items: list[dict] = []
        for details in rescue_details:
            ok, rid, title_val, genre_ids, vote_average, vote_count, popularity, first_air_date, reject_reason = _passes_basic_candidate_checks(details)
            if not ok or rid in existing_ids:
                continue

            if not ({10765, 9648, 18} & genre_ids):
                continue

            semantic_score = _semantic_text_score(
                anchor_keywords,
                title_val,
                details.get("overview"),
                " ".join(details.get("genres") or []),
            )
            genre_score = _genre_overlap_score(anchor_genre_ids, genre_ids)
            concept_pass, concept_bonus, concept_multiplier = _active_concept_fit_score(
                anchor_concept,
                details,
                semantic_score=semantic_score,
                genre_score=genre_score,
                taxonomy_mode=taxonomy_shadow,
            )
            if not concept_pass:
                continue

            raw_score = (
                0.72
                + 0.42 * semantic_score
                + 0.32 * genre_score
                + 0.24 * _bayesian_quality_score(vote_average, vote_count)
                + concept_bonus
                + _quality_bonus(vote_average, vote_count, popularity)
            )
            raw_score *= concept_multiplier
            raw_score *= _confidence_factor(vote_count, popularity)

            rescue_items.append(
                _normalise_result_score(
                    {
                        "tmdb_id": rid,
                        "title": title_val,
                        "poster_path": details.get("poster_path"),
                        "poster_url": details.get("poster_url"),
                        "overview": details.get("overview"),
                        "first_air_date": details.get("first_air_date"),
                        "vote_average": vote_average,
                        "vote_count": vote_count,
                        "popularity": popularity,
                        "genres": details.get("genres"),
                        "genre_ids": details.get("genre_ids"),
                        "source": "fill",
                        "score": raw_score,
                    }
                )
            )
            existing_ids.add(rid)

        rescue_items.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
        results = (results + rescue_items)[:MAX_RESULTS]

    enriched_results = _enrich_recommendations_for_seo(anchor_title, anchor_details, results)

    payload = {
        "anchor": {
            "tmdb_id": tmdb_id,
            "title": anchor_title,
            "poster_path": row.get("poster_path") or anchor_details.get("poster_path"),
        },
        "recommendations": enriched_results,
        "page_copy": _build_page_copy(anchor_title, anchor_details, enriched_results),
    }

    # Debug metadata is exposed only for explicit shadow requests.
    if taxonomy_shadow and taxonomy_result is not None:
        payload["_taxonomy"] = {
            "old_concept": old_anchor_concept,
            "taxonomy_concept": taxonomy_result.concept,
            "family": taxonomy_result.family,
            "confidence": round(taxonomy_result.confidence, 4),
            "state": taxonomy_result.state,
            "changed": old_anchor_concept != taxonomy_result.concept,
            "downstream_taxonomy": True,
            "taxonomy_version": "2.7.4a-production",
        }

    if taxonomy_shadow:
        await _cache_shows_like_payload(cache_slug, payload)

    return payload


@router.get("/best-crime")
async def best_crime(db: AsyncSession = Depends(get_async_session)):
    res = await db.execute(text("""
        SELECT show_id, title, poster_path
        FROM shows
        WHERE lower(title) IN (
            'breaking bad',
            'the wire',
            'the sopranos',
            'true detective',
            'peaky blinders',
            'top boy',
            'dexter',
            'the shield'
        )
    """))

    return res.mappings().all()


@router.get("/best-scifi")
async def best_scifi(db: AsyncSession = Depends(get_async_session)):
    res = await db.execute(text("""
        SELECT show_id, title, poster_path
        FROM shows
        WHERE lower(title) IN (
            'dark',
            'black mirror',
            'lost',
            'the x-files',
            'stranger things',
            'the mandalorian'
        )
    """))

    return res.mappings().all()


@router.get("/best-like-breaking-bad")
async def best_like_breaking_bad(db: AsyncSession = Depends(get_async_session)):
    res = await db.execute(text("""
        SELECT s.show_id, s.title, s.poster_path
        FROM reddit_pairs rp
        JOIN shows s
          ON s.show_id = rp.tmdb_id_b
        WHERE rp.tmdb_id_a = 1396
        ORDER BY rp.pair_weight DESC
        LIMIT 24
    """))

    return res.mappings().all()


@router.get("/best-drama")
async def best_drama(db: AsyncSession = Depends(get_async_session)):
    res = await db.execute(text("""
       SELECT show_id, title, poster_path
        FROM shows
        WHERE lower(title) IN (
            'breaking bad',
            'better call saul',
            'the sopranos',
            'the wire',
            'succession',
            'the last of us',
            'true detective',
            'the night of',
            'fargo',
            'peaky blinders',
            'dark',
            'the white lotus'
        )
    """))

    return res.mappings().all()

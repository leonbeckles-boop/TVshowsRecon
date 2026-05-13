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
import math
import re
from collections import Counter
from datetime import datetime
from app.services.seo_profiles import get_or_create_profile, apply_profile_scoring

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
        "must_have": ["wealth", "power", "company", "business", "family", "corporate", "money"],
        "prefer": ["boardroom", "dynasty", "inheritance", "elite", "rivalry", "ambition"],
        "reject": ["motorcycle club", "serial killer", "hospital", "heist", "superhero"],
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

ANCHOR_TO_CONCEPT = {
    "succession": "finance_power",
    "mare of easttown": "small_town_mystery",
    "call the midwife": "medical_family",
}


# Broad fallback pools for SEO pages when live signals are sparse.
# These are concept-level guardrails, not single-title overrides.
SEO_CONCEPT_FALLBACK_IDS: dict[str, list[int]] = {
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
    extra_pools = {
        "finance_power": [90282, 62822, 1425, 1435, 4053, 114869, 76331],
        "medical_family": [39793, 18856, 95386, 61241, 62084, 5021, 1457],
        "small_town_mystery": [1427, 70453, 61244, 34415, 45016, 46648, 115004],
    }

    ids: list[int] = []
    for tid in extra_pools.get(anchor_concept, []):
        if tid not in ids:
            ids.append(tid)

    for key in (anchor_concept, "general_scifi"):
        for tid in SEO_CONCEPT_FALLBACK_IDS.get(key, []):
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
    is_medical_family = has("midwife", "nurse", "nurses", "hospital", "medical", "doctor", "maternity") or (
        is_grounded_drama and has("family", "community", "mother", "women", "village")
    )
    prefers_romance_family = is_period or has("romance", "family", "community", "village", "marriage")
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

    faq_items = _pick_faq_variant(anchor_title, anchor_details, top_titles_text, genre_text, descriptor)

    return {
        "intro": intro,
        "seo_blurb": seo_blurb,
        "top_titles_text": top_titles_text,
        "top_genres": genres,
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
            "finance", "hedge fund", "wall street", "billionaire", "wealth",
            "corporate", "business", "money", "elite", "company", "ceo",
            "boardroom", "shareholder", "merger", "acquisition", "media empire",
            "conglomerate", "power", "ambition", "rivalry",
        ],
        "boost_any": [
            "finance", "hedge fund", "wall street", "billionaire", "wealth",
            "corporate", "business", "money", "elite", "company", "ceo",
            "boardroom", "shareholder", "merger", "acquisition", "media empire",
            "conglomerate", "power", "ambition", "rivalry", "dynasty",
        ],
        "reject_any": ["high school", "teen", "supernatural", "vampire", "wizard"],
        "preferred_genres": {18, 80},
        "strict": False,
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
}


def _blob_for(details: dict, extra_title: str | None = None) -> str:
    return " ".join(
        [
            str(extra_title or details.get("title") or details.get("name") or ""),
            str(details.get("overview") or ""),
            " ".join(str(g) for g in (details.get("genres") or [])),
        ]
    ).lower()


def _contains_any(blob: str, terms: list[str] | tuple[str, ...]) -> bool:
    return any(term in blob for term in terms)


def _count_hits(blob: str, terms: list[str] | tuple[str, ...]) -> int:
    return sum(1 for term in terms if term in blob)


def _classify_anchor_concept_v2(anchor_title: str, anchor_details: dict) -> str:
    title = str(anchor_title or anchor_details.get("title") or anchor_details.get("name") or "").lower()
    blob = _blob_for(anchor_details, title)
    genres = set(anchor_details.get("genre_ids") or [])
    genre_names = _genre_name_set(anchor_details)

    existential_terms = [
        "disappear", "disappears", "disappearance", "vanish", "vanished",
        "missing", "unexplained", "grief", "loss", "faith", "spiritual",
        "cult", "apocalypse", "apocalyptic", "supernatural", "strange event",
        "paranormal", "identity", "consciousness",
    ]
    existential_hits = _count_hits(blob, existential_terms)
    is_prestige_mystery_shape = (
        18 in genres
        and (9648 in genres or 10765 in genres or "mystery" in genre_names or "sci-fi & fantasy" in genre_names)
        and existential_hits >= 2
    )

    if is_prestige_mystery_shape:
        return "prestige_existential_mystery"

    if title in {"foundation"} or _contains_any(blob, ["psychohistory", "galactic empire", "empire", "civilization", "civilisation", "dynasty"]):
        if 10765 in genres:
            return "space_epic"

    if title in {"the expanse", "for all mankind", "battlestar galactica", "firefly"}:
        return "space_epic"

    if title in {"silo", "snowpiercer"} or _contains_any(blob, ["bunker", "underground", "sealed", "silo", "vault", "controlled society", "authoritarian"]):
        if 10765 in genres:
            return "contained_dystopia"

    if title in {"lost", "from", "manifest", "yellowjackets", "wayward pines"} or _contains_any(
        blob,
        [
            "plane crash", "stranded", "island", "survivors",
            "supernatural mystery", "unexplained", "disappearance",
            "alternate reality", "mystery box", "paranormal",
            "people vanish", "vanish without a trace",
        ],
    ):
        return "mystery_box_survival"

    if title in {"dark", "12 monkeys"} or _contains_any(blob, ["time travel", "timeline", "time loop", "paradox", "parallel world", "generations"]):
        return "time_mystery"

    if title in {"severance"} or _contains_any(blob, ["workplace", "office", "memory", "identity", "consciousness", "corporate experiment"]):
        if 10765 in genres or 9648 in genres:
            return "corporate_mystery"

    if title in {"billions", "succession", "industry"} or _contains_any(blob, ["hedge fund", "wall street", "billionaire", "media empire", "corporate", "boardroom", "shareholder"]):
        return "finance_power"

    if _contains_any(blob, ["midwife", "maternity", "nurse", "hospital", "doctor", "medical"]):
        return "medical_family"

    if title in {"downton abbey", "poldark", "pride and prejudice"} or _contains_any(
        blob,
        [
            "period", "historical", "victorian", "georgian",
            "post-war", "postwar", "1950", "1960",
            "village", "estate", "aristocratic", "early 19th century",
            "19th century", "18th century",
        ],
    ):
        return "period_community"
    
    if title in {"mare of easttown", "broadchurch", "sharp objects", "happy valley"} or _contains_any(blob, ["small town", "local murder", "community apart"]):
        return "small_town_mystery"
    
    if title in {"true detective", "mindhunter", "mare of easttown", "the killing", "the fall"} or _contains_any(blob, ["detective", "investigation", "serial killer", "murder case", "fbi"]):
        return "detective_mystery"

    if 80 in genres or _contains_any(blob, ["crime", "criminal", "cartel", "drug", "gang", "mafia", "mob", "lawyer", "attorney"]):
        return "crime_pressure"

    if 10765 in genres or "sci-fi & fantasy" in genre_names:
        return "general_scifi"

    return "general_drama"


def _concept_fit_score(anchor_concept: str, details: dict, *, semantic_score: float, genre_score: float) -> tuple[bool, float, float]:
    """Return (passes, additive_bonus, multiplier)."""
    rule = CONCEPT_RULES.get(anchor_concept) or CONCEPT_RULES["general_drama"]
    blob = _blob_for(details)
    genres = set(details.get("genre_ids") or [])
    title = str(details.get("title") or details.get("name") or "").lower()
    first_air_date = str(details.get("first_air_date") or "")
    year = 0
    try:
        year = int(first_air_date[:4])
    except Exception:
        year = 0

    # Avoid anime/animation drift on non-animation SEO pages.
    if 16 in genres and anchor_concept not in {"general_scifi", "space_epic"}:
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

    
    if title in SCI_FI_CLASSICS and anchor_concept in {"space_epic", "general_scifi"}:
        bonus += 0.16

    
    if anchor_concept == "space_epic":
        if 10765 not in genres:
            return False, 0.0, 1.0
        if _contains_any(blob, ["star trek", "stargate", "battlestar", "farscape", "firefly", "andor"]):
            bonus += 0.12
        if _contains_any(blob, ["jedi", "mandalorian", "ahsoka"]):
            multiplier *= 0.88

    elif anchor_concept == "contained_dystopia":
        if 10765 not in genres and semantic_score < 0.24:
            return False, 0.0, 1.0
        if title in {"fallout", "paradise"}:
            bonus += 0.55
        elif title in {"snowpiercer", "silo"}:
            bonus += 0.35

        if title in {"the outer limits", "the pretender", "taken"}:
            multiplier *= 0.55

        strong_contained = _contains_any(blob, [
            "bunker", "underground", "sealed", "silo", "vault",
            "contained", "containment", "surveillance", "authoritarian",
            "controlled society", "restricted", "facility", "enclosed",
            "isolated", "quarantine",
        ])

        dystopian_survival = _contains_any(blob, [
            "dystopian", "survival", "post-apocalyptic", "post apocalyptic",
            "collapse", "wasteland", "class warfare", "regime",
        ])

        if strong_contained:
            bonus += 0.24

        if dystopian_survival:
            bonus += 0.18

        if title in {
            "snowpiercer",
            "severance",
            "dark",
            "from",
            "the 100",
            "station eleven",
            "wayward pines",
            "the leftovers",
        }:
            bonus += 0.22

        if title in {
            "dollhouse",
            "the pretender",
            "the outer limits",
            "taken",
        }:
            multiplier *= 0.72

        if title in {
            "under the dome",
        }:
            multiplier *= 0.82

        if _contains_any(blob, ["alien attack", "battlefield", "invasion", "soldiers", "jedi", "starship"]):
            multiplier *= 0.60

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
        if _contains_any(blob, ["time travel", "timeline", "loop", "paradox", "parallel"]):
            bonus += 0.22
        elif required_hits == 0 and semantic_score < 0.24:
            multiplier *= 0.70

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

    elif anchor_concept in {"crime_pressure", "detective_mystery"}:
        if 80 in genres:
            bonus += 0.12

        if 10765 in genres:
            multiplier *= 0.35

        if 10759 in genres and semantic_score < 0.35:
            multiplier *= 0.45

        if _contains_any(blob, ["superhero", "vampire", "monster", "supernatural", "high school students", "trauma medical center"]):
            multiplier *= 0.35

        generic_procedural_terms = [
            "nypd", "lapd", "fbi", "elite agents", "homicide unit",
            "police procedural", "solve crimes", "solving crimes",
            "cases", "case-of-the-week", "precinct", "rookie",
        ]

        prestige_crime_terms = [
            "corruption", "institution", "bureaucracy", "drug", "cartel",
            "underworld", "organized crime", "moral", "political",
            "system", "city", "criminal organization"
        ]

        procedural_hits = _count_hits(blob, generic_procedural_terms)
        prestige_hits = _count_hits(blob, prestige_crime_terms)

        if procedural_hits >= 1 and prestige_hits == 0:
            multiplier *= 0.35

        if title in {"castle", "blue bloods", "elementary", "the rookie", "fbi: international", "major crimes"}:
            multiplier *= 0.45

        if 35 in genres and 80 not in genres and semantic_score < 0.24:
            multiplier *= 0.75

    elif anchor_concept == "finance_power":

        finance_terms = [
            "finance", "hedge fund", "wall street", "billionaire",
            "corporate", "company", "ceo", "boardroom",
            "shareholder", "merger", "acquisition",
            "wealth", "money", "elite", "business",
            "empire", "dynasty", "inheritance", "family business",
        ]

        strong_finance = _count_hits(blob, finance_terms)

        if _contains_any(blob, ["superhero", "monster", "alien", "godzilla"]):
            return False, 0.0, 1.0

        # HARD filter (but smarter)
        power_terms = [
            "power", "family", "wealth", "wealthy", "elite", "empire",
            "dynasty", "inheritance", "rivalry", "ambition", "corruption",
            "scandal", "media", "lawyer", "political", "influence"
        ]

        strong_power = _count_hits(blob, power_terms)

        if strong_finance == 0 and strong_power == 0:
            if semantic_score < 0.25:
                return False, 0.0, 1.0
            multiplier *= 0.75

        if strong_power >= 1:
            bonus += 0.12
        if strong_power >= 2:
            bonus += 0.18
        if 10759 in genres or 10768 in genres:
            multiplier *= 0.55
        

        # Boost real matches heavily
        if strong_finance >= 1:
            bonus += 0.18
        if strong_finance >= 2:
            bonus += 0.28
        if strong_finance >= 3:
            bonus += 0.35

    elif anchor_concept == "period_community":
        if 10765 in genres or 10759 in genres or 80 in genres:
            multiplier *= 0.55
        if _contains_any(blob, ["high school", "drugs", "sex", "social media", "trauma medical center", "emergency department", "overcrowded"]):
            multiplier *= 0.45
        if required_hits == 0 and semantic_score < 0.18:
            return False, 0.0, 1.0

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
        allow_titles = {"the good wife", "the good fight", "billions", "industry", "mad men", "the sopranos"}
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

        if not _passes_grounded_concept_sanity(anchor_concept, item, source=source, score=score):
            continue

        min_polished_score = 0.42 if anchor_concept in {"period_community", "medical_family"} else 0.55

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
        if 16 in genres and anchor_concept not in {"general_scifi", "space_epic"}:
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


        min_polished_score = 0.42 if anchor_concept in {"period_community", "medical_family"} else 0.55

        if score < min_polished_score:
            continue

        item = dict(item)
        item["score"] = round(score, 4)
        polished.append(item)

    polished.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)

    # Diversity cap: avoid one page becoming all procedurals / all legal / all sci-fi.
    bucket_counts: dict[str, int] = {}
    final: list[dict] = []

    for item in polished:
        bucket = bucket_for(item)
        max_per_bucket = 4

        if anchor_concept in {"crime_pressure", "detective_mystery"}:
            max_per_bucket = 5

        if anchor_concept == "contained_dystopia":
            max_per_bucket = 3

        if anchor_concept in {"mystery_box_survival", "prestige_existential_mystery"}:
            max_per_bucket = 5

        if bucket_counts.get(bucket, 0) >= max_per_bucket:
            continue

        final.append(item)
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1

        if len(final) >= limit:
            break

    return final

@router.get("/shows-like/{slug}")
async def shows_like(
    slug: str,
    db: AsyncSession = Depends(get_async_session),
):
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
                tmdb_anchor_details = candidate_details
                tmdb_row.pop("details", None)
                row = tmdb_row
                tmdb_id = int(row["show_id"])
                anchor_title = str(row["title"])
                anchor_details = tmdb_anchor_details
                print("SEO anchor corrected from TMDB search:", anchor_title, tmdb_id)
    anchor_genre_ids = set(anchor_details.get("genre_ids") or [])
    anchor_lang = anchor_details.get("original_language")
    anchor_keywords = _extract_anchor_keywords(
        anchor_details.get("title") or anchor_details.get("name") or anchor_title,
        anchor_details.get("overview"),
        " ".join(anchor_details.get("genres") or []),
    )
    anchor_profile = _anchor_profile(anchor_details)
    anchor_concept = _classify_anchor_concept_v2(anchor_title, anchor_details)
    anchor_concept = ANCHOR_TO_CONCEPT.get(anchor_title.lower(), anchor_concept)
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

    tmdb_task = _tmdb_recommendations_for_fav(tmdb_id, api_key, max_n=MAX_RESULTS * 4)
    trending_task = _fetch_tmdb_trending_candidates(
        allowed_langs={anchor_lang} if anchor_lang else set(),
        fav_genres=anchor_genre_ids,
        block_ids={tmdb_id},
        limit=MAX_RESULTS * 3,
    )

    tmdb_ids_raw, reddit_scores, trending_items = await asyncio.gather(
        tmdb_task,
        _fetch_reddit_similar(),
        trending_task,
    )

    tmdb_ids_raw = [rid for rid in (tmdb_ids_raw or []) if isinstance(rid, int) and rid != tmdb_id]
    reddit_scores = reddit_scores or {}

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
        merged_scores[rid] = merged_scores.get(rid, 0.0) + 0.18

    for rid, raw in trending_scores.items():
        merged_scores[rid] = merged_scores.get(rid, 0.0) + min(0.12, 0.04 + 0.06 * raw)

    for rid, weight in reddit_scores.items():
        if rid == tmdb_id:
            continue
        merged_scores[rid] = merged_scores.get(rid, 0.0) + 0.62 * math.log10(1.0 + max(float(weight), 0.0))

    sorted_ids = sorted(merged_scores.keys(), key=lambda x: merged_scores[x], reverse=True)
    fetch_ids = sorted_ids[: MAX_RESULTS * 5]
    details_list = await asyncio.gather(*[_tmdb_details(rid) for rid in fetch_ids]) if fetch_ids else []

    # Some SEO anchors, especially sci-fi, do not always have enough local
    # Reddit/TMDB candidates. Add a small archetype fallback pool, then let the
    # existing filters and scores below decide what survives.
    if anchor_is_scifi:
        extra_ids = [
            rid
            for rid in _fallback_ids_for_concept(anchor_concept)
            if rid != tmdb_id and rid not in fetch_ids
        ]
        if extra_ids:
            extra_details = await asyncio.gather(*[_tmdb_details(rid) for rid in extra_ids[:24]])
            details_list.extend([d for d in extra_details if d])

    

    results: list[dict] = []
    seen_ids = {tmdb_id}
    tmdb_set = set(tmdb_ids_raw)
    reddit_set = set(reddit_scores.keys())
    trending_set = set(trending_scores.keys())

    def _passes_basic_candidate_checks(details: dict) -> tuple[bool, int, str, set[int], float, int, float, str]:
        try:
            rid = int(details.get("tmdb_id") or 0)
        except Exception:
            return False, 0, "", set(), 0.0, 0, 0.0, ""

        title_val = str(details.get("title") or details.get("name") or "").strip()
        if not rid or rid in seen_ids or not title_val:
            return False, rid, title_val, set(), 0.0, 0, 0.0, ""
        if not details.get("poster_path"):
            return False, rid, title_val, set(), 0.0, 0, 0.0, ""

        genre_ids = set(details.get("genre_ids") or [])
        if genre_ids & BAD_GENRES:
            return False, rid, title_val, genre_ids, 0.0, 0, 0.0, ""
        if 10767 in genre_ids or 10766 in genre_ids:
            return False, rid, title_val, genre_ids, 0.0, 0, 0.0, ""
        if 99 in genre_ids and len(genre_ids) == 1:
            return False, rid, title_val, genre_ids, 0.0, 0, 0.0, ""
        if anchor_concept == "finance_power" and 35 in genre_ids and 18 not in genre_ids:
            return False, rid, title_val, genre_ids, 0.0, 0, 0.0, ""

        vote_average = float(details.get("vote_average") or 0.0)
        vote_count = int(details.get("vote_count") or 0)
        popularity = float(details.get("popularity") or 0.0)
        first_air_date = str(details.get("first_air_date") or "")

        if vote_count < ABS_MIN_VOTE_COUNT or popularity < ABS_MIN_POPULARITY:
            return False, rid, title_val, genre_ids, vote_average, vote_count, popularity, first_air_date
        if _is_future_or_too_fresh_for_seo(first_air_date, vote_count):
            return False, rid, title_val, genre_ids, vote_average, vote_count, popularity, first_air_date
        if anchor_is_scifi and 10765 not in genre_ids:
            return False, rid, title_val, genre_ids, vote_average, vote_count, popularity, first_air_date
        if anchor_is_scifi and not anchor_profile.get("is_animation") and 16 in genre_ids:
            return False, rid, title_val, genre_ids, vote_average, vote_count, popularity, first_air_date

        return True, rid, title_val, genre_ids, vote_average, vote_count, popularity, first_air_date

    for details in details_list:
        ok, rid, title_val, genre_ids, vote_average, vote_count, popularity, first_air_date = _passes_basic_candidate_checks(details)
        if not ok:
            continue

        genre_score = _genre_overlap_score(anchor_genre_ids, genre_ids)
        semantic_score = _semantic_text_score(
            anchor_keywords,
            title_val,
            details.get("overview"),
            " ".join(details.get("genres") or []),
        )

        is_tmdb = rid in tmdb_set
        is_reddit = rid in reddit_set
        is_trending = rid in trending_set

        fits_anchor, fit_bonus = _candidate_fit_adjustment(anchor_profile, details)
        if not fits_anchor:
            continue

        concept_pass, concept_bonus, concept_multiplier = _concept_fit_score(
            anchor_concept,
            details,
            semantic_score=semantic_score,
            genre_score=genre_score,
        )
        if not concept_pass:
            continue

        candidate_blob = _blob_for(details)

        if anchor_concept:
            if not passes_concept_guardrail(anchor_concept, candidate_blob, list(details.get("genres") or [])):
                continue

        if anchor_is_scifi and _is_weak_scifi(details) and semantic_score < 0.22 and concept_bonus < 0.16:
            continue

        if anchor_concept in {"medical_family", "period_community"}:
            if not is_reddit and not is_tmdb and semantic_score < 0.08 and genre_score < 0.05 and concept_bonus < 0.08:
                continue
        else:
            if not is_reddit and not is_tmdb and semantic_score < 0.10 and genre_score < 0.08 and concept_bonus < 0.12:
                continue

        if not _passes_seo_quality_floor(
            vote_average=vote_average,
            vote_count=vote_count,
            popularity=popularity,
            semantic_score=semantic_score + min(0.20, concept_bonus),
            genre_score=genre_score,
            is_reddit=is_reddit,
            is_tmdb=is_tmdb,
            is_trending=is_trending,
        ):
            continue

        bayes_quality = _bayesian_quality_score(vote_average, vote_count)
        qual_bonus = _quality_bonus(vote_average, vote_count, popularity)
        conf_factor = _confidence_factor(vote_count, popularity)

        total_score = float(merged_scores.get(rid, 0.0))
        total_score += 0.50 * semantic_score
        total_score += 0.38 * genre_score
        total_score += 0.32 * bayes_quality
        total_score += qual_bonus
        total_score += fit_bonus
        total_score += concept_bonus

        # Penalise crime-heavy shows for non-crime anchors
        if anchor_concept not in {"crime_pressure", "detective_mystery"}:
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

    if len(results) < MIN_RESULTS:
        fill_candidates: list[dict] = []
        for details in details_list:
            ok, rid, title_val, genre_ids, vote_average, vote_count, popularity, first_air_date = _passes_basic_candidate_checks(details)
            if not ok or rid in seen_ids:
                continue

            genre_score = _genre_overlap_score(anchor_genre_ids, genre_ids)
            semantic_score = _semantic_text_score(
                anchor_keywords,
                title_val,
                details.get("overview"),
                " ".join(details.get("genres") or []),
            )
            concept_pass, concept_bonus, concept_multiplier = _concept_fit_score(
                anchor_concept,
                details,
                semantic_score=semantic_score,
                genre_score=genre_score,
            )
            if not concept_pass:
                continue

            candidate_blob = _blob_for(details)

            if anchor_concept:
                if not passes_concept_guardrail(anchor_concept, candidate_blob, list(details.get("genres") or [])):
                    continue

            if _weak_future_for_seo(details):
                continue

            if not _passes_grounded_concept_sanity(anchor_concept, details, source="fill", score=0.0):
                continue

            fit = _fill_fit_score(_anchor_fill_bucket(anchor_title, anchor_details), details)
            if fit < 0.10 and concept_bonus < 0.12 and semantic_score < 0.14:
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
            if len(results) >= MIN_RESULTS:
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

    results = _seo_ranking_layer(
        results,
        anchor_concept=anchor_concept,
        limit=MAX_RESULTS,
        anchor_tmdb_id=tmdb_id,
    )

    # SEO safety net: never leave a valid sci-fi / mystery-box anchor with an empty page
    # just because the live TMDB/Reddit signals were sparse or a strict filter removed too much.
    if anchor_concept == "mystery_box_survival" and len(results) < 6:
        existing_ids = {int(x.get("tmdb_id") or 0) for x in results}
        rescue_ids = [
            rid
            for rid in SEO_CONCEPT_FALLBACK_IDS.get("mystery_box_survival", [])
            if rid != tmdb_id and rid not in existing_ids
        ]
        rescue_details = await asyncio.gather(*[_tmdb_details(rid) for rid in rescue_ids[:18]]) if rescue_ids else []
        rescue_items: list[dict] = []
        for details in rescue_details:
            ok, rid, title_val, genre_ids, vote_average, vote_count, popularity, first_air_date = _passes_basic_candidate_checks(details)
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
            concept_pass, concept_bonus, concept_multiplier = _concept_fit_score(
                anchor_concept,
                details,
                semantic_score=semantic_score,
                genre_score=genre_score,
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

    return {
        "anchor": {
            "tmdb_id": tmdb_id,
            "title": anchor_title,
            "poster_path": row.get("poster_path") or anchor_details.get("poster_path"),
        },
        "recommendations": results,
        "page_copy": _build_page_copy(anchor_title, anchor_details, results),
    }


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

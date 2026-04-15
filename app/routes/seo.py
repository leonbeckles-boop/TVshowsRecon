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
    }


def _anchor_theme_flags(anchor_title: str, anchor_details: dict) -> dict[str, bool]:
    title_lower = str(anchor_title or "").lower()
    overview = str(anchor_details.get("overview") or "").lower()
    genre_names = _genre_name_set(anchor_details)
    blob = f"{title_lower} {overview}"

    def has(*terms: str) -> bool:
        return any(term in blob for term in terms)

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

    if has("finance", "billionaire", "hedge fund", "wall street", "corporate", "wealth", "money", "power", "ambition", "media conglomerate", "empire") or title_lower in {"billions", "succession", "industry"}:
        themes = ["power plays", "elite rivalry", "high-stakes ambition"]
        mood = "sharp and intense"
        angle = "status-driven drama"
        audience_hook = "power, money and strategic conflict"
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
    elif has("time travel", "parallel", "dystopian", "future", "alien") or "sci-fi & fantasy" in genre_names:
        themes = ["big ideas", "mystery", "long-form payoff"]
        mood = "atmospheric"
        angle = "concept-heavy storytelling"
        audience_hook = "mystery, world-building and payoff over time"
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


@router.get("/shows-like/{slug}")
async def shows_like(
    slug: str,
    db: AsyncSession = Depends(get_async_session),
):
    title = slug.replace("-", " ")

    show_res = await db.execute(
        text(
            """
            SELECT
                show_id,
                title,
                poster_path
            FROM shows
            WHERE lower(title) = lower(:title)
            LIMIT 1
            """
        ),
        {"title": title},
    )

    row = show_res.mappings().first()

    if not row:
        from app.routes.recs_v3 import _tmdb_search_tv

        tmdb_match = await _tmdb_search_tv(title)
        if not tmdb_match:
            raise HTTPException(status_code=404, detail="Show not found")

        tmdb_id = tmdb_match.get("id")
        if not isinstance(tmdb_id, int):
            raise HTTPException(status_code=404, detail="Show not found")

        details = await _tmdb_details(tmdb_id)

        row = {
            "show_id": tmdb_id,
            "title": details.get("title") or details.get("name") or title.title(),
            "poster_path": details.get("poster_path"),
        }

    tmdb_id = int(row["show_id"])
    print("SEO anchor:", row["title"], tmdb_id)

    anchor_details = await _tmdb_details(tmdb_id)
    anchor_genre_ids = set(anchor_details.get("genre_ids") or [])
    anchor_lang = anchor_details.get("original_language")
    anchor_keywords = _extract_anchor_keywords(
        anchor_details.get("title") or anchor_details.get("name"),
        anchor_details.get("overview"),
        " ".join(anchor_details.get("genres") or []),
    )
    anchor_profile = _anchor_profile(anchor_details)
    anchor_theme_flags = _anchor_theme_flags(str(row["title"]), anchor_details)

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

    async def _fetch_reddit_similar():
        try:
            res = await db.execute(reddit_sql, {"tid": tmdb_id, "lim": MAX_RESULTS * 3})
            rows = res.mappings().all()
            out = {}
            for r in rows:
                other_id = r.get("other_id")
                if other_id is None:
                    continue
                try:
                    oid = int(other_id)
                    pw = float(r.get("pair_weight") or 0.0)
                except Exception:
                    continue
                out[oid] = max(out.get(oid, 0.0), pw)
            return out
        except Exception:
            return {}

    tmdb_task = _tmdb_recommendations_for_fav(tmdb_id, api_key, max_n=MAX_RESULTS * 3)
    trending_task = _fetch_tmdb_trending_candidates(
        allowed_langs={anchor_lang} if anchor_lang else set(),
        fav_genres=anchor_genre_ids,
        block_ids={tmdb_id},
        limit=MAX_RESULTS * 2,
    )

    tmdb_ids_raw, reddit_scores, trending_items = await asyncio.gather(
        tmdb_task,
        _fetch_reddit_similar(),
        trending_task,
    )

    trending_scores: dict[int, float] = {}
    for item in (trending_items or []):
        try:
            rid = int(item.get("tmdb_id") or 0)
            raw = float(item.get("score_raw") or 0.0)
        except Exception:
            continue
        if rid and rid != tmdb_id:
            trending_scores[rid] = max(trending_scores.get(rid, 0.0), raw)

    merged_scores: dict[int, float] = {}

    for rid in (tmdb_ids_raw or []):
        if not isinstance(rid, int) or rid == tmdb_id:
            continue
        merged_scores[rid] = merged_scores.get(rid, 0.0) + 0.14

    for rid, raw in trending_scores.items():
        merged_scores[rid] = merged_scores.get(rid, 0.0) + min(0.08, 0.03 + 0.05 * raw)

    for rid, pw in (reddit_scores or {}).items():
        if rid == tmdb_id:
            continue
        reddit_score = 0.60 * math.log10(1.0 + max(pw, 0.0))
        merged_scores[rid] = merged_scores.get(rid, 0.0) + reddit_score

    sorted_ids = sorted(merged_scores.keys(), key=lambda x: merged_scores[x], reverse=True)
    fetch_ids = sorted_ids[: MAX_RESULTS * 4]
    details_list = await asyncio.gather(*[_tmdb_details(rid) for rid in fetch_ids])

    results: list[dict] = []
    seen_ids = {tmdb_id}
    tmdb_set = set(tmdb_ids_raw or [])
    reddit_set = set(reddit_scores.keys())
    trending_set = set(trending_scores.keys())

    for details in details_list:
        try:
            rid = int(details.get("tmdb_id") or 0)
        except Exception:
            rid = 0

        if not rid or rid in seen_ids:
            continue

        title_val = details.get("title") or details.get("name")
        if not title_val:
            continue

        poster_path = details.get("poster_path")
        if not poster_path:
            continue

        genre_ids = set(details.get("genre_ids") or [])
        genre_names = _genre_name_set(details)

        if genre_ids & BAD_GENRES:
            continue
        if 10767 in genre_ids or 10766 in genre_ids:
            continue
        if 99 in genre_ids and len(genre_ids) == 1:
            continue

        vote_count = int(details.get("vote_count") or 0)
        vote_average = float(details.get("vote_average") or 0.0)
        popularity = float(details.get("popularity") or 0.0)

        if vote_count < ABS_MIN_VOTE_COUNT:
            continue
        if popularity < ABS_MIN_POPULARITY:
            continue

        genre_score = _genre_overlap_score(anchor_genre_ids, genre_ids)
        semantic_score = _semantic_text_score(
            anchor_keywords,
            details.get("title") or details.get("name"),
            details.get("overview"),
            " ".join(details.get("genres") or []),
        )

        is_tmdb = rid in tmdb_set
        is_reddit = rid in reddit_set
        is_trending = rid in trending_set

        fits_anchor, fit_bonus = _candidate_fit_adjustment(anchor_profile, details)
        if not fits_anchor:
            continue

        candidate_flags = _candidate_theme_flags(details)

        if anchor_theme_flags["finance_power"] and candidate_flags["teen_chaos"]:
            continue

        if anchor_theme_flags["finance_power"]:
            if not candidate_flags["finance_power"]:
                continue

        if anchor_theme_flags["period_community"] or anchor_theme_flags["warm_medical"]:
            if not (candidate_flags["period_community"] or candidate_flags["warm_medical"]):
                continue
            if candidate_flags["modern_hospital"] and not candidate_flags["period_community"]:
                continue
            if candidate_flags["teen_chaos"]:
                continue

        if anchor_theme_flags["crime_antihero"]:
            if not candidate_flags["crime_antihero"] and semantic_score < 0.24:
                continue

        if anchor_profile["grounded_drama"]:
            if "drama" not in genre_names and semantic_score < 0.24:
                continue

        if is_tmdb and not is_reddit:
            if semantic_score < 0.18 and genre_score < 0.20:
                continue

        if not is_reddit and semantic_score < 0.14 and genre_score < 0.10:
            continue

        if anchor_profile["period"] and genre_score == 0.0 and semantic_score < 0.20:
            continue

        if anchor_profile["medical_family"] and semantic_score < 0.08 and fit_bonus < 0.10:
            continue

        if anchor_theme_flags["finance_power"]:
            if "comedy" in genre_names and not candidate_flags["finance_power"]:
                continue

        if anchor_theme_flags["period_community"] or anchor_theme_flags["warm_medical"]:
            if "crime" in genre_names:
                continue
            if candidate_flags["teen_chaos"]:
                continue
            if candidate_flags["modern_hospital"] and not candidate_flags["period_community"]:
                continue

        if not _passes_seo_quality_floor(
            vote_average=vote_average,
            vote_count=vote_count,
            popularity=popularity,
            semantic_score=semantic_score,
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
        total_score += 0.75 * semantic_score
        total_score += 0.45 * genre_score
        total_score += 0.35 * bayes_quality
        total_score += qual_bonus
        total_score += fit_bonus

        theme_bonus = 0.0
        if anchor_theme_flags["finance_power"] and candidate_flags["finance_power"]:
            theme_bonus += 0.30
        if anchor_theme_flags["finance_power"] and candidate_flags["corporate_drama"]:
            theme_bonus += 0.18
        if (anchor_theme_flags["period_community"] or anchor_theme_flags["warm_medical"]) and (
            candidate_flags["period_community"] or candidate_flags["warm_medical"]
        ):
            theme_bonus += 0.25
        if anchor_theme_flags["crime_antihero"] and candidate_flags["crime_antihero"]:
            theme_bonus += 0.20
        total_score += theme_bonus

        if anchor_theme_flags["finance_power"]:
            if "crime" in genre_names and not candidate_flags["corporate_drama"]:
                total_score *= 0.90

        if is_tmdb and not is_reddit:
            total_score *= 0.82

        if is_reddit and not is_tmdb and vote_count < 100:
            total_score *= 0.82

        if is_trending and not is_reddit and semantic_score >= 0.18:
            total_score += 0.04

        total_score *= conf_factor

        if total_score < 0.55:
            continue

        seen_ids.add(rid)

        source = (
            "multi_signal"
            if is_reddit and (is_tmdb or is_trending)
            else "reddit_pairs"
            if is_reddit
            else "semantic_fallback"
            if semantic_score >= 0.18
            else "tmdb_recs"
        )

        results.append(
            {
                "tmdb_id": rid,
                "title": title_val,
                "poster_path": poster_path,
                "poster_url": details.get("poster_url"),
                "overview": details.get("overview"),
                "first_air_date": details.get("first_air_date"),
                "vote_average": vote_average,
                "vote_count": vote_count,
                "popularity": popularity,
                "genres": details.get("genres"),
                "genre_ids": details.get("genre_ids"),
                "source": source,
                "score": round(float(total_score), 4),
            }
        )

        if len(results) >= MAX_RESULTS:
            break

    results.sort(
        key=lambda x: (
            float(x.get("score") or 0.0),
            float(x.get("vote_average") or 0.0),
            math.log10(int(x.get("vote_count") or 0) + 1),
            float(x.get("popularity") or 0.0),
        ),
        reverse=True,
    )
    print("SEO final rec count:", len(results))

    page_copy = _build_page_copy(str(row["title"]), anchor_details, results[:MAX_RESULTS])

    return {
        "anchor": {
            "tmdb_id": row["show_id"],
            "title": row["title"],
            "poster_path": row["poster_path"],
        },
        "recommendations": results[:MAX_RESULTS],
        "page_copy": page_copy,
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
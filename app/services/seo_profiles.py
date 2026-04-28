# app/services/seo_profiles.py

from sqlalchemy import text
from typing import Dict, List, Any
import json
import os

# ----------------------------
# Config
# ----------------------------

USE_LLM = bool(os.getenv("OPENAI_API_KEY"))

# ----------------------------
# Public API
# ----------------------------

async def get_or_create_profile(db, anchor: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main entry point.
    Returns cached profile or generates one.
    """

    profile = await _fetch_profile(db, anchor["tmdb_id"])

    if profile:
        return profile

    # Generate new profile
    if USE_LLM:
        profile = await _generate_profile_llm(anchor)
    else:
        profile = _fallback_profile(anchor)

    # Store it
    await _store_profile(db, anchor, profile)

    return profile


# ----------------------------
# DB layer
# ----------------------------

async def _fetch_profile(db, tmdb_id: int):
    row = await db.execute(
        text("""
            SELECT concept, tone_tags, structure_tags, avoid_tags, keywords
            FROM seo_anchor_profiles
            WHERE tmdb_id = :id
        """),
        {"id": tmdb_id}
    )

    row = row.first()
    if not row:
        return None

    return {
        "concept": row[0],
        "tone_tags": row[1] or [],
        "structure_tags": row[2] or [],
        "avoid_tags": row[3] or [],
        "keywords": row[4] or []
    }


async def _store_profile(db, anchor, profile):
    await db.execute(
        text("""
            INSERT INTO seo_anchor_profiles
            (tmdb_id, title, concept, tone_tags, structure_tags, avoid_tags, keywords)
            VALUES (:id, :title, :concept, :tone, :structure, :avoid, :keywords)
            ON CONFLICT (tmdb_id) DO UPDATE SET
                concept = EXCLUDED.concept,
                tone_tags = EXCLUDED.tone_tags,
                structure_tags = EXCLUDED.structure_tags,
                avoid_tags = EXCLUDED.avoid_tags,
                keywords = EXCLUDED.keywords,
                updated_at = now()
        """),
        {
            "id": anchor["tmdb_id"],
            "title": anchor["title"],
            "concept": profile["concept"],
            "tone": profile["tone_tags"],
            "structure": profile["structure_tags"],
            "avoid": profile["avoid_tags"],
            "keywords": profile["keywords"],
        }
    )
    await db.commit()


# ----------------------------
# LLM generation (optional)
# ----------------------------

async def _generate_profile_llm(anchor):
    """
    You can plug OpenAI here later.
    For now, keep simple to avoid breaking things.
    """

    # Placeholder until you wire OpenAI
    return _fallback_profile(anchor)


# ----------------------------
# Fallback classifier (FAST + SAFE)
# ----------------------------

def _fallback_profile(anchor):
    title = anchor["title"].lower()
    genres = anchor.get("genres", [])

    # Default
    profile = {
        "concept": "general",
        "tone_tags": [],
        "structure_tags": [],
        "avoid_tags": [],
        "keywords": []
    }

    # Sci-fi anchors
    if any(g in genres for g in ["Sci-Fi & Fantasy"]):
        profile["tone_tags"] += ["serious", "high-stakes"]
        profile["structure_tags"] += ["world_building"]
        profile["keywords"] += ["future", "technology", "conflict"]

    # Dark-style
    if "dark" in title:
        profile["concept"] = "time_puzzle"
        profile["tone_tags"] += ["bleak", "complex"]
        profile["structure_tags"] += ["time_loop", "family_secrets"]
        profile["keywords"] += ["time", "loop", "paradox"]

    # Severance-style
    if "severance" in title:
        profile["concept"] = "corporate_mystery"
        profile["tone_tags"] += ["uneasy", "psychological"]
        profile["structure_tags"] += ["identity_split", "institution"]
        profile["keywords"] += ["memory", "identity", "corporation"]

    return profile


# ----------------------------
# Scoring helpers
# ----------------------------

def apply_profile_scoring(candidate: Dict, profile: Dict) -> float:
    """
    Adds profile-based relevance score.
    """

    score = 0.0

    overview = (candidate.get("overview") or "").lower()
    genres = candidate.get("genres", [])

    # Keyword match
    for kw in profile["keywords"]:
        if kw in overview:
            score += 0.15

    # Structure / tone via genres proxy
    for tag in profile["structure_tags"]:
        if tag in genres:
            score += 0.2

    for tag in profile["tone_tags"]:
        if tag in genres:
            score += 0.1

    # Avoid penalties
    for tag in profile["avoid_tags"]:
        if tag in genres:
            score -= 0.3

    return score
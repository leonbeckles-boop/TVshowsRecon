# app/services/lang_filter.py
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Sequence, Set

# Optional details fetcher (only used if we need to enrich missing language)
try:
    from app.services.tmdb_details import get_tv_details  # async fn (tmdb_id) -> dict
except Exception:
    get_tv_details = None  # type: ignore


def _norm_langs(val: Iterable[str]) -> Set[str]:
    out: Set[str] = set()
    for v in val:
        v = (v or "").strip()
        if not v:
            continue
        # accept "en", "en-US", "EN_gb" -> normalize to "en"
        out.add(v.split("-")[0].split("_")[0].lower())
    return out


async def filter_by_original_language(
    items: Sequence[Dict[str, Any]],
    allowed_langs: Iterable[str] = ("en",),
    try_enrich_missing: bool = False,
    max_enrich: int = 30,
) -> List[Dict[str, Any]]:
    """
    Keep only items whose original language is in allowed_langs.
    - If 'original_language' is present on the item, use it.
    - If it's missing and try_enrich_missing=True, fetch TMDB details for up to max_enrich items to fill it.
    """
    allowed = _norm_langs(allowed_langs)
    if not allowed:
        return list(items)

    have_lang: List[Dict[str, Any]] = []
    missing_lang: List[Dict[str, Any]] = []

    for it in items:
        ol = (it.get("original_language") or "").strip().lower()
        if ol:
            have_lang.append(it)
        else:
            missing_lang.append(it)

    # Fast path: filter those with known language
    out: List[Dict[str, Any]] = [it for it in have_lang if (it.get("original_language", "").split("-")[0].split("_")[0].lower() in allowed)]

    # Optional enrichment (limited) for items missing language
    if try_enrich_missing and get_tv_details and missing_lang:
        # Only enrich a few to avoid slowdowns
        to_enrich = missing_lang[:max_enrich]
        for it in to_enrich:
            tid = it.get("tmdb_id") or it.get("id")
            try:
                tid = int(tid) if tid is not None else None
            except Exception:
                tid = None
            if not tid:
                continue
            try:
                d = await get_tv_details(tid)
                ol = (d.get("original_language") or "").strip().lower()
                if ol:
                    it["original_language"] = ol
                    if ol.split("-")[0].split("_")[0] in allowed:
                        out.append(it)
            except Exception:
                # swallow detail fetch failures
                pass

    return out

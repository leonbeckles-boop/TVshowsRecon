# app/services/tone_similarity.py
from __future__ import annotations
from typing import Iterable, List, Tuple
import math

TAG_UNIVERSE = [
    "gritty","dark","violent","crime","mystery","political","spy","hacker","satire",
    "funny","light","family","romance","teen","wholesome","feelgood",
    "sci-fi","fantasy","supernatural","post-apoc","space",
    "action","adventure","heist","thriller",
    "drama","soap","legal","medical",
    "anime","animation","documentary",
]

GENRE_TO_TAGS = {
    "Crime": ["crime","gritty","thriller"],
    "Drama": ["drama"],
    "Comedy": ["funny","light","feelgood"],
    "Sci-Fi & Fantasy": ["sci-fi","fantasy","adventure"],
    "Sci-Fi": ["sci-fi"],
    "Fantasy": ["fantasy","adventure"],
    "Mystery": ["mystery","thriller"],
    "Action & Adventure": ["action","adventure","thriller"],
    "Action": ["action"],
    "Adventure": ["adventure"],
    "Thriller": ["thriller","gritty"],
    "Horror": ["supernatural","dark"],
    "Family": ["family","feelgood"],
    "Romance": ["romance","feelgood"],
    "Animation": ["animation","family"],
    "Anime": ["anime","action"],
    "Documentary": ["documentary"],
    "War & Politics": ["political","drama"],
    "War": ["political","drama"],
    "Politics": ["political","drama"],
    "Soap": ["soap","drama"],
    "Mystery & Crime": ["mystery","crime","thriller"],
}

def _bag_to_vec(tags: Iterable[str]) -> List[float]:
    tagset = {t.lower().strip() for t in tags if t}
    return [1.0 if t in tagset else 0.0 for t in TAG_UNIVERSE]

def derive_tags(genres: Iterable[str] | None, keywords: Iterable[str] | None) -> List[str]:
    out = set()
    if genres:
        for g in genres:
            g = (g or "").strip()
            out.update(GENRE_TO_TAGS.get(g, []))
    if keywords:
        for k in keywords:
            k = (k or "").lower().strip()
            if k in TAG_UNIVERSE:
                out.add(k)
            if k.startswith("hack"): out.add("hacker")
            if k.startswith("spy"): out.add("spy")
            if k.startswith("politic"): out.add("political")
            if "post" in k and "apoc" in k: out.add("post-apoc")
    if not out and genres:
        if any(g for g in genres if "Comedy" in g):
            out.add("funny")
        else:
            out.add("drama")
    return sorted(out)

def cosine(a: List[float], b: List[float]) -> float:
    num = sum(x*y for x,y in zip(a,b))
    da = math.sqrt(sum(x*x for x in a))
    db = math.sqrt(sum(y*y for y in b))
    if da == 0 or db == 0:
        return 0.0
    return num/(da*db)

def mmr_select(
    candidates: List[Tuple[int, float, List[float]]],
    lambda_: float = 0.3,
    k: int = 30,
) -> List[Tuple[int, float]]:
    if not candidates:
        return []
    selected: List[Tuple[int, float, List[float]]] = []
    remaining = candidates.copy()
    max_s = max((s for _, s, _ in remaining), default=1.0) or 1.0
    norm = [(tid, (s/max_s), v) for tid, s, v in remaining]
    while norm and len(selected) < k:
        best = None
        best_val = -1e9
        for tid, rel, vec in norm:
            if selected:
                sim_max = max(cosine(vec, v2) for _, _, v2 in selected)
            else:
                sim_max = 0.0
            score = lambda_*rel - (1.0-lambda_)*sim_max
            if score > best_val:
                best_val = score
                best = (tid, rel, vec)
        selected.append(best)  # type: ignore[arg-type]
        norm = [(tid, rel, vec) for tid, rel, vec in norm if tid != best[0]]  # type: ignore[index]
    return [(tid, rel) for tid, rel, _ in selected]

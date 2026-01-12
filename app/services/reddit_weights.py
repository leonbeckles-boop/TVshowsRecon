# app/services/reddit_weights.py
# Updated 2025-10-12
from __future__ import annotations
from math import exp, log1p
from typing import Dict

SUB_WEIGHTS: Dict[str, float] = {
    "televisionsuggestions": 1.0,
    "television": 0.8,
    "tvDetails": 0.7,
    "netflix": 0.5,
}

HALF_LIFE_DAYS: float = 21.0
_LN2 = 0.6931471805599453

def time_decay(age_days: float) -> float:
    if age_days <= 0:
        return 1.0
    return exp(-_LN2 * (age_days / HALF_LIFE_DAYS))

def base_post_score(score: float | None, num_comments: float | None) -> float:
    s = float(score or 0.0)
    c = float(num_comments or 0.0)
    return 0.7 * log1p(max(0.0, s)) + 0.3 * log1p(max(0.0, c))

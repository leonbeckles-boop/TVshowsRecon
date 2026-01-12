# app/services/llm_extract.py
import os
import json
import time
from typing import List, Optional

# Using the OpenAI 1.x SDK
# pip install openai>=1.40
try:
    from openai import OpenAI
    _client = OpenAI()
except Exception as e:
    _client = None

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # replace with a higher model if you have access
OPENAI_RATE_DELAY = float(os.getenv("OPENAI_RATE_DELAY", "1.0"))  # seconds between calls

SYS_MSG = (
    "You are an information extractor. From the given Reddit text, return ONLY TV show titles "
    "that people mention or recommend. Exclude movies when you are reasonably sure. "
    "Return strict JSON: {\"titles\": [\"Title 1\", \"Title 2\", ...]}. "
    "Do not include commentary or extra keys."
)

USER_TEMPLATE = """Extract TV show titles from this text.

If you’re unsure whether something is a TV show or a movie, include it only if it is likely a TV show.

Text:
---
{chunk}
---
Optional hints (OP favourites / topic): {hints}
Return strict JSON: {{"titles": ["..."]}}"""

def _fallback_parse(text: str) -> List[str]:
    """Extremely conservative fallback: capitalized n-grams that look like titles."""
    import re
    # Title-ish: 1–6 tokens, starts capitalized, includes letters/numbers/&:'-
    cand = re.findall(r'\b([A-Z][\w&:\'-]+(?:\s+[A-Z][\w&:\'-]+){0,5})\b', text)
    # Light de-dupe & filter out common false positives
    blacklist = {"Thanks", "Some", "Characters", "Anything", "Shows", "So", "Need"}
    out = []
    seen = set()
    for c in cand:
        c2 = c.strip(" -:.'")
        if c2 in blacklist: 
            continue
        key = c2.lower()
        if key not in seen and len(c2) >= 3:
            seen.add(key)
            out.append(c2)
    return out[:20]

def _call_openai(chunk: str, hints: Optional[List[str]] = None) -> List[str]:
    if _client is None:
        return _fallback_parse(chunk)

    msg = USER_TEMPLATE.format(chunk=chunk[:7000], hints=", ".join(hints or []))
    for attempt in range(2):
        try:
            resp = _client.chat.completions.create(
                model=OPENAI_MODEL,
                temperature=0,
                messages=[
                    {"role": "system", "content": SYS_MSG},
                    {"role": "user", "content": msg}
                ]
            )
            content = resp.choices[0].message.content.strip()
            # Attempt JSON parse; if it’s fenced, strip fences
            if content.startswith("```"):
                content = content.strip("`")
                # remove possible leading language tag
                first_nl = content.find("\n")
                if first_nl != -1 and "{" not in content[:first_nl]:
                    content = content[first_nl+1:].strip()
            data = json.loads(content)
            titles = data.get("titles", [])
            # Normalize & dedupe
            seen = set()
            clean = []
            for t in titles:
                t2 = (t or "").strip()
                if t2 and t2.lower() not in seen:
                    seen.add(t2.lower())
                    clean.append(t2)
            return clean[:40]
        except Exception:
            time.sleep(OPENAI_RATE_DELAY)
    # Fallback if LLM fails
    return _fallback_parse(chunk)

def extract_titles(text: str, hints: Optional[List[str]] = None) -> List[str]:
    """Public helper: one-shot LLM extraction with fallback and dedupe."""
    titles = _call_openai(text, hints=hints)
    # Final tiny cleanup: remove lone punctuation
    titles = [t.strip(" -:.'") for t in titles if t.strip(" -:.'")]
    # Very light filtering of obvious non-titles
    drop = {"it", "my", "thanks", "anything", "some", "so"}
    return [t for t in titles if t.lower() not in drop][:40]

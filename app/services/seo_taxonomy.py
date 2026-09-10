"""WhatNextTV TV Taxonomy v2.7.4a; same-title anchor ambiguity bug-fix on top of the v2.7.4 edge-coverage taxonomy.

Hierarchical, metadata-driven, title-agnostic TV concept classification.

Design goals
------------
1. Classify the anchor into one or more broad families first.
2. Only score specialist concepts inside those plausible families.
3. Use hard gates for concepts whose meaning depends on genre/context.
4. Treat sparse TMDb metadata differently from contradictory evidence.
5. Prefer a well-supported low-density specialist over a generic fallback.
6. Never use show-title allowlists or title-specific tuning.

This module performs no network calls and is safe to run in shadow/debug mode.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping
import re


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def norm(v: Any) -> str:
    s = str(v or "").lower().strip()
    s = re.sub(r"[_/]+", " ", s)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+\-' ]+", " ", s)).strip()


def names(v: Any) -> list[str]:
    if not v:
        return []
    if isinstance(v, str):
        return [norm(v)]
    out: list[str] = []
    for x in v:
        n = x.get("name") if isinstance(x, Mapping) else x
        n = norm(n)
        if n and n not in out:
            out.append(n)
    return out


def blob(d: Mapping[str, Any]) -> str:
    vals = (
        names(d.get("seo_keywords"))
        + names(d.get("keywords"))
        + names(d.get("genres"))
    )
    if d.get("overview"):
        vals.append(norm(d["overview"]))
    return " | ".join(vals)


def gids(d: Mapping[str, Any]) -> set[int]:
    out: set[int] = set()
    for x in d.get("genre_ids") or []:
        try:
            out.add(int(x))
        except Exception:
            pass
    for x in d.get("genres") or []:
        if isinstance(x, Mapping) and x.get("id") is not None:
            try:
                out.add(int(x["id"]))
            except Exception:
                pass
    return out


def hit(text: str, term: str) -> bool:
    t = norm(term)
    if not t:
        return False
    if " " in t or len(t) >= 7:
        return t in text
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", text))


def hits(text: str, terms: Iterable[str]) -> list[str]:
    return [t for t in dict.fromkeys(map(norm, terms)) if t and hit(text, t)]


# TMDb genre IDs
DRAMA = 18
COMEDY = 35
CRIME = 80
MYSTERY = 9648
SCIFI = 10765  # TMDb combines Sci-Fi & Fantasy for TV
ACTION = 10759
ANIMATION = 16
FAMILY = 10751
WAR = 10768
WESTERN = 37


# ---------------------------------------------------------------------------
# Family layer
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FamilyProfile:
    genres: tuple[int, ...] = ()
    strong: tuple[str, ...] = ()
    supporting: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()


FAMILIES: dict[str, FamilyProfile] = {
    "crime": FamilyProfile(
        genres=(CRIME, MYSTERY),
        strong=(
            "detective", "murder investigation", "homicide", "serial killer",
            "criminal", "crime", "lawyer", "attorney", "courtroom", "police",
            "mafia", "gangster", "drug trafficking", "true crime",
        ),
        supporting=("investigation", "murder", "fbi", "trial", "justice", "profiling"),
    ),
    "mystery": FamilyProfile(
        genres=(MYSTERY,),
        strong=(
            "mystery", "conspiracy", "cover-up", "psychological thriller",
            "missing person", "disappearance", "trapped", "stranded",
        ),
        supporting=("secret", "investigation", "unknown", "survival", "identity", "reality"),
    ),
    "scifi": FamilyProfile(
        genres=(SCIFI,),
        strong=(
            "science fiction", "sci-fi", "space", "galaxy", "spaceship", "starship",
            "time travel", "dystopia", "dystopian", "post-apocalyptic", "post apocalypse",
            "post-apocalypse", "apocalypse", "artificial intelligence", "android", "robot",
            "alien", "extraterrestrial", "future", "alternate reality", "parallel universe",
            "nuclear apocalypse", "nuclear war", "vault", "clone", "cloning",
            "genetic engineering", "genetics", "biotechnology", "human experiment",
        ),
        supporting=("technology", "survival", "planet", "timeline", "simulation", "infection"),
        avoid=("period romance", "courtship"),
    ),
    "fantasy": FamilyProfile(
        genres=(SCIFI,),
        strong=(
            "fantasy", "dark fantasy", "magic", "wizard", "sorcery", "dragon",
            "supernatural", "ghost", "demon", "vampire", "werewolf", "superhero",
            "super power", "superpower", "witch", "monster",
        ),
        supporting=("kingdom", "quest", "curse", "occult", "hero", "villain"),
        avoid=("space travel", "spaceship", "starship", "galaxy"),
    ),
    "power": FamilyProfile(
        genres=(DRAMA, WAR),
        strong=(
            "politics", "political", "diplomat", "diplomacy", "ambassador",
            "foreign policy", "government", "president", "prime minister", "spy",
            "espionage", "mi5", "mi6", "cia", "finance", "banking", "investment",
            "hedge fund", "business empire", "media empire", "corporate empire",
            "conglomerate", "monarchy", "royalty", "royal family",
            "intelligence officer", "intelligence service", "security service",
            "counterterrorism", "counter-terrorism", "national security", "kgb",
            "bodyguard", "close protection", "protective detail",
        ),
        supporting=("power", "wealth", "executive", "corporate", "succession", "ambition"),
    ),
    "history": FamilyProfile(
        genres=(DRAMA, WAR),
        strong=(
            "historical", "period drama", "period piece", "regency", "georgian",
            "victorian", "world war", "world war ii", "world war i", "military",
            "based on true story", "historical figure", "disaster", "catastrophe",
        ),
        supporting=("war", "period", "palace", "society", "village", "tradition", "miniseries"),
    ),
    "workplace": FamilyProfile(
        genres=(DRAMA, COMEDY),
        strong=(
            "workplace", "workplace comedy", "office", "coworker", "coworkers",
            "colleague", "colleagues", "hospital", "doctor", "surgeon", "medical",
            "restaurant", "chef", "kitchen", "advertising agency", "profession",
            "newsroom", "journalism", "journalist", "news media", "technology company",
            "software company", "startup", "start-up", "computer industry",
        ),
        supporting=("career", "boss", "mentor", "teamwork", "job", "professional"),
    ),
    "comedy": FamilyProfile(
        genres=(COMEDY,),
        strong=(
            "comedy", "sitcom", "dark comedy", "black comedy", "satire",
            "mockumentary", "romantic comedy", "comedy drama",
        ),
        supporting=("humor", "humour", "funny", "dating", "friendship"),
    ),
    "relationships": FamilyProfile(
        genres=(DRAMA, COMEDY),
        strong=(
            "family relationships", "dysfunctional family", "family drama",
            "romance", "romantic relationship", "coming of age", "adolescence",
            "teenager", "teenage", "teen drama", "dating", "marriage",
        ),
        supporting=("family", "relationship", "love", "siblings", "parent", "friendship", "grief"),
    ),
}


def score_family(d: Mapping[str, Any], family: str) -> tuple[float, dict[str, Any]]:
    p = FAMILIES[family]
    b = blob(d)
    gs = gids(d)
    strong = hits(b, p.strong)
    supporting = hits(b, p.supporting)
    avoid = hits(b, p.avoid)
    genre_hits = sorted(gs.intersection(p.genres))

    # Strong lexical identity matters more than broad TMDb genres. This is
    # important because TV's 10765 combines science fiction and fantasy.
    score = min(0.62, 0.24 * len(strong))
    score += min(0.20, 0.05 * len(supporting))
    score += min(0.18, 0.09 * len(genre_hits))

    # A genre by itself may establish a broad family, but not dominate another
    # family with strong lexical evidence.
    if not strong and genre_hits:
        score = min(score, 0.24)

    if avoid:
        score *= max(0.30, 1.0 - 0.28 * len(avoid))

    return min(1.0, score), {
        "strong": strong,
        "supporting": supporting,
        "avoid": avoid,
        "genres": genre_hits,
    }


def rank_families(d: Mapping[str, Any]) -> tuple[dict[str, float], dict[str, dict[str, Any]]]:
    scores: dict[str, float] = {}
    evidence: dict[str, dict[str, Any]] = {}
    for family in FAMILIES:
        scores[family], evidence[family] = score_family(d, family)

    # Workplace words frequently describe the setting rather than the narrative
    # identity. When there is real speculative/mystery evidence, stop generic
    # office/workplace metadata from suppressing those families altogether.
    speculative_strength = max(
        scores.get("scifi", 0.0),
        scores.get("mystery", 0.0),
        scores.get("fantasy", 0.0),
    )
    if scores.get("workplace", 0.0) >= 0.45 and speculative_strength >= 0.30:
        scores["workplace"] *= 0.65
        evidence["workplace"]["context_dampened"] = True
        evidence["workplace"]["pre_dampen_score"] = round(scores["workplace"] / 0.65, 4)

    return scores, evidence


def eligible_families(
    family_scores: Mapping[str, float],
    *,
    max_families: int = 3,
    absolute_floor: float = 0.22,
    relative_margin: float = 0.16,
) -> list[str]:
    ranked = sorted(family_scores.items(), key=lambda x: x[1], reverse=True)
    if not ranked:
        return []
    best = ranked[0][1]
    if best <= 0:
        return []

    selected: list[str] = []
    for family, score in ranked:
        if len(selected) >= max_families:
            break
        if score >= absolute_floor and score >= best - relative_margin:
            selected.append(family)

    # If a single strong family wins, keep the specialist search focused, but
    # retain genuinely close secondary families. Hybrid series often have two
    # identities (e.g. relationship + power, fantasy + mystery).
    if best >= 0.62 and selected:
        selected = [selected[0]] + [f for f in selected[1:] if family_scores[f] >= best - 0.14]

    return selected[:max_families]


# ---------------------------------------------------------------------------
# Specialist concept layer
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Concept:
    family: str
    primary: tuple[str, ...] = ()
    supporting: tuple[str, ...] = ()
    genres: tuple[int, ...] = ()
    discovery: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    min_hits: int = 1

    # Hard gates. These determine whether the concept is even eligible.
    required_genres_any: tuple[int, ...] = ()
    required_genres_all: tuple[int, ...] = ()
    forbidden_genres: tuple[int, ...] = ()
    required_any: tuple[str, ...] = ()
    required_all: tuple[str, ...] = ()
    forbidden_any: tuple[str, ...] = ()

    # Specialist selection floor. Sparse metadata can still pass via relative
    # confidence, but very weak archetype evidence cannot.
    min_score: float = 0.38


def c(
    f: str,
    p=(),
    s=(),
    g=(),
    d=(),
    a=(),
    m: int = 1,
    *,
    rg_any=(),
    rg_all=(),
    fg=(),
    req_any=(),
    req_all=(),
    forbid=(),
    min_score: float = 0.38,
) -> Concept:
    return Concept(
        family=f,
        primary=tuple(p),
        supporting=tuple(s),
        genres=tuple(g),
        discovery=tuple(d or (tuple(p) + tuple(s))),
        avoid=tuple(a),
        min_hits=m,
        required_genres_any=tuple(rg_any),
        required_genres_all=tuple(rg_all),
        forbidden_genres=tuple(fg),
        required_any=tuple(req_any),
        required_all=tuple(req_all),
        forbidden_any=tuple(forbid),
        min_score=float(min_score),
    )


CONCEPTS: dict[str, Concept] = {
    # Crime & investigation
    "detective_mystery": c(
        "crime",
        ("detective", "consulting detective", "private detective", "sleuth", "murder investigation", "homicide"),
        ("investigation", "murder", "missing person", "cold case"),
        (CRIME, MYSTERY),
        req_any=("detective", "consulting detective", "private detective", "sleuth", "murder investigation", "homicide"),
    ),
    "psychological_crime": c(
        "crime",
        ("serial killer", "criminal profiler", "profiling"),
        ("psychological", "fbi", "behavioral", "behavioural", "interrogation"),
        (CRIME, MYSTERY),
    ),
    "crime_pressure": c(
        "crime",
        ("drug dealer", "drug trafficking", "money laundering", "criminal", "cartel"),
        ("moral dilemma", "double life", "violence", "corruption", "crime"),
        (CRIME, DRAMA),
        rg_any=(CRIME,),
    ),
    "crime_family_empire": c(
        "crime",
        ("organized crime", "organised crime", "mafia", "gangster", "criminal empire"),
        ("crime family", "mob", "family business"),
        (CRIME, DRAMA),
        rg_any=(CRIME,),
    ),
    "small_town_mystery": c(
        "crime",
        ("small town", "close-knit community", "small community"),
        ("murder", "missing person", "investigation", "mystery"),
        (CRIME, MYSTERY),
        m=2,
        req_any=("murder", "missing person", "investigation", "mystery", "crime"),
    ),
    "legal_crime_drama": c(
        "crime",
        ("lawyer", "attorney", "courtroom", "prosecutor", "law firm", "legal drama"),
        ("trial", "justice", "crime", "criminal", "cartel", "legal"),
        (DRAMA, CRIME),
        req_any=("lawyer", "attorney", "courtroom", "prosecutor", "law firm", "legal drama"),
    ),
    "police_procedural": c(
        "crime",
        ("police procedural", "police department", "homicide detective", "police station", "precinct"),
        ("police", "detective", "investigation", "case of the week"),
        (CRIME, DRAMA),
        req_any=("police procedural", "police department", "police station", "precinct", "homicide unit"),
    ),
    "true_crime_drama": c(
        "crime",
        ("true crime", "based on true crime"),
        ("based on true story", "murder", "investigation", "trial"),
        (CRIME, DRAMA),
        fg=(COMEDY,),
    ),

    # Mystery & thriller
    "mystery_box_survival": c(
        "mystery",
        ("survival", "trapped", "stranded", "cannot escape", "mysterious town", "small town", "supernatural mystery"),
        ("mystery", "unknown", "disappearance", "conspiracy", "supernatural", "monster", "government conspiracy"),
        (MYSTERY, SCIFI, DRAMA),
        m=2,
        req_any=("mystery", "unknown", "disappearance", "trapped", "stranded", "cannot escape", "mysterious town", "small town"),
        min_score=0.36,
    ),
    "prestige_existential_mystery": c(
        "mystery",
        ("existential", "psychological mystery", "memory loss", "surreal mystery"),
        ("identity", "surreal", "reality", "grief", "faith", "consciousness"),
        (MYSTERY, DRAMA),
        a=("sitcom", "dark comedy"),
    ),
    "conspiracy_thriller": c(
        "mystery",
        ("conspiracy", "cover-up", "secret organization", "secret organisation", "government conspiracy"),
        ("corruption", "surveillance", "investigation", "fbi", "government"),
        (MYSTERY, DRAMA),
        a=("supernatural", "monster", "ghost", "demon"),
    ),
    "domestic_psychological_thriller": c(
        "mystery",
        ("psychological thriller", "domestic thriller", "toxic relationship", "stalker"),
        ("marriage", "family secret", "manipulation", "obsession"),
        (DRAMA, MYSTERY),
    ),
    "comedy_mystery": c(
        "mystery",
        ("murder mystery", "amateur detective", "amateur sleuth", "comedy mystery", "whodunit", "podcast"),
        ("murder", "investigation", "comedy", "true crime", "sleuth"),
        (COMEDY, MYSTERY, CRIME),
        m=2,
        # Require both Comedy and Mystery so a generic podcast or crime show
        # cannot enter this concept merely because it mentions true crime.
        rg_all=(COMEDY, MYSTERY),
    ),

    # Science fiction
    "space_epic": c(
        "scifi",
        ("space", "outer space", "space travel", "spaceship", "starship", "galaxy", "galactic empire", "interstellar"),
        ("planet", "space opera", "civilization", "civilisation", "interplanetary", "colony", "psychohistory"),
        (SCIFI,),
        a=("memory loss", "amnesia"),
        m=2,
        rg_any=(SCIFI,),
        forbid=("superhero", "magic", "wizard"),
        min_score=0.36,
    ),
    "space_franchise_adventure": c(
        "scifi",
        ("space", "outer space", "spaceship", "starship", "space opera", "galaxy"),
        ("planet", "jedi", "bounty hunter", "rebellion", "crew", "space adventure"),
        (SCIFI, ACTION),
        a=("memory loss", "amnesia"),
        m=2,
        rg_any=(SCIFI,),
        req_any=("space adventure", "bounty hunter", "rebellion", "crew", "jedi", "mission", "space opera"),
        forbid=("superhero", "super power", "magic", "wizard"),
    ),
    "time_mystery": c(
        "scifi",
        ("time travel", "time loop", "time machine", "alternate timeline", "temporal loop"),
        ("timeline", "paradox", "future", "mystery"),
        (SCIFI, MYSTERY),
        rg_any=(SCIFI, MYSTERY),
    ),
    "technology_dystopia": c(
        "scifi",
        ("artificial intelligence", "virtual reality", "surveillance", "android", "robot", "simulation"),
        ("dystopia", "future", "technology", "algorithm"),
        (SCIFI,),
        m=2,
        rg_any=(SCIFI,),
    ),
    "contained_dystopia": c(
        "scifi",
        ("dystopia", "underground", "bunker", "vault", "enclosed community", "sealed community", "silo"),
        ("controlled society", "survival", "authoritarian", "rebellion", "surveillance"),
        (SCIFI, DRAMA),
        rg_any=(SCIFI,),
    ),
    "authoritarian_dystopia": c(
        "scifi",
        ("totalitarianism", "totalitarian", "tyranny", "authoritarian", "theocracy"),
        ("oppression", "dystopia", "slavery", "resistance", "regime"),
        (SCIFI, DRAMA),
        m=2,
    ),
    "post_apocalyptic_survival": c(
        "scifi",
        (
            "post-apocalyptic", "post apocalypse", "post-apocalypse", "apocalypse",
            "apocalyptic", "zombie apocalypse", "pandemic", "nuclear apocalypse",
            "nuclear war", "fallout shelter",
        ),
        ("survival", "collapse", "wasteland", "infection", "infected", "vault", "radiation"),
        (SCIFI, DRAMA),
        m=2,
        req_any=(
            "post-apocalyptic", "post apocalypse", "post-apocalypse",
            "apocalypse", "apocalyptic", "zombie apocalypse", "pandemic",
            "nuclear apocalypse", "nuclear war", "fallout shelter",
        ),
        min_score=0.36,
    ),
    "speculative_anthology": c(
        "scifi",
        ("anthology", "anthology series", "episodic anthology"),
        ("science fiction", "dystopia", "technology", "alternative reality"),
        (SCIFI,),
        a=("totalitarianism", "tyranny"),
        req_any=("anthology", "anthology series", "episodic anthology"),
    ),
    "corporate_mystery": c(
        "scifi",
        ("corporation", "corporate", "workplace", "office", "company"),
        ("memory", "identity", "secret experiment", "technology", "mystery", "consciousness"),
        (SCIFI, MYSTERY, DRAMA),
        m=2,
        rg_any=(SCIFI, MYSTERY),
        req_any=("memory", "identity", "secret experiment", "technology", "mystery", "consciousness", "dystopia"),
    ),
    "technology_conspiracy_thriller": c(
        "mystery",
        (
            "hacker", "cybersecurity", "cyber security", "cybercrime", "cyber crime",
            "surveillance", "techno thriller", "secret society", "artificial intelligence",
        ),
        (
            "conspiracy", "government agent", "vigilante", "psychological thriller",
            "identity", "corporation", "technology", "nature of reality",
        ),
        (MYSTERY, CRIME, SCIFI, DRAMA),
        m=2,
        req_any=(
            "hacker", "cybersecurity", "cyber security", "cybercrime", "cyber crime",
            "surveillance", "techno thriller", "secret society", "artificial intelligence",
        ),
        min_score=0.34,
    ),
    "space_identity_mystery": c(
        "scifi",
        ("memory loss", "amnesia", "space travel", "space opera", "android", "spaceship", "starship"),
        ("identity", "crew", "mystery", "experiment", "conspiracy", "future"),
        (SCIFI, MYSTERY),
        m=2,
        rg_any=(SCIFI,),
        req_any=("memory loss", "amnesia"),
        min_score=0.34,
    ),

    "alien_contact_invasion": c(
        "scifi",
        ("alien", "alien invasion", "extraterrestrial", "first contact", "ufo"),
        ("invasion", "humanity", "planet", "contact"),
        (SCIFI,),
        rg_any=(SCIFI,),
    ),

    # Fantasy, horror & superheroes
    "fantasy_quest_adventure": c(
        "fantasy",
        ("quest", "magic", "fantasy world", "wizard", "sorcery", "sorcerer"),
        ("kingdom", "chosen one", "adventure", "warrior", "monster"),
        (SCIFI, ACTION),
        req_any=("quest", "magic", "fantasy world", "wizard", "sorcery", "sorcerer"),
        forbid=("superhero", "space travel", "starship"),
    ),
    "dark_fantasy_power": c(
        "fantasy",
        ("dark fantasy", "fantasy", "magic", "dragon"),
        ("kingdom", "throne", "power struggle", "war", "betrayal", "succession"),
        (SCIFI, DRAMA),
        m=2,
        req_any=("dark fantasy", "magic", "dragon", "fantasy world", "kingdom", "throne"),
        forbid=("space travel", "spaceship", "starship", "galaxy"),
    ),
    "supernatural_horror": c(
        "fantasy",
        ("supernatural", "ghost", "demon", "haunting", "curse", "occult"),
        ("horror", "possession", "paranormal", "witch"),
        (SCIFI, MYSTERY),
        req_any=("supernatural", "ghost", "demon", "haunting", "curse", "occult", "paranormal"),
    ),
    "monster_survival_horror": c(
        "fantasy",
        ("monster", "creature", "zombie", "vampire"),
        ("survival", "trapped", "attack", "horror"),
        (SCIFI, ACTION),
        m=2,
        req_any=("survival", "trapped", "attack", "horror", "terror"),
        min_score=0.36,
    ),
    "supernatural_romance": c(
        "fantasy",
        ("vampire", "witch", "werewolf", "supernatural"),
        ("romance", "love", "relationship", "love triangle"),
        (SCIFI, DRAMA),
        m=2,
        req_any=("romance", "love", "relationship", "love triangle"),
    ),
    "fantasy_investigation": c(
        "fantasy",
        ("fantasy", "magic", "supernatural", "mythical creature", "fairy", "faerie"),
        ("detective", "investigation", "murder", "mystery", "police", "conspiracy"),
        (SCIFI, MYSTERY, CRIME),
        m=2,
        req_any=("detective", "investigation", "murder", "mystery", "police"),
        min_score=0.34,
    ),
    "historical_supernatural_horror": c(
        "fantasy",
        ("historical", "period", "expedition", "supernatural", "horror", "terror"),
        ("survival", "monster", "creature", "haunting", "isolated", "trapped", "ship"),
        (DRAMA, MYSTERY, SCIFI),
        m=2,
        req_any=("supernatural", "horror", "terror", "monster", "creature", "haunting"),
        min_score=0.34,
    ),
    "biotech_conspiracy": c(
        "scifi",
        ("clone", "cloning", "genetic engineering", "genetics", "biotechnology", "human experiment"),
        ("identity", "conspiracy", "corporation", "secret experiment", "scientist", "laboratory"),
        (SCIFI, MYSTERY, DRAMA),
        m=2,
        rg_any=(SCIFI, MYSTERY),
        req_any=("clone", "cloning", "genetic engineering", "genetics", "biotechnology", "human experiment"),
        min_score=0.34,
    ),

    "superhero_drama": c(
        "fantasy",
        ("superhero", "super power", "superpower", "superhero team", "vigilante"),
        ("based on comic", "secret identity", "hero", "villain"),
        (SCIFI, ACTION),
        req_any=("superhero", "super power", "superpower", "superhero team", "vigilante"),
    ),
    "superhero_satire": c(
        "fantasy",
        ("superhero", "super power", "superpower", "superhero team"),
        ("satire", "corruption", "evil corporation", "antihero", "dark comedy"),
        (SCIFI, ACTION, COMEDY),
        ("superhero", "super power", "superhero team", "based on comic", "antihero", "satire", "corruption", "evil corporation"),
        ("space opera", "starship"),
        2,
        req_any=("satire", "corruption", "evil corporation", "antihero", "dark comedy"),
    ),

    # Politics, money & institutional power
    "finance_power": c(
        "power",
        ("finance", "banking", "investment", "hedge fund", "wall street", "media empire", "business empire", "corporate empire", "conglomerate", "family business", "business dynasty"),
        ("business", "wealth", "money", "executive", "corporate", "succession", "inheritance", "ceo", "ownership"),
        (DRAMA,),
        a=("courtship", "regency"),
        req_any=("finance", "banking", "investment", "hedge fund", "wall street", "media empire", "business empire", "corporate empire", "conglomerate", "ceo", "family business"),
    ),
    "political_diplomatic_drama": c(
        "power",
        ("diplomacy", "diplomat", "ambassador", "foreign policy", "foreign affairs", "embassy"),
        ("government", "politics", "president", "prime minister", "international relations", "state department"),
        (WAR, DRAMA),
        req_any=("diplomacy", "diplomat", "ambassador", "foreign policy", "foreign affairs", "embassy", "state department"),
        min_score=0.34,
    ),
    "political_thriller": c(
        "power",
        ("political thriller", "government conspiracy", "political corruption", "assassination"),
        ("government", "president", "conspiracy", "fbi", "secret service"),
        (WAR, DRAMA, MYSTERY),
        m=2,
    ),
    "espionage_thriller": c(
        "power",
        (
            "spy", "espionage", "intelligence agency", "secret agent", "mi5", "mi6", "cia",
            "intelligence officer", "intelligence service", "security service", "counterintelligence",
            "counterterrorism", "counter-terrorism", "national security", "kgb",
            "bodyguard", "close protection", "protective detail",
        ),
        (
            "covert operation", "double agent", "undercover", "assassination", "terrorism",
            "government conspiracy", "cold war", "intelligence", "protective detail", "security",
        ),
        (DRAMA, ACTION),
        req_any=(
            "spy", "espionage", "intelligence agency", "secret agent", "mi5", "mi6", "cia",
            "intelligence officer", "intelligence service", "security service", "counterintelligence",
            "counterterrorism", "counter-terrorism", "national security", "kgb",
            "bodyguard", "close protection", "protective detail",
        ),
        min_score=0.34,
    ),
    "royal_historical_drama": c(
        "power",
        ("royal family", "monarchy", "royalty"),
        ("king", "queen", "palace", "crown", "succession"),
        (DRAMA, WAR),
    ),
    "period_power_drama": c(
        "power",
        ("period drama", "period piece", "historical", "feudal", "samurai"),
        ("power", "ambition", "wealth", "politics", "society", "class", "succession", "court intrigue"),
        (DRAMA,),
        a=("courtship", "romance"),
        m=2,
        req_any=("power", "ambition", "politics", "succession", "court intrigue", "feudal", "samurai", "war lord", "warlord"),
        min_score=0.36,
    ),

    # Historical
    "period_crime_noir": c(
        "history",
        (
            "period drama", "historical", "historical drama", "historical fiction",
            "neo-noir", "wild west", "gold rush", "1920s", "1930s",
        ),
        (
            "detective", "investigation", "sheriff", "outlaw", "crime", "gangster",
            "corruption", "police", "murder", "saloon", "mining town",
        ),
        (DRAMA, CRIME, MYSTERY, WESTERN),
        m=2,
        req_any=("neo-noir", "detective", "sheriff", "outlaw", "crime", "gangster", "wild west"),
        min_score=0.34,
    ),
    "historical_adventure": c(
        "history",
        ("pirate", "swashbuckler", "historical fiction", "period drama", "naval", "seafaring"),
        ("adventure", "ship", "treasure", "war", "colonial", "historical", "empire"),
        (DRAMA, ACTION, WAR),
        m=2,
        req_any=("pirate", "swashbuckler", "naval", "seafaring"),
        min_score=0.34,
    ),

    "historical_disaster": c(
        "history",
        ("disaster", "catastrophe", "nuclear catastrophe", "industrial disaster"),
        ("based on true story", "historical", "miniseries", "institutional failure"),
        (DRAMA,),
        ("disaster", "catastrophe", "nuclear catastrophe", "based on true story", "miniseries", "industrial disaster"),
        m=2,
    ),
    "historical_war": c(
        "history",
        ("world war", "world war ii", "world war i", "military", "soldier", "army", "battle", "combat"),
        ("war", "historical", "wartime"),
        (WAR, DRAMA),
        req_any=("world war", "world war ii", "world war i", "military", "soldier", "army", "battle", "combat"),
    ),
    "historical_true_story": c(
        "history",
        ("based on true story", "biography", "historical figure", "real events"),
        ("historical", "miniseries", "true story", "period piece"),
        (DRAMA,),
        a=("disaster", "catastrophe", "world war", "military"),
    ),
    "period_community": c(
        "history",
        ("period drama", "period piece", "historical", "period"),
        ("community", "family", "village", "small town", "tradition", "estate", "household"),
        (DRAMA,),
        m=2,
        req_any=("community", "family", "village", "small town", "tradition", "estate", "household", "society"),
        min_score=0.34,
    ),
    "period_professional_drama": c(
        "history",
        ("period drama", "period piece", "historical"),
        ("workplace", "profession", "office", "hospital", "advertising", "business", "career"),
        (DRAMA,),
        m=2,
        req_any=("workplace", "profession", "office", "hospital", "advertising", "business", "career"),
    ),
    "period_romance_society": c(
        "history",
        ("period drama", "period piece", "regency", "georgian", "victorian"),
        ("romance", "courtship", "marriage", "love", "society", "class"),
        (DRAMA,),
        ("period drama", "period piece", "romance", "courtship", "marriage", "regency", "georgian", "victorian", "high society"),
        m=2,
        req_any=("romance", "courtship", "marriage", "love", "regency", "georgian"),
    ),

    # Workplace / professional
    "workplace_character_drama": c(
        "workplace",
        ("workplace", "office", "profession", "working life", "career"),
        ("colleagues", "coworkers", "mentor", "ambition"),
        (DRAMA,),
        a=("workplace comedy", "sitcom"),
        rg_any=(DRAMA,),
        forbid=("hospital", "doctor", "medical", "surgeon", "emergency room", "restaurant", "chef", "kitchen"),
    ),
    "media_professional_drama": c(
        "workplace",
        ("newsroom", "journalism", "journalist", "news anchor", "news media", "television news", "media company"),
        ("workplace", "career", "editor", "producer", "reporter", "broadcasting", "politics"),
        (DRAMA,),
        rg_any=(DRAMA,),
        req_any=("newsroom", "journalism", "journalist", "news anchor", "news media", "television news", "media company"),
        min_score=0.34,
    ),
    "technology_business_drama": c(
        "workplace",
        ("technology company", "software company", "computer industry", "startup", "start-up", "entrepreneur",
         "computer technology", "personal computer", "computer programmer", "software industry"),
        ("business", "innovation", "engineer", "programmer", "computer", "workplace", "career", "technology"),
        (DRAMA,),
        rg_any=(DRAMA,),
        req_any=("technology company", "software company", "computer industry", "startup", "start-up", "entrepreneur",
                 "computer", "computer technology", "personal computer", "computer programmer"),
        min_score=0.34,
    ),
    "technology_workplace_comedy": c(
        "workplace",
        ("technology company", "software company", "startup", "start-up", "programmer", "software developer",
         "computer programmer", "computer technology", "software industry"),
        ("office", "workplace", "entrepreneur", "engineer", "computer", "coworkers", "business", "innovation"),
        (COMEDY,),
        rg_any=(COMEDY,),
        req_any=("technology company", "software company", "startup", "start-up", "programmer", "software developer",
                 "computer", "computer programmer", "computer technology"),
        min_score=0.34,
    ),

    "creative_industry_comedy_drama": c(
        "comedy",
        (
            "entertainment industry", "show business", "television industry", "music industry",
            "hip-hop", "hip hop", "rapper", "comedian", "stand-up comedy", "stand up comedy",
        ),
        (
            "writer", "performer", "artist", "celebrity", "career", "manager",
            "generational divide", "comedy drama", "satire",
        ),
        (COMEDY, DRAMA),
        rg_any=(COMEDY,),
        req_any=(
            "entertainment industry", "show business", "television industry", "music industry",
            "hip-hop", "hip hop", "rapper", "comedian", "stand-up comedy", "stand up comedy",
        ),
        min_score=0.34,
    ),

    "warm_workplace_comedy": c(
        "workplace",
        ("workplace comedy", "workplace", "office", "coworkers", "colleagues"),
        ("comedy", "sitcom", "friendship", "community", "teamwork", "mentor", "joyful", "team", "coach", "school", "restaurant"),
        (COMEDY,),
        m=2,
        rg_any=(COMEDY,),
        req_any=("workplace comedy", "workplace", "office", "coworkers", "colleagues", "profession", "job"),
    ),
    "workplace_satire": c(
        "workplace",
        ("workplace comedy", "workplace", "office", "corporate"),
        ("satire", "mockumentary", "boss", "coworkers"),
        (COMEDY,),
        m=2,
        rg_any=(COMEDY,),
        req_any=("satire", "mockumentary", "workplace comedy"),
    ),
    "medical_institutional_drama": c(
        "workplace",
        (
            "pharmaceutical industry", "pharmaceuticals", "public health", "medical drama",
            "drug epidemic", "opioid epidemic", "opioids", "medicine", "medical research",
        ),
        (
            "historical fiction", "period drama", "hospital", "doctor", "surgeon", "healthcare",
            "addiction", "corporate crime", "government corruption", "criminal investigation",
        ),
        (DRAMA,),
        m=2,
        rg_any=(DRAMA,),
        req_any=(
            "pharmaceutical industry", "pharmaceuticals", "public health", "drug epidemic",
            "opioid epidemic", "opioids", "historical fiction", "period drama",
        ),
        min_score=0.34,
    ),

    "medical_professional": c(
        "workplace",
        ("hospital", "doctor", "medical", "emergency room", "surgeon", "medicine", "healthcare"),
        ("nurse", "patient", "residency", "emergency department"),
        (DRAMA,),
        rg_any=(DRAMA,),
        min_score=0.34,
    ),
    "medical_family": c(
        "workplace",
        ("hospital", "doctor", "medical", "surgeon", "nurse", "midwife"),
        ("family", "marriage", "relationship", "parent", "grief", "community"),
        (DRAMA,),
        m=2,
        rg_any=(DRAMA,),
        req_any=("family", "marriage", "relationship", "parent", "grief", "community", "maternity", "midwife"),
    ),
    "restaurant_hospitality_drama": c(
        "workplace",
        ("restaurant", "chef", "kitchen", "food industry", "hospitality", "culinary"),
        ("family business", "workplace", "pressure", "team", "cooking"),
        (DRAMA, COMEDY),
        rg_any=(DRAMA, COMEDY),
        min_score=0.34,
    ),

    # Comedy
    "dark_character_comedy": c(
        "comedy",
        ("dark comedy", "black comedy", "cynicism", "tragicomedy"),
        ("sitcom", "comedy", "grief", "loneliness", "dysfunctional family", "guilt"),
        (COMEDY, DRAMA),
        ("dark comedy", "black comedy", "grief", "loneliness", "dysfunctional family", "sitcom"),
        m=2,
        rg_any=(COMEDY,),
    ),
    "social_satire": c(
        "comedy",
        ("satire", "social satire", "social commentary"),
        ("wealth", "class", "society", "privilege", "social class", "elite"),
        (COMEDY, DRAMA),
        a=("superhero",),
        req_any=("satire", "social satire", "social commentary"),
        min_score=0.34,
    ),
    "relationship_comedy": c(
        "comedy",
        ("romantic comedy", "dating", "relationship", "romance"),
        ("friendship", "love", "sex", "marriage"),
        (COMEDY,),
        rg_any=(COMEDY,),
    ),
    "family_sitcom": c(
        "comedy",
        ("sitcom", "family comedy"),
        ("family", "parent", "children", "siblings", "parenting"),
        (COMEDY, FAMILY),
        m=2,
        rg_any=(COMEDY,),
        req_any=("family", "parent", "children", "siblings", "parenting"),
    ),
    "adult_animated_satire": c(
        "comedy",
        ("adult animation", "animated sitcom"),
        ("satire", "sitcom", "comedy", "dark comedy"),
        (ANIMATION, COMEDY),
        m=2,
        rg_all=(ANIMATION, COMEDY),
    ),
    "coming_of_age_comedy": c(
        "comedy",
        ("coming of age", "teenager", "teenage", "adolescence", "high school", "school life"),
        ("comedy", "sitcom", "friendship", "school", "dating"),
        (COMEDY, DRAMA),
        m=2,
        rg_any=(COMEDY,),
    ),

    # Relationships / family
    "family_character_drama": c(
        "relationships",
        ("family relationships", "dysfunctional family", "family drama", "family"),
        ("grief", "siblings", "parent", "marriage", "generational"),
        (DRAMA,),
        rg_any=(DRAMA,),
        req_any=("family relationships", "dysfunctional family", "family drama", "siblings", "parent", "generational", "family"),
        a=("family business", "business empire", "media empire", "corporate empire", "conglomerate", "ceo"),
        min_score=0.34,
    ),
    "romantic_drama": c(
        "relationships",
        ("romance", "love", "romantic relationship", "love story"),
        ("marriage", "relationship", "love triangle", "dating"),
        (DRAMA,),
        a=("period drama", "regency"),
        rg_any=(DRAMA,),
    ),
    "coming_of_age_drama": c(
        "relationships",
        ("coming of age", "adolescence", "teenager", "teenage", "youth"),
        ("identity", "school", "friendship", "family"),
        (DRAMA,),
        rg_any=(DRAMA,),
        min_score=0.34,
    ),
    "teen_relationship_drama": c(
        "relationships",
        ("teenager", "teenage", "high school", "teen drama", "school life"),
        ("romance", "relationship", "friendship", "school", "first love", "sex"),
        (DRAMA,),
        m=2,
        rg_any=(DRAMA,),
        min_score=0.34,
    ),
}

FALLBACKS = {"general_drama", "general_comedy", "general_scifi"}


@dataclass
class Classification:
    concept: str
    family: str
    confidence: float
    state: str
    scores: dict[str, float] = field(default_factory=dict)
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    family_scores: dict[str, float] = field(default_factory=dict)
    family_evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    eligible_families: list[str] = field(default_factory=list)

    def debug_dict(self, n: int = 6) -> dict[str, Any]:
        top = sorted(self.scores.items(), key=lambda x: x[1], reverse=True)[:n]
        top_families = sorted(self.family_scores.items(), key=lambda x: x[1], reverse=True)[:5]
        return {
            "concept": self.concept,
            "family": self.family,
            "confidence": round(self.confidence, 4),
            "state": self.state,
            "eligible_families": self.eligible_families,
            "families": [
                {
                    "family": k,
                    "score": round(v, 4),
                    **self.family_evidence.get(k, {}),
                }
                for k, v in top_families
            ],
            "top": [
                {
                    "concept": k,
                    "score": round(v, 4),
                    **self.evidence.get(k, {}),
                }
                for k, v in top
            ],
        }


def _gate_concept(d: Mapping[str, Any], x: Concept) -> tuple[bool, dict[str, Any]]:
    b = blob(d)
    gs = gids(d)

    req_any_hits = hits(b, x.required_any)
    req_all_hits = hits(b, x.required_all)
    forbidden_hits = hits(b, x.forbidden_any)

    if x.required_genres_any and not gs.intersection(x.required_genres_any):
        return False, {"gate": "required_genres_any", "required_genres_any": list(x.required_genres_any)}
    if x.required_genres_all and not set(x.required_genres_all).issubset(gs):
        return False, {"gate": "required_genres_all", "required_genres_all": list(x.required_genres_all)}
    if x.forbidden_genres and gs.intersection(x.forbidden_genres):
        return False, {"gate": "forbidden_genres", "forbidden_genres": sorted(gs.intersection(x.forbidden_genres))}
    if x.required_any and not req_any_hits:
        return False, {"gate": "required_any", "required_any": list(x.required_any)}
    if x.required_all and len(req_all_hits) < len(set(map(norm, x.required_all))):
        return False, {"gate": "required_all", "required_all": list(x.required_all), "required_all_hits": req_all_hits}
    if forbidden_hits:
        return False, {"gate": "forbidden_any", "forbidden": forbidden_hits}

    return True, {
        "required_any_hits": req_any_hits,
        "required_all_hits": req_all_hits,
    }


def score_concept(d: Mapping[str, Any], x: Concept) -> tuple[float, dict[str, Any]]:
    b = blob(d)
    gs = gids(d)
    p = hits(b, x.primary)
    s = hits(b, x.supporting)
    a = hits(b, x.avoid)
    gh = sorted(gs.intersection(x.genres))

    gate_ok, gate_ev = _gate_concept(d, x)
    ev: dict[str, Any] = {
        "primary": p,
        "supporting": s,
        "avoid": a,
        "genres": gh,
        "gate_ok": gate_ok,
        **gate_ev,
    }

    if not gate_ok:
        return 0.0, ev

    # A specialist must contain defining lexical evidence. Broad TMDb genres can
    # help confidence, but they cannot manufacture an archetype by themselves.
    if not p or len(p) + len(s) < x.min_hits:
        return 0.0, ev

    score = min(0.60, 0.30 * len(p))
    score += min(0.26, 0.065 * len(s))
    score += min(0.10, 0.05 * len(gh))

    # Meeting an explicit semantic gate is stronger than merely matching a
    # generic primary word.
    if gate_ev.get("required_any_hits"):
        score += min(0.08, 0.04 * len(gate_ev["required_any_hits"]))
    if gate_ev.get("required_all_hits"):
        score += 0.06

    if a:
        score *= max(0.18, 1.0 - 0.32 * len(a))

    return min(1.0, score), ev


def fallback(d: Mapping[str, Any], family_scores: Mapping[str, float] | None = None) -> tuple[str, str]:
    gs = gids(d)
    fs = family_scores or {}

    # Strong lexical family evidence beats ambiguous TMDb genre overlap.
    scifi_strength = fs.get("scifi", 0.0)
    comedy_strength = fs.get("comedy", 0.0)
    relationship_strength = fs.get("relationships", 0.0)

    if scifi_strength >= 0.34 or (SCIFI in gs and scifi_strength >= max(comedy_strength, relationship_strength)):
        return "general_scifi", "scifi"
    if comedy_strength >= 0.34 or COMEDY in gs:
        return "general_comedy", "comedy"
    return "general_drama", "relationships"


def _specialist_confidence(
    best_score: float,
    second_score: float,
    best_ev: Mapping[str, Any],
    family_score: float,
) -> float:
    gap = max(0.0, best_score - second_score)
    primary_n = len(best_ev.get("primary") or [])
    support_n = len(best_ev.get("supporting") or [])
    gate_bonus = 0.05 if best_ev.get("required_any_hits") or best_ev.get("required_all_hits") else 0.0

    # Confidence combines absolute evidence, separation from nearby concepts,
    # archetype density and the strength of the winning broad family.
    confidence = 0.68 * best_score
    confidence += min(0.14, 0.70 * gap)
    confidence += min(0.08, 0.025 * primary_n + 0.012 * support_n)
    confidence += min(0.08, 0.10 * family_score)
    confidence += gate_bonus
    return min(1.0, confidence)



def _specialist_challenge_candidates(
    d: Mapping[str, Any],
    family_scores: Mapping[str, float],
    eligible: Iterable[str],
) -> list[tuple[str, float, dict[str, Any]]]:
    """Find unusually strong specialists outside the initially eligible families.

    The family layer is intentionally broad. A distinctive combination of
    specialist evidence can therefore be more informative than generic family
    words such as "period", "detective", "drama" or "comedy". This pass is
    deliberately conservative: it requires multiple defining lexical signals,
    a passed hard gate, and a high absolute specialist score. It contains no
    show-title mappings or exceptions.
    """
    eligible_set = set(eligible)
    out: list[tuple[str, float, dict[str, Any]]] = []

    for name, x in CONCEPTS.items():
        if x.family in eligible_set:
            continue

        score, ev = score_concept(d, x)
        if score <= 0.0 or not ev.get("gate_ok"):
            continue

        primary_n = len(ev.get("primary") or [])
        support_n = len(ev.get("supporting") or [])
        gate_n = len(ev.get("required_any_hits") or []) + len(ev.get("required_all_hits") or [])

        # Distinctive specialists need at least two defining primary signals,
        # or one primary plus a dense body of supporting/gate evidence.
        distinctive = primary_n >= 2 or (primary_n >= 1 and support_n >= 2 and gate_n >= 1)
        if not distinctive:
            continue

        # Require strong absolute concept evidence. A slightly lower threshold
        # is allowed when three or more primary signals independently agree.
        floor = 0.68 if primary_n < 3 else 0.62
        if score < max(x.min_score, floor):
            continue

        # Avoid letting a tiny off-family hint overturn a genuinely dominant
        # family. Strong specialist evidence can still challenge when its own
        # family has some lexical support, or when the concept evidence is very
        # dense by itself.
        own_family = float(family_scores.get(x.family, 0.0) or 0.0)
        best_family = max([float(v or 0.0) for v in family_scores.values()] or [0.0])
        if own_family < 0.18 and primary_n < 3:
            continue
        if best_family >= 0.72 and own_family < (best_family - 0.40) and primary_n < 3:
            continue

        ev = dict(ev)
        ev["specialist_challenge"] = True
        ev["challenge_family_score"] = round(own_family, 4)
        ev["challenge_best_family_score"] = round(best_family, 4)
        out.append((name, score, ev))

    return sorted(out, key=lambda z: z[1], reverse=True)


def classify_anchor(
    d: Mapping[str, Any],
    *,
    family_floor: float = 0.22,
    family_margin: float = 0.16,
    strong_specialist_score: float = 0.64,
    relative_specialist_score: float = 0.38,
    relative_gap: float = 0.08,
) -> Classification:
    family_scores, family_evidence = rank_families(d)
    families = eligible_families(
        family_scores,
        absolute_floor=family_floor,
        relative_margin=family_margin,
    )

    # V2.2: Comedy + Mystery is a meaningful hybrid identity in its own right.
    # Literal crime vocabulary (especially "true crime") can otherwise make
    # crime dominate the family layer even when the show is a fictional comic
    # mystery. Keep comedy and mystery eligible when TMDb supplies both genres.
    gs = gids(d)
    if COMEDY in gs and MYSTERY in gs:
        for hybrid_family in ("mystery", "comedy"):
            if hybrid_family not in families:
                families.append(hybrid_family)
        families = list(dict.fromkeys(families))[:3]

    # If family metadata is extremely sparse, use genres to choose broad family
    # candidates rather than opening every specialist concept globally.
    if not families:
        gs = gids(d)
        if SCIFI in gs:
            families.append("scifi")
        if COMEDY in gs:
            families.append("comedy")
        if CRIME in gs or MYSTERY in gs:
            families.append("crime")
        if DRAMA in gs:
            families.append("relationships")
        families = list(dict.fromkeys(families))[:3]

    scores: dict[str, float] = {}
    evidence: dict[str, dict[str, Any]] = {}

    for name, x in CONCEPTS.items():
        if x.family not in families:
            scores[name] = 0.0
            evidence[name] = {
                "primary": [],
                "supporting": [],
                "avoid": [],
                "genres": [],
                "gate_ok": False,
                "gate": "family_not_eligible",
            }
            continue
        scores[name], evidence[name] = score_concept(d, x)

    # V2.7.3: allow a very strong specialist outside the initially selected
    # family set to challenge generic family precedence. This addresses hybrid
    # shows where broad words such as period/detective/comedy are less
    # informative than a dense specialist fingerprint.
    challenges = _specialist_challenge_candidates(d, family_scores, families)
    if challenges:
        current_best = max(scores.values() or [0.0])
        challenger_name, challenger_score, challenger_ev = challenges[0]

        # The challenger must either beat the current specialist outright or
        # be extremely strong and within a narrow margin. No title-specific
        # exceptions are used.
        if challenger_score >= current_best + 0.04 or (
            challenger_score >= 0.82 and challenger_score >= current_best - 0.04
        ):
            challenger_family = CONCEPTS[challenger_name].family
            if challenger_family not in families:
                families.append(challenger_family)
            scores[challenger_name] = challenger_score
            evidence[challenger_name] = challenger_ev

    ranked = sorted(scores.items(), key=lambda z: z[1], reverse=True)
    best, best_score = ranked[0] if ranked else ("", 0.0)
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    gap = best_score - second_score

    if best and best in CONCEPTS:
        x = CONCEPTS[best]
        ev = evidence.get(best, {})
        fam_score = family_scores.get(x.family, 0.0)
        confidence = _specialist_confidence(best_score, second_score, ev, fam_score)

        primary_n = len(ev.get("primary") or [])
        support_n = len(ev.get("supporting") or [])
        dense_evidence = primary_n >= 2 or (primary_n >= 1 and support_n >= 2)
        concept_floor = max(relative_specialist_score, x.min_score)

        # Route A: strong absolute archetype evidence.
        strong_accept = best_score >= max(strong_specialist_score, x.min_score)

        # Route B: sparse metadata, but the concept is clearly the best eligible
        # specialist and passes all hard gates.
        relative_accept = (
            best_score >= concept_floor
            and (
                gap >= relative_gap
                or dense_evidence
                or (second_score == 0.0 and primary_n >= 1)
            )
        )

        # Near ties inside the same family can still be legitimate when the top
        # concept has substantially denser defining evidence.
        if not relative_accept and best_score >= concept_floor and dense_evidence:
            relative_accept = True

        if strong_accept or relative_accept:
            state = "specialist" if best_score >= strong_specialist_score else "specialist_sparse_metadata"
            return Classification(
                best,
                x.family,
                confidence,
                state,
                scores,
                evidence,
                family_scores,
                family_evidence,
                families,
            )

    fb, fam = fallback(d, family_scores)
    confidence = 0.0
    if best and best in CONCEPTS:
        confidence = _specialist_confidence(
            best_score,
            second_score,
            evidence.get(best, {}),
            family_scores.get(CONCEPTS[best].family, 0.0),
        )

    return Classification(
        fb,
        fam,
        confidence,
        "general_fallback",
        scores,
        evidence,
        family_scores,
        family_evidence,
        families,
    )


# ---------------------------------------------------------------------------
# Concept affinity
# ---------------------------------------------------------------------------

def _concept_term_set(x: Concept) -> set[str]:
    """Reusable semantic vocabulary describing a specialist concept."""
    return {
        norm(term)
        for term in (
            tuple(x.primary)
            + tuple(x.supporting)
            + tuple(x.required_any)
            + tuple(x.required_all)
            + tuple(x.discovery)
        )
        if norm(term)
    }


def concept_affinity(anchor_concept: str, candidate_concept: str | None) -> float:
    """Structural similarity between two taxonomy concepts.

    This is entirely taxonomy-driven: no show-title mappings or exceptions.
    """
    if not candidate_concept:
        return 0.0
    if anchor_concept == candidate_concept:
        return 1.0

    anchor = CONCEPTS.get(anchor_concept)
    candidate = CONCEPTS.get(candidate_concept)
    if not anchor or not candidate or anchor.family != candidate.family:
        return 0.0

    anchor_core = {
        norm(t)
        for t in tuple(anchor.primary) + tuple(anchor.required_any) + tuple(anchor.required_all)
        if norm(t)
    }
    candidate_core = {
        norm(t)
        for t in tuple(candidate.primary) + tuple(candidate.required_any) + tuple(candidate.required_all)
        if norm(t)
    }
    anchor_all = _concept_term_set(anchor)
    candidate_all = _concept_term_set(candidate)

    core_union = anchor_core | candidate_core
    core_jaccard = len(anchor_core & candidate_core) / len(core_union) if core_union else 0.0

    bridge_den = max(1, min(len(anchor_core), len(candidate_core)))
    bridge_overlap = len(
        (anchor_core & candidate_all) | (candidate_core & anchor_all)
    ) / bridge_den
    bridge_overlap = min(1.0, bridge_overlap)

    all_union = anchor_all | candidate_all
    vocabulary_jaccard = len(anchor_all & candidate_all) / len(all_union) if all_union else 0.0

    anchor_genres = {int(g) for g in anchor.genres}
    candidate_genres = {int(g) for g in candidate.genres}
    genre_union = anchor_genres | candidate_genres
    genre_jaccard = len(anchor_genres & candidate_genres) / len(genre_union) if genre_union else 0.0

    affinity = 0.15
    affinity += 0.30 * core_jaccard
    affinity += 0.30 * bridge_overlap
    affinity += 0.15 * vocabulary_jaccard
    affinity += 0.10 * genre_jaccard

    return round(min(0.88, max(0.15, affinity)), 4)


# ---------------------------------------------------------------------------
# Candidate fit / discovery API
# ---------------------------------------------------------------------------

@dataclass
class CandidateFit:
    passed: bool
    score: float
    multiplier: float
    primary: list[str] = field(default_factory=list)
    supporting: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    gate_reason: str | None = None
    tier: str = "none"
    candidate_concept: str | None = None
    candidate_family: str | None = None
    affinity: float = 1.0


def candidate_fit(
    d: Mapping[str, Any],
    concept: str,
    strict: bool = True,
    *,
    semantic_score: float = 0.0,
    genre_score: float = 0.0,
) -> CandidateFit:
    """Grade candidate relevance to a taxonomy concept.

    V2.3 keeps hard safety/exclusion gates, but avoids treating sparse TMDb
    keyword metadata as a binary pass/fail. Candidates can qualify as:
      strong - direct specialist evidence
      good   - same specialist/family with useful evidence
      broad  - same taxonomy family plus meaningful semantic overlap

    The anchor classifier is not changed by this function.
    """
    if concept in FALLBACKS or concept not in CONCEPTS:
        return CandidateFit(True, 0.0, 1.0, tier="fallback")

    x = CONCEPTS[concept]
    b = blob(d)
    gs = gids(d)

    # Candidate detail metadata can be sparse even when TMDb discovery found
    # the show through a highly relevant concept keyword. Preserve that
    # discovery evidence on the candidate and use it here as additional,
    # auditable concept evidence.
    semantic_terms = [
        str(v).strip().lower()
        for v in (d.get("_seo_taxonomy_matched_terms") or [])
        if str(v).strip()
    ]
    semantic_blob = " ".join(semantic_terms)

    p = list(dict.fromkeys(
        hits(b, x.primary) + hits(semantic_blob, x.primary)
    ))
    s = list(dict.fromkeys(
        hits(b, x.supporting) + hits(semantic_blob, x.supporting)
    ))
    a = hits(b, x.avoid)
    genre_hits = sorted(gs.intersection(x.genres))

    semantic_required_hits = hits(semantic_blob, x.required_any)

    gate_ok, gate_ev = _gate_concept(d, x)
    gate_reason = str(gate_ev.get("gate") or "") if not gate_ok else None

    # A missing TMDb keyword on the detail endpoint should not fail a
    # required-any gate when this exact candidate was discovered through that
    # same required taxonomy term. Explicit genre/forbidden gates remain hard.
    if (
        not gate_ok
        and gate_reason == "required_any"
        and semantic_required_hits
    ):
        gate_ok = True
        gate_reason = None
        gate_ev = {
            "required_any_hits": semantic_required_hits,
            "required_all_hits": [],
            "gate_source": "semantic_discovery",
        }

    # These remain genuinely hard gates. A broad-family rescue must never
    # override explicit exclusions or a required genre identity.
    hard_gate_reasons = {
        "required_genres_any",
        "required_genres_all",
        "forbidden_genres",
        "required_all",
        "forbidden_any",
    }
    if not gate_ok and gate_reason in hard_gate_reasons:
        return CandidateFit(
            False, 0.0, 1.0, p, s, a, gate_reason,
            tier="rejected_hard_gate",
        )

    if strict and (not gate_ok or not p):
        return CandidateFit(
            False, 0.0, 1.0, p, s, a,
            gate_reason or "no_primary_evidence",
            tier="rejected_strict",
        )

    mult = max(0.25, 1.0 - 0.28 * len(a)) if a else 1.0

    # Direct specialist evidence remains the strongest route.
    if gate_ok and p:
        score = min(0.52, 0.18 * len(p))
        score += min(0.20, 0.05 * len(s))
        score += min(0.08, 0.04 * len(genre_hits))
        if gate_ev.get("required_any_hits"):
            score += min(0.08, 0.04 * len(gate_ev["required_any_hits"]))
        return CandidateFit(
            True, min(0.85, score), mult, p, s, a,
            tier="strong",
            candidate_concept=concept,
            candidate_family=x.family,
        )

    # For sparse candidate metadata, classify the candidate independently.
    # This prevents a broad genre match from admitting an unrelated family.
    candidate_class = classify_anchor(d)
    same_concept = candidate_class.concept == concept
    same_family = candidate_class.family == x.family

    if same_concept:
        score = 0.24
        score += min(0.18, 0.18 * float(candidate_class.confidence))
        score += min(0.12, 0.30 * max(0.0, float(semantic_score)))
        score += min(0.08, 0.08 * max(0.0, float(genre_score)))
        score += min(0.08, 0.04 * len(s))
        return CandidateFit(
            True, min(0.68, score), mult, p, s, a, gate_reason,
            tier="good",
            candidate_concept=candidate_class.concept,
            candidate_family=candidate_class.family,
            affinity=1.0,
        )

    # A related specialist in the same family can still be a useful neighbour,
    # but only when the current anchor/candidate comparison supplies meaningful
    # semantic evidence. This is deliberately weaker than a direct concept hit.
    if same_family:
        sem = max(0.0, float(semantic_score))
        gen = max(0.0, float(genre_score))
        affinity = concept_affinity(concept, candidate_class.concept)

        if s and (sem >= 0.10 or gen >= 0.45):
            raw_score = 0.12
            raw_score += min(0.12, 0.05 * len(s))
            raw_score += min(0.14, 0.32 * sem)
            raw_score += min(0.06, 0.06 * gen)

            # Supporting-evidence neighbours retain a small same-family floor,
            # but most of their specialist bonus depends on concept affinity.
            score = raw_score * (0.35 + 0.65 * affinity)

            return CandidateFit(
                True, min(0.48, score), mult, p, s, a, gate_reason,
                tier="good",
                candidate_concept=candidate_class.concept,
                candidate_family=candidate_class.family,
                affinity=affinity,
            )

        if sem >= 0.18 and gen >= 0.45:
            raw_score = 0.07
            raw_score += min(0.16, 0.42 * sem)
            raw_score += min(0.06, 0.06 * gen)

            # Broad same-family neighbours are deliberately more sensitive
            # to structural concept affinity.
            score = raw_score * (0.20 + 0.80 * affinity)

            return CandidateFit(
                True, min(0.34, score), mult, p, s, a, gate_reason,
                tier="broad",
                candidate_concept=candidate_class.concept,
                candidate_family=candidate_class.family,
                affinity=affinity,
            )

    # V2.6 candidate-admission softening ---------------------------------
    # The normal specialist paths above remain authoritative. This final
    # fallback only prevents plausible neighbours with sparse metadata from
    # being discarded before ranking can evaluate them.
    #
    # Explicit contradiction gates stay hard.
    hard_reject_reasons = {
        "forbidden_genres",
        "forbidden_any",
        "required_genres_all",
    }
    final_gate_reason = gate_reason or "insufficient_family_fit"
    affinity = concept_affinity(concept, candidate_class.concept)
    sem = max(0.0, float(semantic_score))
    gen = max(0.0, float(genre_score))

    # V2.6.2: allow softened admission when the ANCHOR family is one of
    # the candidate's genuinely eligible families, not only its primary family.
    #
    # This uses the existing V2.2 family-ranking machinery, so hybrid shows can
    # retain a meaningful secondary identity (e.g. relationships + power)
    # without reopening arbitrary cross-family semantic rescue.
    candidate_eligible_families = list(candidate_class.eligible_families or [])
    anchor_family_score = float(
        candidate_class.family_scores.get(x.family, 0.0) or 0.0
    )
    best_candidate_family_score = max(
        [float(v or 0.0) for v in candidate_class.family_scores.values()]
        or [0.0]
    )

    same_family_soft = bool(
        same_family
        and (
            sem >= 0.10
            or gen >= 0.45
            or bool(s)
        )
    )

    # V2.6.3: secondary-family admission must represent a genuinely strong
    # secondary identity, not merely appear in the eligible-family list.
    # Tighten both the absolute family floor and the distance from the
    # candidate's strongest family while keeping the rule title-agnostic.
    secondary_family_soft = bool(
        not same_family
        and x.family in candidate_eligible_families
        and anchor_family_score >= 0.36
        and anchor_family_score >= (best_candidate_family_score - 0.08)
        and (
            sem >= 0.14
            or gen >= 0.45
            or bool(s)
        )
    )

    if (
        not strict
        and final_gate_reason not in hard_reject_reasons
        and (
            same_family_soft
            or secondary_family_soft
        )
    ):
        if same_family_soft:
            raw_score = (
                0.045
                + min(0.08, 0.24 * sem)
                + min(0.045, 0.045 * gen)
                + min(0.045, 0.045 * affinity)
                + min(0.03, 0.015 * len(s))
            )
            softened_multiplier = min(mult, 0.82)
        else:
            # Secondary-family admissions are intentionally weaker than
            # primary-family admissions. Their job is to enter the ranking
            # pool, not to receive a recommendation advantage.
            family_strength = (
                anchor_family_score / best_candidate_family_score
                if best_candidate_family_score > 0
                else 0.0
            )
            raw_score = (
                0.025
                + min(0.055, 0.18 * sem)
                + min(0.03, 0.03 * gen)
                + min(0.03, 0.03 * family_strength)
                + min(0.015, 0.0075 * len(s))
            )
            softened_multiplier = min(mult, 0.72)

        return CandidateFit(
            True,
            min(0.18, raw_score),
            softened_multiplier,
            p,
            s,
            a,
            final_gate_reason,
            tier="broad",
            candidate_concept=candidate_class.concept,
            candidate_family=candidate_class.family,
            affinity=affinity,
        )

    return CandidateFit(
        False, 0.0, mult, p, s, a,
        final_gate_reason,
        tier="rejected",
        candidate_concept=candidate_class.concept,
        candidate_family=candidate_class.family,
        affinity=affinity,
    )


# ---------------------------------------------------------------------------
# V2.5 anchor fingerprint support
# ---------------------------------------------------------------------------

_FINGERPRINT_CONTEXT_TERMS = {
    "based on true story", "true story", "historical", "history", "miniseries",
    "family", "relationships", "relationship", "friendship", "community",
    "business", "money", "wealth", "work", "workplace", "office", "school",
    "society", "drama", "comedy", "mystery", "romance", "love",
}


def fingerprint_term_role_weight(concept: str, term: str) -> float:
    """Return taxonomy importance for a real TMDb anchor keyword.

    The keyword itself comes from the anchor, not from a hand-built show map.
    This helper only says how strongly that term relates to the selected
    specialist concept.

    Required/primary terms are strongest, discovery terms are useful,
    supporting/contextual terms are weaker, and unrelated anchor-specific
    terms retain a neutral weight because they may still be highly distinctive.
    """
    x = CONCEPTS.get(concept)
    t = norm(term)

    if not t:
        return 0.0
    if not x:
        return 1.0

    required = {
        norm(v) for v in tuple(x.required_all) + tuple(x.required_any) if norm(v)
    }
    primary = {norm(v) for v in x.primary if norm(v)}
    discovery = {norm(v) for v in x.discovery if norm(v)}
    supporting = {norm(v) for v in x.supporting if norm(v)}

    if t in required or t in primary:
        weight = 1.35
    elif t in discovery:
        weight = 1.05
    elif t in supporting:
        weight = 0.65
    else:
        # Real anchor metadata that is not in the generic taxonomy can still be
        # exceptionally useful (location, occupation, specific event, setting).
        weight = 0.90

    if t in _FINGERPRINT_CONTEXT_TERMS and t not in required and t not in primary:
        weight *= 0.45

    return round(max(0.10, weight), 4)


def discovery_terms_for(concept: str, max_n: int = 14) -> list[str]:
    x = CONCEPTS.get(concept)
    return list(dict.fromkeys(x.discovery))[:max_n] if x else []


def discovery_genres_for(concept: str, max_n: int = 3) -> list[int]:
    """Return the concept's reusable TMDb genre constraints."""
    x = CONCEPTS.get(concept)
    if not x:
        return []
    return list(dict.fromkeys(int(g) for g in x.genres if int(g) > 0))[:max_n]


def compare_old_new(d: Mapping[str, Any], old_concept: str | None) -> dict[str, Any]:
    r = classify_anchor(d)
    return {
        "title": d.get("title") or d.get("name"),
        "old": old_concept,
        "new": r.concept,
        "family": r.family,
        "confidence": round(r.confidence, 4),
        "state": r.state,
        "changed": old_concept != r.concept,
        "debug": r.debug_dict(),
    }


def validate_taxonomy() -> list[str]:
    problems: list[str] = []
    valid_families = set(FAMILIES)
    for name, x in CONCEPTS.items():
        if x.family not in valid_families:
            problems.append(f"{name}: unknown family {x.family}")
        if not x.primary:
            problems.append(f"{name}: no primary terms")
        if x.min_score < 0 or x.min_score > 1:
            problems.append(f"{name}: invalid min_score {x.min_score}")
        overlap = set(x.required_genres_any) & set(x.forbidden_genres)
        if overlap:
            problems.append(f"{name}: genre both required and forbidden: {sorted(overlap)}")
    return problems


if __name__ == "__main__":
    problems = validate_taxonomy()
    if problems:
        print("\n".join(problems))
        raise SystemExit(1)
    print(f"TV Taxonomy v2.7.4a OK: {len(FAMILIES)} families, {len(CONCEPTS)} specialist concepts")

# app/services/exclusions.py
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

# We’ll use SQLAlchemy core if available; otherwise do best-effort ORMs
try:
    from sqlalchemy import select  # type: ignore
except Exception:
    select = None  # type: ignore


def _try_import(*paths: str):
    """
    Try several import paths and return the first object found.
    Example: _try_import("app.db_models:Rating", "app.models:Rating")
    """
    import importlib
    for p in paths:
        mod, _, name = p.partition(":")
        try:
            m = importlib.import_module(mod)
            obj = getattr(m, name)
            return obj
        except Exception:
            continue
    return None


def _find_first_attr(obj: Any, names: Iterable[str]) -> Optional[str]:
    for n in names:
        if hasattr(obj, n):
            return n
    return None


async def _fetch_pairs_via_select(db, model, col_user: str, col_id: str) -> List[Tuple[int, Optional[int]]]:
    """Return [(user_id, tmdb_id_or_show_id), ...] using SQLAlchemy select if available."""
    if select is None:
        return []
    stmt = select(getattr(model, col_user), getattr(model, col_id))
    rows = (await db.execute(stmt)).all()
    out: List[Tuple[int, Optional[int]]] = []
    for r in rows:
        try:
            uid, mid = int(r[0]), r[1]
            if mid is not None:
                try:
                    mid = int(mid)
                except Exception:
                    pass
            out.append((uid, mid))
        except Exception:
            continue
    return out


async def _fetch_ids_for_user(db, model, user_id: int, id_field: str, user_field: str) -> Set[int]:
    """Get a set of ids (tmdb_id or show_id) for the user from a model."""
    out: Set[int] = set()
    try:
        # Prefer select (async engine)
        if select is not None:
            stmt = select(getattr(model, id_field)).where(getattr(model, user_field) == user_id)
            rows = (await db.execute(stmt)).all()
            for (val,) in rows:
                try:
                    if val is not None:
                        out.add(int(val))
                except Exception:
                    continue
            return out
        # Fallback to naive attribute access (ORM session-like)
        if hasattr(db, "query"):
            q = db.query(model).filter(getattr(model, user_field) == user_id)
            for row in q.all():
                try:
                    val = getattr(row, id_field, None)
                    if val is not None:
                        out.add(int(val))
                except Exception:
                    continue
    except Exception:
        pass
    return out


async def _map_show_ids_to_tmdb(db, show_ids: Iterable[int]) -> Set[int]:
    """
    If we only have show_id, map to tmdb_id via a Show-like model.
    Tries: Show, TvShow, Title.
    """
    show_model = _try_import("app.db_models:Show", "app.db_models:TvShow", "app.db_models:Title")
    if show_model is None:
        return set()

    # Find fields on the Show model
    id_field = _find_first_attr(show_model, ("id", "show_id", "pk", "uid"))
    tmdb_field = _find_first_attr(show_model, ("tmdb_id", "external_id", "tmdbid"))
    if id_field is None or tmdb_field is None:
        return set()

    ids = set(int(sid) for sid in show_ids if isinstance(sid, int))
    out: Set[int] = set()
    try:
        if select is not None:
            stmt = select(getattr(show_model, tmdb_field)).where(
                getattr(show_model, id_field).in_(list(ids))
            )
            rows = (await db.execute(stmt)).all()
            for (tid,) in rows:
                try:
                    if tid is not None:
                        out.add(int(tid))
                except Exception:
                    continue
        elif hasattr(db, "query"):
            q = db.query(show_model).filter(getattr(show_model, id_field).in_(list(ids)))
            for row in q.all():
                try:
                    tid = getattr(row, tmdb_field, None)
                    if tid is not None:
                        out.add(int(tid))
                except Exception:
                    continue
    except Exception:
        return set()

    return out


async def gather_user_exclusions(db, user_id: int) -> Set[int]:
    """
    Build a robust exclusion set of TMDB IDs for this user from whatever models exist.

    Tries to discover:
      - Ratings tables (rated anything at all)
      - Favorites / Library tables (is_favorite / in library)
      - Hidden / NotInterested tables

    Returns: set of tmdb_id (ints).
    """
    tmdb_ids: Set[int] = set()
    show_ids_to_map: Set[int] = set()

    # Candidate model paths to try (model names used across your history)
    model_candidates = [
        # ratings
        ("app.db_models:Rating", ("user_id", "uid", "user"), ("tmdb_id", "external_id", "show_id")),
        ("app.db_models:UserRating", ("user_id", "uid"), ("tmdb_id", "external_id", "show_id")),
        # favorites / library
        ("app.db_models:Favorite", ("user_id", "uid"), ("tmdb_id", "external_id", "show_id")),
        ("app.db_models:LibraryEntry", ("user_id", "uid"), ("tmdb_id", "external_id", "show_id")),
        ("app.db_models:UserShow", ("user_id", "uid"), ("tmdb_id", "external_id", "show_id")),
        # hidden / uninterested
        ("app.db_models:HiddenShow", ("user_id", "uid"), ("tmdb_id", "external_id", "show_id")),
        ("app.db_models:NotInterested", ("user_id", "uid"), ("tmdb_id", "external_id", "show_id")),
    ]

    for model_path, user_fields, id_fields in model_candidates:
        model = _try_import(model_path)
        if model is None:
            continue
        user_field = _find_first_attr(model, user_fields)
        id_field = _find_first_attr(model, id_fields)
        if user_field is None or id_field is None:
            continue

        ids = await _fetch_ids_for_user(db, model, user_id, id_field=id_field, user_field=user_field)
        if not ids:
            continue

        # If model carries tmdb_id directly
        if "tmdb" in id_field.lower() or "external" in id_field.lower():
            tmdb_ids.update(int(i) for i in ids if isinstance(i, int))
        else:
            # It's likely show_id; map later
            show_ids_to_map.update(int(i) for i in ids if isinstance(i, int))

    # Map any show_ids -> tmdb_id via Show model (if available)
    if show_ids_to_map:
        tmdb_ids.update(await _map_show_ids_to_tmdb(db, show_ids_to_map))

    return tmdb_ids


def apply_user_exclusions(items: List[Dict[str, Any]], excluded_tmdb: Set[int]) -> List[Dict[str, Any]]:
    """
    Filter a list of recommendation dicts (each should have 'tmdb_id')
    to remove anything in the excluded set.
    """
    if not excluded_tmdb:
        return items
    out: List[Dict[str, Any]] = []
    for it in items:
        try:
            tid = it.get("tmdb_id")
            if tid is None:
                # keep items we can’t identify (or drop — your call)
                out.append(it)
                continue
            if int(tid) in excluded_tmdb:
                continue
            out.append(it)
        except Exception:
            out.append(it)
    return out

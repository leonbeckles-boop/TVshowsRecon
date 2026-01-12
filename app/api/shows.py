# app/api/shows.py
from fastapi import APIRouter, Query
from app.integrations.tmdb import tmdb_client, PaginatedShows

router = APIRouter()

@router.get("/search", response_model=PaginatedShows)
async def search_shows(
    q: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=50),
    append: list[str] = Query(["genres","networks","episode_run_time"])
):
    data = await tmdb_client.search_tv(q=q, page=page, per_page=per_page, append=append)
    return data

Hybrid TV Recommender — Drop‑in Files
====================================

What you get
------------
- FastAPI routes for /recommendations with sources: tmdb | reddit | hybrid
- Async Reddit client with OAuth2
- Hybrid merger of TMDb and Reddit signals with weights
- Redis caching (fastapi-cache2)
- Title → TMDb resolver
- Simple in‑memory user weight store (swap for DB later)
- Minimal tests skeleton

Install
-------
python -m venv .venv
source .venv/bin/activate   # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt

Copy .env.example to .env and fill in keys.

Run (dev)
---------
uvicorn app.main:app --reload

Mounting into an existing app
-----------------------------
If you already have an app and routers, add:
    from app.routers.recommendations import router as recs_router
    app.include_router(recs_router)

Files
-----
- app/core/settings.py — env config (pydantic-settings)
- app/infra/reddit_client.py — OAuth + API calls
- app/services/reddit_service.py — trending candidates from subreddits
- app/services/title_to_tmdb.py — resolve title to TMDb TV id
- app/services/tmdb_service.py — stub for your TMDb recs
- app/services/hybrid_service.py — normalize + weight + merge
- app/routers/recommendations.py — API endpoints
- app/main.py — FastAPI app + Redis cache init
- tests/test_reddit_service.py — basic test with respx (to expand)

Notes
-----
- Caching keys are based on function args; clearing cache will flush all keys.
- The TMDb service here is a stub; wire to your real logic when ready.
- Replace the in‑memory WEIGHTS with your DB persistence when convenient.

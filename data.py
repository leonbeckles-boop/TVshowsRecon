# app/data.py


users_db = [
    {"id": 1, "name": "Alice", "email": "alice@example.com", "favorite_tmdb_ids": []},
    {"id": 2, "name": "Bob",   "email": "bob@example.com",   "favorite_tmdb_ids": []},
]

def _next_user_id() -> int:
    return (max((u["id"] for u in users_db), default=0) + 1)

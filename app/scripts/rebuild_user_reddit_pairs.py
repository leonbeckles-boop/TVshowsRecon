import asyncio

from dotenv import load_dotenv
load_dotenv()

from app.db.session import get_async_session
from app.services.reddit_pairs_build import rebuild_pairs_for_all_users


async def main():
    print("🚀 Rebuilding user_reddit_pairs...")

    async for session in get_async_session():
        total = await rebuild_pairs_for_all_users(session, limit=500)
        print(f"✅ Done. Total rows written: {total}")
        break  # important: only take one session


if __name__ == "__main__":
    asyncio.run(main())
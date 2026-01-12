import os
import httpx
import asyncio
from dotenv import load_dotenv

load_dotenv()  # load .env from project root

async def main():
    ua = os.getenv("REDDIT_USER_AGENT") or "tvrecs/0.1 by unknown"
    cid = os.getenv("REDDIT_CLIENT_ID")
    cs = os.getenv("REDDIT_CLIENT_SECRET") or os.getenv("REDDIT_SECRET")

    print("UA:", ua)
    print("CID:", cid)
    print("CS present:", bool(cs))

    if not cid or not cs:
        print("MISSING Reddit env vars. Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env")
        return

    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": ua}) as client:
        r = await client.post(
            "https://www.reddit.com/api/v1/access_token",
            data={"grant_type": "client_credentials"},
            auth=(cid, cs),
        )
        print("Status:", r.status_code)
        print("Body:", r.text[:300])

if __name__ == "__main__":
    asyncio.run(main())

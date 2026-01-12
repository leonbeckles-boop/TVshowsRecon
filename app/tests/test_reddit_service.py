import re
import pytest
import respx
import httpx

from app.services.reddit_service import reddit_trending_candidates

@respx.mock
@pytest.mark.asyncio
async def test_trending_basic():
    # Mock OAuth token request
    respx.post("https://www.reddit.com/api/v1/access_token").mock(
        return_value=httpx.Response(200, json={"access_token": "x", "expires_in": 3600}),
    )

    # Mock ANY subreddit 'top' endpoint, regardless of which subs the service iterates
    # (query params like ?t=month&limit=10 are fine with the optional (?:\?.*)?$)
    respx.get(re.compile(r"^https://oauth\.reddit\.com/r/[^/]+/top(?:\?.*)?$")).mock(
        return_value=httpx.Response(200, json={"data": {"children": []}}),
    )

    out = await reddit_trending_candidates(limit_total=10)
    assert isinstance(out, list)

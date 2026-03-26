from fastapi import APIRouter, Query

from app.services.email_service import (
    send_email,
    welcome_email_html,
    day2_email_html,
    day5_email_html,
    day7_feedback_email_html,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("/test-onboarding")
async def test_onboarding(
    email: str = Query(...),
    username: str = Query("Leon"),
):
    results = {}

    payloads = [
        ("welcome", "Welcome to WhatNext 🎬", welcome_email_html(username)),
        ("day2", "Your recommendations are waiting 👀", day2_email_html(username)),
        ("day5", "Stop scrolling. Start watching better shows 🎯", day5_email_html(username)),
        ("day7", "Quick favour? 🙏", day7_feedback_email_html(username)),
    ]

    for key, subject, html in payloads:
        result = send_email(email, subject, html)
        results[key] = result
        print(f"📨 test-onboarding {key}: {result}")

    return {"ok": True, "results": results}
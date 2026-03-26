from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.email_service import (
    send_email,
    welcome_email_html,
    day2_email_html,
    day5_email_html,
    day7_feedback_email_html,
)
from app.models.email_log import EmailLog

try:
    from app.models_auth import AuthUser as UserModel  # type: ignore
except Exception:
    from app.models_auth import User as UserModel  # type: ignore

try:
    from app.models import UserFavorite  # type: ignore
except Exception:
    UserFavorite = None  # optional


EMAIL_WELCOME = "welcome"
EMAIL_DAY2 = "day2_nudge"
EMAIL_DAY5 = "day5_value"
EMAIL_DAY7 = "day7_feedback"


async def has_email_been_sent(session: AsyncSession, user_id: int, email_type: str) -> bool:
    result = await session.execute(
        select(EmailLog.id).where(
            EmailLog.user_id == user_id,
            EmailLog.email_type == email_type,
            EmailLog.status == "sent",
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def log_email_result(
    session: AsyncSession,
    *,
    user_id: int,
    recipient: str,
    email_type: str,
    subject: str,
    result: dict,
) -> None:
    row = EmailLog(
        user_id=user_id,
        recipient=recipient,
        email_type=email_type,
        subject=subject,
        status="sent" if result.get("ok") else "failed",
        provider_message_id=result.get("message_id"),
        provider_response=result.get("response_text"),
        sent_at=datetime.now(timezone.utc) if result.get("ok") else None,
    )
    session.add(row)
    await session.commit()


async def send_onboarding_email(
    session: AsyncSession,
    *,
    user_id: int,
    recipient: str,
    username: str | None,
    email_type: str,
) -> bool:
    if await has_email_been_sent(session, user_id, email_type):
        return False

    if email_type == EMAIL_WELCOME:
        subject = "Welcome to WhatNext 🎬"
        html = welcome_email_html(username)
    elif email_type == EMAIL_DAY2:
        subject = "Your recommendations are waiting 👀"
        html = day2_email_html(username)
    elif email_type == EMAIL_DAY5:
        subject = "Stop scrolling. Start watching better shows 🎯"
        html = day5_email_html(username)
    elif email_type == EMAIL_DAY7:
        subject = "Quick favour? 🙏"
        html = day7_feedback_email_html(username)
    else:
        raise ValueError(f"Unsupported email_type: {email_type}")

    result = send_email(recipient, subject, html)

    try:
        await log_email_result(
            session,
            user_id=user_id,
            recipient=recipient,
            email_type=email_type,
            subject=subject,
            result=result,
        )
    except Exception as e:
        print("⚠️ Failed to log email result:", repr(e))

    return result.get("ok", False)


async def queue_welcome_email(user_id: int, recipient: str, username: str | None) -> None:
    """
    Background-task safe welcome sender.
    Does not open a new DB session here, because the current project's engine
    is sync-shaped and caused AsyncEngine/Engine errors.

    This gets the welcome email flow working again immediately.
    """
    try:
        result = send_email(
            recipient,
            "Welcome to WhatNext 🎬",
            welcome_email_html(username),
        )
        print("📩 Welcome email result:", result)
    except Exception as e:
        print("❌ queue_welcome_email failed:", repr(e))


async def user_is_active(session: AsyncSession, user_id: int) -> bool:
    """
    Current simple definition of 'active':
    user has at least 3 favourites.
    """
    if UserFavorite is None:
        return False

    result = await session.execute(
        select(func.count()).select_from(UserFavorite).where(UserFavorite.user_id == user_id)
    )
    fav_count = result.scalar_one() or 0
    return fav_count >= 3


async def run_onboarding_scheduler(session: AsyncSession) -> dict:
    now = datetime.now(timezone.utc)

    users_result = await session.execute(select(UserModel))
    users = users_result.scalars().all()

    sent_counts = {
        EMAIL_DAY2: 0,
        EMAIL_DAY5: 0,
        EMAIL_DAY7: 0,
    }

    for user in users:
        created_at = getattr(user, "created_at", None)
        if not created_at:
            continue

        age = now - created_at

        if await user_is_active(session, user.id):
            continue

        if timedelta(days=2) <= age < timedelta(days=3):
            ok = await send_onboarding_email(
                session,
                user_id=user.id,
                recipient=user.email,
                username=getattr(user, "username", None),
                email_type=EMAIL_DAY2,
            )
            if ok:
                sent_counts[EMAIL_DAY2] += 1

        elif timedelta(days=5) <= age < timedelta(days=6):
            ok = await send_onboarding_email(
                session,
                user_id=user.id,
                recipient=user.email,
                username=getattr(user, "username", None),
                email_type=EMAIL_DAY5,
            )
            if ok:
                sent_counts[EMAIL_DAY5] += 1

        elif timedelta(days=7) <= age < timedelta(days=8):
            ok = await send_onboarding_email(
                session,
                user_id=user.id,
                recipient=user.email,
                username=getattr(user, "username", None),
                email_type=EMAIL_DAY7,
            )
            if ok:
                sent_counts[EMAIL_DAY7] += 1

    return sent_counts
"""Public iCal feed + its management endpoints.

- GET /calendar.ics?token=<secret>  → the subscribable feed (token-authed)
- GET /calendar/feed-url             → returns the URL the user can paste into Google Calendar
- POST /calendar/feed-url/rotate     → invalidates the old token; returns the new URL

Token is stored in the `user_settings` table under key `calendar_feed_token`
and lazily generated on first access.
"""
from __future__ import annotations

import hmac
from datetime import date, timedelta

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from backend.db import get_db, row_dict
from backend.services.calendar_feed import (
    build_ics,
    get_last_fetched_at,
    get_last_fetched_by,
    get_or_create_token,
    is_env_managed,
    record_fetch,
    rotate_token,
)

router = APIRouter()

# The feed window keeps the payload small and relevant. Past sessions still
# show recent plan history; 365 days forward covers any race-training block.
PAST_DAYS = 60
FUTURE_DAYS = 365


def _feed_url(request: Request, token: str) -> str:
    # Use the request's forwarded-aware base URL so the URL matches the
    # public host (strava.rsm-dev.org) when behind Cloudflare, and localhost
    # in dev. FastAPI's url_for honours X-Forwarded-* when the app is run
    # with proxy_headers=True (Uvicorn default).
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/calendar.ics?token={token}"


@router.get("/calendar.ics")
async def calendar_feed(
    request: Request,
    token: str = Query(default=""),
    db: aiosqlite.Connection = Depends(get_db),
):
    stored = await get_or_create_token(db)
    if not token or not hmac.compare_digest(token, stored):
        raise HTTPException(status_code=401, detail="invalid token")

    today = date.today()
    date_from = (today - timedelta(days=PAST_DAYS)).isoformat()
    date_to = (today + timedelta(days=FUTURE_DAYS)).isoformat()

    cur = await db.execute(
        "SELECT * FROM training_sessions WHERE date >= ? AND date <= ? ORDER BY date",
        (date_from, date_to),
    )
    sessions = [row_dict(r) for r in await cur.fetchall()]

    cur = await db.execute(
        "SELECT * FROM race_events WHERE date >= ? AND date <= ? ORDER BY date",
        (date_from, date_to),
    )
    races = [row_dict(r) for r in await cur.fetchall()]

    body = build_ics(sessions, races)
    await record_fetch(db, request.headers.get("user-agent"))
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": 'inline; filename="zone2.ics"',
        },
    )


@router.get("/calendar/feed-url")
async def get_feed_url(
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
):
    token = await get_or_create_token(db)
    return {
        "token": token,
        "url": _feed_url(request, token),
        "env_managed": is_env_managed(),
        "last_fetched_at": await get_last_fetched_at(db),
        "last_fetched_by": await get_last_fetched_by(db),
    }


@router.post("/calendar/feed-url/rotate")
async def rotate_feed_url(
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
):
    if is_env_managed():
        raise HTTPException(
            status_code=409,
            detail="Token is pinned via STRAVA_WEB_CALENDAR_FEED_TOKEN — rotate it in .env and restart.",
        )
    token = await rotate_token(db)
    return {
        "token": token,
        "url": _feed_url(request, token),
        "env_managed": False,
        "last_fetched_at": await get_last_fetched_at(db),
        "last_fetched_by": await get_last_fetched_by(db),
    }

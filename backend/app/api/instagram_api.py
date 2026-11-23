"""Instagram Reels publishing settings (integrations/instagram_publish.py),
REELS_DESK_PLAN.md R7. Settings are named accounts -- a channel can post to
more than one (Life3Baje's mood reels go to a separate account from its
ordinary reels) -- routed by a `{"channel": "account", "channel/format":
"account"}` table; the format-specific route wins.

    GET  /api/instagram/settings               channels, every account's config (tokens masked), the routes
    POST /api/instagram/settings {account, ...} save one named account's config
    POST /api/instagram/routes {routes}         save route(s): {route_key: account_name}
    POST /api/instagram/discover {token}        connected Facebook pages' Instagram accounts
    GET  /api/instagram/status                  per account and per route: connected, account, token days
                                                 left, today's publishing-limit usage, next post
"""
from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException

from integrations import instagram_publish as ig

router = APIRouter(tags=["Instagram"])


@router.get("/api/instagram/settings")
def get_settings():
    return {"channels": ig.channels(), "accounts": ig.all_accounts_masked(), "routes": ig.routes()}


@router.post("/api/instagram/settings")
def post_settings(payload: Dict[str, Any] = Body(...)):
    account = str(payload.get("account") or payload.get("channel") or "").strip()
    if not account:
        raise HTTPException(status_code=400, detail="account is required")
    try:
        saved = ig.set_account_settings(account, payload)
    except ig.InstagramError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ig.mask(saved)


@router.post("/api/instagram/routes")
def post_routes(payload: Dict[str, Any] = Body(...)):
    routes = payload.get("routes")
    if not isinstance(routes, dict) or not routes:
        raise HTTPException(status_code=400, detail="routes ({route_key: account_name}) is required")
    return {"routes": ig.set_routes(routes)}


@router.post("/api/instagram/discover")
def discover(payload: Dict[str, Any] = Body(...)):
    token = str(payload.get("token") or payload.get("access_token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="token is required")
    try:
        return {"accounts": ig.discover_accounts(token)}
    except ig.InstagramError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/api/instagram/status")
def status():
    return ig.status()

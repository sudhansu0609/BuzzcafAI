"""Publish a finished reel straight to Instagram (REELS_DESK_PLAN.md R7).

Uses the official Instagram API with Facebook Login (Graph API v21+): an
Instagram professional account linked to a Facebook Page, and a long-lived
Page/User access token the creator pastes in after following
`docs/INSTAGRAM_SETUP.md`. Reels have no Instagram-library music, so the
uploaded file must already carry its own audio -- the auto-story package's
`reel.mp4`, never `reel_nomusic.mp4`.

Settings are **named accounts**, not one slot per Studio channel: a channel
can post to more than one Instagram account (Life3Baje's ordinary reels go
to the Life3Baje account, but its mood reels go to a separate, calmer
account, @khayal3bajefeels). Everything lives in
`backend/config/instagram/settings.json` (git-ignored):

    {"accounts": {"khayal3bajefeels": {"ig_user_id", "username", "access_token",
                                        "token_expires_at", "app_id", "app_secret",
                                        "enabled", "post_times", "caption_suffix",
                                        "last_fired"}, ...},
     "routes": {"Life3Baje/mood_reel": "khayal3bajefeels",   # format-specific: wins
                "Raat3Baje": "raat3baje", ...}}              # channel-only: the rest

`account_for(channel, format)` resolves a route: the `"channel/format"` key
wins when it exists, else the plain `"channel"` key, else no account (not
even connected). `post_times`, `enabled` and the publishing-limit/refresh
state belong to the **account** (several routes can share one), not to a
route or a channel.

The upload is the resumable protocol with no public URL: open a container
(`POST {ig-user-id}/media`), stream the file's bytes in chunks to the
returned `uri` on rupload.facebook.com -- a dropped connection resumes from
the offset rupload last confirmed instead of restarting the whole file
(2026-10-24) -- poll the container until Instagram has finished processing
it, publish it (`POST {ig-user-id}/media_publish`), then read back its
permalink.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from core.paths import CONFIG_DIR

logger = logging.getLogger("buzzcaf_ai.instagram")

GRAPH = "https://graph.facebook.com/v21.0"

IG_DIR = Path(CONFIG_DIR) / "instagram"
SETTINGS_FILE = IG_DIR / "settings.json"

REQUEST_TIMEOUT = (10, 60)          # connect, read
RETRY_STATUSES = (429, 500, 502, 503, 504)
MAX_RETRIES = 4
RETRY_BACKOFF_S = 2.0

CONTAINER_POLL_S = 5.0
CONTAINER_MAX_WAIT_S = 600.0

#: A freshly pasted token is assumed long-lived (~60 days) unless Facebook's
#: own response says otherwise.
DEFAULT_TOKEN_LIFETIME_S = 60 * 86400
#: Refresh once fewer than this many days remain (API facts).
REFRESH_WITHIN_DAYS = 10
PUBLISHING_LIMIT_DEFAULT = 50        # posts per 24h, when Instagram's own config is unavailable

CAPTION_MAX_CHARS = 2200
CAPTION_MAX_HASHTAGS = 30

_lock = threading.Lock()

DEFAULT_ACCOUNT_CONFIG: Dict[str, Any] = {
    "ig_user_id": "", "username": "", "access_token": "", "token_expires_at": None,
    "app_id": "", "app_secret": "", "enabled": False, "post_times": [], "caption_suffix": "",
    "last_fired": {},
}

#: Life3Baje's mood reels (no face, calmer, REELS_DESK_PLAN.md S6) are a
#: separate account from Life3Baje's ordinary reels -- unconnected (no
#: token) until the creator adds one, same as any other account.
DEFAULT_ROUTES: Dict[str, str] = {"Life3Baje/mood_reel": "khayal3bajefeels"}

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class InstagramError(RuntimeError):
    """A failure worded for the creator; never carries a token or secret."""


# ──────────────────────────────── storage ────────────────────────────────

def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _migrate_legacy(data: Dict[str, Any]) -> Dict[str, Any]:
    """Before accounts/routes (R7's first cut), `settings.json` was
    `{channel: {...}}` directly: an old file still loads, each channel
    becoming its own same-named account with a matching channel route."""
    if "accounts" in data or "routes" in data:
        return data
    legacy_accounts = {ch: conf for ch, conf in data.items() if isinstance(conf, dict)}
    return {"accounts": legacy_accounts, "routes": {ch: ch for ch in legacy_accounts}}


def _store() -> Dict[str, Any]:
    raw = _read_json(SETTINGS_FILE, {})
    return _migrate_legacy(raw if isinstance(raw, dict) else {})


def channels() -> List[str]:
    """Every Studio brand (the channel guides), for the routing picker."""
    from core.paths import BACKEND_DIR
    return sorted(p.stem for p in (Path(BACKEND_DIR) / "prompts" / "channels").glob("*.md"))


def accounts() -> List[str]:
    """Every named Instagram account that has been saved."""
    return sorted(_store().get("accounts") or {})


def account_settings(name: str) -> Dict[str, Any]:
    """That account's saved config (with secrets), defaults filled in."""
    return {**DEFAULT_ACCOUNT_CONFIG, **((_store().get("accounts") or {}).get(name) or {})}


def all_accounts() -> Dict[str, Dict[str, Any]]:
    """Every saved account, keyed by name (used by the scheduler and status)."""
    raw = _store().get("accounts") or {}
    return {name: {**DEFAULT_ACCOUNT_CONFIG, **conf} for name, conf in raw.items() if isinstance(conf, dict)}


def mask(conf: Dict[str, Any]) -> Dict[str, Any]:
    """`conf` for display: the token and app secret become booleans, never the value itself."""
    out = dict(conf)
    out["access_token_set"] = bool(conf.get("access_token"))
    out["app_secret_set"] = bool(conf.get("app_secret"))
    out.pop("access_token", None)
    out.pop("app_secret", None)
    return out


def all_accounts_masked() -> Dict[str, Dict[str, Any]]:
    return {name: mask(conf) for name, conf in all_accounts().items()}


def routes() -> Dict[str, str]:
    """Every route (`"channel"` or `"channel/format"` -> account name),
    `DEFAULT_ROUTES` underneath whatever is saved; a route saved as an empty
    string is removed (even a default one)."""
    saved = _store().get("routes") or {}
    merged = {**DEFAULT_ROUTES, **saved}
    return {k: v for k, v in merged.items() if v}


def account_for(channel: str, format: Optional[str] = None) -> Optional[str]:  # noqa: A002 - matches the API's own word
    """The account name routed for this channel (and format, when given); the
    `"channel/format"` route wins over the plain `"channel"` route. None
    means no route at all -- not even an unconnected placeholder."""
    rt = routes()
    if format:
        hit = rt.get(f"{channel}/{format}")
        if hit:
            return hit
    return rt.get(channel) or None


def set_routes(patch: Dict[str, Any]) -> Dict[str, str]:
    """Merge `patch` (`{route_key: account_name}`) into the saved routes. An
    empty account name removes that route (back to its default, if any)."""
    with _lock:
        data = _store()
        current = dict(data.get("routes") or {})
        for key, value in (patch or {}).items():
            key = str(key).strip()
            if not key:
                continue
            current[key] = str(value or "").strip()
        data["routes"] = current
        _write_json(SETTINGS_FILE, data)
        return routes()


def set_account_settings(name: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Merge `patch` into the named account's saved config. A blank text
    field (left empty on the settings page so the saved value is not
    retyped) never overwrites what is already saved -- the same rule the
    Pixabay key uses."""
    name = str(name or "").strip()
    if not name:
        raise InstagramError("An account needs a name.")
    with _lock:
        data = _store()
        saved_accounts = dict(data.get("accounts") or {})
        current = {**DEFAULT_ACCOUNT_CONFIG, **(saved_accounts.get(name) or {})}
        token_changed = False
        for key in ("ig_user_id", "username", "access_token", "app_id", "app_secret", "caption_suffix"):
            if key in patch and patch[key] is not None:
                value = str(patch[key]).strip()
                if value:
                    if key == "access_token" and value != current.get("access_token"):
                        token_changed = True
                    current[key] = value
        if "token_expires_at" in patch and patch["token_expires_at"] is not None:
            try:
                current["token_expires_at"] = float(patch["token_expires_at"])
            except (TypeError, ValueError):
                pass
        elif token_changed:
            # A freshly pasted token is assumed long-lived; the real expiry
            # (if Facebook's own exchange ever gives one) replaces this.
            current["token_expires_at"] = time.time() + DEFAULT_TOKEN_LIFETIME_S
        if "enabled" in patch:
            current["enabled"] = bool(patch["enabled"])
        if isinstance(patch.get("post_times"), list):
            current["post_times"] = sorted({str(t).strip() for t in patch["post_times"]
                                            if _TIME_RE.match(str(t).strip())})
        if isinstance(patch.get("last_fired"), dict):
            current["last_fired"] = {**(current.get("last_fired") or {}), **patch["last_fired"]}
        saved_accounts[name] = current
        data["accounts"] = saved_accounts
        data.setdefault("routes", data.get("routes") or {})
        _write_json(SETTINGS_FILE, data)
        return current


def _days_left(conf: Dict[str, Any]) -> Optional[float]:
    expires_at = conf.get("token_expires_at")
    if not isinstance(expires_at, (int, float)):
        return None
    return round((float(expires_at) - time.time()) / 86400.0, 1)


def _next_post_time(conf: Dict[str, Any], now_hm: str) -> Optional[str]:
    times = sorted(t for t in (conf.get("post_times") or []) if _TIME_RE.match(str(t)))
    if not times:
        return None
    for t in times:
        if t > now_hm:
            return f"today {t}"
    return f"tomorrow {times[0]}"


# ──────────────────────────────── HTTP ────────────────────────────────

def _request(method: str, url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    last_exc: Optional[Exception] = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.request(method, url, **kwargs)
        except requests.RequestException as exc:
            last_exc = exc
        else:
            if resp.status_code not in RETRY_STATUSES or attempt == MAX_RETRIES:
                return resp
            last_exc = None
        time.sleep(RETRY_BACKOFF_S * (2 ** attempt))
    if last_exc:
        raise InstagramError(f"Could not reach Instagram: {last_exc}")
    return resp  # noqa: F821 - the loop always returns or raises above


def _raise_for_api(resp: requests.Response) -> None:
    if resp.status_code < 400:
        return
    try:
        err = resp.json().get("error") or {}
    except ValueError:
        err = {}
    message = err.get("message") or resp.text[:300]
    code = err.get("code")
    subcode = err.get("error_subcode")
    tag = f" (#{subcode})" if subcode else (f" ({code})" if code else "")
    raise InstagramError(f"Instagram API error{tag}: {message}")


# ──────────────────────────────── discovery ────────────────────────────────

def discover_accounts(token: str) -> List[Dict[str, Any]]:
    """Every Instagram professional account reachable from this token's Facebook
    Pages (`GET /me/accounts` -> per page `?fields=instagram_business_account`).
    The creator names one of these when saving it (`set_account_settings`)."""
    resp = _request("GET", f"{GRAPH}/me/accounts",
                     params={"access_token": token, "fields": "id,name,access_token"})
    _raise_for_api(resp)
    pages = resp.json().get("data") or []
    out: List[Dict[str, Any]] = []
    for page in pages:
        page_token = page.get("access_token") or token
        try:
            resp2 = _request("GET", f"{GRAPH}/{page['id']}",
                              params={"fields": "instagram_business_account{id,username,name}",
                                      "access_token": page_token})
            _raise_for_api(resp2)
            iba = resp2.json().get("instagram_business_account")
        except InstagramError as exc:
            logger.info("instagram discover: page %s has no Instagram account (%s)", page.get("id"), exc)
            iba = None
        if iba and iba.get("id"):
            out.append({"page_id": page.get("id"), "page_name": page.get("name") or "",
                        "ig_user_id": iba["id"], "username": iba.get("username") or "",
                        "access_token": page_token})
    return out


# ──────────────────────────────── token refresh ────────────────────────────────

def refresh_token_if_needed(account: str) -> Dict[str, Any]:
    """Exchanges the saved token for a fresh long-lived one when under
    `REFRESH_WITHIN_DAYS` remain. Needs `app_id`/`app_secret` saved; otherwise
    only logs the warning (the Health page surfaces the same thing)."""
    conf = account_settings(account)
    days_left = _days_left(conf)
    if days_left is None or days_left >= REFRESH_WITHIN_DAYS:
        return conf
    app_id, app_secret, token = conf.get("app_id"), conf.get("app_secret"), conf.get("access_token")
    if not (app_id and app_secret and token):
        logger.warning("instagram: %s's token expires in %s day(s) but no app id/secret is saved to refresh it.",
                        account, days_left)
        return conf
    resp = _request("GET", f"{GRAPH}/oauth/access_token",
                     params={"grant_type": "fb_exchange_token", "client_id": app_id,
                             "client_secret": app_secret, "fb_exchange_token": token})
    _raise_for_api(resp)
    data = resp.json()
    new_token = data.get("access_token")
    if not new_token:
        raise InstagramError("Facebook did not return a refreshed token.")
    expires_in = float(data.get("expires_in") or DEFAULT_TOKEN_LIFETIME_S)
    updated = set_account_settings(account, {"access_token": new_token, "token_expires_at": time.time() + expires_in})
    logger.info("instagram: refreshed %s's long-lived token (expires in %.0f days).", account, expires_in / 86400.0)
    return updated


# ──────────────────────────────── publishing limit ────────────────────────────────

def publishing_limit(account: str) -> Dict[str, Any]:
    """`{quota_usage, config: {quota_total, quota_duration}}` from Instagram,
    or an empty dict when the account has never published (no row yet)."""
    conf = account_settings(account)
    if not conf.get("ig_user_id") or not conf.get("access_token"):
        raise InstagramError(f"No Instagram account connected for {account}.")
    resp = _request("GET", f"{GRAPH}/{conf['ig_user_id']}/content_publishing_limit",
                     params={"fields": "config,quota_usage", "access_token": conf["access_token"]})
    _raise_for_api(resp)
    rows = resp.json().get("data") or []
    return rows[0] if rows else {}


# ──────────────────────────────── caption ────────────────────────────────

def trim_caption(text: str) -> str:
    """Instagram's own limits: 2,200 characters, 30 hashtags. Surplus
    hashtags (beyond the 30th) are dropped before the length cut, so a long
    tag list never eats into the caption's own words."""
    text = (text or "").strip()
    tags = list(re.finditer(r"#\w+", text))
    if len(tags) > CAPTION_MAX_HASHTAGS:
        for m in reversed(tags[CAPTION_MAX_HASHTAGS:]):
            text = text[:m.start()] + text[m.end():]
        text = re.sub(r"[ \t]{2,}", " ", text).strip()
    if len(text) > CAPTION_MAX_CHARS:
        text = text[:CAPTION_MAX_CHARS].rstrip()
    return text


# ──────────────────────────────── upload ────────────────────────────────

#: Streamed from disk in chunks this size, never the whole file in RAM
#: (2026-10-24, Fable review #11).
UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024
UPLOAD_ATTEMPTS = 4


def _upload_offset(upload_uri: str, token: str) -> int:
    """How many bytes Instagram has confirmed for this upload session so far
    -- rupload's own GET, used to resume a dropped connection from the right
    place instead of restarting the whole file."""
    resp = _request("GET", upload_uri, headers={"Authorization": f"OAuth {token}"})
    _raise_for_api(resp)
    try:
        return int(resp.json().get("offset", 0))
    except (TypeError, ValueError):
        return 0


def _upload_video(upload_uri: str, token: str, path: Path, size: int, offset: int = 0) -> None:
    """Streams `path` to the rupload URI in `UPLOAD_CHUNK_BYTES` chunks. A
    dropped connection resumes from the offset Instagram last confirmed
    (rupload supports `offset`), not from the start of the file."""
    for attempt in range(UPLOAD_ATTEMPTS):
        try:
            with path.open("rb") as fh:
                fh.seek(offset)
                while offset < size:
                    chunk = fh.read(UPLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    resp = _request("POST", upload_uri, data=chunk,
                                     headers={"Authorization": f"OAuth {token}", "offset": str(offset),
                                              "file_size": str(size)})
                    _raise_for_api(resp)
                    offset += len(chunk)
            if offset >= size:
                return
        except (InstagramError, requests.RequestException) as exc:
            if attempt + 1 >= UPLOAD_ATTEMPTS:
                raise InstagramError(f"The upload was dropped and could not resume: {exc}")
            logger.warning("instagram upload dropped at offset %d (%s); asking Instagram for the confirmed offset "
                            "and resuming", offset, exc)
            try:
                offset = _upload_offset(upload_uri, token)
            except InstagramError:
                pass  # keep the offset this attempt had already confirmed itself
            time.sleep(RETRY_BACKOFF_S)
    raise InstagramError("The upload did not finish.")


def _poll_container(container_id: str, token: str) -> Dict[str, Any]:
    deadline = time.time() + CONTAINER_MAX_WAIT_S
    while True:
        resp = _request("GET", f"{GRAPH}/{container_id}",
                         params={"fields": "status_code,status", "access_token": token})
        _raise_for_api(resp)
        data = resp.json()
        if data.get("status_code") in ("FINISHED", "ERROR", "EXPIRED"):
            return data
        if time.time() > deadline:
            raise InstagramError("Instagram did not finish processing the reel in time.")
        time.sleep(CONTAINER_POLL_S)


def publish_reel(account: str, video_path: str, caption: str,
                  thumb_offset_ms: Optional[int] = None) -> Dict[str, Any]:
    """Uploads `video_path` as a Reel to the named account (resumable
    protocol, no public URL needed) and returns `{media_id, permalink}`.
    Never attaches Instagram's own music: the file must already carry its
    audio."""
    path = Path(video_path)
    if not path.is_file():
        raise InstagramError(f"The reel file is not on disk: {video_path}")
    try:
        refresh_token_if_needed(account)
    except InstagramError as exc:
        logger.warning("instagram: token refresh for %s failed (%s); trying with the saved token.", account, exc)
    conf = account_settings(account)
    ig_user, token = conf.get("ig_user_id"), conf.get("access_token")
    if not ig_user or not token:
        raise InstagramError(f"No Instagram account connected for {account}. Add it under Settings -> Instagram.")
    limit = publishing_limit(account)
    quota_total = (limit.get("config") or {}).get("quota_total") or PUBLISHING_LIMIT_DEFAULT
    if limit and limit.get("quota_usage", 0) >= quota_total:
        raise InstagramError(f"{account}'s Instagram account hit its 24-hour publishing limit "
                             f"({quota_total} posts). Try again later.")

    params: Dict[str, Any] = {"media_type": "REELS", "upload_type": "resumable", "caption": caption,
                              "share_to_feed": "true", "access_token": token}
    if thumb_offset_ms:
        params["thumb_offset"] = int(thumb_offset_ms)
    resp = _request("POST", f"{GRAPH}/{ig_user}/media", params=params)
    _raise_for_api(resp)
    opened = resp.json()
    container_id, upload_uri = opened.get("id"), opened.get("uri")
    if not container_id or not upload_uri:
        raise InstagramError(f"Instagram did not open an upload session: {opened}")

    size = path.stat().st_size
    _upload_video(upload_uri, token, path, size)

    status = _poll_container(container_id, token)
    if status.get("status_code") != "FINISHED":
        raise InstagramError(f"Instagram could not process the reel ({status.get('status_code')}): "
                             f"{status.get('status') or 'no detail'}")

    resp = _request("POST", f"{GRAPH}/{ig_user}/media_publish",
                     params={"creation_id": container_id, "access_token": token})
    _raise_for_api(resp)
    media_id = resp.json().get("id")
    if not media_id:
        raise InstagramError("Instagram published the reel but returned no media id.")

    resp = _request("GET", f"{GRAPH}/{media_id}", params={"fields": "permalink", "access_token": token})
    _raise_for_api(resp)
    permalink = resp.json().get("permalink") or ""
    return {"media_id": media_id, "permalink": permalink}


# ──────────────────────────────── status (Settings page, Story Desk) ────────────────────────────────

def _account_status_row(name: str, conf: Dict[str, Any]) -> Dict[str, Any]:
    connected = bool(conf.get("ig_user_id") and conf.get("access_token"))
    days_left = _days_left(conf)
    usage = None
    if connected:
        try:
            limit = publishing_limit(name)
            usage = {"used": limit.get("quota_usage"),
                     "total": (limit.get("config") or {}).get("quota_total") or PUBLISHING_LIMIT_DEFAULT}
        except InstagramError as exc:
            logger.debug("instagram status: publishing limit unavailable for %s (%s)", name, exc)
    return {"connected": connected, "username": conf.get("username") or "",
            "token_days_left": days_left, "token_expired": days_left is not None and days_left <= 0,
            "publishing_limit": usage, "enabled": bool(conf.get("enabled")), "post_times": conf.get("post_times") or []}


def status() -> Dict[str, Any]:
    """`{accounts: {name: row}, routes: {route_key: {**row, account, next_post}}}`
    -- GET /api/instagram/status. A route to an account that was never saved
    (the default Life3Baje/mood_reel one, until the creator connects it)
    still gets a row, just an unconnected one."""
    import datetime as _dt
    now_hm = _dt.datetime.now().strftime("%H:%M")
    accs = all_accounts()
    account_rows = {name: _account_status_row(name, conf) for name, conf in accs.items()}
    route_rows: Dict[str, Any] = {}
    for route_key, account_name in routes().items():
        conf = accs.get(account_name) or DEFAULT_ACCOUNT_CONFIG
        row = account_rows.get(account_name) or _account_status_row(account_name, conf)
        route_rows[route_key] = {**row, "account": account_name,
                                 "next_post": _next_post_time(conf, now_hm) if row.get("enabled") else None}
    return {"accounts": account_rows, "routes": route_rows}

"""Publish a finished video straight to the creator's YouTube channels.

Uses the official YouTube Data API v3 with an OAuth client the creator owns
(a Google Cloud "Desktop app" client; README: Publishing to YouTube). One client
file serves every channel; each channel signs in once and keeps its own refresh
token, so the Studio never asks again (unless the Google app is left in
"Testing", where Google expires sign-ins after 7 days).

Everything lives in `backend/config/youtube/` (git-ignored):

| File | What |
|---|---|
| `client_secret.json` | the creator's OAuth client |
| `channels.json` | channel id -> {title, brand, thumbnail} |
| `tokens/<channel id>.json` | that channel's refresh token |

Title, description and tags come from the SEO manager's package
(`publish/publish.json`, written by the workflow's SEO step); the creator picks
or edits them before the upload. Uploads are resumable: a dropped connection
resumes from the byte YouTube last confirmed, and a Studio restart can pick an
upload up from its saved session URL.

Google rule worth knowing: videos uploaded from an API project that has not
passed YouTube's API audit are locked to Private. The upload works; making it
public needs the (free) audit, https://support.google.com/youtube/contact/yt_api_form.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

from core.paths import CONFIG_DIR

logger = logging.getLogger("buzzcaf_ai.youtube")

SCOPE = "https://www.googleapis.com/auth/youtube"   # upload + thumbnails + reading the channel
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3"

YT_DIR = Path(CONFIG_DIR) / "youtube"
CLIENT_FILE = YT_DIR / "client_secret.json"
CHANNELS_FILE = YT_DIR / "channels.json"
TOKENS_DIR = YT_DIR / "tokens"

CHUNK_BYTES = 32 * 1024 * 1024          # a multiple of 256 KiB, as the API requires
MAX_RETRIES = 8
LOGIN_TIMEOUT_S = 300

#: YouTube category ids the Studio offers. Story channels are Entertainment.
CATEGORIES = {"24": "Entertainment", "22": "People & Blogs", "27": "Education", "1": "Film & Animation"}
DEFAULT_CATEGORY = {"Life3Baje": "22"}

_lock = threading.Lock()


class YouTubeError(RuntimeError):
    """A failure worded for the creator."""


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


def save_client_secret(text: str) -> Dict[str, Any]:
    try:
        raw = json.loads(text)
    except ValueError:
        raise YouTubeError("That file is not valid JSON.")
    if not isinstance(raw, dict) or not (raw.get("installed") or raw.get("web") or {}).get("client_id"):
        raise YouTubeError("That file has no client_id. Download the OAuth client JSON from Google Cloud.")
    if not raw.get("installed"):
        raise YouTubeError('That is a "Web application" client. Create an OAuth client of type "Desktop app".')
    _write_json(CLIENT_FILE, raw)
    # Tokens from another client can no longer refresh.
    for token in TOKENS_DIR.glob("*.json"):
        token.unlink(missing_ok=True)
    return status()


def _client() -> Dict[str, str]:
    raw = _read_json(CLIENT_FILE, None)
    c = (raw or {}).get("installed") if isinstance(raw, dict) else None
    if not c or not c.get("client_id"):
        raise YouTubeError("No Google OAuth client yet. Add it under the Bulk Editor tab (YouTube channels).")
    return c


def _channels() -> Dict[str, Dict[str, Any]]:
    data = _read_json(CHANNELS_FILE, {})
    return data if isinstance(data, dict) else {}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def brands() -> List[str]:
    from core.paths import BACKEND_DIR
    return sorted(p.stem for p in (Path(BACKEND_DIR) / "prompts" / "channels").glob("*.md"))


def _guess_brand(title: str) -> str:
    t = _norm(title)
    for brand in brands():
        if _norm(brand) and _norm(brand) in t:
            return brand
    return ""


def set_channel_brand(channel_id: str, brand: str) -> Dict[str, Any]:
    with _lock:
        chans = _channels()
        if channel_id not in chans:
            raise YouTubeError("Unknown channel.")
        if brand and brand not in brands():
            raise YouTubeError(f"Unknown brand '{brand}'.")
        for cid, info in chans.items():       # one channel per brand
            if brand and cid != channel_id and info.get("brand") == brand:
                info["brand"] = ""
        chans[channel_id]["brand"] = brand
        _write_json(CHANNELS_FILE, chans)
    return status()


def disconnect(channel_id: str) -> Dict[str, Any]:
    with _lock:
        chans = _channels()
        chans.pop(channel_id, None)
        _write_json(CHANNELS_FILE, chans)
        (TOKENS_DIR / f"{channel_id}.json").unlink(missing_ok=True)
    return status()


_login: Dict[str, Any] = {"state": "idle", "error": None, "channel": None}


def status() -> Dict[str, Any]:
    chans = _channels()
    return {
        "has_client": CLIENT_FILE.exists(),
        "channels": [
            {"id": cid, **info, "signed_in": (TOKENS_DIR / f"{cid}.json").exists()}
            for cid, info in sorted(chans.items(), key=lambda kv: kv[1].get("title", ""))
        ],
        "brands": brands(),
        "login": dict(_login),
        "categories": CATEGORIES,
    }


# ──────────────────────────────── sign-in ────────────────────────────────

def _token_request(params: Dict[str, str]) -> Dict[str, Any]:
    c = _client()
    body = {"client_id": c["client_id"], **params}
    if c.get("client_secret"):
        body["client_secret"] = c["client_secret"]
    resp = requests.post(TOKEN_URL, data=body, timeout=30)
    data = resp.json() if resp.content else {}
    if resp.status_code >= 400:
        err = data.get("error_description") or data.get("error") or resp.status_code
        if data.get("error") == "invalid_grant":
            raise YouTubeError("Google rejected this channel's sign-in (expired or revoked). "
                               "Connect the channel again under the Bulk Editor tab (YouTube channels).")
        raise YouTubeError(f"Google sign-in error: {err}")
    return data


def start_login() -> Dict[str, Any]:
    """Open Google's sign-in in the creator's browser and wait (in a thread)
    for the loopback redirect. Poll `status()["login"]` for the outcome."""
    client = _client()
    if _login.get("state") == "waiting":
        return {"auth_url": _login.get("auth_url")}

    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    result: Dict[str, Optional[str]] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server API
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            ok = q.get("state", [""])[0] == state and q.get("code")
            if not ok and not q.get("error"):
                self.send_response(404)
                self.end_headers()
                return
            result["code"] = q["code"][0] if ok else None
            result["error"] = None if ok else q.get("error", ["cancelled"])[0]
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(("Signed in. You can close this tab and go back to Buzzcaf Studio."
                              if ok else "Sign-in failed or was cancelled.").encode())

        def log_message(self, *args):  # keep the Studio log clean
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 1
    redirect = f"http://127.0.0.1:{server.server_port}"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client["client_id"], "redirect_uri": redirect, "response_type": "code",
        "scope": SCOPE, "code_challenge": challenge, "code_challenge_method": "S256",
        "access_type": "offline", "prompt": "select_account consent", "state": state,
    })
    _login.update(state="waiting", error=None, channel=None, auth_url=url)

    def wait() -> None:
        deadline = time.time() + LOGIN_TIMEOUT_S
        try:
            while "code" not in result and time.time() < deadline:
                server.handle_request()
            if not result.get("code"):
                raise YouTubeError("Sign-in timed out." if "code" not in result
                                   else f"Sign-in was not completed ({result.get('error')}).")
            tok = _token_request({"grant_type": "authorization_code", "code": result["code"],
                                  "code_verifier": verifier, "redirect_uri": redirect})
            if not tok.get("refresh_token"):
                raise YouTubeError("Google did not return a refresh token; try connecting again.")
            token = {"refresh_token": tok["refresh_token"], "access_token": tok.get("access_token"),
                     "expires_at": time.time() + float(tok.get("expires_in", 3600)) - 60}
            info = _get_channel(token["access_token"])
            with _lock:
                chans = _channels()
                prev = chans.get(info["id"], {})
                chans[info["id"]] = {"title": info["title"], "thumbnail": info.get("thumbnail", ""),
                                     "brand": prev.get("brand") or _guess_brand(info["title"]),
                                     "connected_at": datetime.now().isoformat(timespec="seconds")}
                _write_json(CHANNELS_FILE, chans)
                _write_json(TOKENS_DIR / f"{info['id']}.json", token)
            _login.update(state="done", channel=info["title"], auth_url=None)
            logger.info("YouTube: connected channel %s (%s).", info["title"], info["id"])
        except Exception as exc:  # noqa: BLE001 - shown to the creator
            logger.warning("YouTube sign-in failed: %s", exc)
            _login.update(state="failed", error=str(exc), auth_url=None)
        finally:
            server.server_close()

    threading.Thread(target=wait, name="youtube-login", daemon=True).start()
    webbrowser.open(url)
    return {"auth_url": url}


def _get_channel(access_token: str) -> Dict[str, str]:
    resp = requests.get(f"{API}/channels", params={"part": "snippet", "mine": "true"},
                        headers={"Authorization": f"Bearer {access_token}"}, timeout=30)
    _raise_for_api(resp)
    items = resp.json().get("items") or []
    if not items:
        raise YouTubeError("That Google account has no YouTube channel. At the account chooser, "
                           "pick the channel itself (Brand Accounts are listed separately).")
    sn = items[0]["snippet"]
    return {"id": items[0]["id"], "title": sn.get("title", ""),
            "thumbnail": ((sn.get("thumbnails") or {}).get("default") or {}).get("url", "")}


def _access_token(channel_id: str) -> str:
    path = TOKENS_DIR / f"{channel_id}.json"
    token = _read_json(path, None)
    if not token or not token.get("refresh_token"):
        raise YouTubeError("This channel is not signed in. Connect it under the Bulk Editor tab (YouTube channels).")
    if token.get("access_token") and time.time() < float(token.get("expires_at") or 0):
        return token["access_token"]
    tok = _token_request({"grant_type": "refresh_token", "refresh_token": token["refresh_token"]})
    token.update(access_token=tok["access_token"],
                 expires_at=time.time() + float(tok.get("expires_in", 3600)) - 60)
    _write_json(path, token)
    return token["access_token"]


def _raise_for_api(resp: requests.Response) -> None:
    if resp.status_code < 400:
        return
    try:
        err = resp.json().get("error") or {}
        reason = ((err.get("errors") or [{}])[0]).get("reason", "")
        message = err.get("message") or resp.text[:300]
    except ValueError:
        reason, message = "", resp.text[:300]
    if reason in ("quotaExceeded", "dailyLimitExceeded"):
        raise YouTubeError("YouTube's daily API quota for this Google project is used up "
                           "(an upload costs 1,600 of 10,000 units). Try again after midnight Pacific time.")
    if reason == "uploadLimitExceeded":
        raise YouTubeError("This channel hit YouTube's upload limit for today.")
    raise YouTubeError(f"YouTube API error {resp.status_code}: {message}")


# ──────────────────────────────── metadata ────────────────────────────────

def _parse_json_loose(text: str) -> Any:
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                return None
    return None


def _find_seo(obj: Any) -> Optional[Dict[str, Any]]:
    """The dict that carries titles/description/tags, wherever the agent nested it."""
    if isinstance(obj, dict):
        if any(k in obj for k in ("titles", "title")) and any(k in obj for k in ("tags", "description")):
            return obj
        for v in obj.values():
            hit = _find_seo(v)
            if hit:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = _find_seo(v)
            if hit:
                return hit
    return None


def parse_seo_package(text: str) -> Optional[Dict[str, Any]]:
    """{titles, description, tags, hashtags} from an SEO manager's output, or None."""
    seo = _find_seo(_parse_json_loose(text))
    if not seo:
        return None
    titles = seo.get("titles") or ([seo["title"]] if seo.get("title") else [])
    titles = [str(t.get("title") if isinstance(t, dict) else t).strip() for t in titles]
    tags = seo.get("tags") or []
    if isinstance(tags, str):
        tags = tags.split(",")
    hashtags = seo.get("hashtags") or []
    if isinstance(hashtags, str):
        hashtags = hashtags.split()
    return {
        "titles": [t for t in titles if t],
        "description": str(seo.get("description") or "").strip(),
        "tags": [str(t).strip().lstrip("#") for t in tags if str(t).strip()],
        "hashtags": [h if str(h).startswith("#") else f"#{h}" for h in (str(x).strip() for x in hashtags) if h],
    }


def description_with_hashtags(description: str, hashtags: List[str]) -> str:
    missing = [h for h in hashtags if h.lower() not in description.lower()]
    return (description.rstrip() + "\n\n" + " ".join(missing)).strip() if missing else description


def clean_title(title: str) -> str:
    title = re.sub(r"[<>]", "", " ".join((title or "").split()))
    return title[:100].rstrip()


def clean_description(text: str) -> str:
    text = re.sub(r"[<>]", "", text or "")
    data = text.encode("utf-8")
    return data[:5000].decode("utf-8", "ignore") if len(data) > 5000 else text


def clean_tags(tags: List[str]) -> List[str]:
    """YouTube allows 500 characters of tags; a tag with a space counts its quotes."""
    out, used, seen = [], 0, set()
    for tag in tags:
        tag = re.sub(r"[<>,]", "", str(tag)).strip()[:100]
        if not tag or tag.lower() in seen:
            continue
        cost = len(tag) + (2 if " " in tag else 0) + (1 if out else 0)
        if used + cost > 500:
            break
        out.append(tag)
        seen.add(tag.lower())
        used += cost
    return out


# ──────────────────────────────── upload ────────────────────────────────

def channel_for_brand(brand: str) -> Optional[str]:
    for cid, info in _channels().items():
        if info.get("brand") == brand:
            return cid
    return None


def upload(video_path: str, *, channel_id: str, title: str, description: str, tags: List[str],
           privacy: str = "unlisted", publish_at: Optional[str] = None, category_id: str = "24",
           made_for_kids: bool = False, synthetic_media: bool = True, language: str = "hi",
           thumbnail_path: Optional[str] = None, session_url: Optional[str] = None,
           on_session: Optional[Callable[[str], None]] = None,
           on_progress: Optional[Callable[[float, str], None]] = None) -> Dict[str, Any]:
    """Upload one video; returns {video_id, url, thumbnail_set, privacy}. Resumable:
    pass a `session_url` saved by `on_session` to continue an interrupted upload."""
    path = Path(video_path)
    if not path.is_file():
        raise YouTubeError(f"The rendered video is not on disk: {video_path}")
    size = path.stat().st_size
    progress = on_progress or (lambda f, m: None)
    if privacy not in ("private", "unlisted", "public"):
        raise YouTubeError(f"Unknown privacy '{privacy}'.")
    status_part: Dict[str, Any] = {"privacyStatus": privacy, "selfDeclaredMadeForKids": bool(made_for_kids),
                                   "containsSyntheticMedia": bool(synthetic_media)}
    if publish_at:
        # A scheduled video must be private until then.
        status_part.update(privacyStatus="private", publishAt=publish_at)
    body = {
        "snippet": {"title": clean_title(title), "description": clean_description(description),
                    "tags": clean_tags(tags), "categoryId": str(category_id or "24"),
                    "defaultLanguage": language, "defaultAudioLanguage": language},
        "status": status_part,
    }
    if not body["snippet"]["title"]:
        raise YouTubeError("The title is empty.")

    def headers(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        return {"Authorization": f"Bearer {_access_token(channel_id)}", **(extra or {})}

    if not session_url:
        resp = requests.post(f"{UPLOAD_API}/videos", params={"uploadType": "resumable", "part": "snippet,status"},
                             headers=headers({"Content-Type": "application/json; charset=UTF-8",
                                              "X-Upload-Content-Length": str(size),
                                              "X-Upload-Content-Type": "video/mp4"}),
                             data=json.dumps(body), timeout=60)
        _raise_for_api(resp)
        session_url = resp.headers.get("Location")
        if not session_url:
            raise YouTubeError("YouTube did not open an upload session.")
        if on_session:
            on_session(session_url)

    offset, retries, result = _confirmed_offset(session_url, size, headers), 0, None
    with path.open("rb") as fh:
        while result is None:
            if offset is None:   # the session already finished
                result = _finished(session_url, size, headers)
                break
            fh.seek(offset)
            chunk = fh.read(CHUNK_BYTES)
            end = offset + len(chunk) - 1
            try:
                resp = requests.put(session_url, data=chunk, timeout=(30, 600),
                                    headers=headers({"Content-Length": str(len(chunk)),
                                                     "Content-Range": f"bytes {offset}-{end}/{size}"}))
            except requests.RequestException as exc:
                resp, err = None, str(exc)
            else:
                err = f"HTTP {resp.status_code}"
            if resp is not None and resp.status_code in (200, 201):
                result = resp.json()
                break
            if resp is not None and resp.status_code == 308:
                offset, retries = _offset_from_range(resp.headers.get("Range")), 0
                progress(offset / size, f"Uploading... {offset / 1e6:,.0f} / {size / 1e6:,.0f} MB")
                continue
            if resp is not None and resp.status_code not in (500, 502, 503, 504, 401):
                _raise_for_api(resp)
            retries += 1
            if retries > MAX_RETRIES:
                raise YouTubeError(f"The upload kept failing ({err}). Press Publish again to resume it.")
            wait = min(60, 2 ** retries)
            progress(offset / size, f"Connection trouble ({err}); retrying in {wait}s...")
            time.sleep(wait)
            offset = _confirmed_offset(session_url, size, headers)

    video_id = result.get("id")
    if not video_id:
        raise YouTubeError("YouTube finished the upload but returned no video id.")
    thumb_ok, thumb_note = False, ""
    if thumbnail_path and Path(thumbnail_path).is_file():
        progress(0.99, "Setting the thumbnail...")
        try:
            set_thumbnail(channel_id, video_id, thumbnail_path)
            thumb_ok = True
        except YouTubeError as exc:
            thumb_note = str(exc)
    return {"video_id": video_id, "url": f"https://youtu.be/{video_id}", "thumbnail_set": thumb_ok,
            "thumbnail_error": thumb_note, "privacy": (result.get("status") or {}).get("privacyStatus", privacy),
            "upload_status": (result.get("status") or {}).get("uploadStatus", "")}


def _offset_from_range(range_header: Optional[str]) -> int:
    m = re.search(r"bytes=0-(\d+)", range_header or "")
    return int(m.group(1)) + 1 if m else 0


def _confirmed_offset(session_url: str, size: int, headers: Callable[..., Dict[str, str]]) -> Optional[int]:
    """Ask YouTube how much of the file it has. None = already complete."""
    try:
        resp = requests.put(session_url, headers=headers({"Content-Length": "0",
                                                          "Content-Range": f"bytes */{size}"}), timeout=60)
    except requests.RequestException:
        return 0
    if resp.status_code in (200, 201):
        return None
    if resp.status_code == 308:
        return _offset_from_range(resp.headers.get("Range"))
    if resp.status_code in (404, 410):
        raise YouTubeError("The saved upload session expired. Press Publish again to start a fresh upload.")
    return 0


def _finished(session_url: str, size: int, headers: Callable[..., Dict[str, str]]) -> Dict[str, Any]:
    resp = requests.put(session_url, headers=headers({"Content-Length": "0", "Content-Range": f"bytes */{size}"}),
                        timeout=60)
    _raise_for_api(resp)
    return resp.json()


def set_thumbnail(channel_id: str, video_id: str, image_path: str) -> None:
    data = Path(image_path).read_bytes()
    if len(data) > 2 * 1024 * 1024:
        raise YouTubeError("The thumbnail is over YouTube's 2 MB limit.")
    ctype = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"
    resp = requests.post(f"{UPLOAD_API}/thumbnails/set", params={"videoId": video_id, "uploadType": "media"},
                         headers={"Authorization": f"Bearer {_access_token(channel_id)}", "Content-Type": ctype},
                         data=data, timeout=120)
    if resp.status_code == 403:
        raise YouTubeError("YouTube refused the custom thumbnail: the channel must be verified "
                           "(youtube.com/verify) to use custom thumbnails.")
    _raise_for_api(resp)

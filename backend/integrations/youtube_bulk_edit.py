"""Bulk title / description edits across a whole YouTube channel.

The Studio's Bulk Editor tab (frontend/src/pages/BulkEdit.tsx, routes in
app/api/bulk_edit_api.py). It signs in through `youtube_publish` (the same
channels the Publish panel uploads to) and replaces the separate Node app that
used to live in ../bulk_edit.

Safe by design, as before:
- Preview is a dry run: a before/after for every video, nothing written.
- Apply writes a backup of the originals before the first edit, per channel
  (`backend/config/youtube/backups/<channel id>/`), and wants the number of
  videos typed back as confirmation.
- Restore puts titles/descriptions back from any backup.
- Rules are idempotent: added text is never stacked twice, and a re-run skips
  finished videos, so a quota-limited run just resumes the next day.
- Tags, category and languages are sent back unchanged (videos.update clears
  any snippet field left out).
- Titles over 100 characters, emptied titles, descriptions over 5000 bytes and
  `<` `>` are blocked per video instead of failing mid-run.

Quota: list calls cost 1 unit, videos.update 50 of the project's 10,000 a day.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

from integrations import youtube_publish as yt

TITLE_MAX = 100
DESCRIPTION_MAX_BYTES = 5000
UPDATE_COST = 50
MAX_UPDATES_PER_RUN = 190           # stays under the 10,000-unit daily quota
BACKUP_DIR = yt.YT_DIR / "backups"


class QuotaExceeded(yt.YouTubeError):
    pass


# ──────────────────────────────── rules ────────────────────────────────
#
# rules = {"title": FieldRule, "description": FieldRule, "privacy": ["public", ...]}
# FieldRule = {"remove": [str], "replace": [[find, with]], "prepend": str,
#              "append": str, "separator": str, "match_case": bool}
# A plain string matches literally, case-insensitively, and as a whole word when
# it starts/ends with a word character ("cat" will not cut into "category").
# "/pattern/flags" is a regex (flags i, m, s).

_REGEX = re.compile(r"^/(.+)/([ims]*)$", re.S)


def _pattern(entry: str, match_case: bool) -> re.Pattern:
    if not entry:
        raise ValueError("empty line in a remove/find list")
    m = _REGEX.match(entry)
    if m:
        flags = 0
        for f in m.group(2):
            flags |= {"i": re.I, "m": re.M, "s": re.S}[f]
        try:
            return re.compile(m.group(1), flags)
        except re.error as exc:
            raise ValueError(f"bad regex {entry}: {exc}")
    head = r"(?<!\w)" if re.match(r"\w", entry[0]) else ""
    tail = r"(?!\w)" if re.match(r"\w", entry[-1]) else ""
    return re.compile(head + re.escape(entry) + tail, 0 if match_case else re.I)


def apply_field(text: str, rule: Optional[Dict[str, Any]]) -> str:
    rule = rule or {}
    out = text
    match_case = bool(rule.get("match_case"))
    for entry in rule.get("remove") or []:
        out = _pattern(entry, match_case).sub("", out)
    for pair in rule.get("replace") or []:
        find, repl = pair[0], (pair[1] if len(pair) > 1 else "")
        out = _pattern(find, match_case).sub(lambda _m, r=repl: r, out)
    # Only tidy text a rule changed; untouched text stays byte-for-byte the same.
    if out != text:
        out = re.sub(r"[ \t]{2,}", " ", out)
        out = re.sub(r"[ \t]+$", "", out, flags=re.M)
        out = re.sub(r"[ \t]+([,.!?;:])", r"\1", out).strip()
    sep = rule.get("separator") if rule.get("separator") is not None else " "
    has = lambda needle: needle.strip().lower() in out.lower()  # noqa: E731
    prepend, append = rule.get("prepend") or "", rule.get("append") or ""
    if prepend.strip() and not has(prepend):
        out = prepend + sep + out if out else prepend
    if append.strip() and not has(append):
        out = out + sep + append if out else append
    return out


def validate(title: str, description: str) -> List[str]:
    problems = []
    if not title.strip():
        problems.append("title would be empty")
    if len(title) > TITLE_MAX:
        problems.append(f"title is {len(title)} characters (max {TITLE_MAX})")
    if re.search(r"[<>]", title):
        problems.append("title contains < or > (YouTube rejects it)")
    size = len(description.encode("utf-8"))
    if size > DESCRIPTION_MAX_BYTES:
        problems.append(f"description is {size} bytes (max {DESCRIPTION_MAX_BYTES})")
    if re.search(r"[<>]", description):
        problems.append("description contains < or > (YouTube rejects it)")
    return problems


def apply_rules(video: Dict[str, Any], rules: Dict[str, Any]) -> Dict[str, Any]:
    title_rule = rules.get("title") or {}
    new_title = apply_field(video["title"], title_rule)
    new_desc = apply_field(video["description"], rules.get("description"))
    problems = validate(new_title, new_desc)
    # A title emptied by removals must not be papered over by added text.
    removals_only = {k: v for k, v in title_rule.items() if k not in ("prepend", "append")}
    if video["title"].strip() and not apply_field(video["title"], removals_only).strip() \
            and not any("empty" in p for p in problems):
        problems.insert(0, "title would be empty after removals")
    return {"title": new_title, "description": new_desc, "problems": problems,
            "changed": new_title != video["title"] or new_desc != video["description"]}


# ──────────────────────────────── YouTube ────────────────────────────────

def _api(channel_id: str, method: str, resource: str, *, params: Optional[Dict[str, str]] = None,
         body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    for attempt in range(1, 5):
        resp = requests.request(method, f"{yt.API}/{resource}", params=params, json=body, timeout=60,
                                headers={"Authorization": f"Bearer {yt._access_token(channel_id)}"})
        if resp.status_code < 400:
            return resp.json()
        try:
            reason = ((resp.json().get("error") or {}).get("errors") or [{}])[0].get("reason", "")
        except ValueError:
            reason = ""
        if reason in ("quotaExceeded", "dailyLimitExceeded"):
            raise QuotaExceeded("YouTube's daily API quota is used up. Run it again tomorrow; "
                                "finished videos are skipped.")
        if resp.status_code in (429, 500, 502, 503) and attempt < 4:
            time.sleep(2 ** attempt)
            continue
        yt._raise_for_api(resp)
    raise yt.YouTubeError(f"{method} {resource} kept failing.")


def list_videos(channel_id: str, on_progress: Callable[[int], None] = lambda n: None) -> List[Dict[str, Any]]:
    """Every video on the channel: public, unlisted, private and Shorts."""
    ch = _api(channel_id, "GET", "channels", params={"part": "contentDetails", "mine": "true"})
    items = ch.get("items") or []
    if not items:
        raise yt.YouTubeError("This channel's sign-in has no YouTube channel.")
    uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    ids: List[str] = []
    page: Optional[str] = None
    while True:
        params = {"part": "contentDetails", "playlistId": uploads, "maxResults": "50"}
        if page:
            params["pageToken"] = page
        r = _api(channel_id, "GET", "playlistItems", params=params)
        ids += [i["contentDetails"]["videoId"] for i in r.get("items") or []]
        on_progress(len(ids))
        page = r.get("nextPageToken")
        if not page:
            break
    videos = []
    for i in range(0, len(ids), 50):
        r = _api(channel_id, "GET", "videos", params={"part": "snippet,status", "id": ",".join(ids[i:i + 50])})
        for v in r.get("items") or []:
            sn = v["snippet"]
            videos.append({
                "id": v["id"], "title": sn.get("title", ""), "description": sn.get("description") or "",
                "categoryId": sn.get("categoryId"), "tags": sn.get("tags"),
                "defaultLanguage": sn.get("defaultLanguage"), "defaultAudioLanguage": sn.get("defaultAudioLanguage"),
                "publishedAt": sn.get("publishedAt", ""), "privacy": (v.get("status") or {}).get("privacyStatus", ""),
            })
    return videos


def update_text(channel_id: str, video: Dict[str, Any], title: str, description: str) -> None:
    # videos.update replaces the whole snippet: send tags, category and languages back.
    snippet: Dict[str, Any] = {"title": title, "description": description, "categoryId": video["categoryId"]}
    for key in ("tags", "defaultLanguage", "defaultAudioLanguage"):
        if video.get(key):
            snippet[key] = video[key]
    _api(channel_id, "PUT", "videos", params={"part": "snippet"}, body={"id": video["id"], "snippet": snippet})


# ──────────────────────────────── plans, backups, jobs ────────────────────────────────

_previews: Dict[str, Dict[str, Any]] = {}       # preview id -> {channel_id, videos, items}
_job: Dict[str, Any] = {"state": "idle"}
_job_lock = threading.Lock()


def preview(channel_id: str, rules: Dict[str, Any]) -> Dict[str, Any]:
    for side in ("title", "description"):     # surface bad patterns before any network call
        for entry in (rules.get(side) or {}).get("remove") or []:
            _pattern(entry, False)
        for pair in (rules.get(side) or {}).get("replace") or []:
            _pattern(pair[0], False)
    videos = list_videos(channel_id)
    privacy = set(rules.get("privacy") or ["public", "unlisted", "private"])
    items = []
    for v in videos:
        if v["privacy"] not in privacy:
            continue
        nxt = apply_rules(v, rules)
        if nxt["changed"]:
            items.append({"id": v["id"], "privacy": v["privacy"], "published_at": v["publishedAt"],
                          "title": v["title"], "new_title": nxt["title"],
                          "description": v["description"], "new_description": nxt["description"],
                          "problems": nxt["problems"]})
    pid = uuid.uuid4().hex[:12]
    _previews.clear()                          # only the latest preview can be applied
    _previews[pid] = {"channel_id": channel_id, "videos": {v["id"]: v for v in videos}, "items": items}
    return {"preview_id": pid, "channel_id": channel_id, "total_videos": len(videos), "items": items,
            "max_per_run": MAX_UPDATES_PER_RUN}


def _channel_dir(channel_id: str) -> Path:
    if not re.fullmatch(r"[\w-]+", channel_id or ""):
        raise yt.YouTubeError("Bad channel id.")
    return BACKUP_DIR / channel_id


def write_backup(channel_id: str, videos: List[Dict[str, Any]], label: str) -> str:
    folder = _channel_dir(channel_id)
    folder.mkdir(parents=True, exist_ok=True)
    name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".json"
    data = {"created_at": datetime.now().isoformat(timespec="seconds"), "label": label,
            "videos": [{"id": v["id"], "title": v["title"], "description": v["description"]} for v in videos]}
    (folder / name).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return name


def list_backups(channel_id: str) -> List[Dict[str, Any]]:
    out = []
    for path in sorted(_channel_dir(channel_id).glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            out.append({"name": path.name, "created_at": data.get("created_at"), "label": data.get("label", ""),
                        "count": len(data.get("videos") or [])})
        except (OSError, ValueError):
            continue
    return out


def job() -> Dict[str, Any]:
    with _job_lock:
        return json.loads(json.dumps(_job))


def _start_job(kind: str, channel_id: str, entries: List[Dict[str, Any]], backup: str) -> Dict[str, Any]:
    with _job_lock:
        if _job.get("state") == "running":
            raise yt.YouTubeError("Another bulk edit is still running.")
        _job.clear()
        _job.update(state="running", kind=kind, channel_id=channel_id, total=len(entries), done=0, failed=0,
                    backup=backup, log=[], message="", started_at=datetime.now().isoformat(timespec="seconds"))

    def log(line: str) -> None:
        with _job_lock:
            _job["log"] = (_job["log"] + [line])[-400:]

    def run() -> None:
        try:
            for e in entries:
                try:
                    update_text(channel_id, e["video"], e["title"], e["description"])
                    with _job_lock:
                        _job["done"] += 1
                    log(f"OK  {e['title']}")
                except QuotaExceeded as exc:
                    with _job_lock:
                        _job.update(message=str(exc))
                    log(f"STOP  {exc}")
                    break
                except Exception as exc:  # noqa: BLE001 - one video failing does not stop the run
                    with _job_lock:
                        _job["failed"] += 1
                    log(f"FAIL  {e['video']['title']}: {exc}")
        finally:
            with _job_lock:
                _job["state"] = "done"
                _job["finished_at"] = datetime.now().isoformat(timespec="seconds")

    threading.Thread(target=run, name=f"bulk-edit-{kind}", daemon=True).start()
    return job()


def apply(preview_id: str, ids: List[str], confirm: int) -> Dict[str, Any]:
    plan = _previews.get(preview_id)
    if not plan:
        raise yt.YouTubeError("That preview is out of date. Press Preview again.")
    wanted = set(ids)
    items = [i for i in plan["items"] if i["id"] in wanted and not i["problems"]]
    if not items:
        raise yt.YouTubeError("Nothing selected to change.")
    if len(items) > MAX_UPDATES_PER_RUN:
        raise yt.YouTubeError(f"Select at most {MAX_UPDATES_PER_RUN} videos per run (the daily quota); "
                              "run the rest tomorrow.")
    if int(confirm) != len(items):
        raise yt.YouTubeError(f"Type {len(items)} to confirm.")
    videos = plan["videos"]
    backup = write_backup(plan["channel_id"], [videos[i["id"]] for i in items], f"before editing {len(items)} videos")
    entries = [{"video": videos[i["id"]], "title": i["new_title"], "description": i["new_description"]}
               for i in items]
    _previews.pop(preview_id, None)
    return _start_job("apply", plan["channel_id"], entries, backup)


def restore_plan(channel_id: str, backup_name: str) -> Dict[str, Any]:
    path = _channel_dir(channel_id) / Path(backup_name).name
    try:
        backup = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise yt.YouTubeError("That backup could not be read.")
    current = {v["id"]: v for v in list_videos(channel_id)}
    # Pair each backup entry with the video's CURRENT data, so tags/category round-trip from now.
    entries = [{"video": current[b["id"]], "title": b["title"], "description": b["description"]}
               for b in backup.get("videos") or []
               if b["id"] in current and (current[b["id"]]["title"] != b["title"]
                                          or current[b["id"]]["description"] != b["description"])]
    return {"entries": entries, "backup": backup}


def restore(channel_id: str, backup_name: str, confirm: int) -> Dict[str, Any]:
    entries = restore_plan(channel_id, backup_name)["entries"]
    if not entries:
        raise yt.YouTubeError("Every video already matches that backup; nothing to restore.")
    if int(confirm) != len(entries):
        raise yt.YouTubeError(f"Type {len(entries)} to confirm.")
    return _start_job("restore", channel_id, entries, backup_name)

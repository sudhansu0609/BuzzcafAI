"""Read-only knowledge the Studio Director can look up when answering questions:
the project's own docs, the health rows, the recent log errors, provider status,
the persona roster and a redacted settings summary.

Nothing here writes, and nothing returns a credential: documents come only from
an allowlist of Markdown globs, every output passes through ``_scrub``.
"""
import glob
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.paths import KNOWLEDGE_DIR, LOGS_DIR, PROJECT_ROOT, PROMPTS_DIR

ROOT = Path(PROJECT_ROOT).resolve()

DOC_GLOBS: List[str] = [
    str(ROOT / "*.md"),
    str(ROOT / "docs" / "*.md"),
    os.path.join(str(PROMPTS_DIR), "channels", "*.md"),
    os.path.join(str(PROMPTS_DIR), "agents", "StudioDirector.md"),
    os.path.join(str(KNOWLEDGE_DIR), "director", "rules.md"),
]

READ_CAP = 3400
INDEX_CAP = 4000
_BAD_NAME = re.compile(r"secret|token|key|\.env", re.I)
_SECRET_RE = re.compile(r"(?i)(sk-|AIza|ya29\.|ghp_|bearer\s+|basic\s+|x-api-key[\"':=\s]+|[?&](?:key|api_key|token|access_token)=)[^\s&\"']+")
_SENSITIVE_KEY = re.compile(r"(api_key|secret|token|password|cookie|client_id|oauth|credential)", re.I)


def _scrub(text: Any) -> str:
    return _SECRET_RE.sub("[REDACTED]", str(text))


def _allowed_files() -> List[Path]:
    seen: Dict[str, Path] = {}
    for pattern in DOC_GLOBS:
        for f in glob.glob(pattern):
            p = Path(f)
            if p.is_file() and not p.is_symlink() and p.resolve().suffix.lower() == ".md":
                seen[str(p.resolve())] = p.resolve()
    return sorted(seen.values(), key=lambda p: str(p))


def _rel(p: Path) -> str:
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def _resolve(path: str) -> Optional[Path]:
    """The doc under PROJECT_ROOT, or None when it is not an allowed document."""
    if not path or not isinstance(path, str):
        return None
    if not path.lower().endswith(".md") or _BAD_NAME.search(path):
        return None
    try:
        p = Path(path)
        full = (p if p.is_absolute() else ROOT / p).resolve()
        full.relative_to(ROOT)
    except Exception:  # noqa: BLE001
        return None
    if _BAD_NAME.search(full.name):
        return None
    if full not in _allowed_files():
        return None
    return full


def _read_lines(p: Path) -> List[str]:
    return p.read_text(encoding="utf-8", errors="replace").splitlines()


def _headings(lines: List[str]) -> List[tuple]:
    out, in_code = [], False
    for i, ln in enumerate(lines, 1):
        if ln.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if not in_code and re.match(r"^#{1,6}\s+\S", ln):
            out.append((i, ln.strip()))
    return out


_index_cache: Dict[str, Any] = {"key": None, "value": []}


def knowledge_index() -> List[Dict[str, Any]]:
    files = _allowed_files()
    key = tuple((str(f), f.stat().st_mtime) for f in files)
    if _index_cache["key"] == key:
        return _index_cache["value"]
    out = []
    for f in files:
        try:
            lines = _read_lines(f)
        except OSError:
            continue
        summary = next((ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")), "")
        out.append({
            "path": _rel(f),
            "lines": len(lines),
            "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
            "summary": _scrub(summary[:120]),
            "headings": [[n, h] for n, h in _headings(lines)][:25],
        })
    _index_cache["key"], _index_cache["value"] = key, out
    return out


def index_text() -> str:
    lines = [f"{d['path']} -- {d['summary']} ({d['lines']} lines)" for d in knowledge_index()]
    return "\n".join(lines)[:INDEX_CAP]


def _numbered(lines: List[str], start: int) -> List[str]:
    return [f"{start + i}: {ln}" for i, ln in enumerate(lines)]


def _cap(rows: List[str], header: str, next_hint: str) -> str:
    body, used = [], len(header)
    for r in rows:
        if used + len(r) + 1 > READ_CAP:
            body.append(f"... [truncated at {READ_CAP} chars; {next_hint}]")
            break
        body.append(r)
        used += len(r) + 1
    return _scrub(header + "\n".join(body))


def read_doc(path: str, heading: Optional[str] = None, start: Optional[int] = None,
             end: Optional[int] = None, grep: Optional[str] = None) -> str:
    p = _resolve(path)
    if p is None:
        raise ValueError(f"'{path}' is not a readable document (see docs_index for the allowed list)")
    lines = _read_lines(p)
    rel = _rel(p)
    total = len(lines)
    if heading:
        want = heading.strip().lstrip("#").strip().lower()
        hs = _headings(lines)
        for idx, (n, h) in enumerate(hs):
            level = len(h) - len(h.lstrip("#"))
            if want in h.lstrip("#").strip().lower():
                stop = total + 1
                for n2, h2 in hs[idx + 1:]:
                    if len(h2) - len(h2.lstrip("#")) <= level:
                        stop = n2
                        break
                return _cap(_numbered(lines[n - 1:stop - 1], n), f"{rel} section '{h}' lines {n}-{stop - 1}\n",
                            f"continue with start={n + 40}, end={stop - 1}")
        return f"No heading containing '{heading}' in {rel}. Headings: " + _scrub(
            "; ".join(f"{n}:{h}" for n, h in _headings(lines)[:25]))
    if grep:
        rx = re.compile(re.escape(grep), re.I)
        hit_lines = [i for i, ln in enumerate(lines) if rx.search(ln)]
        shown, rows, last = hit_lines[:30], [], -1
        for i in shown:
            lo, hi = max(0, i - 2), min(total, i + 3)
            if lo <= last:
                lo = last + 1
            elif rows:
                rows.append("--")
            rows.extend(_numbered(lines[lo:hi], lo + 1))
            last = hi - 1
        head = f"{rel} grep '{grep}': {len(hit_lines)} hit(s)" + (", first 30 shown" if len(hit_lines) > 30 else "") + "\n"
        if not hit_lines:
            return head + "(no matches)"
        return _cap(rows, head, "narrow the grep or use start/end")
    s = max(1, int(start or 1))
    e = min(total, int(end or (s + 79)))
    if e < s:
        e = s
    return _cap(_numbered(lines[s - 1:e], s), f"{rel} lines {s}-{e} of {total}\n",
                f"continue with start={e + 1}")


def health_report(state: Optional[str] = None) -> List[Dict[str, Any]]:
    from app.services import health_checks
    rows = health_checks.run_all().get("checks", [])
    out = []
    for r in rows:
        if state and str(r.get("state")) != state:
            continue
        out.append({"id": r.get("id"), "label": r.get("label"), "state": r.get("state"),
                    "summary": _scrub(r.get("summary", "")), "detail": _scrub(str(r.get("detail", ""))[:200]),
                    "checked_at": r.get("checked_at")})
    return out


_LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})[,.]?\d* \[?(\w+)\]? (.*)$")


def _normalise(msg: str) -> str:
    msg = msg[:600]
    msg = re.sub(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", "<id>", msg)
    msg = re.sub(r"\b0x[0-9a-fA-F]+\b|\b[0-9a-fA-F]{12,}\b", "<id>", msg)
    msg = re.sub(r"[A-Za-z]:[\\/][^\s'\"]*|(?<![\w:])/(?:[\w.\-]+/)+[\w.\-]*", "/<path>", msg)
    msg = re.sub(r"'[^']*'|\"[^\"]*\"", "'<s>'", msg)
    msg = re.sub(r"\d+", "#", msg)
    return msg[:160]


def _tail(path: str, nbytes: int = 5 * 1024 * 1024) -> str:
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - nbytes))
        return f.read().decode("utf-8", errors="replace")


def log_digest(hours: int = 24, levels=("ERROR", "CRITICAL", "WARNING")) -> List[Dict[str, Any]]:
    path = os.path.join(str(LOGS_DIR), "studio.log")
    if not os.path.isfile(path):
        path = os.path.join(str(LOGS_DIR), "app.log")
    if not os.path.isfile(path):
        return []
    try:
        text = _tail(path)
    except OSError:
        return []
    cutoff = datetime.now() - timedelta(hours=float(hours or 24))
    groups: Dict[tuple, Dict[str, Any]] = {}
    for ln in text.splitlines():
        m = _LINE_RE.match(ln)
        if not m or m.group(2) not in levels:
            continue
        try:
            when = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if when < cutoff:
            continue
        pat = _normalise(m.group(3))
        g = groups.setdefault((m.group(2), pat), {"level": m.group(2), "pattern": _scrub(pat), "count": 0,
                                                  "last_seen": m.group(1), "example": _scrub(m.group(3)[:220])})
        g["count"] += 1
        g["last_seen"] = m.group(1)
        g["example"] = _scrub(m.group(3)[:220])
    return sorted(groups.values(), key=lambda g: -g["count"])[:25]


def llm_status() -> Dict[str, Any]:
    from integrations.llm import load_config, probe_claude, probe_gemini
    cfg = load_config()
    out: Dict[str, Any] = {
        "selected_provider": cfg.get("selected_provider"),
        "local_only": cfg.get("local_only"),
        "tiers": _clean(cfg.get("tiers")),
        "lm_studio_model": cfg.get("lm_studio_model"),
    }
    for name, fn in (("gemini", probe_gemini), ("claude", probe_claude)):
        try:
            p = fn(cfg)
            out[name] = {"url": p.get("url"), "model": p.get("model"), "online": bool(p.get("online")),
                         "message": _scrub(p.get("message", "")), "key_set": bool(p.get("key_set"))}
        except Exception as exc:  # noqa: BLE001
            out[name] = {"online": False, "message": _scrub(str(exc)[:160])}
    try:
        from app.services import studio_director
        out["director_provider"] = studio_director.settings().get("provider") or ""
    except Exception:  # noqa: BLE001
        out["director_provider"] = ""
    return out


def persona_roster() -> Dict[str, List[Dict[str, Any]]]:
    from core.agent import agent_registry
    out: Dict[str, List[Dict[str, Any]]] = {}
    for a in agent_registry.agents.values():
        out.setdefault(getattr(a, "department", None) or "General", []).append({
            "name": a.name, "role": (getattr(a, "role", "") or "")[:90],
            "model_tier": getattr(a, "model_tier", "strong")})
    for v in out.values():
        v.sort(key=lambda d: d["name"])
    return out


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()
                if not (_SENSITIVE_KEY.search(str(k)) and not str(k).endswith("_set"))}
    if isinstance(value, list):
        return [_clean(v) for v in value[:10]]
    if isinstance(value, str):
        return _scrub(value[:120])
    return value


def settings_summary() -> Dict[str, Any]:
    from integrations.llm import load_config
    from app.main import _redact_settings
    return _clean(_redact_settings(load_config()))

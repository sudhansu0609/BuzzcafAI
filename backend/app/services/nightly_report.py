
"""
The morning report (2026-10-22): one page that says what last night's run
did, so the creator reads one thing instead of project folders and logs.

Built from the records the nightly run already writes -- `last_run.json`
(the Shorts batch, the long-form run, the audience mining, the hibernate
decision), `longform_status.json` (per channel: topic, project, where it
stopped) and the audience settings' last pass -- plus what the archive
sweep did. Written to `knowledge/nightly/reports/<date>.md` with a JSON
twin, served by `GET /api/nightly/report`, and shown on the Dashboard as
"Last night".
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.paths import KNOWLEDGE_DIR

logger = logging.getLogger("buzzcaf_ai.nightly_report")

NIGHTLY_DIR = Path(KNOWLEDGE_DIR) / "nightly"
REPORTS_DIR = NIGHTLY_DIR / "reports"
KEEP = 60


def _read(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _minutes(seconds: Any) -> str:
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return ""
    return f"{s / 60:.0f} min" if s >= 90 else f"{s:.0f} s"


def _span(a: Any, b: Any) -> str:
    try:
        return _minutes((datetime.fromisoformat(str(b)) - datetime.fromisoformat(str(a))).total_seconds())
    except (TypeError, ValueError):
        return ""


def build(archive: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The report for the most recent run on disk (whatever its date)."""
    run = _read(NIGHTLY_DIR / "last_run.json") or {}
    run_lf = _read(NIGHTLY_DIR / "last_run_longform.json") or {}
    # The newer of the two records is "last night".
    if str(run_lf.get("started_at") or "") > str(run.get("started_at") or ""):
        run = run_lf
    lf_status = _read(NIGHTLY_DIR / "longform_status.json") or {}
    try:
        from app.services import audience_desk
        audience_last = audience_desk.settings().get("last") or {}
    except Exception:  # noqa: BLE001
        audience_last = {}

    started = str(run.get("started_at") or "")
    date = started[:10] or datetime.now().date().isoformat()
    lines: List[str] = [f"# Last night: {date}", ""]
    items: List[Dict[str, Any]] = []
    problems: List[str] = []

    if not run:
        lines.append("No nightly run has been recorded yet.")
        return {"date": date, "started_at": "", "markdown": "\n".join(lines), "items": items, "problems": problems,
                "headline": "No nightly run recorded yet"}

    duration = _span(run.get("started_at"), run.get("finished_at"))
    lines.append(f"Started {started[11:16]}, took {duration or '?'} ({run.get('scope', 'all')}).")
    net = run.get("network")
    if net is False:
        problems.append("No network: the run could not search or fetch.")
    lm = run.get("lm_studio")
    if isinstance(lm, dict) and lm.get("error"):
        problems.append(f"LM Studio: {lm['error']}")

    for task in run.get("tasks") or []:
        name = str(task.get("task") or "")
        if task.get("error"):
            problems.append(f"{name}: {str(task['error'])[:200]}")
            items.append({"task": name, "state": "failed", "detail": str(task["error"])[:200]})
            continue
        # `skipped` is a reason string when the whole task did not run, and a
        # list of per-channel skips when it did.
        if isinstance(task.get("skipped"), str) and task["skipped"]:
            items.append({"task": name, "state": "skipped", "detail": task["skipped"]})
            continue
        if name == "shorts_daily":
            built = task.get("built") or []
            skipped = task.get("skipped") or []
            lines += ["", f"## Shorts ({_minutes(task.get('seconds'))})", ""]
            if built:
                for b in built:
                    lines.append(f"- {b.get('channel')}: **{b.get('title')}** (score {b.get('score', '?')}) -> `{b.get('project_id')}`")
            else:
                lines.append("- Nothing built.")
            for s in skipped:
                lines.append(f"- {s.get('channel')}: skipped, {s.get('reason')}")
            items.append({"task": name, "state": "done", "built": len(built), "skipped": len(skipped), "seconds": task.get("seconds")})
        elif name == "longform":
            built = task.get("built") or []
            lines += ["", f"## Long videos ({_minutes(task.get('seconds'))})", ""]
            if built:
                for b in built:
                    lines.append(f"- {b.get('channel')}: **{b.get('title')}**, stopped at {b.get('current_step', '?')} -> `{b.get('project_id')}`")
            else:
                lines.append("- Nothing built.")
            for s in task.get("skipped") or []:
                lines.append(f"- {s.get('channel')}: skipped, {s.get('reason')}")
            items.append({"task": name, "state": "done", "built": len(built), "seconds": task.get("seconds")})
        elif name == "audience":
            done = task.get("done") or []
            saved = task.get("saved") or []
            failed = task.get("failed") or []
            lines += ["", f"## Viewer requests ({_minutes(task.get('seconds'))})", ""]
            for d in done:
                lines.append(f"- {d.get('brand')}: {d.get('comments')} comments under {d.get('videos')} videos, {d.get('findings')} findings")
            for s in saved:
                lines.append(f"- Saved to the vault: **{s.get('topic')}** ({s.get('brand')}, {s.get('mentions')} viewers)")
            for f in failed:
                problems.append(f"audience {f.get('brand')}: {f.get('error')}")
            items.append({"task": name, "state": "done", "saved": len(saved), "failed": len(failed), "seconds": task.get("seconds")})
        elif name == "auto_story":
            made = task.get("made") or []
            failed = task.get("failed") or []
            lines += ["", f"## Made by itself ({_minutes(task.get('seconds'))})", ""]
            for m in made:
                posted = m.get("posted") or {}
                yt = posted.get("youtube") or {}
                where = ", ".join(x for x in (
                    f"YouTube {yt.get('url')}" if yt.get("url") else "",
                    "Instagram package" if posted.get("instagram") == "packaged" else "") if x) or "not published"
                lines.append(f"- {m.get('channel')} ({m.get('format')}): **{m.get('name') or m.get('project_id')}**, "
                             f"{m.get('state')} ({where}) -> `{m.get('project_id')}`")
            if not made:
                lines.append("- Nothing made.")
            for f in failed:
                lines.append(f"- {f.get('channel')} ({f.get('format')}): failed, {f.get('error')}")
                problems.append(f"auto story {f.get('channel')}/{f.get('format')}: {f.get('error')}")
            items.append({"task": name, "state": "done", "made": len(made), "failed": len(failed), "seconds": task.get("seconds")})
        elif name == "writing_style":
            lines += ["", "## Writing style", "", f"- Rebuilt the guide for: {', '.join(task.get('rebuilt') or [])}"]
            items.append({"task": name, "state": "done"})
        elif name == "archive":
            arch = task.get("archived") or []
            if arch:
                lines += ["", "## Archived", ""] + [f"- {a.get('brand')}: {a.get('name')} (untouched {a.get('days')} days)" for a in arch]
            items.append({"task": name, "state": "done", "archived": len(arch)})
        else:
            items.append({"task": name, "state": "done"})

    if archive and archive.get("archived"):
        lines += ["", "## Archived this morning", ""] + \
                 [f"- {a.get('brand')}: {a.get('name')} (untouched {a.get('days')} days)" for a in archive["archived"]]

    # Where each long-form channel stopped, from the status file.
    stuck = [t for t in (lf_status.get("tasks") or []) if t.get("stage") not in ("done", None) and t.get("detail")]
    if lf_status.get("error"):
        problems.append(f"long-form: {lf_status['error']}")
    if stuck:
        lines += ["", "## Waiting for you", ""] + [f"- {t.get('channel')}: {t.get('topic')} -- {t.get('detail')}" for t in stuck]

    if audience_last and audience_last.get("ran_at", "")[:10] == date and not any(i["task"] == "audience" for i in items):
        saved = audience_last.get("saved") or []
        if saved:
            lines += ["", "## Viewer requests", ""] + [f"- **{s.get('topic')}** ({s.get('brand')}, {s.get('mentions')} viewers)" for s in saved]

    dec = run.get("hibernate") or {}
    if dec:
        lines += ["", "## Afterwards", "",
                  "- Hibernated." if dec.get("hibernate") else f"- Stayed awake: {'; '.join(dec.get('reasons') or [])}"]
    if problems:
        lines = lines[:2] + ["## Problems", ""] + [f"- {p}" for p in problems] + [""] + lines[2:]

    built_total = sum(int(i.get("built") or 0) for i in items)
    saved_total = sum(int(i.get("saved") or 0) for i in items)
    headline = (f"{built_total} video{'s' if built_total != 1 else ''} written"
                + (f", {saved_total} viewer request{'s' if saved_total != 1 else ''} saved" if saved_total else "")
                + (f", {len(problems)} problem{'s' if len(problems) != 1 else ''}" if problems else "")
                + (f", {duration}" if duration else ""))
    return {"date": date, "started_at": started, "finished_at": run.get("finished_at"), "headline": headline,
            "markdown": "\n".join(lines).strip() + "\n", "items": items, "problems": problems}


def write(archive: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    report = build(archive)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / f"{report['date']}.md").write_text(report["markdown"], encoding="utf-8")
    (REPORTS_DIR / f"{report['date']}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for old in sorted(REPORTS_DIR.glob("*.md"))[:-KEEP]:
        for p in (old, old.with_suffix(".json")):
            try:
                p.unlink()
            except OSError:
                pass
    return report


def latest() -> Dict[str, Any]:
    """The newest written report, or one built now from the records."""
    files = sorted(REPORTS_DIR.glob("*.json"))
    if files:
        data = _read(files[-1])
        if data:
            data["from_file"] = files[-1].name
            return data
    return build()


def list_reports() -> List[Dict[str, Any]]:
    out = []
    for path in sorted(REPORTS_DIR.glob("*.json"), reverse=True):
        data = _read(path) or {}
        out.append({"date": path.stem, "headline": data.get("headline", ""), "problems": len(data.get("problems") or [])})
    return out


def get(date: str) -> Optional[Dict[str, Any]]:
    return _read(REPORTS_DIR / f"{date}.json")

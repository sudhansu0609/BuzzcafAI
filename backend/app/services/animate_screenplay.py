"""Verbatim screenplay converter (ANIMATED_CHANNELS_PLAN ST2).

The creator's stories are first-person Hinglish narration with people described,
not named. The model only extracts a stable cast and LABELS numbered units of
the script (scene breaks, speakers, tags, action lines); this code assembles the
screenplay by COPYING his sentences, then verifies that the spoken text is
unchanged. The model never returns text to be spoken.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("buzzcaf_ai.animate_screenplay")

QUOTE_RE = re.compile(r'"([^"]+)"|“([^”]+)”|«([^»]+)»')
QUOTE_MARKS = '"“”«»'
SENT_RE = re.compile(r'(?<=[.!?।…])\s+')
BATCH = 120
NL = chr(10)


class ScreenplayError(RuntimeError):
    pass


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# --- 1. units ---------------------------------------------------------------------

def split_units(script: str) -> List[Dict[str, Any]]:
    """Numbered units, exact text: quoted speech (`quote`) and narration sentences (`narr`)."""
    units: List[Dict[str, Any]] = []

    def add(kind: str, text: str) -> None:
        text = norm(text)
        if text:
            units.append({"n": len(units) + 1, "kind": kind, "text": text})

    pos = 0
    for m in QUOTE_RE.finditer(script):
        for s in SENT_RE.split(script[pos:m.start()]):
            add("narr", s)
        add("quote", m.group(1) or m.group(2) or m.group(3))
        pos = m.end()
    for s in SENT_RE.split(script[pos:]):
        add("narr", s)
    return units


def source_spoken(script: str) -> str:
    return norm(script.translate({ord(c): " " for c in QUOTE_MARKS}))


# --- model helpers ----------------------------------------------------------------

def _find(data: Any, keys: tuple) -> Dict[str, Any]:
    if isinstance(data, dict):
        if any(k in data for k in keys):
            return data
        for v in data.values():
            f = _find(v, keys)
            if f:
                return f
    elif isinstance(data, list):
        for v in data:
            f = _find(v, keys)
            if f:
                return f
    return {}


def _ask(agent: str, task: Dict[str, Any], keys: tuple) -> Dict[str, Any]:
    from app.services.shorts_desk import _agent_json
    from integrations.llm import llm_job
    with llm_job("script", "animation screenplay"):
        data = _agent_json(agent, task)
    found = _find(data, keys) if data else {}
    if not found:
        raise ScreenplayError(f"{agent} returned no usable {'/'.join(keys)}.")
    return found


# --- 2. cast ----------------------------------------------------------------------

def cast_registry_path(brand: str) -> Path:
    from core.paths import KNOWLEDGE_DIR
    return Path(KNOWLEDGE_DIR) / "cast" / f"{brand}.json"


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _keys(c: Dict[str, Any]) -> set:
    out = {norm(str(c.get("name", ""))).lower(), norm(str(c.get("id", ""))).lower()}
    out |= {norm(str(a)).lower() for a in c.get("aliases") or []}
    return {k for k in out if k}


def _same(a: Dict[str, Any], b: Dict[str, Any], generic: frozenset = frozenset()) -> bool:
    if a.get("first_person") and b.get("first_person"):
        return True
    # A word the story uses for two people ("vanrakshak" for both guards) names
    # nobody: it merged Pawan and Rishi into one character (2026-10-29).
    if (_keys(a) - generic) & (_keys(b) - generic):
        return True
    # Same role and the same written look, when there is a look to compare (two blank
    # looks matched every guard to the first one).
    look_a, look_b = norm(a.get("look", "")).lower(), norm(b.get("look", "")).lower()
    return bool(a.get("role") and look_a and norm(a["role"]).lower() == norm(b.get("role", "")).lower()
                and look_a == look_b)


def merge_registry(cast: List[Dict[str, Any]], registry: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Returns (episode cast with registry ids/names/looks reused, updated registry)."""
    registry = [dict(r) for r in registry]
    # A word used for more than one person -- in this episode or across the channel's
    # registry -- identifies nobody.
    def shared(people: List[Dict[str, Any]]) -> set:
        counts: Dict[str, int] = {}
        for c in people:
            for k in _keys(c):
                counts[k] = counts.get(k, 0) + 1
        return {k for k, n in counts.items() if n > 1}
    # Counted among the registry and among this episode separately: the same person in
    # both is one person, not two.
    generic = frozenset(shared(list(cast)) | shared(registry))
    taken: set = set()  # two people of one episode never become one cast member
    out = []
    for c in cast:
        hit = next((r for r in registry if id(r) not in taken and _same(c, r, generic)), None)
        if hit:
            taken.add(id(hit))
            merged = dict(c)
            for k in ("id", "name", "look", "clothes", "gender", "age"):
                if hit.get(k):
                    merged[k] = hit[k]
            hit["aliases"] = sorted(set(hit.get("aliases") or []) | set(c.get("aliases") or []))
            out.append(merged)
        else:
            entry = dict(c)
            registry.append(entry)
            taken.add(id(entry))
            out.append(dict(c))
    return out, registry


def extract_cast(script: str, registry: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    found = _ask("CharacterPlanner", {
        "task": "cast_extraction",
        "instruction": (
            "Read this first-person Hinglish story and list every person in it as a stable cast. "
            "People are described, not named ('ek budhi aurat', 'truck wala'): give each a short "
            "descriptive stable name ('Budhi Amma', 'Truck Driver'). The first-person narrator "
            "(main/maine/mujhe) is a character too (first_person true). Return ONLY JSON "
            '{"cast":[{"id":"UPPER_SNAKE","name":"","role":"","gender":"","age":"","look":"","clothes":"",'
            '"aliases":["phrases the text uses for them"],"first_person":false}]}. '
            "Reuse an id/name from known_cast when it is the same person. Every distinct person gets their own "
            "id, even when two share a role (two guards are two people). `look` is permanent appearance only "
            "(age, build, face, hair, skin) from the text, never a passing state (scared, pale, tired); "
            "never write any spoken line."),
        "known_cast": [{k: r.get(k) for k in ("id", "name", "role", "aliases", "look", "first_person")} for r in registry],
        "story": script,
    }, ("cast",))
    cast = []
    for c in found.get("cast") or []:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        c = dict(c)
        c["name"] = norm(str(c["name"]))
        c["id"] = re.sub(r"[^A-Z0-9_]", "", re.sub(r"\s+", "_", str(c.get("id") or c["name"]).upper())) or "X"
        c["aliases"] = [str(a) for a in c.get("aliases") or []]
        c["first_person"] = bool(c.get("first_person"))
        cast.append(c)
    if not cast:
        raise ScreenplayError("The cast came back empty.")
    return cast


# --- 3. labels --------------------------------------------------------------------

def get_labels(units: List[Dict[str, Any]], cast: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merged labels for all units: scenes {n: slugline}, speakers {n: id}, tags {n: [..]}, actions {n: [..]}."""
    scenes: Dict[int, str] = {}
    speakers: Dict[int, str] = {}
    tags: Dict[int, List[Dict[str, str]]] = {}
    actions: Dict[int, List[str]] = {}
    ids = [{"id": c["id"], "name": c["name"], "aliases": c.get("aliases", []), "first_person": c["first_person"]} for c in cast]
    prev = ""
    for i in range(0, len(units), BATCH):
        chunk = units[i:i + BATCH]
        found = _ask("StoryboardPlanner", {
            "task": "label_units",
            "instruction": (
                "Label numbered story units. Return ONLY numbers and labels, NEVER text to be spoken. JSON: "
                '{"scenes":[{"start":N,"slugline":"INT. PLACE - NIGHT"}],"speakers":{"N":"CAST_ID"},'
                '"tags":[{"before":N,"character":"Name","pose":"sitting","position":"left"}],'
                '"actions":[{"before":N,"text":"Budhi Amma turns towards the door."}]}. '
                "scenes: every place/time change (INT./EXT.), the first unit starts a scene. speakers: for every "
                "unit marked quote, the cast id of who says it. tags/actions are optional, short, and describe only "
                "what the narration already says."),
            "cast": ids,
            "previous_slugline": prev,
            "units": [{"n": u["n"], "kind": u["kind"], "text": u["text"][:400]} for u in chunk],
        }, ("scenes", "speakers", "tags", "actions"))
        for s in found.get("scenes") or []:
            try:
                scenes[int(s["start"])] = norm(str(s["slugline"])).upper()
            except Exception:  # noqa: BLE001
                continue
        if isinstance(found.get("speakers"), dict):
            for k, v in found["speakers"].items():
                try:
                    speakers[int(k)] = str(v)
                except ValueError:
                    continue
        for t in found.get("tags") or []:
            try:
                tags.setdefault(int(t["before"]), []).append(t)
            except Exception:  # noqa: BLE001
                continue
        for a in found.get("actions") or []:
            try:
                actions.setdefault(int(a["before"]), []).append(norm(str(a["text"])))
            except Exception:  # noqa: BLE001
                continue
        if scenes:
            prev = scenes[max(scenes)]
    return {"scenes": scenes, "speakers": speakers, "tags": tags, "actions": actions}


# --- 4. assemble + verify ---------------------------------------------------------

def _slug(text: str) -> str:
    t = norm(text).upper()
    t = re.sub(r"\s+[-–]+\s+", " — ", t)
    return t


def _title(slug: str) -> str:
    t = re.sub(r"^(INT|EXT)[./]*\s*", "", slug)
    return t.split(" — ")[0].strip() or "SCENE"


def assemble(units: List[Dict[str, Any]], cast: List[Dict[str, Any]], labels: Dict[str, Any]) -> str:
    """BuzzAnimate's format: `## SCENE n — TITLE`, bold slugline, action lines with inline
    `[Name: pose, position]` tags, bold cue lines (two trailing spaces) then the text."""
    by_id = {c["id"].upper(): c for c in cast}
    by_name = {c["name"].lower(): c for c in cast}
    first_names = [c for c in cast if c.get("first_person")]
    introduced: set = set()
    blocks: List[str] = []
    last_speaker = None
    scene_no = 0

    def intro(c: Dict[str, Any]) -> None:
        # The producer reads no description file: a character without pictures is
        # drawn from the first action line that mentions them.
        if c["id"] in introduced:
            return
        introduced.add(c["id"])
        bits = [norm(str(c.get(k, ""))) for k in ("age", "look")]
        bits = [b for b in bits if b]
        text = f"{c['name']} is " + ", ".join(bits) if bits else ""
        if c.get("clothes"):
            text = (text + ", " if text else f"{c['name']} is ") + f"wearing {norm(str(c['clothes']))}"
        if text:
            blocks.append(text + ".")

    for u in units:
        n = u["n"]
        if n == 1 and n not in labels["scenes"]:
            labels["scenes"][1] = "INT. UNKNOWN PLACE — NIGHT"
        if n in labels["scenes"]:
            scene_no += 1
            slug = _slug(labels["scenes"][n])
            blocks.append(f"## SCENE {scene_no} — {_title(slug)}")
            blocks.append(f"**{slug}**")
        for t in labels["tags"].get(n, []):
            who = by_name.get(norm(str(t.get("character", ""))).lower()) or by_id.get(str(t.get("character", "")).upper())
            if who:
                intro(who)
                tag = f"[{who['name']}: {norm(str(t.get('pose', 'standing')))}, {norm(str(t.get('position', 'centre')))}]"
                acts = labels["actions"].get(n, [])
                if acts:
                    acts[0] = f"{acts[0]} {tag}"
                else:
                    blocks.append(f"{who['name']} {norm(str(t.get('pose', 'stands')))}. {tag}")
        for a in labels["actions"].get(n, []):
            blocks.append(a)
        if u["kind"] == "quote":
            sp = by_id.get(str(labels["speakers"].get(n, "")).upper()) or by_name.get(str(labels["speakers"].get(n, "")).lower())
            if sp is None:
                sp = (by_id.get((last_speaker or "").upper())) or (first_names[0] if first_names else cast[0])
            last_speaker = sp["id"]
            if sp["id"] not in introduced:
                intro(sp)
            blocks.append("**" + sp["name"].upper() + "**  " + NL + u["text"])
        else:
            blocks.append("**NARRATOR (V.O.)**  " + NL + u["text"])
    return (NL + NL).join(blocks) + NL


_CUE_RE = re.compile(r"^\*\*[A-Z0-9][A-Z0-9 .'_\-]*(?: \(V\.O\.\))?\*\*$")
_SLUG_RE = re.compile(r"^\*\*(INT|EXT)[./ ]")


def spoken_text(screenplay: str) -> str:
    """All spoken text in a screenplay: the lines under a bold cue (`**NARRATOR (V.O.)**` / `**NAME**`)."""
    out = []
    for block in re.split(r"\n\s*\n", screenplay):
        lines = [l for l in block.strip().splitlines() if l.strip()]
        if len(lines) >= 2 and _CUE_RE.match(lines[0].strip()) and not _SLUG_RE.match(lines[0].strip()):
            out.append(" ".join(lines[1:]))
    return norm(" ".join(out))


def verify(screenplay: str, script: str) -> None:
    got, want = spoken_text(screenplay), source_spoken(script)
    if got == want:
        return
    i = next((k for k, (a, b) in enumerate(zip(got, want)) if a != b), min(len(got), len(want)))
    raise ScreenplayError(
        "The screenplay's spoken text differs from the script at character %d: script %r vs screenplay %r"
        % (i, want[max(0, i - 40):i + 60], got[max(0, i - 40):i + 60]))


def convert(script: str, brand: str, cast_out: Optional[str] = None) -> str:
    """Script -> verified screenplay text. Writes the episode cast to `cast_out`
    and updates the channel registry."""
    units = split_units(script)
    if not units:
        raise ScreenplayError("The script has no text.")
    reg_path = cast_registry_path(brand)
    registry = _load(reg_path, [])
    cast, registry = merge_registry(extract_cast(script, registry), registry)
    labels = get_labels(units, cast)
    screenplay = assemble(units, cast, labels)
    verify(screenplay, script)
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    reg_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    if cast_out:
        Path(cast_out).parent.mkdir(parents=True, exist_ok=True)
        Path(cast_out).write_text(json.dumps(cast, ensure_ascii=False, indent=2), encoding="utf-8")
    return screenplay

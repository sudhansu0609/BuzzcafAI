"""Narrated story reels (REELS_DESK_PLAN.md VR5): the auto-story reel formats
(Raat3Baje's rules/ghost/folklore/horror-incident, Beyond3Baje's what_if/
anomaly_file, and -- per `auto_story.run` -- any other vertical, non-long-story
run) are rendered by BuzzEdit's recording-less vibe-reel renderer in its
narration mode instead of the synthetic-take + production-queue path:
continuous pictures and clips timed to the already-recorded narration, no
blank space, captions on screen, the same one lead character wherever a shot
shows a person.

    plan   plan_story_shots()   StoryReelPlanner -> validate_story_plan() (shot
                                 count from the narration's own length, about a
                                 third "video", no camera words, `shows_character`
                                 only with a character)
    body   vibe_story_body()    the exact `POST /api/reels/vibe` body, narration
                                 mode: a `narration` block instead of `lines`/`cards`

The render, retry and package are `auto_story.run`'s reel branch (`_run_reel`),
the way `mood_reel`'s pieces feed `auto_story.make_mood_reel`.
"""

import logging
import math
import re
from typing import Any, Dict, List, Optional

from app.services.mood_reel import strip_banned

logger = logging.getLogger("buzzcaf_ai.story_reel")

#: One shot per roughly 4-5 s of narration (REELS_DESK_PLAN.md VR5): BuzzEdit
#: fails an impossible shot count with "need N-M shots for X s" before it
#: generates anything, so the plan is kept inside a band that always works.
MIN_SHOT_S, MAX_SHOT_S = 4.0, 5.0
SHOT_CEILING_S = 7.0
MIN_SHOTS = 3
#: About a third of the shots carry real motion; the rest are repaired down
#: to "still" rather than failing the plan over it (mood_reel's own pattern).
VIDEO_SHARE = 1.0 / 3.0
#: A story with a being in it (a shot marked `entity: true`) must actually
#: show it, not just talk about it (REELS_DESK_PLAN.md VR9, creator follow-up
#: 2026-10-24): once any shot is marked `entity`, the final plan needs at
#: least this many of them.
MIN_ENTITY_SHOTS = 2
#: The narration-mode vibe body's own fields: a slow still/video push and the
#: dissolve between shots, since there are no couplet cards to time instead.
DEFAULT_PUSH = 0.06
DEFAULT_DISSOLVE_S = 0.4


def shot_count_range(seconds: float) -> "tuple[int, int]":
    """The acceptable shot-count band for `seconds` of narration: never fewer
    than `MIN_SHOTS`, and never so many a shot would need under `MIN_SHOT_S`."""
    seconds = max(0.0, float(seconds or 0.0))
    lo = max(MIN_SHOTS, math.floor(seconds / MAX_SHOT_S))
    hi = max(lo, math.ceil(seconds / MIN_SHOT_S))
    return lo, hi


def target_shot_count(seconds: float) -> int:
    """The exact shot count StoryReelPlanner is told to return for `seconds`
    of narration (REELS_DESK_PLAN.md VR9): `seconds / 4.5`, the renderer's
    own average shot length, clamped inside `shot_count_range`'s band -- a
    planner that is simply told "about N" can come back with far fewer (a
    189 s narration once got 7, needing 37-48)."""
    lo, hi = shot_count_range(seconds)
    return max(lo, min(hi, round(max(0.0, float(seconds or 0.0)) / 4.5)))


def _character(raw: Any) -> Optional[Dict[str, str]]:
    """`{name, description, gender}`, or None when the plan names no one --
    `shows_character` only means something once there is one."""
    if not isinstance(raw, dict):
        return None
    name = strip_banned(str(raw.get("name") or "")).strip()
    description = strip_banned(str(raw.get("description") or "")).strip()
    if not name or not description:
        return None
    return {"name": name, "description": description, "gender": str(raw.get("gender") or "").strip()}


_SHOT_COUNT_SHORT_RE = re.compile(r"^The plan has \d+ usable shot")


def _world_and_character(plan: Dict[str, Any]) -> "tuple[str, Optional[Dict[str, str]]]":
    """Raises when `plan` has no usable `world`; else `(world, character)`."""
    world = strip_banned(plan.get("world") or "")
    if not world:
        raise ValueError("The plan has no world.")
    return world, _character(plan.get("character"))


#: A `kind: "stick"` shot's own fields (STICK_WORLD_PLAN.md), passed through
#: to BuzzEdit's vibe reel `Shot` as written.
STICK_FIELDS = ("action", "scene", "era", "outfit", "bg", "caption")


def _parse_shots(plan: Dict[str, Any], character: Optional[Dict[str, str]],
                 art_style: str = "real") -> List[Dict[str, Any]]:
    """Every usable shot in `plan["shots"]`, banned-word-stripped and typed,
    in script order -- before the shot-count band is enforced. A `stick`
    shot is kept only for a stick_world reel; elsewhere it becomes a still
    of its own `bg`/`scene`."""
    shots: List[Dict[str, Any]] = []
    for s in plan.get("shots") or []:
        if not isinstance(s, dict):
            continue
        kind = str(s.get("kind") or "").strip().lower()
        stick = {k: strip_banned(str(s.get(k) or "")) for k in STICK_FIELDS if s.get(k)}
        if kind == "stick" and art_style == "stick_world" and stick.get("action"):
            try:
                secs = float(s.get("seconds") or 0)
            except (TypeError, ValueError):
                secs = 0.0
            shots.append({"prompt": stick.get("bg") or stick.get("scene") or "", "motion": "", "kind": "stick",
                          "seconds": secs, "shows_character": False, "entity": bool(s.get("entity")),
                          "stick": stick})
            continue
        prompt = strip_banned(s.get("prompt") or s.get("image_prompt") or stick.get("bg") or stick.get("scene") or "")
        motion = strip_banned(s.get("motion") or s.get("video_prompt") or "")
        if not prompt and not motion:
            continue
        prompt = prompt or motion
        if kind not in ("still", "video"):
            kind = "video" if motion and motion != prompt else "still"
        try:
            secs = float(s.get("seconds") or 0)
        except (TypeError, ValueError):
            secs = 0.0
        shots.append({"prompt": prompt, "motion": motion or prompt, "kind": kind, "seconds": secs,
                      "shows_character": bool(s.get("shows_character")) and character is not None,
                      "entity": bool(s.get("entity"))})
    return shots


def _finish_plan(world: str, character: Optional[Dict[str, str]], shots: List[Dict[str, Any]],
                 hi: int, art_style: str = "real") -> Dict[str, Any]:
    """The shared tail of `validate_story_plan` and `_repair_shot_count`: cut
    to `hi` in script order, cap "video" to about a third, clamp durations,
    enforce `MIN_ENTITY_SHOTS` once the story has a being at all."""
    had_being = any(s["entity"] for s in shots)
    # The plan is already in script order: a plan with too many shots is cut
    # at the end, not thinned through the middle, so the opening is never the
    # part that is dropped.
    shots = shots[:hi]

    if had_being:
        # A quality rule, not a safety rule: repair instead of failing the reel after its
        # narration was already made (Fable review, 2026-10-24) -- the shots nearest the
        # end (the climax) become entity shots, the existing one's look carried over.
        entity_count = sum(1 for s in shots if s["entity"])
        if entity_count < MIN_ENTITY_SHOTS:
            look = next((s["prompt"] for s in shots if s["entity"]), "")
            for s in reversed(shots):
                if entity_count >= MIN_ENTITY_SHOTS:
                    break
                if not s["entity"]:
                    s["entity"] = True
                    if look:
                        s["prompt"] = f"{s['prompt']}; the being from the story glimpsed: {look}"
                    entity_count += 1
            logger.info("Story reel plan repaired to %d entity shot(s)", entity_count)

    # At most roughly a third "video": the rest are repaired to "still"
    # rather than failing the plan over it.
    cap = max(1, round(len(shots) * VIDEO_SHARE))
    seen_video = 0
    for s in shots:
        if s["kind"] == "video":
            seen_video += 1
            if seen_video > cap:
                s["kind"] = "still"

    for s in shots:
        if s["seconds"] <= 0:
            s["seconds"] = MAX_SHOT_S if s["kind"] in ("video", "stick") else MIN_SHOT_S
        s["seconds"] = round(max(MIN_SHOT_S, min(SHOT_CEILING_S, s["seconds"])), 2)

    return {"world": world, "art_style": art_style, "character": character,
            "shots": [{**{k: s[k] for k in ("prompt", "motion", "seconds", "kind", "shows_character")},
                       **s.get("stick", {})} for s in shots]}


def validate_story_plan(plan: Optional[Dict[str, Any]], seconds: float,
                        art_style: str = "real") -> Dict[str, Any]:
    """Repairs/enforces a StoryReelPlanner answer: the shot count from
    `seconds`, about a third of the shots marked "video", no camera words,
    `shows_character` only when the plan also named a `character`, and at
    least `MIN_ENTITY_SHOTS` shots marked `entity` once any shot is (the
    story has a being, so the reel must actually show it). Raises when the
    plan is unusable (including too few usable shots -- the caller,
    `plan_story_shots`, re-asks and then repairs that case instead of
    failing the reel)."""
    if not isinstance(plan, dict):
        raise ValueError("The planner returned no plan.")
    world, character = _world_and_character(plan)
    shots = _parse_shots(plan, character, art_style)

    lo, hi = shot_count_range(seconds)
    if len(shots) < lo:
        raise ValueError(f"The plan has {len(shots)} usable shot(s); needs {lo}-{hi} for {round(seconds)} s.")
    return _finish_plan(world, character, shots, hi, art_style)


def _repair_shot_count(plan: Dict[str, Any], seconds: float, art_style: str = "real") -> Dict[str, Any]:
    """When StoryReelPlanner still returns too few usable shots after one
    re-ask (REELS_DESK_PLAN.md VR9): split its longest-covering shots into
    consecutive variations of the same scene -- a closer and a wider still
    framing of the same prompt -- until `shot_count_range`'s minimum for
    `seconds` is met. Never fails a reel for being a few shots short; still
    raises when the plan itself (world, any usable shot) is unusable."""
    world, character = _world_and_character(plan)
    shots = _parse_shots(plan, character, art_style)
    if not shots:
        raise ValueError("The plan has no usable shots to repair.")

    lo, hi = shot_count_range(seconds)
    framings = ("a closer framing of the same scene", "a wider framing of the same scene")
    i = 0
    while len(shots) < lo:
        # The shot covering the most seconds splits first: the most room to
        # share between two consecutive variations of the same scene. A
        # stick shot splits only when nothing else is left to split.
        pool = [k for k in range(len(shots)) if shots[k]["kind"] != "stick"] or list(range(len(shots)))
        idx = max(pool, key=lambda k: shots[k]["seconds"])
        base = shots[idx]
        half = round(max(MIN_SHOT_S, base["seconds"] / 2.0), 2)
        variation = {"prompt": f"{base['prompt']}, {framings[i % 2]}", "motion": base["motion"],
                     "kind": "still", "seconds": half, "shows_character": base["shows_character"],
                     "entity": base["entity"]}
        base["seconds"], base["kind"] = half, "still"
        base.pop("stick", None)
        shots.insert(idx + 1, variation)
        i += 1
    return _finish_plan(world, character, shots, hi, art_style)


def plan_story_shots(text: str, seconds: float, channel: str, format_key: str,
                     art_style: str = "real") -> Dict[str, Any]:
    """StoryReelPlanner (the narration text + its duration + channel + format,
    told the exact `shots` count to return, `target_shot_count`) ->
    `validate_story_plan`. Too few usable shots re-asks once with that same
    count and the unusable plan; still short, `_repair_shot_count` splits
    shots deterministically rather than failing the reel."""
    from app.services import shorts_desk
    target = target_shot_count(seconds)
    task = {"script": text, "seconds": round(seconds), "channel": channel, "format": format_key, "shots": target,
            "art_style": art_style}
    raw = shorts_desk._agent_json("StoryReelPlanner", task)
    try:
        return validate_story_plan(raw, seconds, art_style)
    except ValueError as exc:
        if not _SHOT_COUNT_SHORT_RE.match(str(exc)):
            raise
        retry_task = {**task, "previous_plan": raw,
                      "instruction": f"That plan had too few shots. Return exactly {target} shots this time, "
                                     f"still covering the whole script in order."}
        retried = shorts_desk._agent_json("StoryReelPlanner", retry_task)
        try:
            return validate_story_plan(retried, seconds, art_style)
        except ValueError as exc2:
            if not _SHOT_COUNT_SHORT_RE.match(str(exc2)):
                return _repair_shot_count(raw, seconds, art_style)
            try:
                return _repair_shot_count(retried if isinstance(retried, dict) else raw, seconds, art_style)
            except ValueError:
                return _repair_shot_count(raw, seconds, art_style)


def vibe_story_body(out_dir: str, name: str, plan: Dict[str, Any], narration_path: str,
                    narration_text: str, *, ambience: Optional[List[Dict[str, Any]]] = None,
                    music: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The exact `POST /api/reels/vibe` body in its narration mode (BuzzEdit's
    `VibeReelRequest` with `narration` set): no `lines`/`cards` -- the captions
    come from the narration itself, not from timed couplet cards. `quality:
    "reel_hq"` (2026-10-23): the same hyper-realistic AI clips as the mood
    reel, for the plan's own mix of shots (about a third "video", unchanged)."""
    return {"out_dir": out_dir, "name": name, "art_style": plan["art_style"], "world": plan["world"],
            "quality": "reel_hq", "shots": plan["shots"],
            "narration": {"path": narration_path, "text": narration_text, "language": "hi"},
            "captions": {"style": "phrases"}, "dissolve_s": DEFAULT_DISSOLVE_S, "push": DEFAULT_PUSH,
            "character": plan.get("character"), "ambience": ambience or [], "music": music}

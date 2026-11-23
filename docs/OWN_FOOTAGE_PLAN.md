# Own footage mode (2026-10-29)

The creator films his own talking parts and his own B-roll clips (desk, timeline,
notebook, violin, car...). The Studio's agents must line each clip up with what he
says, add the graphics and effects, and edit it. **His clips come first; AI pictures support his ideas**
(creator, 2026-10-29), capped at 40% of the picture time, never depicting his real life; no stock. First user: Life3Baje Episode 01 (project
`2026-10-29_Life3Baje_ImTryingToBuildSomethingBeyondMySoftwareJob`, his own script
with Shot 1..20 and camera notes).

Built in worktrees `B:\youtubeProjects\_worktrees\ownfootage\{BuzzcafStudio,BuzzEdit}`
(staged baseline = live state; the feature is the unstaged diff + new files). Merge
into the live trees only after review, when no production runs.

## How it works
1. **Footage in.** The project gets a footage folder (`project.metadata["footage_dir"]`,
   default `<project>/production/footage/`). He drops clips there or points it at a folder.
   Naming a clip by the script's shot (`shot06_notebook.mp4`, `s11 violin.mov`,
   `scene4_car.mp4`) pins it; any other name is matched by what it shows.
2. **Catalog.** For each clip: duration, resolution, has-audio, the shot tag from the
   filename, and a description from 3 frames (local Gemma 4 12B vision, LM Studio):
   `{what, place, action, mood, people}`. Saved to `production/footage_catalog.json`;
   cached per file (size + mtime). His own note per clip (optional) wins over the model.
3. **Planning.** When `project.metadata["footage_mode"] == "own"`, the record-first
   visual planner (`produce_api` -> per-window planning -> directive script) gets the
   catalog and may use only:
   - `[video: <short description> | own=<clip_id> | in=<seconds into the clip> | seconds=<n>]`
     for pictures -- never `[broll:]` stills or generated `[video:]` prompts;
   - the effect catalog's graphics (statement card, kinetic text, pill labels,
     numbered point, flow diagram, timeline, canvas card, callout, name title), sparse,
     as the channel guide says.
   Matching: a clip with a shot tag goes where that shot's lines are said (the script's
   `Shot N` sections aligned to the transcript -- BuzzEdit/Studio script alignment), else
   the planner matches descriptions to what is being said. Voice-over stretches are fully
   covered by clips; direct-to-camera lines stay on his face. A clip is used once unless
   reuse is needed; `in` skips the first ~0.5 s and picks a steady stretch. Unused clips
   are listed in the plan, not forced in.
4. **Render.** BuzzEdit resolves `own=` to the local file (copied into the project's
   asset cache), trims `in`..`in+seconds`, never generates or downloads for that beat,
   and keeps the clip's natural sound low under the voice (`natsound`, default 0.15,
   0 = muted).
5. **UI.** Projects page: "Own footage" toggle (default on for Life3Baje projects),
   the footage folder, "Read my clips" (builds the catalog), and the catalog as a list
   (thumbnail frame, name, shot tag, description, duration, used/unused after planning).

## Rules
- His clips first. AI pictures only for ideas/concepts/feelings where no clip fits, at most 40% of
  picture time (`footage.GENERATED_SHARE_MAX`), never his desk/car/violin/dashboard/face as if real. No stock.
- Graphics stay sparse and clean (Life3Baje guide "Pictures and graphics").
- Private details: the planner never adds a graphic that enlarges a dashboard number he
  did not say aloud.
- Tests: 2-3 small ones per item, no real-render pytest; visuals verified by frames.

## Status
| Item | State | Notes |
|---|---|---|
| OF1 Studio: footage folder + catalog (vision) + API | done | services/footage.py, api/footage_api.py, main.py (router + Life3Baje default own) |
| OF2 Studio: own-footage planning (shot tags, matching, directives) | done | produce_api.py, footage.py, buzzedit_script.py (own_clip), tests/test_footage.py |
| OF3 BuzzEdit: `own=` clips on `[video:]` (resolve, trim, natsound) | done | script.py parse, assets.resolve_own_assets, placement._place_own (V3 clip + A2 sound, duck 0.5); balance/live/camera skip own; 3 tests |
| OF4 Studio UI: toggle, folder, Read my clips, catalog list | done | components/OwnFootage.tsx under the estimate in Projects.tsx; Used/Unused from produce status planning.unused_clips when present |
| OF5 Review + merge | done | live vision test fixed (reasoning_effort none, 3 s/clip); merged 2026-10-29 12:48, Studio restarted; first real render = Life3Baje Ep01, check its frames |

Each implementer updates its row (todo -> doing -> done, one-line note: files, tests,
samples) after every item, so a cut-off leaves a hand-off.

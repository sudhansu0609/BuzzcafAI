# Stick World plan (2026-10-29)

Creator ask: stick figures dressed for their period, standing in an illustrated
scene ("a Greek library court, the stick figures in Greek clothes"), for every
period from prehistoric to modern and the future; used for documentary, case
study and What If videos on Beyond3Baje and for the story types on The Tall
Storyteller.

## Build rule: the live apps are never touched until the end

The creator keeps using the Studio while this is built, and both apps restart
themselves onto changed code. So all work happens in worktrees:

- Studio: `B:\youtubeProjects\_worktrees\stickworld\BuzzcafStudio`
- BuzzEdit: `B:\youtubeProjects\_worktrees\stickworld\BuzzEdit`

Their baseline (the live working tree on 2026-10-29) is **staged**; your work is
the unstaged diff plus new untracked files. **Never run `git add`, `commit`,
`stash`, `checkout`, `reset` or `npm install`/`npm ci`** (`motion/node_modules`
and `frontend/node_modules` are junctions to the live installs). No new npm or
pip dependencies. Never edit anything under `B:\youtubeProjects\Buzzcaf_Media\`.
Never start ComfyUI, LM Studio or a production; the PC is in use. Remotion
renders only, concurrency 2.

Run things like this:
- BuzzEdit Python: `B:\youtubeProjects\Buzzcaf_Media\BuzzEdit\.venv\Scripts\python.exe -m pytest ...`
  with cwd `...\_worktrees\stickworld\BuzzEdit\backend`.
- Motion: `node render.mjs --selftest` with cwd `...\_worktrees\stickworld\BuzzEdit\motion`.
- Studio: `python -m pytest ...` with cwd `...\_worktrees\stickworld\BuzzcafStudio\backend`;
  `npx tsc --noEmit` in its `frontend`.
- Samples go to `B:\youtubeProjects\Buzzcaf_Media\Samples\stick_world\` (never the
  Desktop, never a project folder). Backgrounds for samples: COPIES of real
  generated stills from `B:\youtubeProjects\Buzzcaf_Media\BuzzEdit\data\projects\*\assets\generated\`.

Tests: 2-3 small ones per item, no real-render pytest. Verify visuals by frames.

## The shared vocabulary (fixed)

`BuzzEdit/motion/src/stick_world.json` is the ONE source: `body`, `head`,
`held`, `hair` piece names (unique across categories) and `eras` (23 rows: label,
default `people` outfit specs for figures 1-3, `palette` fills, `bg` style
words). An **outfit spec** is order-free tokens joined by `+`
(`chiton+laurel+scroll+beard`); unknown tokens are dropped, a second piece of
the same category is dropped. The Studio keeps a byte-identical copy at
`backend/integrations/stick_world.json`, pinned by a test against the BuzzEdit
file when it exists. Change the vocabulary only in the BuzzEdit file and copy it.

## Contracts (fixed; items build against these)

**Directive** (BuzzEdit `script.py`, emitted by the Studio):
```
[stick: action=point | scene=a Greek library court | era=ancient_greece |
 outfit=chiton+laurel+scroll+beard ; toga+staff | figures=2 |
 bg=ancient Greek library courtyard, marble columns, scroll shelves |
 caption=Athens, 399 BC | seconds=6]
```
All fields optional except `action`. `outfit` is one spec per figure, `;`
between figures. `era` alone fills each figure from the era's `people`. A
figure with no outfit and no era is the plain stick figure of today. `bg` is an
English picture prompt; with it the scene is drawn over a generated picture,
without it over today's plain grounds. `figures` defaults to the number of
outfits, else 1; max 3.

**StickScene props** (new, all optional; old props unchanged):
```ts
era?: string;                 // stick_world.json eras key: palette + defaults
people?: { outfit?: string }[];   // 1-3 outfit specs; overrides `figures`
background?: string;          // data: URI (JPEG) of the scene picture
bgLuma?: number;              // 0-255 mean luma of the lower-middle band
```

**Beat data** (BuzzEdit `Beat.data` for `stick_scene`): `era`, `outfits`
(list of specs), `bg` (prompt), plus `bg_image` (path, set after generation)
and `bg_luma`.

**Art style `stick_world`** (one row in each of: Studio
`integrations/art_style.py` STYLES, BuzzEdit `presentation/art_style.py`
STYLES, Studio `frontend/src/lib/artStyles.ts`): label "Stick world (dressed
stick figures in illustrated scenes)"; plain pictures are hand-painted
storybook illustrations of the PLACE, rich period detail, nobody close up
(people moments are `stick_scene` beats); motion = illustrated's; text "on";
no face swap. Not a per-shot mix.

## Items

- **SW1 StickScene: outfits, eras, picture backgrounds, portrait** (BuzzEdit
  `motion/src` only). Every piece in the vocabulary drawn as SVG on the rig in
  the same hand-drawn boiling line, flat fill from the era palette: body pieces
  as drapes/garments following shoulders, hips and knees through every pose;
  headwear on the head; one held item in the leading hand (follows the arm);
  hair/beard on the head. Over a `background`: the picture fills the frame with
  a slow push (1.0 -> 1.05), a soft floor shadow under each figure, strokes
  light or dark from `bgLuma` (< 110 = light) with a contrasting halo so a
  figure always reads, today's ground line hidden. 9:16 canvas: figure size and
  placement from the short side, figures not cut off. `--selftest` passes.
  Samples: Greek court (3 figures), prehistoric, Mughal darbar, Victorian
  detective, modern office, future, one 1080x1920; frames at 20/50/90%.
- **SW2 BuzzEdit pipeline** (BuzzEdit `backend` only). `script.py`
  `_stick_options` reads `era`/`outfit`/`bg`; `motion_stick.py` loads the
  vocabulary, normalises specs, fills from the era, passes the new props;
  background pictures generated as zero-length `broll_image` sub-beats exactly
  the way `motion_collage.py` does it (`expand_*` / `annotate_*` / `drop_*`,
  wired in `director.py` beside the collage calls); prompt = `bg` + the era's
  `bg` words + "a wide view of the place with nobody in it, an open floor across
  the lower fifth" + the art style look (stick_world: the illustrated look);
  `bg_luma` measured from the picture. Fallbacks: no picture -> plain ground; a
  failed render -> `render_stick_still` drawn over the picture when there is one.
  Vibe reels (`vibe_reel.py`): a shot `kind: "stick"` (action, scene, era,
  outfit, bg, caption) whose background is made like a still shot, rendered
  through motion at the reel's size and placed as a video shot; fallback = the
  picture as a still shot. Tests 2-3.
- **SW3 Studio: catalog, art style, agents, formats** (Studio worktree, plus
  BuzzEdit `presentation/art_style.py` row only). `effect_catalog.py` stick row
  gains `era`/`outfit`/`bg` (normalised against `integrations/stick_world.json`;
  `_arg_stick` emits the contract grammar); the `stick_world` art style in all
  three tables; `story_visuals.py` keeps `stick` + map/timeline/chart for
  stick_world, planner text says how (people moments = stick_scene with `era`,
  `outfit` and `bg`; places/objects = illustrated pictures; documentary/case
  study = maps, timelines, callouts); cast direction: each character gets one
  fixed outfit spec + era in the cast sheet, and a stick beat naming `who` takes
  its outfit from there (same characters rule). Personas: PromptEngineer,
  CharacterPlanner, StoryReelPlanner (reels may use stick shots). Channel guides
  Beyond3Baje.md / TheTallStoryteller.md: when to use it. Format defaults: Story
  Desk `FORMATS` rows get `"art_style": "stick_world"` for Beyond3Baje
  `what_if`, `anomaly_file`, `case_file`, `unsolved` and every
  TheTallStoryteller format; Auto Story applies a format's art style when the
  request names none. Tests 2-3.
- **SW4 Review** (Opus): samples by frames, consistency across the three tables,
  merge into the live trees when idle.

## Status

| Item | State | Notes |
|---|---|---|
| SW1 StickScene | done | motion/src/compositions/StickScene.tsx (era/people/background/bgLuma props, garments/headwear/hair/held items, portrait sizing); `node render.mjs --selftest` passes; samples in B:\youtubeProjects\Buzzcaf_Media\Samples\stick_world\ (sw1_greek_court, sw1_prehistoric, sw1_mughal_darbar, sw1_victorian_detective, sw1_modern_office, sw1_future, sw1_future_portrait [1080x1920] + frames/) |
| SW1b Figure fixes | done | StickScene.tsx only (stick_world.json unchanged): drape garments drawn over body lines, skin-filled heads with dot eyes + mouth, hair/beard as shapes, headwear above the eye line, arms calmed + upright rods, spacing/portrait scale. Samples re-rendered (frames 20/50/90) on stills: greek 8935da69/721676d1, prehistoric 656774a3/0584db2e, mughal 674aefab/7de952b1, victorian 5fbc856f/1c9eb02a, office 5fbc856f/b9929ee6, future a1c79ff5/9ffcf829, future_portrait 5fbc856f/c35e86eb (copies in Samples/stick_world/bg/) |
| SW2 BuzzEdit pipeline | done | script.py/motion_stick.py/director.py/vibe_reel.py; 2 new test files/additions, 6 new tests, all pass |
| SW3 Studio | done | effect_catalog.py/art_style.py/story_visuals.py/artStyles.ts/3 personas/2 channel guides/shorts_desk.py/auto_story.py + BuzzEdit presentation/art_style.py row; 5 new tests, all pass; tsc clean |
| SW4 Review + merge | doing | Fixed so far: BuzzEdit `presentation/__init__.py` loads `motion` first (circular ImportError when motion_collage/stick/data/ui loaded first -- live too, hidden by startup order); BuzzEdit `tests/test_art_style.py` tuple +stick_world; reels end to end: `story_reel.py` carries `art_style` + `kind: "stick"` shots (STICK_FIELDS), `auto_story._run_reel` passes stick_world, BuzzEdit `vibe_reel` accepts stick_world (illustrated look pass); `auto_story.CHANNEL_ART_STYLE_DEFAULTS` (TheTallStoryteller's genre formats are not Story Desk rows). Studio 78 + BuzzEdit 108 passed. Left: SW1, samples by frames, merge. |

Each implementer updates its row (todo -> doing -> done, with a one-line note
of files, test counts and sample paths) **after every item**, so a cut-off
leaves a hand-off.

# Mixed art style: real + stick figure + maps & charts

Creator's request (2026-10-27): "a mode that includes the stick figure and real
as well, a combination of both, and maps, graphs etc." -- first for the
Beyond3Baje survival stories.

## Design

A seventh art style, `mixed` ("Mixed (real + stick figure + maps & charts)").
The medium is chosen **per shot**, not per video:

- **real** -- the story's moments as they looked: people, places, the event,
  emotion. Photoreal, the main character's face swapped in (`face=main`)
  as today. About half the pictures.
- **stick_figure** -- explaining: how or why something happened, a
  cutaway/diagram (the air pocket inside the capsized ship), a sequence,
  cause and effect, a "what would you do". Stick-figure look + prefix, no
  face swap, no realistic cast look appended. About a third.
- **map** -- whenever a place, route or distance first matters
  (BuzzEdit `[map: place]`, offline Natural Earth maps; noir look on horror).
- **chart** -- whenever numbers are compared or change over time
  (BuzzEdit `[chart: bar|line|pie: Title: A=1, B=2]`).
- Short text cards (`popup`, `stat_callout`, `definition_card`) are on, as for
  explainer / stick figure.

The planner writes `"art": "real" | "stick_figure"` on every picture beat; the
plan -> directive step carries it as ` | art=stick_figure`; `story_visuals`
applies that shot's look/motion/face rules and strips the option before
BuzzEdit sees it. Map/chart directives are timed like still pictures
(`| seconds=N`, never a clip, never split into continuation parts). The
thumbnail stays real.

BuzzEdit gets the same `mixed` table entry (keeps the two tables in step):
behaves as real for face swap, genre look and thumbnail; cards use the
explainer's card style; its script parser honours `| seconds=N` on
`map`/`chart`/`timeline`.

## Second mix: quirky documentary (2026-10-27)

Creator: "one mixed that has more of illustrated style and stick figure and
less real, for more quirky documentaries, and more engaging."

`mixed_quirky` -- "Quirky documentary (illustrated + stick figure, a little
real)". Same per-shot mechanism, three media per shot (`art`:
`illustrated` | `stick_figure` | `real`):

- **illustrated** ~45% -- the story told as hand-drawn illustration (the
  existing `illustrated` look), characters with exaggerated, expressive poses.
- **stick_figure** ~35% -- the explaining, plus visual gags: a stick figure
  reacting to the absurd number, a "you are here" arrow, before/after.
- **real** ~10-15% -- only the moments that land harder as real: the actual
  place, the object, the one face that matters.
- maps and charts as often as places and numbers come up; text cards on and
  used more (a popup for every surprising number or term).
- Engaging: a new picture every few seconds, a playful contrast between
  shots, curiosity-first framing; never horror-grim. Thumbnail: illustrated.

Both mixes are driven by one table entry each: the allowed per-shot media
and their target shares, so a third mix is a table row, not new code.

## Status

| # | Item | Repo | Status |
|---|------|------|--------|
| S1 | `mixed` in `integrations/art_style.py` (+ per-shot helpers) | Studio | done |
| S2 | `story_visuals`: kept kinds, planner section, per-shot `_picture`/`_video_prompt`/`stamp_art_style` | Studio | done |
| S3 | `story_visuals._apply_timed` + `plan_timed_shots`: map/chart/timeline timed as stills | Studio | done |
| S4 | `art` carried plan beat -> directive (`effect_catalog`, `buzzedit_script`) | Studio | done |
| S5 | `frontend/src/lib/artStyles.ts` entry | Studio | done |
| S6 | Studio tests | Studio | done |
| B1 | `mixed` in `backend/presentation/art_style.py` | BuzzEdit | done |
| B2 | `script.py`: `seconds=` on map/chart/timeline | BuzzEdit | done |
| B3 | BuzzEdit tests | BuzzEdit | done |
| S7 | `mixed_quirky` + table-driven mixes (shares, allowed media) in Studio | Studio | done |
| B4 | `mixed_quirky` in BuzzEdit table | BuzzEdit | done |

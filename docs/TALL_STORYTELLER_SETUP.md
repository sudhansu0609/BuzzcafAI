# The Tall Storyteller: setup

A sixth channel brand (handle `@TheTallStoryteller`, brand key
`TheTallStoryteller`): narrated, no-face storytelling across every genre --
folk tales, mystery, thriller, history, mythology, adventure, emotional/drama,
romance, comedy, classic world and Indian literature retold, and some horror
-- told in Hinglish in the creator's own cloned voice (`sudhansu_story`,
mood `warm`). See `AGENTS.md` -> "The Tall Storyteller" for the short version
and `prompts/channels/TheTallStoryteller.md` for the full channel guide.

Defaults: Hinglish narration and on-screen text; long stories 15-25 minutes
(20 by default); Shorts/reels one minute (60 seconds); `art_style: real`;
no face (`face_layout: face_intro`, 0 seconds, unless the creator sets a
face-intro clip); `visual_style: story` (pictures and videos only, same
rule as Raat3Baje/Khayal3Baje/Beyond3Baje); publishing review-first
(publish off); fixed greeting "Hello doston, mera naam hai Sudhansu aur aap
dekh rahe hain The Tall Storyteller."

## Status

| # | Item | Status | Notes |
|---|---|---|---|
| 1 | Channel guide, strategist persona, long-form workflow, seed topics | Done | `prompts/channels/TheTallStoryteller.md`, `prompts/agents/TheTallStorytellerStrategist.md` (added to `ResearchDepartment`), `prompts/workflows/thetallstoryteller_story.json`, `knowledge/seed_topics/thetallstoryteller.json` (42 ideas across the 10 genres) |
| 2 | Shorts Desk / Story Desk formats, Auto Story `per_channel`/`formats`, voice/style defaults | Done | `shorts_desk.FORMATS["TheTallStoryteller"]` (10 genre formats); `auto_story.DEFAULT_SETTINGS["per_channel"]["TheTallStoryteller"] = 0` and `["formats"]` seeded with 5 starter formats; `default_voice_for`/`voice_style_for` refactored to a `CHANNEL_VOICE_DEFAULTS` table (Raat3Baje/Beyond3Baje unchanged; TheTallStoryteller -> `sudhansu_story` / `{"mood": "warm"}`) |
| 3 | `channel_formats` default (long_only, face_intro 0s, art_style real, story visual style) | Done | `config/config.json` `channel_formats.TheTallStoryteller` = `{"shorts_first": false, "face_layout": "face_intro", "face_intro_seconds": 0}`; `buzzedit_settings._SEED_PROFILES["thetallstoryteller"]` = `{"genre": "general", "density": "balanced", "voice_preset": "warm_radio", "visual_style": "story"}` (art_style left at the system default "real"); `session_format.clamp_intro` extended to treat 0 as "no face" (previously floored to 30s -- see Decisions below) |
| 4 | YouTube channel registration | Partial, by design | No entry added to `config/youtube/channels.json` -- see Decisions below. `brands()` (channel-guide driven) already offers `TheTallStoryteller`; sign in on the Bulk Editor tab and assign the brand to finish this. Instagram packaging needs no channel-specific wiring (already generic) |
| 5 | Writing Style folder, "my style" mode, greeting rendering | Done | `writing_style.CHANNELS` + `canonical_channel()` updated; mode defaults to "mine" the same way every channel does (lazy folder creation, no pre-seeded files); `spoken_channel_name()` extended with a camelCase word-boundary split (needed for this channel's name, which has no digit to split on) so the greeting renders "...aap dekh rahe hain The Tall Storyteller." -- verified in `test_the_tall_storyteller_is_fully_wired` |
| 6 | Frontend channel pickers/filters | Done | `frontend/src/lib/channels.ts` (`CHANNEL_META`, icon 📖) and `frontend/src/pages/WritingStyle.tsx` (`CHANNELS`); every other page reads `CHANNEL_META`/`GET /api/brands`, so no further edit was needed. `StoryDesk.tsx`, `app/services/mood_reel.py`, `app/services/story_reel.py` and BuzzEdit's vibe-reel files were left untouched (another agent's in-flight work); `story_reel.py` is channel-agnostic already so this channel's reels need nothing from it. Build run at the end (see Verification) |
| 7 | Tests | Done | New `test_the_tall_storyteller_is_fully_wired` in `test_channels_and_logs.py`; existing channel-list assertions extended in `test_channels_and_logs.py`, `test_auto_story.py` (`per_channel` default) and `test_longform_nightly.py` (`minutes` dict, twice) -- see Verification for the run |
| 8 | Docs | Done | This file; `AGENTS.md` "The Tall Storyteller" section; `README.md` channel count/list |

## Decisions worth recording

- **`config/youtube/channels.json` was not touched.** Reading
  `integrations/youtube_publish.py` shows this file holds only channels that
  have already completed Google OAuth (`channel_id -> {title, brand,
  thumbnail}`, written by `start_login()`); there is no "handle" field and no
  concept of a placeholder/unconnected row. Adding a fabricated entry would
  either do nothing or make `channel_for_brand("TheTallStoryteller")` return a
  non-working id, turning a clean "not signed in" skip into a confusing
  upload error -- and the task explicitly says not to attempt OAuth. Because
  `youtube_publish.brands()` lists channel names straight from
  `prompts/channels/*.md`, `TheTallStoryteller` is already offered wherever a
  signed-in channel is assigned a brand; the creator only needs to sign in on
  the Bulk Editor tab as planned.
- **`session_format.clamp_intro` now treats 0 as "no face at all"** instead of
  flooring it to 30 seconds. This mirrors a sentinel
  `buzzedit_settings.face_intro_seconds()` already honours; without it, a
  `channel_formats` default of `face_intro_seconds: 0` would silently become
  30 the first time it was read back. No existing channel saves 0 today, so
  this is additive only.
- **TheTallStoryteller is deliberately not in `longform_nightly.DEFAULT_CHANNELS`
  or `session_format.SESSION_CHANNELS`.** It is fully wired into
  `longform_nightly.WORKFLOWS`/`FORMAT_ROTATION` (so Auto Story and a manual
  nightly run naming it both work) and `auto_story.DEFAULT_SETTINGS`, but the
  nightly scheduler keeps running only Raat3Baje/Beyond3Baje/Life3Baje until
  the creator adds it to `longform_nightly_channels`, and it is never treated
  as a recorded session (it is narrated, not recorded).

## Verification

- `cd backend && python -m pytest tests/test_channels_and_logs.py tests/test_all_79_agents.py tests/test_auto_story.py tests/test_shorts_desk.py tests/test_longform_nightly.py tests/test_studio_api.py tests/test_departments_api.py -q`
- `cd frontend && npm run build`

## Creator to-do

- Sign in `@TheTallStoryteller` on the Bulk Editor tab and assign it the
  `TheTallStoryteller` brand when ready to publish.
- Turn the channel on in Auto Story settings (`per_channel` > 0) and/or add it
  to `longform_nightly_channels` when ready for unattended runs.
- Record or supply a face-intro clip for the channel on the Story Desk if any
  face is wanted; otherwise it stays fully narrated.
- Add written samples on the Writing Style page for `TheTallStoryteller` so
  its "my style" scoring has something to measure against (it starts with
  none, same as a brand-new channel folder for any brand).

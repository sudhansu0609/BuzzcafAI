---
name: produce
description: Produce a finished video in Buzzcaf Studio from a recording the creator already cut. Use when the creator says "produce <path> for <channel>" or types /produce. Starts the Studio, creates the project, turns auto-cut off, fixes eye gaze from his own camera looks, keeps his face only for the first 45 s (pictures + clips after), sets the picture/clip mix and queues it.
---

# /produce <recording path> <channel> [options]

The creator's standing defaults (2026-11-23). Apply all of them unless his message says otherwise; ask only about real doubts.

## Inputs
- **Recording**: a path. It is ALREADY CUT by him, so auto-cut is OFF (`precut: true`).
- **Channel** -> workflow:
  Raat3Baje -> `after_dark_narration`, Beyond3Baje -> `beyond3baje_documentary`, Khayal3Baje -> `khayal3baje_horror`,
  Life3Baje -> `life3baje_video`, Originals -> `spilled_coffee_story`, TheTallStoryteller -> `thetallstoryteller_story`.
  If no channel is given, guess from the path (`B:\youtubeProjects\<Channel>\...`) and say which.
- **Project name**: the recording's folder name, capitalised (e.g. `elanthoor` -> `Elanthoor`).
- Options he may add: "real story" (real pictures), "fast", a clip %, a picture %.

## Steps
1. **Studio up?** `curl -s -m 3 http://127.0.0.1:8099/health`. If it is down, start
   `B:\youtubeProjects\Buzzcaf_Media\BuzzcafStudio\Buzzcaf Studio.exe` (PowerShell `Start-Process`, WorkingDirectory = that folder) and poll health.
2. **Project**: `POST /api/projects {"name","brand","workflow_name","art_style":"real"}`. Reuse an existing project of the same name and channel when one exists (`GET /api/projects`).
3. **Video settings**: `PUT /api/projects/{id}/video_settings`:
   - `precut: true`: auto-cut off.
   - `face_layout: "face_intro"`, `face_intro_seconds: 45`. His rule (2026-11-23, "for all unless I tell"): his face ONLY for the first 45 s, then pictures + clips to the end. This is the Studio default now (`session_format._defaults_for`); use another layout only when his message says so.
   - `video_broll_share: 0.15`: clips 15% max.
   - `image_broll_share: 0.85`.
   - `target_coverage: 0.95`.
   - `review_mode: "none"`: fast, no pause. Use `"plan"` only when something must be checked before the render.
   - Real story: `allow_free_stock: true`. Real photos only from free-licence stock; never copyrighted news or police photos. AI pictures for people and scenes.
   - Channel atmosphere, grade and effects come from the channel profile. Do not override them.
4. **Eye contact, base = his camera looks.** Make a contact sheet of the first 12 s:
   `ffmpeg -ss 0 -t 12 -i REC -vf "fps=1,scale=320:-1,crop=200:180:60:0,tile=6x2" -frames:v 1 <scratchpad>/open_sheet.jpg`.
   Read it and list the seconds where he looks straight into the lens. Then
   `PUT /api/projects/{id}/eye_contact {"enabled":true,"mode":"auto","lens_marks":[those seconds]}`.
5. **Camera looks:** with the face only in the first 45 s, camera looks after that get pictures too. The camera-look face windows (`BuzzEdit/docs/CAMERA_LOOK_FACE_PLAN.md`) only matter for a video he asks to be "mixed".
6. **Start**: `POST /api/projects/{id}/produce_video {"recording_path":"B:/...forward/slashes...","precut":true,"mode":"record_first"}`.
   Use forward slashes in the JSON. A 409 `video_running` means another video holds the slot: resend with `?when_free=1`, so it waits its turn.
7. **GPU**: never run training or other GPU jobs while a production runs (one video at a time).
8. **Since 2026-11-23 the pass does this itself, before its single render** (`BuzzEdit/docs/AUTO_FINISH_PLAN.md`): stage `face_fill` fills every face stretch after the opening, and stage `picture_check` has Gemma's vision check every still and remake the bad ones. Read `presentation_report.json` (`face_fill`, `picture_check`, `speed_summary`) and still glance at a contact sheet. Do the manual steps below only if a stage was skipped or failed.
   **After the render, check his face.** Make a contact sheet (1 frame every 8 s). His face may only show in the first 45 s. If it shows later, fill every face stretch after 45 s with new pictures; existing pictures are kept:
   `cd BuzzEdit/backend && ../.venv/Scripts/python.exe -m tools.broll_topup --project <buzzedit id> --face-intro 45`
   then re-render the saved edit (`director.rerender_presented`, which now accepts status "rendered"). Never let the Studio queue fall back to a fresh pass after a top-up: a fresh pass rebuilds the edit and drops the added pictures.
   (`buzzedit_project_id` is in the Studio project's metadata.)
   **Check every picture too, and fix without asking.** Make numbered sheets of all the stills the edit uses. Remake any with garbled or foreign-script text (signs, posters, ID cards, newspapers, forms), people who don't fit the story's country (non-Indian people in an Indian story), or objects out of their era (computers in the 1970s). Write new prompts with no text-bearing subject, generate, swap each source path in the timeline, and re-render. Then tell him it is fixed. He does not want a list of issues to decide on (2026-11-23).
   The eye-gaze fix stays at its default strength. He rejected a stronger one (2026-11-23): the lids stay lowered.
9. Reply in 3-4 lines: project id, settings used, queue position, where the final file lands (`<recording>_final.mp4` beside it).

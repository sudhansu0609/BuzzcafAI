# Morning note, 2026-10-23

Everything below is on disk, tested, and running on the live Studio and BuzzEdit.
Nothing is committed to git. Nothing paid was used.

## What you can do this morning

1. **Story Desk tab** (new): pick a channel, a format, a length, your voice,
   a style, press "Make one now". The tool writes the script, narrates it in
   your cloned voice, builds the take, produces it, and writes an Instagram
   package (`publish/instagram/`: `reel.mp4`, `caption.txt`, `cover.jpg`).
   Open the package folder from the record and post from the phone. YouTube
   upload happens when the switch is on and the channel is signed in.
2. **Your face intro**: on the Story Desk, set a clip of you per channel
   ("Face intro clip"). Every auto story then opens with it; after it, pictures
   only. Without a clip the first second or two is dark before the first shot.
3. **Story Library** (bottom of the Story Desk): search a writer or a theme in
   any language, see the rights badge, add to the library, pick a story, parts
   and minutes, "Adapt into my style". Public-domain authors (died before 1966)
   are translated and adapted; protected writers (Narayan Dharap, died 2008)
   are inspiration only, and the tool records which mode was used.
4. **Beyond3Baje**: the What If and Anomaly File formats, 105 ideas in the
   vault with the pilots marked, and two 5-minute scripts filed ready to record
   (the CCTV pilot, written by the Studio; your room script, filed as given).

## What was proven live tonight

| Piece | Result |
|---|---|
| Narration in your voice | Chatterbox clones you from a 40 s reference; 13.6 s of speech in 61 s |
| Raat3Baje rules-horror reel, 75 s, vertical | Made end to end twice. The first came out black (pictures covered 11 of 70 s); fixed by forcing full picture coverage for auto stories. The second has pictures from the first shot on: `projects/2026-10-23_Raat3Baje_ShortRaatKeKapdeTabuHorror/publish/instagram/reel.mp4` |
| Story Library | M. R. James found on Gutenberg, 45,404 words, public domain confirmed via Wikidata; splits into 8 stories |
| Adaptation | "Oh, Whistle, and I'll Come to You" (7,926 words) was adapting into your style when I had to stop: project `2026-10-23_Raat3Baje_OhWhistleAndIllComeToYouMyLad`. Check it on the Projects page: `script/script_final.md`, `metadata.human_score` |
| Life3Baje mood reel | First attempt failed honestly (every poem found was by a living poet); the finder now tries public-domain eras and poets (Ghalib, Mir, Kabir, Meera, Nirala, Prasad) first. A second attempt was queued to run after the adaptation; see the Story Desk records for Life3Baje |

## Where things are

- Plans with status tables: `AUTO_STORY_PLAN.md` (the engine, contracts, §7 the
  Story Library), `REELS_DESK_PLAN.md`. Changelog: `CHANGELOG.md` (top four
  entries are tonight's). Agent docs: `AGENTS.md` "Auto Story" section.
- New personas: NarrationDirector, MoodReelPlanner, StoryProducer, StoryScout,
  StoryAdapter, HumanTouch, WhatIfWriter.
- Nightly: `auto_story` task (off by default: switch it on in the Story Desk's
  nightly panel), `audience` task (on), archive sweep, morning report.
- Your voice reference: `BuzzEdit/data/voices/sudhansu.wav` (40 s cut from the
  ep1 recording). A cleaner 60 s clip, read calmly, will improve the clone:
  drop it in the same folder under the same name.

## Known limits, honestly

- Instagram is a package, not an upload: their API needs hosting and a business
  account. You post from the phone.
- A mood reel reads its lines softly in your voice; the pipeline refuses a take
  with no words, so a silent reel is not possible without a BuzzEdit change.
- The transliteration for the voice engine comes from the NarrationDirector
  persona (Devanagari); listen to the first few and tell me which words it
  mispronounces, and I will add them to its spelling list.
- The two reels made tonight used the default Raat3Baje story visuals; the
  anomaly-file and what-if formats have not been produced end to end yet.
- The cut editor stays on Claude; local models caught 25 to 47 percent of your
  cuts against about 75 percent (measured earlier tonight).

## Also fixed tonight, in passing

The Studio's self-restart ignored background jobs (it killed a narration
mid-way); a stale UI bundle used to block the launch with a modal; the idle
check had been failing silently since the afternoon; re-saving a vault topic
changed its id; SageAttention was measured slower on your card and turned off;
batched Whisper was measured lossy and kept off.

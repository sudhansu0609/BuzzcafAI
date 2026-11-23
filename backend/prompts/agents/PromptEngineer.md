---
name: "PromptEngineer"
department: "Production"
role: "AI Image & Video Prompt Engineer creating optimized generative prompts."
inputs: ["scene_descriptions", "style_preset", "script"]
outputs: ["ai_prompt_dossier", "visual_plan"]
dependencies: ["StoryboardPlanner"]
permissions: ["read_write_projects"]
version: "1.2.0"
---

# Agent Specification: PromptEngineer

## 1. Identity
- **Agent Name**: PromptEngineer
- **Department**: Production
- **Role Title**: AI Image & Video Prompt Engineer creating optimized generative prompts.
- **Version**: 1.1.0

## 2. Mission
To craft highly detailed, photorealistic, and stylistically consistent image and video generation prompts tailored for Midjourney, Flux, Stable Diffusion, and Runway Gen-3.

## 3. Purpose
Translates scene concepts into high-performing generative AI prompts complete with lighting, framing, subject details, and negative prompts.

## 4. Responsibilities
- Write master prompts for each storyboard shot following target model syntax.
- Specify framing and look (e.g. wide shot, close-up, shallow depth of field, volumetric lighting, photorealistic) -- never camera gear or the words camera, DSLR, lens, tripod or photographer: the image model draws whatever is named, and a camera then appears in the shot. Describe what the viewer sees and the move itself ("slow pan across the corridor", not "the camera pans across the corridor"). A camera is shown only when the story is about one.
- Define negative prompts to eliminate unwanted artifacts, text, extra limbs, and any visible camera, tripod or film crew.
- Never make a sign, poster, newspaper, ID card, ration card, form, certificate, chart, banner or open document the SUBJECT of an `image_prompt` or `video_prompt`: the image model fills them with gibberish or Chinese-looking characters. Show papers closed, stacked, tied, face-down or out of focus, and walls bare. Real names, numbers and headlines go in the editor's own cards, never in the picture. (Creator, 2026-11-23: the Emergency render had garbled posters, Chinese ID cards and fake newspapers.)
- People, clothes, objects and buildings match the story's country and era. In an Indian story every person is Indian (South Asian) in Indian clothing of the time: say "Indian" in the prompt for every person. Nothing appears before its time: no computers, monitors or mobile phones in a 1970s story. (Same render had East Asian and European officials at computer desks in 1976 India.)
- Never write "no X" or "without X" inside a prompt. The image model (Z-Image Turbo, cfg 1) ignores negation and negative prompts, and draws X. Name what IS there instead: "a black typewriter and a rotary telephone on the desk", not "no computers"; "plain whitewashed walls", not "no posters". Avoid words that invite lettering: shop, sign, poster, headline, label, title, a country or year written as a phrase.
- Deliver `ai_prompt_dossier` JSON.
- Story channels (Raat3Baje, Khayal3Baje, Beyond3Baje): plan only `broll_image` and `broll_video` beats -- no cards, text, headings, newspapers, maps or fx. Shots follow the story in order, each the next moment of the narration; every character keeps the exact look from the cast sheet in every prompt; motion is slow, calm and eerie, never rushed or news-like; no camera, DSLR, lens or film crew is ever named or seen.
- TheTallStoryteller is a story channel too (same `broll_image`/`broll_video`-only plan, story order, fixed cast-sheet looks, no camera named or seen) but spans every genre: the mood follows the scene's own genre (warm for a folk tale or drama, light for comedy, tense for a thriller or mystery, eerie only for its occasional horror beat), never defaulting to eerie.
- The art style. When the task names a style other than "real" (explainer, stick figure, cartoon), write every prompt in that medium: no photograph, film-still, lens, lighting or texture words; end every `image_prompt` and `video_prompt` with the look line the task gives; `style_hint` is `illustration`. Explainer and stick figure put the numbers, names and terms on screen as `popup`, `stat_callout` and `definition_card` beats beside the picture (text rendered by the editor, never drawn by the image model); cartoon is pictures only. In a drawn style no character has a real face.
- Stick World: every plain `broll_image`/`broll_video` is the PLACE itself (an illustrated period scene, nobody close up) -- a person moment is a `stick_scene` beat instead, with `era` (dress every figure for the period) or `outfit` (a named character's own fixed spec from the cast sheet, word for word, or `who=<name>` to reuse it) and `bg` (an English picture prompt for the place behind them, no camera words).

## 5. Authority
- Authorized permissions: ["read_write_projects"].

## 6. Key Performance Indicators (KPIs)
- **Prompt Generation Quality**: >90% first-pass image generation success rate.
- **Style Consistency**: Identical color grading and texture descriptors across prompts.

## 7. Inputs
- `scene_descriptions`: Visual descriptions from `StoryboardPlanner`.
- `style_preset`: Target aesthetic preset ("cinematic_horror", "mythology_epic", "anime_dark").

## 8. Outputs
- `ai_prompt_dossier`: Collection of generative AI prompts with parameters.
- `visual_plan`: A structured per-scene beat list (`production/visual_plan.json`)
  handed to the BuzzEdit bridge -- each beat anchors a directive (B-roll image
  or video prompt, map, chart (bar/pie/line), newspaper clipping, case file /
  government dossier, stat/quote/character/location/definition card, or a
  chapter heading) to a verbatim phrase in the script, so it can be spliced
  into a directive-annotated script for BuzzEdit/ComfyUI to render.

## 9. Dependencies
- Upstream Prerequisite: `StoryboardPlanner`
- Downstream Consumer: Image/Video Generation Engine

## 10. Tools & Integrations
- `LLMService` and Midjourney/Flux prompt syntax library.

## 11. Model Preferences
- Primary Model: Gemini 3.6 Flash / GPT-4o.

## 12. Memory Strategy
- Reads channel style guidelines and master negative prompt lists.

## 13. Knowledge Strategy
- References prompt engineering tricks for Midjourney v6, Flux.1, and SDXL.

## 14. Decision Framework
1. Extract primary subject, action, environment, and mood from scene description.
2. Append channel visual style modifiers and lighting specs.
3. Formulate negative prompt string to filter quality flaws.

## 15. Planning Algorithm
- Scene Ingestion -> Subject Isolation -> Modifier Append -> Negative Prompt Synthesis -> Dossier Export.

## 16. Execution Workflow
1. Receive `scene_descriptions` and `style_preset`.
2. Generate prompt strings per scene shot.
3. Save `ai_prompt_dossier` to project folder.

## 17. Reflection Process
- Ensure prompt strings avoid forbidden words that trigger safety filters on AI image generators.

## 18. Error Recovery
- Simplify prompt syntax if generator returns prompt length errors.

## 19. Escalation Rules
- Escalate unresolvable style mismatches to `ProductionManager`.

## 20. Communication Rules
- Structure output by shot ID and generator model target.

## 21. Security Rules
- Workspace directory isolation.

## 22. Logging Rules
- Log total prompts generated and character count length.

## 23. Prompt Template
```markdown
### Role
You are PromptEngineer in the Production Department.

### Objective
Generate optimized AI image generation prompts for Midjourney / Flux based on the storyboard descriptions.

### Context
{context_data}

### Instructions
Craft master positive prompts (subject, lighting, lens, mood, resolution) and negative prompts for every shot.
```

## 24. JSON Input Schema
```json
{
  "task_name": "PromptEngineer_Task",
  "project_id": "string",
  "inputs": {
    "scene_descriptions": ["object"],
    "style_preset": "cinematic_horror"
  }
}
```

## 25. JSON Output Schema

### Legacy shot dossier (`ai_prompt_dossier`, storyboard-driven steps)
```json
{
  "status": "success",
  "agent": "PromptEngineer",
  "results": {
    "ai_prompt_dossier": [
      {
        "shot_id": "SHOT_001",
        "target_model": "Midjourney_v6",
        "positive_prompt": "string",
        "negative_prompt": "string",
        "aspect_ratio": "16:9"
      }
    ]
  }
}
```

### Visual plan (`visual_plan`, the "Visual Plan" workflow step -> `production/visual_plan.json`)
When the step's `output_asset_type` is `visual_plan`, reply with **this** shape
instead -- a single JSON object, nothing else, no `status`/`agent`/`results`
wrapper:
```json
{
  "genre": "documentary",
  "beats": [
    {"anchor": "almost took down a country", "kind": "broll_image",
     "image_prompt": "1990s Bombay Stock Exchange trading floor, chaos, film grain",
     "negative_prompt": "text, watermark, logo", "style_hint": "photoreal",
     "aspect_ratio": "16:9", "priority": 1.0},
    {"anchor": "the rupee collapsed", "kind": "broll_video",
     "video_prompt": "stock ticker crashing, red numbers falling, slow zoom",
     "style_hint": "photoreal"},
    {"anchor": "Harshad Mehta", "kind": "character_card",
     "text": "Harshad Mehta", "subtext": "The Big Bull"},
    {"anchor": "forty percent of investors", "kind": "stat_callout",
     "data": {"value": 40, "suffix": "%"}},
    {"anchor": "split three ways", "kind": "chart",
     "data": {"chart_type": "pie", "labels": ["Cash", "Gold", "Bonds"],
              "values": [40, 35, 25]}},
    {"anchor": "grew every year", "kind": "chart",
     "data": {"chart_type": "line", "title": "Deposits (cr)",
              "labels": ["2019", "2020", "2021"], "values": [10, 22, 31]}},
    {"anchor": "made the front page", "kind": "newspaper",
     "data": {"masthead": "THE DAILY CHRONICLE", "headline": "BANK VANISHES OVERNIGHT",
              "dateline": "MARCH 1987", "highlight": "BANK VANISHES OVERNIGHT"}},
    {"anchor": "the investigation file", "kind": "case_file",
     "data": {"title": "CASE FILE No. 47", "stamp": "CLASSIFIED",
              "fields": [{"label": "SUSPECT", "value": "Harshad Mehta"},
                         {"label": "CHARGE", "value": "Securities fraud"}],
              "redactions": ["Harshad Mehta"]}},
    {"anchor": "in Mumbai", "kind": "map", "place": "Mumbai, India"},
    {"anchor": "you have to spend more hours", "kind": "statement_card",
     "text": "If you want *more money*, you have to spend *more hours* on it"},
    {"anchor": "when I was fourteen", "kind": "canvas_card",
     "image_prompt": "teenager gaming late at night, monitor glow on his face",
     "caption": "Me at age 14"},
    {"anchor": "financially free, retire my parents", "kind": "pill_labels",
     "items": ["Financially free", "Retire my parents", "Pay off the loan"]},
    {"anchor": "the first thing is", "kind": "numbered_point",
     "number": 1, "text": "Start before you feel ready"},
    {"anchor": "James Clear says", "kind": "name_title",
     "text": "James Clear", "subtext": "Author of Atomic Habits"},
    {"anchor": "according to the report", "kind": "source_quote",
     "source": "The Hindu", "text": "The unit operated for ==eleven months== without a single leave",
     "image_prompt": "army camp in snowy mountains at dusk"},
    {"anchor": "the article said", "kind": "document", "format": "web",
     "site": "www.thesentinel.com", "text": "The Hidden Story of ==Operation Rakshak==",
     "subtext": "Operations were led by the Army's ==Para Special Forces== units"},
    {"anchor": "by 1985 he weighed", "kind": "timeline",
     "ticks": ["1975", "1980", "1985", "1990"], "active": 2, "text": "60 KG",
     "subtext": "gained in four weeks"},
    {"anchor": "and then everything changed", "kind": "transition", "effect": "whiteflash"},
    {"anchor": "almost took down a country", "kind": "music_cue",
     "music": "suspense, pulsing synth bass, low strings, 100 bpm"},
    {"anchor": "the frozen border", "kind": "broll_image",
     "image_prompt": "boot prints in fresh snow at dawn, pine forest", "look": "blue_duotone"}
  ]
}
```
`anchor` MUST be a short phrase copied character-for-character from the
script you were given -- it is how the bridge locates where each beat
belongs. Valid `kind` values: `broll_image`, `broll_video`, `map`, `chart`,
`newspaper`, `case_file`, `stat_callout`, `quote_card`, `character_card`,
`location_card`, `definition_card`, `split`, `chapter`, and the designed
graphics `statement_card`, `canvas_card`, `pill_labels`, `numbered_point`,
`name_title`, `source_quote`, `document`, `timeline`, `transition`, and
`music_cue` (the background music from that line on). Include
only the fields relevant to the chosen `kind`; do not invent an anchor that is
not in the script. The full, authoritative field list and one example per kind
is the **Effect catalog** section appended to every visual-plan request
(`integrations/effect_catalog.py`) -- follow it exactly; a beat missing a
required field is dropped before it reaches the editor.

Designed graphics (all channels; the catalog lists which fit this genre best):
- `statement_card` -> `text`, 6-18 words, 1-3 key words in `*asterisks*`
  (coloured). The speaker stays live beside it. Thesis lines and punchlines;
  about one per two minutes.
- `canvas_card` -> `image_prompt`, optional `caption` and `look`. A picture
  in a floating card with the speaker beside it -- examples, memories,
  products. Alternate with plain `broll_image`.
- `pill_labels` -> `items`: 2-4 labels of 1-4 words. Only when the speaker
  actually lists things.
- `numbered_point` -> `number` + `text` (2-8 words) at the start of each
  point of a list or step of a method.
- `name_title` -> `text` name + `subtext` role, the first time a person is
  introduced or quoted.
- `source_quote` -> `source` (a real, named publication -- never invent one)
  + `text` with the key phrase in `==double equals==`; optional
  `image_prompt` background.
- `document` -> `format` `web` or `book`, `text` headline, `subtext`
  excerpt with `==highlights==`, optional `site`.
- `timeline` -> `ticks` (2-9 ordered dates), `active` index, `text` the big
  figure, optional `subtext`.
- `transition` -> `effect`: `whiteflash` (documentary cut to white) or
  `glitch`; at most one every 30-45 seconds.
- `music_cue` -> `music`: a short English description of the instrumental
  bed from this anchor on -- 1-2 instruments + a mood, optional genre and
  bpm (`"sad solo violin, 70 bpm"`, `"dark ambient, tanpura drone, eerie"`),
  or `"off"` for silence. One on the opening line, then one per real shift of
  feeling (2-5 per video, 40+ s apart), in the channel's Music direction. The
  prompt's "Music cues" and "This video's music" sections list the vocabulary
  and say when to plan none.
- `look` on `broll_image`/`canvas_card`: `bw`, `noir`, `sepia`,
  `red_duotone`, `blue_duotone`, `warm`, `cool` -- documentary drama wants
  `noir`/`red_duotone`/`sepia`; explainers usually none.

On-screen text is read in about three seconds: keep it short, and write it in
the language the viewer reads (Hinglish in Roman script for this studio)
unless quoting a source verbatim. `image_prompt` and `video_prompt` are the
exception: always English, whatever the video's language -- the image model
reads English. Each designed effect has a minimum gap before it may repeat
(e.g. one `statement_card` per ~75 s); more are removed, so spend them on the
strongest moments.

Fields per kind:
- `chart` -> `data.chart_type` is `bar` (default), `pie` or `line`, plus
  `data.labels`, `data.values`, optional `data.title`/`data.unit`.
- `newspaper` -> `data.headline` (required), optional `data.masthead`,
  `data.dateline`, `data.highlight` (a phrase to spotlight). Best for a dated
  public event; suits true-crime, horror, news and general.
- `case_file` -> `data.title`, `data.stamp` (e.g. `CLASSIFIED`, `TOP SECRET`),
  `data.fields` (a list of `{label, value}`), optional `data.redactions` (a
  list of values to black out). Investigative genres only (true-crime, horror,
  news). Camera-shutter/flash hits and the "recreation" dramatization look are
  applied automatically by BuzzEdit's mood pass -- do not plan them as beats.

## 26. Examples
### Sample Output (`ai_prompt_dossier`)
`"positive_prompt": "Cinematic shot of ancient ruins at midnight, glowing runes, volumetric mist, shallow depth of field, photorealistic, --ar 16:9"`

### Sample Output (`visual_plan` beat)
`{"anchor": "the reactor core overheated", "kind": "broll_video", "video_prompt": "control room alarms flashing red, steam venting, frantic shaky movement", "style_hint": "photoreal"}`

## 27. Edge Cases
- Character consistency: Inject character trigger tokens or reference image URLs.
- Visual plan: if no phrase in the script fits a beat naturally, omit the beat
  rather than inventing an `anchor` that does not appear verbatim in the text
  -- the bridge silently drops any beat it cannot locate.

## 28. Version History
- **v1.0.0**: Initial 29-part standard release.
- **v1.1.0**: Added the `visual_plan` output (structured per-scene beats for
  the BuzzEdit/ComfyUI production bridge), alongside the existing
  `ai_prompt_dossier` shape.
- **v1.2.0**: Designed graphics from the explainer/documentary reference
  study -- statement and canvas cards, pill labels, numbered points, name
  titles, source quotes, web/book documents, timelines, transitions and
  colour looks -- driven by the shared effect catalog.

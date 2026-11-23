# ComfyUI workflows used by the Studio

The Studio never talks to ComfyUI itself. Every picture, clip, music bed, scene sound and
thumbnail scene it asks for goes through BuzzEdit, and BuzzEdit runs ComfyUI with graph files
kept in one place: **`../BuzzEdit/workflows/`**. That folder's `README.md` is the full reference --
every file, its models and model folders, the custom node packs, which ones are live, and how to
add one. This page maps the Studio's features onto those files.

| Studio feature | BuzzEdit role | Live file (2026-10-24) | Set by |
|---|---|---|---|
| Pictures in every production (stills, character reference, thumbnail scene) | `broll_image` | `zimage1_esrgan.json` | BuzzEdit setting `workflow_broll_image` |
| Main character's face on the lead in pictures (`face=main`) | `broll_image` + face swap | the still graph + `ReActorFaceSwap` (`workflows/reference/*_faceswap.json`) | `main_character` project setting |
| Motion clips in every production | `broll_video` | `zimage_wan22_i2v_lite16.json` | BuzzEdit `workflow_broll_video`; with it cleared, the Projects page **Classic / HQ** toggle (`clip_generation_mode`, synced before each production by `produce_api.sync_clip_generation_to_buzzedit`) |
| Life3Baje vibe reels (Reels Desk) | `reel_hq` still + clip | `zimage1_hq.json`, `zimage_wan22_i2v_reel_portrait.json` (fallback `_hq16`) | `presentation/vibe_reel.py` |
| Music beds (Music page, every production) | `music` / `music15` | `ace_step_music.json` (default engine `ace_step`); `ace_step15_music.json` for a tempo, raga or slow mood | `music_engine` in `integrations/buzzedit_settings.py` / Music page |
| Scene sounds and transition hits | `audio` | `stable_audio_sfx.json` | manifest |
| Thumbnail scene when the still graph cannot make one | `thumbnail` | `thumbnail.json` (SDXL Juggernaut) | BuzzEdit `agents/thumbnail_agent.py` |

Classic clip mode needs the Wan 2.2 Q4_K_S models, parked on `H:` since 2026-10-24 (see the
BuzzEdit README's "Kept but not used"). Models that no workflow uses live in
`E:\ComfyUI_models_parked\` and `H:\ComfyUI_models_parked\`, each with a `MOVED.txt`.

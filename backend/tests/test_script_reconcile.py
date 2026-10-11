"""The spoken-script reconciler: the recording is the truth, the script a guide."""

from integrations.script_reconcile import Reconciliation, clean_spoken_script, extract_vocabulary

SCRIPT = """# Shuruaat

Main ek chhota sa creative business shuru kar raha hoon aur yeh video uske baare mein hai.

Pehla step hamesha sabse mushkil hota hai kyunki dar lagta hai ki log kya kahenge.

Jaipur mein meri pehli dukaan thi jo sirf teen mahine chali aur phir band ho gayi.
"""

# Said: line 1 (with a misheard word), line 2 skipped entirely, a long ad-lib,
# then line 3.
SPOKEN = (
    "main ek chhota sa creative bizness shuru kar raha hoon aur yeh video uske baare mein hai "
    "sach bataun toh kal raat maine socha ki yeh sab chhod doon lekin phir mujhe yaad aaya "
    "ki maine yeh kyun shuru kiya tha "
    "jaipur mein meri pehli dukaan thi jo sirf teen mahine chali aur phir band ho gayi"
)


def _words(text):
    return [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.3} for i, w in enumerate(text.split())]


def test_captions_follow_the_recording_not_the_script():
    rec = Reconciliation(SCRIPT, _words(SPOKEN))
    text = rec.render()
    # The skipped line never reaches BuzzEdit, so it cannot become a caption.
    assert "log kya kahenge" not in text
    # The ad-lib does, word for word.
    assert "kal raat maine socha" in text
    # A clear misspelling takes the script's spelling.
    assert "business" in text and "bizness" not in text
    # The script's chapter heading survives because its paragraph was spoken.
    assert text.startswith("# Shuruaat")


def test_beats_land_where_spoken_and_drop_where_skipped():
    rec = Reconciliation(SCRIPT, _words(SPOKEN))
    assert rec.place_script_beat({"kind": "map", "place": "Jaipur", "anchor": "Jaipur mein meri pehli dukaan"})
    assert not rec.place_script_beat({"kind": "broll_image", "image_prompt": "crowd judging",
                                      "anchor": "log kya kahenge"})
    text = rec.render()
    assert "[map: Jaipur] Jaipur mein" in text
    assert "crowd judging" not in text
    report = rec.report()
    assert report["beats_placed"] == 1
    assert report["beats_dropped"][0]["reason"] == "not spoken in the recording"
    assert any("Pehla step" in p["preview"] for p in report["skipped_paragraphs"])


def test_adlibs_are_found_and_take_their_own_beats():
    rec = Reconciliation(SCRIPT, _words(SPOKEN))
    adlibs = rec.adlib_texts()
    assert len(adlibs) == 1 and adlibs[0].startswith("sach bataun")
    assert rec.place_transcript_beat({"kind": "broll_image", "image_prompt": "late night desk",
                                      "anchor": "kal raat maine socha"})
    text = rec.render()
    assert "[broll: late night desk] kal raat" in text
    # The ad-lib is its own paragraph, so BuzzEdit treats it as its own topic.
    assert any(p.startswith("sach bataun") for p in text.split("\n\n"))


def test_record_first_with_no_script():
    rec = Reconciliation("", _words(SPOKEN))
    assert rec.adlib_texts() == [SPOKEN]
    assert rec.render().strip() == SPOKEN


# From a real Life3Baje take: the script is everyday Hinglish with production
# notes around the narration; the transcript is a letter-by-letter
# transliteration, and the speaker retold one idea in their own words.
NOTED_SCRIPT = """## [SCENE 01: THE HOOK]
**VISUAL:** [A desk covered in sketches and coffee mugs.]
**TEXT OVERLAY:** *"Why are we scared to start?"*

**V.O. (Narrator):** Hum sab ke paas bade sapne hote hain, right? Hum sochte hain ki ek din hum ek amazing brand banayenge.

[Visual: Narrator looks into the camera.]

**V.O. (Narrator):** Main chahta tha ki main ek poori book likhu. Isliye maine kabhi shuru hi nahi kiya.
"""
TRANSLIT = (
    "ham sabake paas ba.de sapane hote hain ham sochate hain ki ek din ham ek amaijing braind banaaenge "
    "ek baar mainne ek buk likhane kaa sochaa thaa lekin main kabhee shuroo naheen kar paayaa"
)


def test_production_notes_are_not_spoken_lines():
    rec = Reconciliation(NOTED_SCRIPT, _words(TRANSLIT))
    tokens = " ".join(rec.parsed.tokens)
    assert "VISUAL" not in tokens and "desk" not in tokens and "OVERLAY" not in tokens
    assert "Narrator" not in tokens and "camera" not in tokens
    assert rec.parsed.paragraphs[0].heading == "THE HOOK"


def test_transliterated_speech_matches_hinglish_script():
    rec = Reconciliation(NOTED_SCRIPT, _words(TRANSLIT))
    assert rec.report()["script_spoken_share"] > 0.5
    text = rec.render()
    assert "bade sapne" in text and "brand banayenge" in text


def test_a_retold_line_still_gets_its_visual():
    rec = Reconciliation(NOTED_SCRIPT, _words(TRANSLIT))
    assert rec.place_script_beat({"kind": "broll_image", "image_prompt": "a tall stack of blank pages",
                                  "anchor": "Main chahta tha ki main ek poori book likhu."})
    assert "[broll: a tall stack of blank pages]" in rec.render()
    assert rec.report()["beats_paraphrased"] == 1


# `clean_spoken_script` / `extract_vocabulary` -- a real Life3Baje draft's
# production noise (a file-path H1, a "---" rule, an emoji-led tone line
# outside any heading, bracketed scene headings, VISUAL:/[Visual: ...] lines,
# a whole-line parenthetical stage direction, and speaker labels).
NOISY_SCRIPT = """# script/draft.md

---

## 🎭 Tone: Lighthearted, Inspiring, Warm, and Conversational

---

## [SCENE 01: THE HOOK]
**VISUAL:** [A desk covered in sketches and coffee mugs.]

(pause for effect)

**V.O. (Narrator):** Hum sab ke paas bade sapne hote hain.

[Visual: Narrator looks into the camera.]

🎭 Off-heading meta line: this should never reach the aligner.

**V.O. (Narrator):** Doosri baat yeh hai ki hum shuru nahi karte.
"""


def test_clean_spoken_script_drops_production_noise():
    cleaned = clean_spoken_script(NOISY_SCRIPT)
    for noise in ("script/draft.md", "---", "Tone", "SCENE 01", "VISUAL", "Visual",
                  "pause for effect", "Off-heading", "Narrator"):
        assert noise not in cleaned


def test_clean_spoken_script_keeps_the_labelled_speech():
    cleaned = clean_spoken_script(NOISY_SCRIPT)
    assert "Hum sab ke paas bade sapne hote hain." in cleaned
    assert "Doosri baat yeh hai ki hum shuru nahi karte." in cleaned


def test_clean_spoken_script_is_a_noop_on_a_record_first_transcript():
    assert clean_spoken_script(SPOKEN) == SPOKEN


def test_extract_vocabulary_dedupes_short_words_and_caps():
    words = extract_vocabulary("Life3Baje life3baje LIFE3BAJE hi ab startup Startup " + " ".join(f"word{i}" for i in range(310)))
    # "hi" and "ab" are under 3 letters and dropped; "Life3Baje" variants and
    # "Startup"/"startup" dedupe case-insensitively, keeping the first spelling.
    assert words.count("Life3Baje") == 1
    assert "life3baje" not in words and "LIFE3BAJE" not in words
    assert words.count("startup") == 1 or words.count("Startup") == 1
    assert "hi" not in words and "ab" not in words
    assert len(words) <= 300


def test_extract_vocabulary_from_a_noisy_script_skips_the_noise_words():
    words = extract_vocabulary(clean_spoken_script(NOISY_SCRIPT))
    assert "Narrator" not in words and "VISUAL" not in words and "SCENE" not in words
    assert "Hum" in words and "sapne" in words


def test_teleprompter_pacing_cues_are_not_spoken_words():
    from integrations.script_reconcile import clean_spoken_script
    text = ("Hum sab ke paas sapne hain. (pause) Lekin aksar... (slow) hum darte hain. "
            "[pause 2s] (long pause) Chalo (Life3Baje) [broll: city] shuru. (normal)")
    assert clean_spoken_script(text) == (
        "Hum sab ke paas sapne hain. Lekin aksar... hum darte hain. Chalo (Life3Baje) shuru.")

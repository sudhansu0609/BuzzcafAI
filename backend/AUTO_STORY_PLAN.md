
## 7. The Story Library: horror by real writers, adapted into his voice (added 01:40)

The creator (01:35): the strategist should find good horror stories by writers in
any language (Marathi: Narayan Dharap; English; others), convert them to modern
Hinglish, write the script in HIS style so it never reads as machine-written,
multi-part when long; he records, the pipeline produces; no copyright issues.

**Rights, enforced by the tool.** Indian law: an author's work is public domain
60 years after the year of death (died before 1966 as of 2026). Narayan Dharap
died in 2008 (protected until 2069), Ratnakar Matkari in 2020: their stories can
only be used as **inspiration** (idea, mechanic, fear), never translated or
closely retold. Public-domain horror is plentiful: M.R. James, Blackwood,
Bierce, Lovecraft, Le Fanu, E.F. Benson, W.W. Jacobs, Poe, Stoker, Tagore's
ghost stories, Hemendra Kumar Roy, Rajshekhar Basu, Devaki Nandan Khatri,
Manto, folklore everywhere. Every library entry carries `rights`:
`public_domain` (death year verified on Wikidata, free API) | `protected`
(inspired-by only) | `unknown` (treated as protected). Adaptation of a protected
text is refused by the workflow; "inspired" keeps nothing of the expression.

| # | Brief | Delivers | Status |
|---|---|---|---|
| L1 | Story Library backend | `app/services/story_library.py` (search Gutenberg / Wikisource / Internet Archive / web, fetch full text, Wikidata death year -> rights, store `knowledge/stories/library/<id>/` with provenance), `StoryScout` persona, `GET/POST /api/stories/*` | not started |
| L2 | Adaptation workflow | `StoryAdapter` persona (translate + transpose to modern Hinglish, Indian setting where it helps, his style section, multi-part with recap lines), `HumanTouch` persona + `writing_style.ai_tells()` detector (triads, "not X but Y", over-explaining, uniform sentence length, no contractions, stock transitions) scored against his fingerprint; workflow `raat3baje_adaptation.json` (library pick -> adaptation -> style gate -> human-touch gate -> Shorts Scripts -> recording script) | not started |
| L3 | Story Library on the Story Desk | search box (language, author, source), results with rights badge and the first lines, "Adapt into my style (N parts)" -> project; library list | not started |

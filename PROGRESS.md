# Buzzcaf Studio — Progress Log

Running record of what has actually landed, newest first. Plan: `PLAN.md`.
A row is **done** only with the evidence that proves it. Nothing is marked done on intent.

## Status at a glance

| Item | Status | Evidence |
|---|---|---|
| 0.1 commit + `pre-v5` tag | ✅ done | 4 commits `a8bf90c..a32e0a3`, `git tag -l` → `pre-v5` (2026-09-06) |
| 0.3 PLAN.md / PROGRESS.md | ✅ done | this file |
| 0.4 ECOSYSTEM.md identical in both repos | ✅ done | `diff ECOSYSTEM.md ../dexter/ECOSYSTEM.md` empty |
| 0.5 test sandbox conftest | ✅ done | `pytest tests -q` → 136 passed; `md5sum backend/knowledge/*_memory.json` identical before/after; `main.py` now lists projects via `core.paths.PROJECTS_DIR` |
| 2.1 build into static mount | ⬜ open | |
| 2.2 desktop shell (**I2**) | ⬜ open | |
| 2.3 voice removed | ⬜ open | |
| 2.4 chat correctness | ⬜ open | |
| 2.5 chat is the front door (**I11**) | ⬜ open | |
| 3.1 control API | ⬜ open | |
| 5.1 BuzzBrain store | ⬜ open | |
| 5.4 frontend split + stub purge | ⬜ open | |
| 5.5 streaming (optional) | ⬜ open | |

## 2026-09-06

- Plan v5 adopted. The repair pass recorded in `IMPROVEMENTS.md` (paths,
  `json` import, masked settings, labelled fallbacks) was committed as four
  commits and tagged `pre-v5` so every v5 change is reversible.

# Gemma context status (2026-10-25)

| Step | Status |
|---|---|
| 1 helpers (estimate_tokens, lm_studio_max_context_length, _overflow_tokens, _round_ctx) | done |
| 2 _grow_lm_studio_context(model, error=None, need=None) | done |
| 3 grow/trim inside gate in chat_local and call_local; ContextTooLarge | done |
| 4 max_tokens (local_max_output_tokens) for local calls only | done |
| 5 runtime/context_budget.py fit_messages | done |
| 6 config defaults 65536 / 131072 / 8192; LM Studio gemma-4-12b.json contextLength 65536 (backup .bak-2026-10-25; no flash-attention key present) | done |
| 7 AGENTS.md, CHANGELOG.md | done |

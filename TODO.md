# TODO

Follow-ups from the 2026-06-06 migration to single-pass Opus synthesis.

## Pending

- [ ] **Confirm CI/Actions model access.** The scheduled run injects repo secrets and runs in PROD mode (`QUICK_TEST=False`, full prediction set — heavier than local dev runs). Verify the repo's `ANTHROPIC_API_KEY` has **Opus 4.8** access and the OpenAI key supports **gpt-5.1 + the Responses API**; otherwise the daily fails silently. (Local end-to-end already validated 2026-06-06 — this is the CI-secret unknown only.)
- [ ] **Eval harness modernization:** `eval_synthesis.py` / `eval_classifier.py` still use the `openai:` model prefix (→ pydantic-ai 1.x deprecation warnings; still functional). Swap to `openai-chat:`, and add `anthropic:claude-opus-4-8` to the default `--models` so the harness is ready for future Opus-vs-X re-checks.
- [ ] **Housekeeping (optional):** clear stale gitignored artifacts in `eval/results/` (`v2_*.md`, `key_themes_smoke.md`, old run JSON).

## Watch-items (no action unless triggered)

- **Opus `max_tokens` headroom:** adaptive thinking shares the 32K output cap with the visible memo. Low risk (the fixture memo was ~1290 words), but if a tension-rich PROD memo ever looks truncated, bump `synthesizing_agent` `max_tokens` (Opus supports up to 128K).
- **Cron comment nit:** `daily_report.yml` says "6am ET" but `0 11 * * *` fires at 7am ET in summer (EDT). Cosmetic; pre-existing.

## Done

- [x] **2026-06-06** — Confidence-calibration discipline in synthesis prompt: calibrate-to-evidence + ground-every-claim (anti-fabrication extended to causal mechanisms/historical precedents) + soft Key Themes confirm/refute tether. [`0ec7ef4`]
- [x] **2026-06-06** — Documented the Key Themes lede + calibration discipline in `CLAUDE.md` and fixed the stale required-env-var mapping (synthesis/citations are Anthropic, only events is OpenAI). Closes the prior "Doc gap" item.
- [x] **2026-06-06** — Live end-to-end run validated (events Responses-API web search → Opus synthesis → Sonnet citations).
- [x] **2026-06-06** — Single-pass Opus 4.8 synthesis (adaptive thinking + high effort); retired two-pass "Cross-Currents"; citations decoupled to Sonnet (`CITATION_MODEL`). [`7e0f7ef`]
- [x] **2026-06-06** — Upgrade pydantic-ai 0.4.3 → 1.x (slim[anthropic,openai]); events agent → OpenAI Responses API; dependency audit passed. [`7e0f7ef`]
- [x] **2026-06-06** — Key Themes lede surfacing mispriced/risk-reversal dynamics. [`56e855c`]
- [x] **2026-06-06** — Disable gpt-4.1 A/B comparison (`COMPARISON_MODEL=None`). [`ed8100c`]

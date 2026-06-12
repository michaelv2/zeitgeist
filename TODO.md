# TODO

Follow-ups from the 2026-06-06/07 build-out (single-pass Opus synthesis → grounded, calibrated, verified pipeline).

## Pending

- [ ] **Phase 1 ledger trial (live).** `ENABLE_LEDGER=True` as of 2026-06-11. Dated ledgers accumulate at `.reports/YYYY/MM/DD/themes_ledger.json` and publish to `gh-pages` with the memos. Watch over ~a week: do statuses differentiate (not everything stuck at `building`), does it sharpen multi-day framing / cut repetition, does the re-test-don't-defend guard hold? Then decide **phase 2** (give the verifier the ledger + a "claimed inflection the evidence doesn't carry" check). `/commit` phase 1 when satisfied.
- [ ] **Housekeeping (optional):** clear stale gitignored artifacts in `eval/results/` (`v2_*.md`, `ab_*.md`, `verifier_revised.md`, `key_themes_smoke.md`, old run JSON).

## Watch-items (no action unless triggered)

- **Opus `max_tokens` headroom:** adaptive thinking shares the 32K output cap with the visible memo. Low risk (fixtures run ~1100-1300 words), but if a tension-rich PROD memo ever looks truncated, bump `synthesizing_agent` `max_tokens` (Opus supports up to 128K).
- **Verifier/revise cost:** each PROD run now adds a second Opus call (verifier) + a Sonnet call (revise). On a heavily-over-reaching draft the revise can rewrite many lines (propagation) — expected, but watch token spend.
- **Eval judge overlap:** synthesis judges (`o3` + `opus-4-6`) sit alongside `opus-4-8` as a contestant; `opus-4-6` shares the Opus family (mild self-preference risk). Swap the 2nd judge to a non-Anthropic for a decisive A/B; fine as-is for qualitative diffs. Also recall judges split 1-1 by ordering (position bias).
- **Cron comment nit:** `daily_report.yml`'s inline comment still says "6am ET" but `0 11 * * *` fires at 7am ET in summer (EDT). The `CLAUDE.md` reference was corrected this session; the `.yml` comment is cosmetic, pre-existing.

## Done

- [x] **2026-06-11** — Phase 1 multi-day **themes ledger**: rolling state at `.reports/YYYY/MM/DD/themes_ledger.json`, fed back into synthesis behind a re-test-don't-defend anchoring guard; a Sonnet update pass does carry/inflect/add/prune (cap 8, ~5-day stale prune). Validated mechanics (`validate_ledger.py`) + anchoring (`validate_anchoring.py` — refuted priors flip, supported ones hold); flipped `ENABLE_LEDGER=True` to start the trial. Documented in `CLAUDE.md`.
- [x] **2026-06-11** — Docs: corrected the run model from "GitHub Actions" to the actual **local cron** (`run_cron.sh` + `gh-pages` worktree) across `CLAUDE.md`/`README`; dropped the now-moot "Confirm CI/Actions model access" item.
- [x] **2026-06-07** — Verifier catalyst-grounding (thread c): the verifier now sees the Upcoming Catalysts list and flags timing pegs that aren't actually upcoming (e.g. "ahead of NVDA's print" when NVDA isn't on the calendar); validated. Full `CLAUDE.md` refresh (FRED tool, verifier, implication directive, writing rules, nudge removal, eval harnesses).
- [x] **2026-06-06** — Verifier revise pass propagates each correction to sibling claims (+ "touch nothing else" guard); retired the now-redundant frequency-vs-trend nudge (verifier+revise carries it, validated 2/2). [`371eb0b`]
- [x] **2026-06-06** — Flag-then-revise **verifier** quality gate (Opus flag → Sonnet revise) catching over-reach post-synthesis, FRED-grounded; validated — caught the retail self-contradiction + 3 more on the saved over-bearish draft. [`476be37`]
- [x] **2026-06-06** — "Land every story on a tradeable, grounded-catalyst read" directive; generalized `ab_nudge.py` into a reusable prompt-line A/B harness. [`1339e6f`]
- [x] **2026-06-06** — Bounded **FRED tool** for synthesis (on-demand grounding, provenance→citations) + headline CPI in `FRED_CODES`; claim-first writing rules; frequency-vs-trend nudge (later retired). [`a625ab8`]
- [x] **2026-06-06** — Eval harness modernization: pinned the `openai-chat:` prefix across `eval_synthesis.py` + `eval_classifier.py`; added `anthropic:claude-opus-4-8` to the synthesis contestant default.
- [x] **2026-06-06** — Confidence-calibration discipline in synthesis prompt: calibrate-to-evidence + ground-every-claim (anti-fabrication extended to causal mechanisms/historical precedents) + soft Key Themes confirm/refute tether. [`0ec7ef4`]
- [x] **2026-06-06** — Documented the Key Themes lede + calibration discipline in `CLAUDE.md` and fixed the stale required-env-var mapping. Closed the prior "Doc gap" item.
- [x] **2026-06-06** — Single-pass Opus 4.8 synthesis (adaptive thinking + high effort); retired two-pass "Cross-Currents"; citations decoupled to Sonnet. [`7e0f7ef`]
- [x] **2026-06-06** — Upgrade pydantic-ai 0.4.3 → 1.x (slim[anthropic,openai]); events agent → OpenAI Responses API; dependency audit passed. [`7e0f7ef`]
- [x] **2026-06-06** — Key Themes lede surfacing mispriced/risk-reversal dynamics. [`56e855c`]; disable gpt-4.1 A/B comparison (`COMPARISON_MODEL=None`). [`ed8100c`]

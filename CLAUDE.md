# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Zeitgeist is a Python application that generates daily investment macro reports by:
1. Fetching prediction market data from Kalshi and Polymarket
2. Filtering for investment-relevant predictions using LLMs
3. Gathering economic data from FRED API
4. Collecting news headlines via GNews
5. Finding upcoming market catalysts via web search
6. Synthesizing everything into a markdown investment memo (the synthesizing agent has a bounded FRED tool for on-demand grounding)
7. Verifying the finished draft for over-reach and revising it before it ships
8. Updating a rolling multi-day **themes ledger** (carry/inflect/prune) that feeds back into the next day's synthesis
9. Adding citations and rendering to HTML

The application runs daily via a **local cron** (`run_cron.sh`) and publishes reports to GitHub Pages. The `.reports/` directory is a git worktree checked out to the `gh-pages` branch; the cron runs the script, then commits and pushes `.reports/` to publish.

## Development Commands

### Run the application
```bash
uv run python zeitgeist.py
```

This will:
- Fetch data from prediction markets, FRED, and news sources
- Generate a report using LLM agents (mix of Anthropic + OpenAI models)
- Save HTML output to `.reports/YYYY/MM/DD/index.html`
- Open the report in your browser (dev mode only)

### Quick smoke test
The script automatically runs in "quick test" mode when `GITHUB_ACTIONS` is not set. This limits data fetching to first few batches for faster iteration during development.

### Validation / eval harnesses
- `ab_nudge.py`: controlled A/B of a single synthesis-prompt line (`--anchor`/`--extract`) on a fixture — strips the line for the "old" arm, runs N draws per arm, diffs a chosen passage
- `validate_verifier.py`: runs the flag-then-revise verifier on a saved draft (e.g. a `.reports/.../index.html`) and prints findings + before/after
- `validate_ledger.py`: dry-runs the themes-ledger update pass (carry/inflect/add/prune) on the latest memo + a crafted prior ledger
- `validate_anchoring.py`: anchoring property test — ledger-on synthesis on a fixture with planted priors (some refuted by the data, one supported); checks it flips the refuted and holds the supported
- `prototype_fred_tool.py`: exercises the synthesis FRED tool on a fixture
- `eval_synthesis.py` / `eval_classifier.py`: LLM-as-judge eval harnesses; fixtures live in `eval/synthesis_fixtures/` (gitignored). Dump today's inputs as a fixture with `ZEITGEIST_DUMP_FIXTURE=1`

### Required environment variables
- `OPENAI_API_KEY` (required) - For the events agent (gpt-5.1 via the Responses API)
- `ANTHROPIC_API_KEY` (required) - For classifier (Haiku), synthesis (Opus), and citations (Sonnet)
- `FRED_API_KEY` (optional) - For economic data; script continues without it

Create a `.env` file with these keys for local development.

## Architecture

### Multi-stage LLM Pipeline

The application uses these specialized pydantic-ai agents:

1. **Relevant Prediction Agent** (`relevant_prediction_agent`)
   - Model: `claude-haiku-4-5-20251001` (fast coarse filter)
   - Processes prediction markets in batches of 100
   - Coarse filter: removes obvious noise (sports, celebrity, memes) and keeps anything plausibly relevant
   - Contextual relevance judgment is deferred to the synthesizing agent which sees news/FRED/events
   - Tags each with affected topics/sectors
   - Template: `templates/classifier_coarse_filter_prompt.mako`

2. **Events Agent** (`events_agent`)
   - Model: `gpt-5.1-2025-11-13`
   - Has web search tool enabled (`search_context_size: "high"`)
   - Finds upcoming macro catalysts (earnings, Fed meetings, regulatory events)
   - Returns structured events with titles, dates, and topics
   - Template: `templates/events_prompt.mako`

3. **Synthesizing Agent** (`synthesizing_agent`)
   - Model: `claude-opus-4-8` (Opus 4.8, single-pass deep synthesis) with **adaptive thinking + high effort**
   - Consolidates all inputs into one coherent memo, reasoning through cross-cutting tensions/confounders and **resolving them into a decisive call** rather than listing both sides
   - Opens with a **Key Themes** lede at the very top: at most 2-3 variant-perception bullets surfacing what may NOT be priced in or what a headline reading would miss (risk-reversals, narrative shifts, thematic inflections); genuine leaps flag a concrete confirm/refute tell
   - Surfaces the disambiguating datapoints as an integrated **Key Tells** block in the Positioning Summary (the forward "what would change this view" tells) — replaces the earlier separate two-pass "Cross-Currents" red-team
   - **Calibrates confidence to evidence** (decisive ≠ certain): grounds every claim in the provided inputs (no fabricated numbers, mechanisms, or historical precedents), separates what the data shows from inference vs. speculation, and labels genuine leaps with what would confirm or refute them
   - **Lands every material story on a tradeable implication**: a concrete expression (name/sector or cross-asset leg) plus a catalyst — but only one confirmably still upcoming in the events inputs, never a stale/assumed peg
   - Has a **bounded FRED tool** (`fred_search`/`fred_series`, capped at `MAX_FRED_TOOL_CALLS`) to fetch an additional series on demand and *compute* a figure rather than estimate it; fetched series flow into the citation sources. Gated by `ENABLE_FRED_TOOL`
   - When the themes ledger is enabled, also receives the **prior days' themes** (with their forward tells) and re-tests each against today's data — confirming, advancing, inflecting, or dropping it — rather than continuing a prior call by inertia. Gated by `ENABLE_LEDGER`
   - Writes **claim-first and structured**: lead with the takeaway, subordinate the evidence; one claim per bullet; compress words, not logic
   - Template: `templates/synthesizing_prompt.mako`

4. **Verifier + Revise** (`verifier_agent` → `revise_agent`) — a flag-then-revise quality gate, gated by `ENABLE_VERIFIER`
   - **Verifier** (`VERIFIER_MODEL` = Opus 4.8, adaptive thinking): re-reads the finished memo adversarially for OVER-reach — overstatement, self-contradiction, ungrounded claims, cherry-picked framing, and stale/ungrounded catalysts. Has the same bounded FRED tool to ground numeric claims, and is given the Upcoming Catalysts list to flag timing pegs that aren't actually upcoming. Returns structured `Finding`s (or none)
   - **Revise** (`REVISE_MODEL` = Sonnet): applies each fix and propagates it to every sibling sentence that restates the corrected claim, touching nothing else
   - Catches over-reach the single-pass synthesis commits to but can't self-critique mid-generation; a failure is logged and the unrevised draft ships
   - Templates: `templates/verifier_prompt.mako`, `templates/revise_prompt.mako`

5. **Citation Agent** (inline, no dedicated variable)
   - Model: `claude-sonnet-4-6` (`CITATION_MODEL`, decoupled from synthesis — mechanical link-insertion doesn't need Opus)
   - Post-processes report to insert markdown citations
   - Template: `templates/citation_prompt.mako`

6. **Ledger Agent** (`ledger_agent`) — gated by `ENABLE_LEDGER`
   - Model: `LEDGER_MODEL` = Sonnet (mechanical extract + prune; judgment-light)
   - Runs after the verify/revise step: reads the prior ledger + the finished memo and emits the updated rolling **themes ledger** (`ThemesLedger`/`LedgerTheme`) — carrying forward stable themes (`first_seen` preserved), setting status (building/intact/inflecting/fading/resolved), adding genuinely new threads, and pruning resolved or ~5-day-stale ones (cap 8)
   - Persists to `.reports/YYYY/MM/DD/themes_ledger.json`; `load_ledger()` reads the newest snapshot from a day *strictly before* today, so same-day re-runs read the prior day rather than their own write
   - Wrapped in try/except — a failure logs and keeps the prior ledger
   - Template: `templates/ledger_update_prompt.mako`

### Data Flow

```
Kalshi API + Polymarket API → pl.DataFrame (predictions)
        ↓
Batched through Relevant Prediction Agent → tagged_predictions
        ↓
                    ┌─ tagged_predictions
                    ├─ Events Agent → upcoming catalysts
Synthesizing Agent ─┤─ GNews → news headlines       (+ bounded FRED tool, on demand)
(Opus 4.8)          ├─ FRED API → macro data points
                    └─ prior themes ledger (re-tested against today's data)
        ↓
Verifier → Revise  (flag over-reach: FRED-grounded + catalyst-checked → apply & propagate fixes)
        ↓
Ledger Agent → updated themes ledger → .reports/YYYY/MM/DD/themes_ledger.json (feeds tomorrow)
        ↓
Citation Agent → final markdown report → HTML (via Mako template)
```

### Key Design Patterns

- **Async concurrency**: All data fetching (markets, events, news, FRED) runs concurrently via `asyncio.gather()`
- **Batched LLM calls**: Predictions processed in batches with delays to respect rate limits
- **Polars DataFrames**: All data manipulation uses Polars for performance
- **Mako templates**: LLM prompts and HTML output both use Mako templating
- **Error resilience**: Individual data source failures are logged but don't crash the pipeline

### Templates Directory

- `about_me.mako`: Shared context about the investor persona (US equities, macro focus)
- `relevant_prediction_prompt.mako`: Filters prediction markets for investment relevance
- `events_prompt.mako`: Instructs agent to find upcoming catalysts via web search
- `synthesizing_prompt.mako`: Main report generation — single-pass synthesis that resolves tensions into a decisive call, opens with a "Key Themes" variant-perception lede, applies a confidence-calibration discipline + claim-first writing rules, lands every story on a tradeable/grounded-catalyst implication, and surfaces forward tells via the integrated "Key Tells" block. A `fred_tool` flag conditionally renders the bounded-FRED-tool instructions; a `ledger` flag conditionally renders the prior-themes re-test instructions
- `verifier_prompt.mako`: Adversarial over-reach review of the finished draft (flag pass) — sees `{memo, upcoming_catalysts}` with FRED grounding; returns structured findings
- `revise_prompt.mako`: Applies the verifier's fixes (revise pass), propagating each correction to sibling claims while touching nothing else
- `ledger_update_prompt.mako`: Maintains the rolling themes ledger (update pass) — reads `{prior_ledger, memo}` and returns the carried/inflected/pruned `ThemesLedger`
- `citation_prompt.mako`: Adds markdown citations to the final report
- `index.html.mako`: HTML wrapper for the final report

### Configuration Constants

At the top of `zeitgeist.py`:
- `QUICK_TEST`: Set to `True` in dev mode to limit data fetching
- `BATCH_SIZE`: Number of predictions per LLM batch (100)
- `BATCH_REQUEST_DELAY_SECONDS`: Delay between batches (5s) to avoid rate limits
- `CLASSIFYING_MODEL`, `EVENTS_MODEL`, `SYNTHESIS_MODEL` (Opus 4.8), `CITATION_MODEL`, `VERIFIER_MODEL` (Opus 4.8), `REVISE_MODEL` (Sonnet), `LEDGER_MODEL` (Sonnet), `COMPARISON_MODEL`: model selection per agent (mix of Anthropic + OpenAI)
- `ENABLE_FRED_TOOL`, `ENABLE_VERIFIER`, `ENABLE_LEDGER`, `ENABLE_CITATIONS`, `ENABLE_EMAIL_BRIEFING`: feature flags for the optional pipeline stages
- `MAX_FRED_TOOL_CALLS`: per-run cap on on-demand FRED fetches, shared by the synthesis and verifier tools (8)
- Synthesis (and the verifier) run adaptive thinking + `anthropic_effort: "high"` (set in `model_settings`)
- `FRED_CODES`: Dict mapping FRED series codes to human-readable names (includes both headline and core CPI/PCE so real-spending reads aren't core-only)
- `NUM_FRED_DATAPOINTS`: How many recent datapoints to fetch per FRED series (10)
- `LEDGER_NAME`: filename of the per-day themes-ledger snapshot under `.reports/YYYY/MM/DD/` (the rolling multi-day state fed back into synthesis)

### Daily run (local cron)

The daily report runs from a **local cron job** (not GitHub Actions) via `run_cron.sh`:
- Sources secrets from `~/.bashrc_env`, then runs `uv run python zeitgeist.py`
- Writes the report into `.reports/YYYY/MM/DD/index.html`
- `.reports/` is a git **worktree** on the `gh-pages` branch; the script `git add -A && commit && push`es it, which publishes to GitHub Pages (<https://michaelv2.github.io/zeitgeist/>)

(A `.github/workflows/daily_report.yml` exists but is **not** the active mechanism — kept as a dormant/manual-dispatch fallback.)

## Critical Implementation Notes

### Verifier (flag-then-revise)
A post-synthesis quality gate for the single-pass synthesis's blind spot: it commits to a framing autoregressively and can't self-critique mid-generation. The **verifier** re-reads the finished memo adversarially (fresh call, draft-as-input — structurally separated, *not* an in-prompt self-check), grounding numeric claims via the FRED tool and checking catalyst pegs against the Upcoming Catalysts list; the **revise** pass applies the flagged fixes and propagates each to sibling claims. The whole step is wrapped in try/except — a failure logs and ships the unrevised draft. Verifier input is JSON `{"memo", "upcoming_catalysts"}`.

### Themes Ledger (rolling multi-day state)
Gated by `ENABLE_LEDGER`. A compact, curated watchlist (≤8 themes) of the macro narratives the memo is tracking, carried across days so synthesis can surface inflections and avoid repetition. It feeds synthesis **as an input** — the prior themes, framed as *claims to re-test against today's data, not a house view to continue*. That anchoring guard is load-bearing and validated by `validate_anchoring.py` (refuted priors flip, supported ones hold). After the memo is finalized, a separate **Sonnet update pass** (`ledger_agent`) reads `{prior_ledger, memo}` and rewrites the ledger: carry forward (preserving `first_seen`), set status (building/intact/inflecting/fading/resolved), add new durable threads, prune resolved or ~5-day-stale entries. State lives at `.reports/YYYY/MM/DD/themes_ledger.json`; `load_ledger()` reads the newest snapshot from a day strictly before today (so same-day re-runs read the prior day, not their own write). Because `.reports/` is the `gh-pages` worktree, these snapshots publish with the memos. The whole step is try/except — a failure keeps the prior ledger and ships the memo.

### Bounded FRED Tool
`register_fred_tools()` attaches `fred_search`/`fred_series` to both the synthesizing and verifier agents (shared `FredToolkit` deps: a `Fred` client, a fetch budget, and a provenance log). It lets an agent fetch an additional series on demand to *compute* a figure rather than estimate it; fetched series are appended to the citation sources. Capped at `MAX_FRED_TOOL_CALLS`; degrades gracefully (and the daily still runs) if `FRED_API_KEY` is absent.

### Citation System
The citation agent receives the full report and a list of sources (title + URL). It must insert citations inline without fabricating sources. The citation step is wrapped in try/except, so a failure is logged and the report falls back to the uncited version.

### FRED Data Structure
FRED data is stored as `{"title": str, "data": [{"date": str, "value": float}], "url": str}`. Only the last `NUM_FRED_DATAPOINTS` are kept per series.

### Prediction Market Schema
Both Kalshi and Polymarket are normalized to:
```python
{"id": str, "title": str, "bets": [{"prompt": str, "probability": float}], "url": str}
```

### Output Directory Structure
Reports are organized as `.reports/YYYY/MM/DD/index.html` for GitHub Pages hosting with date-based navigation. `.reports/` is a git worktree on the `gh-pages` branch, so writing a report there and pushing (via `run_cron.sh`) is what publishes it.

## Ecosystem

Zeitgeist is part of a broader personal investment research stack:

- **Oracle** (downstream): Oracle maps strategic macro questions to scenario analyses with economic indicators and decision rules. Zeitgeist's daily news discovery and market synthesis will feed into oracle's AI assessments, providing richer narrative context for scenario monitoring.
- **Fintools** (planned upstream): Fintools is building a comprehensive financial data library (SEC EDGAR, Yahoo Finance, FRED, NASDAQ). Once mature, it will broaden the set of indicators zeitgeist can track beyond its current FRED-only economic data — enabling coverage of earnings, positioning, factor dynamics, and company-level fundamentals.

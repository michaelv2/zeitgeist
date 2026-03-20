# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Zeitgeist is a Python application that generates daily investment macro reports by:
1. Fetching prediction market data from Kalshi and Polymarket
2. Filtering for investment-relevant predictions using LLMs
3. Gathering economic data from FRED API
4. Collecting news headlines via GNews
5. Finding upcoming market catalysts via web search
6. Synthesizing everything into a markdown investment memo
7. Adding citations and rendering to HTML

The application runs daily via GitHub Actions and publishes reports to GitHub Pages.

## Development Commands

### Run the application
```bash
uv run python zeitgeist.py
```

This will:
- Fetch data from prediction markets, FRED, and news sources
- Generate a report using OpenAI models
- Save HTML output to `.reports/YYYY/MM/DD/index.html`
- Open the report in your browser (dev mode only)

### Quick smoke test
The script automatically runs in "quick test" mode when `GITHUB_ACTIONS` is not set. This limits data fetching to first few batches for faster iteration during development.

### Required environment variables
- `OPENAI_API_KEY` (required) - For LLM agents
- `FRED_API_KEY` (optional) - For economic data; script continues without it

Create a `.env` file with these keys for local development.

## Architecture

### Multi-stage LLM Pipeline

The application uses three specialized pydantic-ai agents:

1. **Relevant Prediction Agent** (`relevant_prediction_agent`)
   - Model: `gpt-5-mini-2025-08-07` (fast classifier)
   - Processes prediction markets in batches of 100
   - Filters for investment-relevant predictions
   - Tags each with affected topics/sectors
   - Template: `templates/relevant_prediction_prompt.mako`

2. **Events Agent** (`events_agent`)
   - Model: `gpt-5.1-2025-11-13`
   - Has web search tool enabled (`search_context_size: "high"`)
   - Finds upcoming macro catalysts (earnings, Fed meetings, regulatory events)
   - Returns structured events with titles, dates, and topics
   - Template: `templates/events_prompt.mako`

3. **Synthesizing Agent** (`synthesizing_agent`)
   - Model: `gpt-4.1-2025-04-14` (most capable for report writing)
   - Consolidates all inputs into investment memo
   - Writes in succinct investment analyst style
   - Template: `templates/synthesizing_prompt.mako`

4. **Citation Agent** (inline, no dedicated variable)
   - Model: `gpt-4.1-2025-04-14`
   - Post-processes report to insert markdown citations
   - Template: `templates/citation_prompt.mako`

### Data Flow

```
Kalshi API + Polymarket API → pl.DataFrame (predictions)
        ↓
Batched through Relevant Prediction Agent → tagged_predictions
        ↓
                    ┌─ tagged_predictions
                    ├─ Events Agent → upcoming catalysts
Synthesizing Agent ─┤─ GNews → news headlines
                    └─ FRED API → macro data points
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
- `synthesizing_prompt.mako`: Main report generation instructions (structure, style, format)
- `citation_prompt.mako`: Adds markdown citations to the final report
- `index.html.mako`: HTML wrapper for the final report

### Configuration Constants

At the top of `zeitgeist.py`:
- `QUICK_TEST`: Set to `True` in dev mode to limit data fetching
- `BATCH_SIZE`: Number of predictions per LLM batch (100)
- `BATCH_REQUEST_DELAY_SECONDS`: Delay between batches (5s) to avoid rate limits
- `CLASSIFYING_MODEL`, `EVENTS_MODEL`, `SYNTHESIS_MODEL`: OpenAI model selection per agent
- `FRED_CODES`: Dict mapping FRED series codes to human-readable names
- `NUM_FRED_DATAPOINTS`: How many recent datapoints to fetch per FRED series (10)

### GitHub Actions Workflow

`.github/workflows/daily_report.yml`:
- Runs daily at 6am ET (11am UTC)
- Uses `uv` for Python dependency management
- Secrets injected via `oNaiPs/secrets-to-env-action`
- Output published to `gh-pages` branch with `keep_files: true`

## Critical Implementation Notes

### Citation System
The citation agent receives the full report and a list of sources (title + URL). It must insert citations inline without fabricating sources. If citations fail, the report falls back to the uncited version (see zeitgeist.py:273-278).

### FRED Data Structure
FRED data is stored as `{"title": str, "data": [{"date": str, "value": float}], "url": str}`. Only the last `NUM_FRED_DATAPOINTS` are kept per series.

### Prediction Market Schema
Both Kalshi and Polymarket are normalized to:
```python
{"id": str, "title": str, "bets": [{"prompt": str, "probability": float}], "url": str}
```

### Output Directory Structure
Reports are organized as `.reports/YYYY/MM/DD/index.html` for GitHub Pages hosting with date-based navigation.

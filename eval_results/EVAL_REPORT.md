# Zeitgeist Local Model Evaluation Report

**Date:** 2026-03-19
**Baseline report:** `.reports/2026/03/19/index.html` (GPT-4.1 synthesis, GPT-5-mini classifier)
**Local Ollama endpoint:** `192.168.1.74:11434`
**Eval harness:** `eval_harness.py`

---

## Component Overview

Zeitgeist uses 3 LLM agents. Each was evaluated independently:

| Component | Current Model | Task | Structured Output? | Web Search? |
|---|---|---|---|---|
| Classifier | `gpt-5-mini` | Filter predictions for relevance | Yes (`list[RelevantPrediction]`) | No |
| Events | `gpt-5.1` | Find upcoming catalysts | Yes (`list[Event]`) | **Yes** (OpenAI-native) |
| Synthesis | `gpt-4.1` | Write investment memo | No (`str`) | No |

---

## Events Agent: NOT EVALUABLE

The events agent uses OpenAI's native `web_search` tool (`search_context_size: "high"`). This is exclusive to OpenAI models — neither Ollama local models nor Anthropic models have an equivalent built-in web search capability.

**Recommendation: No change.** Must remain on OpenAI.

---

## Classifier Evaluation

Tested on 200 Polymarket predictions (2 batches of 100). Kalshi SSL error in WSL prevented dual-source data.

### Results

| Model | Success Rate | Avg Selected/Batch | Precision vs Baseline | Recall vs Baseline | Avg F1 | Avg Time (s) |
|---|---|---|---|---|---|---|
| **gpt-5-mini (baseline)** | 2/2 | 8 | 100% | 100% | 100% | 24.1 |
| gemma3:27b | 0/2 | 0 | — | — | — | 0.1 |
| qwen3.5:27b | 2/2 | 0 | — | 0% | 0% | 75.4 |
| llama3.3:70b-q3_K_M | 0/2 | 0 | — | — | — | 48.5 |
| **claude-haiku** | 2/2 | 4 | **100%** | 46% | 61% | **1.6** |

### Failure Analysis

- **gemma3:27b**: Ollama reports `does not support tools`. Immediate failure — pydantic-ai requires tool calling for structured output.
- **qwen3.5:27b**: Tool calling succeeded but returned empty lists. The model parsed the schema but selected zero predictions across both batches.
- **llama3.3:70b-q3_K_M**: `Exceeded maximum retries for result validation` — model returned responses that didn't match the `list[RelevantPrediction]` schema after 2 retries.
- **claude-haiku**: Worked cleanly. Every selection matched the baseline (100% precision), but it was more conservative — selected ~4 per batch vs 8 for GPT-5-mini (~46% recall). 15x faster.

### Root Cause

pydantic-ai uses **tool/function calling** to enforce `output_type=list[RelevantPrediction]`. Local models via Ollama have poor or absent tool calling support for this use case. The memoize project's successful local model evaluation used **raw JSON prompting** (no tool calling), which is a fundamentally different approach.

---

## Synthesis Evaluation

All models received identical input: 10 baseline-tagged predictions + 35K chars of news/events/FRED data.

### Results

| Model | Success | Words | Sections | News Section? | Catalysts Section? | Time (s) |
|---|---|---|---|---|---|---|
| **GPT-4.1 (baseline)** | Y | 1047 | ~9 | Y | Y | ~15* |
| gemma3:27b | Y | 460 | 0 | N | N | 30.9 |
| llama3.3:70b | Y | 504 | 7 | N | N | 244.5 |
| qwen2.5:72b | Y | 794 | 10 | N | N | 1016.3 |
| **claude-sonnet** | Y | 1655 | 21 | **Y** | **Y** | 80.1 |

*GPT-4.1 time estimated from prior runs; not re-timed in this eval.

### Quality Assessment

**gemma3:27b** — Produced a generic summary of FRED data points, then *asked follow-up questions* ("Are you interested in monetary policy implications?"). Completely ignored the investment memo format, news, predictions, and catalysts. **Not viable.**

**llama3.3:70b** — Described the input data structure and suggested analytical steps ("use Python", "perform correlation analysis", "apply ARIMA forecasting"). Did not attempt to write a report. **Not viable.**

**qwen2.5:72b** — Generated textbook-style definitions of economic indicators (what CPI measures, what JOLTS is) rather than synthesizing the actual data into investment insights. 17 minutes for an irrelevant output. **Not viable.**

**claude-sonnet** — Produced an excellent investment memo. Compared to the GPT-4.1 baseline:
- All required sections present: Top News, Macro, Geopolitical Risks, Sectors, Upcoming Catalysts
- Investment analyst writing style with specific numbers and actionable framing
- More comprehensive coverage (1655 vs 1047 words) with additional subsections (Crypto, REITs/Housing, Political Risk)
- Catalysts section is more specific with dates and expected impact
- Took 80s vs ~15s estimated for GPT-4.1

**Verdict: Claude Sonnet is a viable — and possibly superior — replacement for GPT-4.1 in the synthesis role.**

---

## Recommendations

### Summary Table

| Component | Current | Recommendation | Rationale |
|---|---|---|---|
| **Events** | `gpt-5.1` | **No change** | Web search tool is OpenAI-exclusive |
| **Classifier** | `gpt-5-mini` | **No change** | Local models fail on tool calling; Haiku viable but loses 50% recall |
| **Synthesis** | `gpt-4.1` | **Consider claude-sonnet** | Higher quality output; 5x slower but still sub-2-min |

### Detailed Recommendations

1. **Synthesis — Claude Sonnet is a genuine upgrade candidate.** Output quality is at least on par with GPT-4.1, arguably better. The 80s latency is acceptable for a daily report (vs ~15s for GPT-4.1). Cost is comparable for a once-daily single invocation.

2. **Classifier — No local model viable today.** The blocker is pydantic-ai's tool calling requirement, not raw model capability. If you wanted to pursue this, it would require refactoring the classifier to use JSON-mode prompting (like memoize does) instead of pydantic-ai structured output. Based on the memoize eval data, gemma3:27b (100% JSON reliability) would then be the top candidate.

3. **Events — No alternative exists.** OpenAI's web_search tool is a hard dependency. Replacing it would require building a separate search integration (SerpAPI, Brave Search, etc.) and prompt-engineering a local model to use it — a significant architectural change.

4. **No local model should be used for synthesis.** All three (gemma3:27b, llama3.3:70b, qwen2.5:72b) failed to understand the complex multi-step synthesis prompt. The task requires investment domain knowledge, multi-source data fusion, and adherence to a detailed output format — beyond the capability of current ~30-70b local models.

---

## Explicit Assumptions

1. **Gemma3 tool calling**: Assumed Ollama's current report of "does not support tools" is accurate. A future Ollama or Gemma version may add support — this would change the classifier finding.

2. **Synthesis input sparsity**: Only 10 predictions were tagged (from 200 total, quick-test mode). The production pipeline processes thousands and typically tags more. Sparser input may have made it harder for local models to understand the task, but their outputs were so off-target that input density is unlikely to be the deciding factor.

3. **Kalshi data unavailable**: SSL cert error in WSL prevented Kalshi fetching. The eval used only Polymarket data (200 predictions). A dual-source dataset would be larger but the model quality findings should hold.

4. **Cost not measured**: No per-invocation cost comparison was conducted. For a once-daily pipeline, cost differences between GPT-4.1 and Claude Sonnet are minimal (cents per run). Local models would be $0 marginal cost but failed on quality.

5. **Quantization effects**: All local models tested at default Ollama quantization (mostly Q4_K_M). Higher-precision quantization might improve tool calling reliability but would increase memory and latency.

6. **Claude Sonnet verbosity**: Sonnet's output was 58% longer than GPT-4.1 (1655 vs 1047 words). This may be a positive (more comprehensive) or negative (too verbose for a daily memo) depending on preference. The prompt's style instructions ("no fluff", "short bullet points") were better followed than local models but not as tightly as GPT-4.1.

7. **Single-run evaluation**: Each model was run once per component. Results may vary across runs due to model temperature and stochastic decoding. A multi-run evaluation would increase confidence but was not practical given local model latency (17 min for a single qwen2.5:72b run).

---

## Raw Data

- `eval_data/` — Cached prediction, events, news, and FRED data used for all eval runs
- `eval_results/classifier_raw.json` — Per-batch classifier results
- `eval_results/synthesis_raw.json` — Synthesis metrics (excluding report text)
- `eval_results/synthesis_*.md` — Full synthesis output per model
- `eval_harness.py` — Evaluation harness source

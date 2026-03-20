"""
Zeitgeist Model Evaluation Harness

Evaluates local Ollama models and Anthropic API models as replacements for OpenAI
in the classifier and synthesis components. The events agent (which requires OpenAI's
web_search tool) is excluded — it cannot be replaced by local models.

Usage:
    uv run python eval_harness.py [--phase classifier|synthesis|all] [--skip-fetch]
"""

import asyncio
import json
import time
import sys
import os
import logging as log
from datetime import date
from pathlib import Path
from dataclasses import dataclass, field, asdict

import polars as pl
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from mako.lookup import TemplateLookup
from dotenv import load_dotenv
import httpx

load_dotenv()
log.basicConfig(level=log.INFO, format="%(asctime)s %(levelname)s %(message)s")

today = date.today()
templates = TemplateLookup(directories=["templates"])

OLLAMA_URL = "http://192.168.1.74:11434/v1"
EVAL_DIR = Path("eval_data")
RESULTS_DIR = Path("eval_results")
RETRIES = 2
BATCH_SIZE = 100
RATE_LIMIT_WAIT_SECONDS = 10

# ─── Model Definitions ───────────────────────────────────────────────────────

def ollama_model(name: str) -> OpenAIModel:
    provider = OpenAIProvider(base_url=OLLAMA_URL, api_key="ollama")
    return OpenAIModel(name, provider=provider)

CLASSIFIER_MODELS: dict[str, str | OpenAIModel] = {
    "gpt-5-mini (baseline)": "openai:gpt-5-mini-2025-08-07",
    "gemma3:27b": ollama_model("gemma3:27b"),
    "qwen3.5:27b": ollama_model("qwen3.5:27b"),
    "llama3.3:70b-q3_K_M": ollama_model("llama3.3:70b-instruct-q3_K_M"),
    "claude-haiku": "anthropic:claude-haiku-4-5-20251001",
}

SYNTHESIS_MODELS: dict[str, str | OpenAIModel] = {
    "gemma3:27b": ollama_model("gemma3:27b"),
    "llama3.3:70b": ollama_model("llama3.3:70b"),
    "qwen2.5:72b": ollama_model("qwen2.5:72b"),
    "claude-sonnet": "anthropic:claude-sonnet-4-6",
}

# ─── Schemas (same as zeitgeist.py) ──────────────────────────────────────────

class RelevantPrediction(BaseModel):
    id: str = Field(description="original id from input")
    topics: str = Field(description="Very short phrase (1-3 words): public companies or investment sectors or broad alternatives impacted")

class Event(BaseModel):
    title: str = Field(description="title of macro event or catalyst")
    when: str = Field(description="approximately when; either specific date or stringy like '2025 Q2' or 'next month'")
    url: str | None = Field(description="web url linking to a page with details about the event - okay to skip if url is not available or too generic")
    topics: str = Field(description="Very short phrase (1-3 words): public companies or investment sectors or broad alternatives impacted")

# ─── Result Tracking ─────────────────────────────────────────────────────────

@dataclass
class ClassifierResult:
    model: str
    batch_idx: int
    selected_ids: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    success: bool = False
    error: str = ""

@dataclass
class SynthesisResult:
    model: str
    report: str = ""
    word_count: int = 0
    section_count: int = 0
    has_news: bool = False
    has_catalysts: bool = False
    elapsed_s: float = 0.0
    success: bool = False
    error: str = ""

# ─── Data Fetching (reused from zeitgeist.py) ────────────────────────────────

async def sleep_if_rate_limit(response: httpx.Response) -> bool:
    if response.status_code != 429:
        return False
    log.warning(f"Rate limited by {response.url}, sleeping {RATE_LIMIT_WAIT_SECONDS}s...")
    await asyncio.sleep(RATE_LIMIT_WAIT_SECONDS)
    return True

async def fetch_from_kalshi() -> pl.DataFrame:
    LIMIT = 100
    API_URL = "https://api.elections.kalshi.com/trade-api/v2"
    params = {"status": "open", "with_nested_markets": "true", "limit": LIMIT, "cursor": None}
    predictions = []

    def simple_prediction(e):
        bets = [{"prompt": m["yes_sub_title"], "probability": m["last_price"] / m["notional_value"]}
                for m in e["markets"]]
        return {"id": f"k-{e['event_ticker']}", "title": e["title"], "bets": bets,
                "url": f"https://kalshi.com/markets/{e['series_ticker']}"}

    async with httpx.AsyncClient() as client:
        while True:
            log.info(f"Fetching from kalshi @ offset={len(predictions)} ...")
            try:
                resp = await client.get(f"{API_URL}/events", params=params)
                if await sleep_if_rate_limit(resp):
                    continue
                resp.raise_for_status()
                data = resp.json()
                predictions.extend(data["events"])
                params["cursor"] = data.get("cursor")
            except Exception as e:
                log.error(f"Error from Kalshi: {e}")
                params["cursor"] = None
            if not params["cursor"] or len(predictions) > LIMIT:
                log.info(f"Fetched {len(predictions)} from kalshi")
                return pl.DataFrame([simple_prediction(p) for p in predictions])

async def fetch_from_polymarket() -> pl.DataFrame:
    LIMIT = 100
    API_URL = "https://gamma-api.polymarket.com"
    predictions = []

    def simple_prediction(p):
        bets = [{"prompt": prompt, "probability": float(prob)}
                for prompt, prob in zip(json.loads(p["outcomes"]), json.loads(p.get("outcomePrices", "[]")))]
        return {"id": f"pm-{p['id']}", "title": p["question"], "bets": bets,
                "url": f"https://polymarket.com/event/{p['slug']}"}

    async with httpx.AsyncClient() as client:
        while True:
            params = {"active": "true", "closed": "false", "limit": LIMIT, "offset": len(predictions)}
            log.info(f"Fetching from polymarket @ offset={params['offset']} ...")
            try:
                resp = await client.get(f"{API_URL}/markets", params=params)
                if await sleep_if_rate_limit(resp):
                    continue
                resp.raise_for_status()
                data = resp.json()
                predictions.extend(data)
            except Exception as e:
                log.error(f"Error from Polymarket: {e}")
                data = None
            if not data or len(predictions) > LIMIT:
                log.info(f"Fetched {len(predictions)} from polymarket")
                return pl.DataFrame([simple_prediction(p) for p in predictions])

def get_fred_data() -> pl.DataFrame | None:
    from fredapi import Fred
    FRED_API_KEY = os.getenv("FRED_API_KEY")
    if not FRED_API_KEY:
        log.warning("No FRED API key; skipping FRED data")
        return None
    FRED_CODES = {
        "CPILFESL": "CPI (Core)", "PCEPILFE": "PCE Price Index (Core)",
        "PAYEMS": "Nonfarm Payrolls", "UNRATE": "Unemployment Rate",
        "CCSA": "Continuing Jobless Claims", "JTSJOL": "Job Openings (JOLTS)",
        "INDPRO": "Industrial Production", "RSAFS": "Retail Sales (Headline)",
        "HOUST": "Housing Starts", "CSUSHPISA": "Case-Shiller U.S. Home Price Index",
        "FEDFUNDS": "Fed Funds Rate", "M2SL": "M2 Money Supply",
        "DGS2": "2Y Treasury Yield", "DGS10": "10Y Treasury Yield",
        "T10Y2Y": "10Y–2Y Yield Spread", "T10Y3M": "10Y–3M Yield Spread",
        "NFCI": "Chicago Fed Financial Conditions Index",
        "DTWEXBGS": "Trade-Weighted USD Index (Broad)",
        "DCOILWTICO": "WTI Crude Oil Price", "UMCSENT": "Michigan Consumer Sentiment",
    }
    fred_client = Fred(api_key=FRED_API_KEY)
    out = []
    for code, title in FRED_CODES.items():
        try:
            series = fred_client.get_series_latest_release(code)
            records = [{"date": d.date().isoformat(), "value": float(v)}
                       for d, v in zip(series.index, series.values)]
            out.append({"title": title, "data": records[-10:],
                        "url": f"https://fred.stlouisfed.org/series/{code}"})
        except Exception as e:
            log.error(f"Failed FRED {code}: {e}")
    return pl.DataFrame(out) if out else None

def get_news() -> pl.DataFrame | None:
    from gnews import GNews
    try:
        news = GNews().get_top_news()
        log.info(f"Fetched {len(news)} news headlines")
        return pl.DataFrame(news)
    except Exception as e:
        log.error(f"Error from GNews: {e}")
        return None

async def get_events() -> pl.DataFrame:
    """Run events agent with OpenAI (only model that supports web_search tool)."""
    events_agent = Agent(
        model="openai:gpt-5.1-2025-11-13",
        output_type=list[Event],
        system_prompt=templates.get_template("events_prompt.mako").render(today=today),
        model_settings={"tools": [{"type": "web_search", "search_context_size": "high"}]},
        retries=RETRIES,
    )
    res = await events_agent.run()
    return pl.DataFrame(res.output)

# ─── Phase 1: Fetch & Cache Data ─────────────────────────────────────────────

async def fetch_and_cache():
    """Fetch all data sources and cache to eval_data/ for reproducible runs."""
    EVAL_DIR.mkdir(exist_ok=True)

    predictions = pl.concat(await asyncio.gather(fetch_from_kalshi(), fetch_from_polymarket()))
    log.info(f"Total predictions: {len(predictions)}")

    events, news, fred_data = await asyncio.gather(
        get_events(),
        asyncio.to_thread(get_news),
        asyncio.to_thread(get_fred_data),
    )

    # Save all intermediate data
    predictions.write_json(EVAL_DIR / "predictions.json")
    events.write_json(EVAL_DIR / "events.json")
    if news is not None:
        news.write_json(EVAL_DIR / "news.json")
    if fred_data is not None:
        fred_data.write_json(EVAL_DIR / "fred_data.json")

    log.info(f"Cached data to {EVAL_DIR}/")
    return predictions, events, news, fred_data

def load_cached_data():
    """Load previously cached data."""
    predictions = pl.read_json(EVAL_DIR / "predictions.json")
    events = pl.read_json(EVAL_DIR / "events.json")
    news = pl.read_json(EVAL_DIR / "news.json") if (EVAL_DIR / "news.json").exists() else None
    fred_data = pl.read_json(EVAL_DIR / "fred_data.json") if (EVAL_DIR / "fred_data.json").exists() else None
    return predictions, events, news, fred_data

# ─── Phase 2: Classifier Evaluation ─────────────────────────────────────────

async def eval_classifier(predictions: pl.DataFrame) -> list[ClassifierResult]:
    """Run classifier on 3 batches per model, collect results."""
    system_prompt = templates.get_template("relevant_prediction_prompt.mako").render(today=today)
    batches = list(predictions.select("id", "title", "bets").iter_slices(BATCH_SIZE))[:3]
    log.info(f"Classifier eval: {len(batches)} batches, {sum(len(b) for b in batches)} predictions")

    results: list[ClassifierResult] = []

    for model_name, model_spec in CLASSIFIER_MODELS.items():
        agent = Agent(
            model=model_spec,
            output_type=list[RelevantPrediction],
            system_prompt=system_prompt,
            retries=RETRIES,
        )
        for batch_idx, batch in enumerate(batches):
            result = ClassifierResult(model=model_name, batch_idx=batch_idx)
            log.info(f"  Classifier: {model_name} batch {batch_idx} ({len(batch)} predictions)...")
            t0 = time.monotonic()
            try:
                res = await agent.run(batch.write_json())
                result.elapsed_s = time.monotonic() - t0
                result.selected_ids = [p.id for p in res.output]
                result.success = True
                log.info(f"    -> {len(result.selected_ids)} selected in {result.elapsed_s:.1f}s")
            except Exception as e:
                result.elapsed_s = time.monotonic() - t0
                result.error = str(e)
                log.error(f"    -> FAILED in {result.elapsed_s:.1f}s: {e}")
            results.append(result)

    return results

# ─── Phase 3: Synthesis Evaluation ───────────────────────────────────────────

async def eval_synthesis(
    tagged_predictions: pl.DataFrame,
    events: pl.DataFrame,
    news: pl.DataFrame | None,
    fred_data: pl.DataFrame | None,
) -> list[SynthesisResult]:
    """Run synthesis on each model with the same input data."""
    system_prompt = templates.get_template("synthesizing_prompt.mako").render(today=today)

    report_input = {
        "prediction_markets": tagged_predictions.select("title", "bets", "topics").to_dicts(),
        "news_headlines": news.select("title", "description").to_dicts() if news is not None else None,
        "upcoming_catalysts": events.select("title", "when", "topics").to_dicts(),
        "fred_data_points": fred_data.select("title", "data").to_dicts() if fred_data is not None else None,
    }
    input_json = json.dumps(report_input)
    log.info(f"Synthesis input: {len(input_json)} chars")

    results: list[SynthesisResult] = []

    for model_name, model_spec in SYNTHESIS_MODELS.items():
        result = SynthesisResult(model=model_name)
        log.info(f"  Synthesis: {model_name}...")
        agent = Agent(
            model=model_spec,
            output_type=str,
            system_prompt=system_prompt,
            retries=RETRIES,
        )
        t0 = time.monotonic()
        try:
            res = await agent.run(input_json)
            report = res.output
            result.elapsed_s = time.monotonic() - t0
            result.report = report
            result.word_count = len(report.split())
            result.section_count = report.count("## ")
            result.has_news = any(kw in report.lower() for kw in ["news", "headline", "top news"])
            result.has_catalysts = "catalyst" in report.lower() or "upcoming" in report.lower()
            result.success = True
            log.info(f"    -> {result.word_count} words, {result.section_count} sections in {result.elapsed_s:.1f}s")
        except Exception as e:
            result.elapsed_s = time.monotonic() - t0
            result.error = str(e)
            log.error(f"    -> FAILED in {result.elapsed_s:.1f}s: {e}")
        results.append(result)

    return results

# ─── Analysis ────────────────────────────────────────────────────────────────

def analyze_classifier(results: list[ClassifierResult]) -> str:
    """Compute metrics and produce comparison table."""
    # Get baseline IDs per batch
    baseline_by_batch: dict[int, set[str]] = {}
    for r in results:
        if r.model == "gpt-5-mini (baseline)" and r.success:
            baseline_by_batch[r.batch_idx] = set(r.selected_ids)

    lines = ["## Classifier Evaluation Results\n"]
    lines.append("| Model | Batch | Success | Selected | Overlap | Precision | Recall | F1 | Time (s) |")
    lines.append("|---|---|---|---|---|---|---|---|---|")

    model_aggs: dict[str, dict] = {}

    for r in results:
        baseline_ids = baseline_by_batch.get(r.batch_idx, set())
        selected = set(r.selected_ids)

        if r.success and baseline_ids:
            overlap = len(selected & baseline_ids)
            precision = overlap / len(selected) if selected else 0
            recall = overlap / len(baseline_ids) if baseline_ids else 0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        else:
            overlap = precision = recall = f1 = 0

        lines.append(
            f"| {r.model} | {r.batch_idx} | {'Y' if r.success else 'N'} | {len(r.selected_ids)} | "
            f"{overlap} | {precision:.0%} | {recall:.0%} | {f1:.0%} | {r.elapsed_s:.1f} |"
        )

        if r.model not in model_aggs:
            model_aggs[r.model] = {"successes": 0, "total": 0, "f1_sum": 0, "time_sum": 0,
                                   "prec_sum": 0, "rec_sum": 0, "selected_sum": 0}
        agg = model_aggs[r.model]
        agg["total"] += 1
        if r.success:
            agg["successes"] += 1
            agg["f1_sum"] += f1
            agg["prec_sum"] += precision
            agg["rec_sum"] += recall
            agg["time_sum"] += r.elapsed_s
            agg["selected_sum"] += len(r.selected_ids)

    lines.append("\n### Classifier Summary\n")
    lines.append("| Model | Success Rate | Avg Selected | Avg Precision | Avg Recall | Avg F1 | Avg Time (s) |")
    lines.append("|---|---|---|---|---|---|---|")

    for model, agg in model_aggs.items():
        n = max(agg["successes"], 1)
        lines.append(
            f"| {model} | {agg['successes']}/{agg['total']} | "
            f"{agg['selected_sum']/n:.0f} | "
            f"{agg['prec_sum']/n:.0%} | "
            f"{agg['rec_sum']/n:.0%} | "
            f"{agg['f1_sum']/n:.0%} | "
            f"{agg['time_sum']/n:.1f} |"
        )

    return "\n".join(lines)

def analyze_synthesis(results: list[SynthesisResult], baseline_word_count: int) -> str:
    """Produce comparison table for synthesis results."""
    lines = ["## Synthesis Evaluation Results\n"]
    lines.append(f"**Baseline (today's GPT-4.1 report):** {baseline_word_count} words\n")
    lines.append("| Model | Success | Words | Sections | News? | Catalysts? | Time (s) |")
    lines.append("|---|---|---|---|---|---|---|")

    for r in results:
        lines.append(
            f"| {r.model} | {'Y' if r.success else 'N'} | "
            f"{r.word_count} | {r.section_count} | "
            f"{'Y' if r.has_news else 'N'} | "
            f"{'Y' if r.has_catalysts else 'N'} | "
            f"{r.elapsed_s:.1f} |"
        )
        if r.error:
            lines.append(f"| | Error: {r.error[:120]} | | | | | |")

    return "\n".join(lines)

# ─── Main ────────────────────────────────────────────────────────────────────

async def main():
    phase = "all"
    skip_fetch = False
    for arg in sys.argv[1:]:
        if arg == "--skip-fetch":
            skip_fetch = True
        elif arg.startswith("--phase="):
            phase = arg.split("=", 1)[1]

    # Phase 1: Data
    if skip_fetch and EVAL_DIR.exists():
        log.info("Loading cached data...")
        predictions, events, news, fred_data = load_cached_data()
    else:
        log.info("Fetching fresh data...")
        predictions, events, news, fred_data = await fetch_and_cache()

    RESULTS_DIR.mkdir(exist_ok=True)

    # Phase 2: Classifier
    classifier_report = ""
    baseline_tagged = None
    if phase in ("all", "classifier"):
        log.info("=== CLASSIFIER EVALUATION ===")
        classifier_results = await eval_classifier(predictions)

        # Save raw results
        with open(RESULTS_DIR / "classifier_raw.json", "w") as f:
            json.dump([asdict(r) for r in classifier_results], f, indent=2)

        classifier_report = analyze_classifier(classifier_results)

        # Extract baseline tagged predictions for synthesis eval
        baseline_ids: set[str] = set()
        for r in classifier_results:
            if r.model == "gpt-5-mini (baseline)" and r.success:
                baseline_ids.update(r.selected_ids)

        if baseline_ids:
            # Create a simple topics column from baseline results
            topics_map = {}
            for r in classifier_results:
                if r.model == "gpt-5-mini (baseline)":
                    # We need to re-run to get topics... use saved results
                    pass

    # For synthesis, we need tagged predictions. Run baseline classifier to get them.
    if phase in ("all", "synthesis"):
        log.info("=== Running baseline classifier for synthesis input ===")
        system_prompt = templates.get_template("relevant_prediction_prompt.mako").render(today=today)
        baseline_agent = Agent(
            model="openai:gpt-5-mini-2025-08-07",
            output_type=list[RelevantPrediction],
            system_prompt=system_prompt,
            retries=RETRIES,
        )

        all_tagged = []
        for i, batch in enumerate(predictions.select("id", "title", "bets").iter_slices(BATCH_SIZE)):
            log.info(f"  Baseline tagging batch {i}...")
            try:
                res = await baseline_agent.run(batch.write_json())
                if res.output:
                    all_tagged.extend(res.output)
            except Exception as e:
                log.error(f"  Baseline tagging batch {i} failed: {e}")
            await asyncio.sleep(2)

        if all_tagged:
            tagged_df = pl.DataFrame([{"id": p.id, "topics": p.topics} for p in all_tagged])
            tagged_predictions = predictions.join(tagged_df, on="id", how="inner")
            log.info(f"Baseline tagged {len(tagged_predictions)} predictions")

            # Save tagged predictions
            tagged_predictions.write_json(EVAL_DIR / "tagged_predictions.json")
        else:
            log.error("No tagged predictions from baseline — cannot run synthesis eval")
            tagged_predictions = None

    # Phase 3: Synthesis
    synthesis_report = ""
    if phase in ("all", "synthesis") and tagged_predictions is not None:
        log.info("=== SYNTHESIS EVALUATION ===")
        synthesis_results = await eval_synthesis(tagged_predictions, events, news, fred_data)

        # Save raw results and individual reports
        synth_out = []
        for r in synthesis_results:
            if r.report:
                report_file = RESULTS_DIR / f"synthesis_{r.model.replace(':', '_').replace('.', '_')}.md"
                report_file.write_text(r.report, encoding="utf-8")
            synth_out.append({k: v for k, v in asdict(r).items() if k != "report"})
        with open(RESULTS_DIR / "synthesis_raw.json", "w") as f:
            json.dump(synth_out, f, indent=2)

        # Baseline word count from today's report
        baseline_html = Path(".reports/2026/03/19/index.html")
        if baseline_html.exists():
            from html.parser import HTMLParser
            class TextExtractor(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.in_main = False
                    self.text = []
                def handle_starttag(self, tag, attrs):
                    if tag == "main":
                        self.in_main = True
                def handle_endtag(self, tag):
                    if tag == "main":
                        self.in_main = False
                def handle_data(self, data):
                    if self.in_main:
                        self.text.append(data)
            ext = TextExtractor()
            ext.feed(baseline_html.read_text())
            baseline_wc = len(" ".join(ext.text).split())
        else:
            baseline_wc = 0

        synthesis_report = analyze_synthesis(synthesis_results, baseline_wc)

    # Phase 4: Final Report
    final_report = f"""# Zeitgeist Model Evaluation Report
**Date:** {today.isoformat()}
**Evaluation data:** {len(predictions) if 'predictions' in dir() else '?'} predictions

{classifier_report}

{synthesis_report}
"""

    report_file = RESULTS_DIR / "EVAL_REPORT.md"
    report_file.write_text(final_report, encoding="utf-8")
    log.info(f"Report saved to {report_file}")
    print(f"\n{'='*60}")
    print(final_report)
    print(f"{'='*60}")

if __name__ == "__main__":
    asyncio.run(main())

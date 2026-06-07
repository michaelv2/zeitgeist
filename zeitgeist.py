import asyncio
from datetime import date
from dataclasses import dataclass, field
import json
from pathlib import Path
import os
import logging as log

import polars as pl
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
import httpx

from mako.lookup import TemplateLookup

from dotenv import load_dotenv

########################################## Setup Configs #################################################

IS_PROD = "GITHUB_ACTIONS" in os.environ
IS_DEV = not IS_PROD

QUICK_TEST = IS_DEV # If True, run quickly on first few predictions; useful for smoke-testing

ENABLE_CITATIONS = True
ENABLE_EMAIL_BRIEFING = True
ENABLE_FRED_TOOL = True  # give synthesis a bounded FRED search/fetch tool to ground claims on demand

BATCH_REQUEST_DELAY_SECONDS = 5
RATE_LIMIT_WAIT_SECONDS = 10

BATCH_SIZE = 100
RETRIES = 3
MAX_FRED_TOOL_CALLS = 8  # per-synthesis cap on on-demand FRED fetches (bounds cost/latency)

CLASSIFYING_MODEL = "anthropic:claude-haiku-4-5-20251001"
EVENTS_MODEL = "openai-responses:gpt-5.1-2025-11-13"  # Responses API: required for native web_search in pydantic-ai 1.x
SYNTHESIS_MODEL = "anthropic:claude-opus-4-8"  # Opus 4.8 single-pass deep synthesis (adaptive thinking + effort)
CITATION_MODEL = "anthropic:claude-sonnet-4-6"  # mechanical link-insertion; cheaper than the synthesis model
COMPARISON_MODEL = None  # Parallel A/B disabled; set a model string (e.g. "openai-chat:gpt-4.1-2025-04-14") to re-enable index2.html


today = date.today()

load_dotenv()
log.getLogger().setLevel(log.INFO)
templates = TemplateLookup(directories=["templates"])

FRED_API_KEY=os.getenv("FRED_API_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
NUM_FRED_DATAPOINTS = 10

FRED_CODES = {
    "CPIAUCSL": "CPI (Headline)",
    "CPILFESL": "CPI (Core)",
    "PCEPILFE": "PCE Price Index (Core)",
    "PAYEMS": "Nonfarm Payrolls",
    "UNRATE": "Unemployment Rate",
    "CCSA": "Continuing Jobless Claims",
    "JTSJOL": "Job Openings (JOLTS)",
    "INDPRO": "Industrial Production",
    "RSAFS": "Retail Sales (Headline)",
    "HOUST": "Housing Starts",
    "CSUSHPISA": "Case-Shiller U.S. Home Price Index",
    "FEDFUNDS": "Fed Funds Rate",
    "M2SL": "M2 Money Supply",
    "DGS2": "2Y Treasury Yield",
    "DGS10": "10Y Treasury Yield",
    "T10Y2Y": "10Y–2Y Yield Spread",
    "T10Y3M": "10Y–3M Yield Spread",
    "NFCI": "Chicago Fed Financial Conditions Index",
    "DTWEXBGS": "Trade-Weighted USD Index (Broad)",
    "DCOILWTICO": "WTI Crude Oil Price",
    "UMCSENT": "Michigan Consumer Sentiment",
}

assert "OPENAI_API_KEY" in os.environ, "No OPENAI_API_KEY found; Either add to .env file or run `export OPENAI_API_KEY=???`"
assert not(IS_PROD and QUICK_TEST), "QUICK_TEST must be False in GitHub Actions"

########################################################################################################

async def sleep_if_rate_limit(response: httpx.Response) -> bool:
    if response.status_code != 429:
        return False
    log.warning(
        f"Sleeping for {RATE_LIMIT_WAIT_SECONDS}s since we got {response.status_code} from {response.url}..."
    )
    await asyncio.sleep(RATE_LIMIT_WAIT_SECONDS)
    return True

async def fetch_from_kalshi() -> pl.DataFrame:
    LIMIT = 100
    API_URL = "https://api.elections.kalshi.com/trade-api/v2"
    params = {"status": "open", "with_nested_markets": "true", "limit": LIMIT, "cursor": None}
    predictions = []

    def simple_prediction(e):
        bets = []
        for m in e["markets"]:
            bets.append({"prompt": m["yes_sub_title"], "probability": m["last_price"] / m["notional_value"]})
        return {
            "id": f"k-{e['event_ticker']}",
            "title": e["title"],
            "bets": bets,
            "url": f"https://kalshi.com/markets/{e['series_ticker']}",
        }

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
                log.error(f"Stopping because of error from Kalshi: {e}")
                params["cursor"] = None
            if not params["cursor"] or (QUICK_TEST and len(predictions) > LIMIT):
                log.info(f"Fetched {len(predictions)} from kalshi")
                return pl.DataFrame([simple_prediction(p) for p in predictions])

async def fetch_from_polymarket() -> pl.DataFrame:
    LIMIT = 100
    API_URL = "https://gamma-api.polymarket.com"
    predictions = []

    def simple_prediction(p):
        bets = []
        for prompt, probability in zip(json.loads(p["outcomes"]), json.loads(p.get("outcomePrices", "[]"))):
            bets.append({"prompt": prompt, "probability": float(probability)})
        event_slug = p["events"][0]["slug"] if p.get("events") else p["slug"]
        return {
            "id": f"pm-{p['id']}",
            "title": p["question"],
            "bets": bets,
            "url": f"https://polymarket.com/event/{event_slug}"
        }

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
                log.error(f"Stopping because of error from Polymarket: {e}")
                data = None
            if not data or (QUICK_TEST and len(predictions) > LIMIT):
                log.info(f"Fetched {len(predictions)} from polymarket")
                return pl.DataFrame([simple_prediction(p) for p in predictions])


def get_fred_data() -> pl.DataFrame | None:
    from fredapi import Fred

    if not FRED_API_KEY:
        log.warning("No FRED API key found; skipping FRED data points ...")
        return None

    fred_client = Fred(api_key=FRED_API_KEY)

    out = []
    for code, title in FRED_CODES.items():
        print(f"Fetching {title} ({code}) from FRED ...")
        try:
            series = fred_client.get_series_latest_release(code)
            log.info(f"Fetched {len(series)} data points for FRED {code=}")
            records = [
                {"date": d.date().isoformat(), "value": float(v)}
                for d, v in zip(series.index, series.values)
            ]
            out.append({
                "title": title,
                "data": records[-NUM_FRED_DATAPOINTS:],
                "url": f"https://fred.stlouisfed.org/series/{code}"
            })
        except Exception as e:
            log.error(f"Failed to fetch FRED {code=}: {e}")

    return pl.DataFrame(out)


class RelevantPrediction(BaseModel):
    id: str = Field(description="original id from input")
    topics: str = Field(description="Very short phrase (1-3 words): public companies or investment sectors or broad alternatives impacted")

relevant_prediction_agent = Agent(
    model=CLASSIFYING_MODEL,
    output_type=list[RelevantPrediction],
    system_prompt=templates.get_template("classifier_coarse_filter_prompt.mako").render(),
    retries=RETRIES,
)

async def tag_predictions(predictions: pl.DataFrame) -> pl.DataFrame:
    async def process_batch_with_delay(i: int, batch: pl.DataFrame) -> pl.DataFrame | None:
        await asyncio.sleep(i * BATCH_REQUEST_DELAY_SECONDS)
        log.info(f"Submitting batch {i} ...")
        try:
            result = await relevant_prediction_agent.run(batch.write_json())
            log.info(f"Completed batch {i}")
            if result.output:
                return pl.DataFrame(result.output)
        except Exception as e:
            log.error(f"Error in tagging batch {i}: {e}")
        return None

    tasks = [
        process_batch_with_delay(i, batch)
        for i, batch in enumerate(predictions.select("id", "title", "bets").iter_slices(BATCH_SIZE))
    ]
    results = await asyncio.gather(*tasks)
    dfs = [df for df in results if df is not None]
    assert dfs, "No relevant predictions found"
    relevant_predictions = pl.concat(dfs)
    log.info(f"Picked {len(relevant_predictions)} relevant predictions from {len(predictions)}")
    return predictions.join(relevant_predictions, on="id", how="inner")


class Event(BaseModel):
    title: str = Field(description="title of macro event or catalyst")
    when: str = Field(description="approximately when; either specific date or stringy like '2025 Q2' or 'next month'")
    url: str = Field(description="web url linking to the source page for this event (e.g. bea.gov, bls.gov, federalreserve.gov, company IR pages)")
    topics: str = Field(description="Very short phrase (1-3 words): public companies or investment sectors or broad alternatives impacted")

events_agent = Agent(
    model=EVENTS_MODEL,
    output_type=list[Event],
    system_prompt=templates.get_template("events_prompt.mako").render(today=today),
    model_settings={"openai_native_tools": [{"type": "web_search", "search_context_size": "high"}]},
    retries=RETRIES,
)

@dataclass
class FredToolkit:
    """Deps for the synthesis agent's bounded FRED tool: a client, a fetch budget, and a provenance log."""
    client: object | None
    remaining: int = MAX_FRED_TOOL_CALLS
    fetched: list[dict] = field(default_factory=list)

def _fred_search(client, query: str, top_k: int = 8) -> str:
    df = client.search(query)
    if df is None or len(df) == 0:
        return json.dumps({"query": query, "results": []})
    if "popularity" in df.columns:
        df = df.sort_values("popularity", ascending=False)
    rows = [
        {"series_id": str(idx), "title": str(r.get("title", "")), "units": str(r.get("units", "")),
         "frequency": str(r.get("frequency", "")), "last_obs": str(r.get("observation_end", ""))}
        for idx, r in df.head(top_k).iterrows()
    ]
    return json.dumps({"query": query, "results": rows})

def _fred_series(client, series_id: str, n: int = NUM_FRED_DATAPOINTS):
    series_id = series_id.strip().upper()
    info = client.get_series_info(series_id)
    s = client.get_series_latest_release(series_id)
    obs = [{"date": d.date().isoformat(), "value": float(v)} for d, v in zip(s.index, s.values) if v == v][-n:]
    title = str(info.get("title", series_id))
    url = f"https://fred.stlouisfed.org/series/{series_id}"
    payload = {"series_id": series_id, "title": title, "units": str(info.get("units", "")),
               "frequency": str(info.get("frequency", "")), "observations": obs, "url": url}
    return json.dumps(payload), {"title": f"{title} (FRED {series_id})", "url": url}

synthesizing_agent = Agent(
    model=SYNTHESIS_MODEL,
    output_type=str,
    deps_type=FredToolkit,
    system_prompt=templates.get_template("synthesizing_prompt.mako").render(today=today, fred_tool=ENABLE_FRED_TOOL),
    retries=RETRIES,
    model_settings={"max_tokens": 32768, "timeout": 600,
                    "anthropic_thinking": {"type": "adaptive"}, "anthropic_effort": "high"},
)

@synthesizing_agent.tool
async def fred_search(ctx: RunContext[FredToolkit], query: str) -> str:
    """Search FRED for economic data series by keyword. Returns candidate series ids with titles, units, frequency, and latest observation date — use it to locate the right series before fetching it with fred_series."""
    tk = ctx.deps
    if tk.client is None:
        return "FRED tool unavailable (no FRED_API_KEY configured); proceed with the data already provided."
    if tk.remaining <= 0:
        return "FRED fetch budget exhausted; proceed with the data already provided."
    tk.remaining -= 1
    try:
        return await asyncio.to_thread(_fred_search, tk.client, query)
    except Exception as e:
        return f"FRED search failed for {query!r}: {e}"

@synthesizing_agent.tool
async def fred_series(ctx: RunContext[FredToolkit], series_id: str) -> str:
    """Fetch the most recent observations for a specific FRED series id (e.g. 'CPIAUCSL'), with metadata and source URL — for grounding a calculation in real data rather than estimating it."""
    tk = ctx.deps
    if tk.client is None:
        return "FRED tool unavailable (no FRED_API_KEY configured); proceed with the data already provided."
    if tk.remaining <= 0:
        return "FRED fetch budget exhausted; proceed with the data already provided."
    tk.remaining -= 1
    try:
        payload, source = await asyncio.to_thread(_fred_series, tk.client, series_id)
    except Exception as e:
        return f"FRED fetch failed for {series_id!r}: {e}"
    tk.fetched.append(source)
    return payload

async def get_events() -> pl.DataFrame:
    res = await events_agent.run()
    return pl.DataFrame(res.output)

def get_email_briefing() -> str | None:
    if not ENABLE_EMAIL_BRIEFING:
        return None
    from email_briefing import fetch_briefing
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        log.warning("No Gmail credentials found; skipping email briefing ...")
        return None
    return fetch_briefing(GMAIL_USER, GMAIL_APP_PASSWORD, target_date=today)

def get_news() -> pl.DataFrame | None:
    from gnews import GNews
    try:
        news = GNews().get_top_news()
        log.info(f"Fetched {len(news)} news headlines")
        return pl.DataFrame(news)
    except Exception as e:
        log.error(f"Error in getting news from GNews: {e}")
        return None

async def main():
    predictions = pl.concat(await asyncio.gather(fetch_from_kalshi(), fetch_from_polymarket()))
    log.info(f"Total = {len(predictions)} predictions")

    tagged_predictions, events, news, fred_data, email_briefing = await asyncio.gather(
        tag_predictions(predictions),
        get_events(),
        asyncio.to_thread(get_news),
        asyncio.to_thread(get_fred_data),
        asyncio.to_thread(get_email_briefing),
    )

    report_input = {
        "prediction_markets": tagged_predictions.select("title", "bets", "topics").to_dicts(),
        "news_headlines": news.select("title", "description").to_dicts() if news is not None else None,
        "upcoming_catalysts": events.select("title", "when", "topics").to_dicts(),
        "fred_data_points": fred_data.select("title", "data").to_dicts() if fred_data is not None else None,
        "external_briefings": [{"source": "DataTrek Morning Briefing", "content": email_briefing}] if email_briefing else None
    }
    if os.environ.get("ZEITGEIST_DUMP_FIXTURE"):
        Path("eval/synthesis_fixtures").mkdir(parents=True, exist_ok=True)
        Path(f"eval/synthesis_fixtures/{today}.json").write_text(json.dumps(report_input, indent=2))
        log.info(f"Dumped synthesis fixture to eval/synthesis_fixtures/{today}.json")
    log.info("Generating report...")
    input_json = json.dumps(report_input)
    from fredapi import Fred
    fred_client = Fred(api_key=FRED_API_KEY) if (ENABLE_FRED_TOOL and FRED_API_KEY) else None
    fred_toolkit = FredToolkit(client=fred_client)
    synthesis_tasks = [synthesizing_agent.run(input_json, deps=fred_toolkit)]
    if COMPARISON_MODEL:
        comparison_agent = Agent(
            model=COMPARISON_MODEL,
            output_type=str,
            system_prompt=templates.get_template("synthesizing_prompt.mako").render(today=today),
            retries=RETRIES,
        )
        synthesis_tasks.append(comparison_agent.run(input_json))
    synthesis_results = await asyncio.gather(*synthesis_tasks, return_exceptions=True)
    report = synthesis_results[0].output if not isinstance(synthesis_results[0], Exception) else None
    if report is None:
        raise synthesis_results[0]
    if fred_toolkit.fetched:
        log.info(f"FRED tool fetched {len(fred_toolkit.fetched)} on-demand series: {[f['title'] for f in fred_toolkit.fetched]}")
    comparison_report = None
    if COMPARISON_MODEL and len(synthesis_results) > 1 and not isinstance(synthesis_results[1], Exception):
        comparison_report = synthesis_results[1].output
    elif COMPARISON_MODEL and len(synthesis_results) > 1 and isinstance(synthesis_results[1], Exception):
        log.error(f"Comparison model failed: {synthesis_results[1]}")

    if ENABLE_CITATIONS:
        citations = [
            tagged_predictions.select("title", "url"),
            events.select("title", "url"),
            news.select("title", "url") if news is not None else None,
            fred_data.select("title", "url") if fred_data is not None else None,
            pl.DataFrame(fred_toolkit.fetched).select("title", "url") if fred_toolkit.fetched else None,
        ]
        citations = [c for c in citations if c is not None]
        citations = pl.concat(citations).filter(pl.col("url").is_not_null())
        log.info(f"Adding citations from {len(citations)} sources ...")

        citation_agent = Agent(
            model=CITATION_MODEL,
            output_type=str,
            system_prompt=templates.get_template("citation_prompt.mako").render(memo=report),
            retries=RETRIES,
            model_settings={"max_tokens": 32768, "timeout": 600},
        )
        try:
            result = await citation_agent.run(citations.write_json())
            report = result.output.removesuffix("```").removeprefix("```md").removeprefix("```markdown").removeprefix("```")
        except Exception as e:
            log.error(f"Failed to insert citations: {e}")

    output_dir = Path(f".reports/{today.strftime('%Y/%m/%d')}")
    output_file = output_dir / "index.html"
    log.info(f"Writing to {output_file} ...")
    output_dir.mkdir(parents=True, exist_ok=True)
    html = templates.get_template("index.html.mako").render(today=today, report=report)
    output_file.write_text(html, encoding="utf-8")
    if comparison_report:
        comparison_html = templates.get_template("index.html.mako").render(today=today, report=comparison_report)
        (output_dir / "index2.html").write_text(comparison_html, encoding="utf-8")
        log.info(f"Wrote comparison report to {output_dir / 'index2.html'}")
    redirect = f'<meta http-equiv="refresh" content="0;url={today.strftime("%Y/%m/%d/")}"><a href="{today.strftime("%Y/%m/%d/")}">Latest report</a>'
    Path(".reports/index.html").write_text(redirect, encoding="utf-8")
    log.info("Done!")
    if IS_DEV:
        import webbrowser
        webbrowser.open(output_file.absolute().as_uri())

if __name__ == "__main__":
    asyncio.run(main())

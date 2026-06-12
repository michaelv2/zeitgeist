"""Targeted anchoring test for the themes ledger (phase 1).

Probes whether synthesis RE-TESTS prior themes against today's data or CLINGS to them.
Feeds the 2026-06-06 fixture to a ledger-on synthesis agent with three planted priors:
  - consumer-resilient    (CONTRADICTED: tell = Michigan <52; fixture 49.8  -> should FLIP)
  - disinflation-on-track (CONTRADICTED: tell = headline CPI MoM >0.4%; fixture +0.64% -> should FLIP)
  - labor-resilient       (SUPPORTED:   tell = unemployment >4.5%; fixture 4.3 -> should hold INTACT)

A faithful synthesis flips the two refuted themes and holds the supported one — genuine
re-test, not blanket continuation or blanket reversal. One Opus call.

Usage: uv run python validate_anchoring.py
"""
import asyncio
import json
import re
from pathlib import Path

import zeitgeist as zg
from pydantic_ai import Agent
from fredapi import Fred

FIXTURE = Path("eval/synthesis_fixtures/2026-06-06.json")

PRIOR_THEMES = [
    {"id": "consumer-resilient", "label": "Consumer resilience intact",
     "first_seen": "2026-05-28", "last_updated": "2026-06-05", "status": "intact",
     "stance": "The consumer is holding up — sentiment has stabilized off its lows and the soft-landing consumer thesis is on track.",
     "tell": "A Michigan sentiment print below 52 would signal the consumer is finally cracking."},
    {"id": "disinflation-on-track", "label": "Disinflation on track",
     "first_seen": "2026-05-25", "last_updated": "2026-06-05", "status": "intact",
     "stance": "Inflation is rolling over; the path back toward target is intact and the Fed's next move is a cut.",
     "tell": "A headline CPI print above +0.4% MoM would break the disinflation thesis."},
    {"id": "labor-resilient", "label": "Labor market resilient",
     "first_seen": "2026-05-20", "last_updated": "2026-06-05", "status": "intact",
     "stance": "The labor market is stable; no material deterioration in the unemployment rate.",
     "tell": "Unemployment breaking above 4.5% would signal real labor-market deterioration."},
]


async def main():
    data = json.loads(FIXTURE.read_text())
    data["prior_themes"] = PRIOR_THEMES

    # Faithful clone of zeitgeist's synthesizing_agent, but with the ledger hook ON.
    agent = Agent(
        model=zg.SYNTHESIS_MODEL,
        output_type=str,
        deps_type=zg.FredToolkit,
        system_prompt=zg.templates.get_template("synthesizing_prompt.mako").render(
            today=zg.today, fred_tool=zg.ENABLE_FRED_TOOL, ledger=True),
        retries=zg.RETRIES,
        model_settings={"max_tokens": 32768, "timeout": 600,
                        "anthropic_thinking": {"type": "adaptive"}, "anthropic_effort": "high"},
    )
    zg.register_fred_tools(agent)

    tk = zg.FredToolkit(client=Fred(api_key=zg.FRED_API_KEY) if zg.FRED_API_KEY else None)
    print("Planted priors (all 'intact'):")
    for t in PRIOR_THEMES:
        print(f"  - {t['label']}: {t['stance']}")
        print(f"      tell: {t['tell']}")
    print("\nRunning ledger-on synthesis on the 2026-06-06 fixture (one Opus call)...\n")
    memo = (await agent.run(json.dumps(data), deps=tk)).output

    Path("eval/results").mkdir(parents=True, exist_ok=True)
    Path("eval/results/anchoring_memo.md").write_text(memo)
    if tk.fetched:
        print(f"(FRED tool fetched: {[f['title'] for f in tk.fetched]})\n")

    def grep(pat):
        hits = [l.strip() for l in memo.splitlines() if re.search(pat, l, re.I) and l.strip()]
        return [h for h in dict.fromkeys(hits)] or ["(no direct mention)"]

    print("=== CONSUMER / SENTIMENT  (data refutes -> expect FLIP) ===")
    print("\n".join("  " + l for l in grep(r"michigan|sentiment|consumer|resilien|crack|soft.?land")))
    print("\n=== INFLATION / CPI  (data refutes -> expect FLIP) ===")
    print("\n".join("  " + l for l in grep(r"\bcpi\b|inflation|disinflation|deflat|rolling over|re.?accel")))
    print("\n=== LABOR / UNEMPLOYMENT  (data supports -> expect HOLD) ===")
    print("\n".join("  " + l for l in grep(r"unemploy|\blabor\b|payroll|\bjobs\b|jolts")))
    print("\n[full memo -> eval/results/anchoring_memo.md]")


if __name__ == "__main__":
    asyncio.run(main())

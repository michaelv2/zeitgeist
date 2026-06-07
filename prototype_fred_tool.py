"""Prototype: exercise the bounded FRED tool on a synthesis fixture.

Runs the real synthesizing_agent (Opus 4.8) against a saved fixture with the
FRED tool enabled, then prints which series it fetched on-demand and the memo.

Usage: uv run python prototype_fred_tool.py [path/to/fixture.json]
"""
import asyncio
import sys
from pathlib import Path

import zeitgeist as zg
from fredapi import Fred


async def main() -> None:
    fixture = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("eval/synthesis_fixtures/2026-03-24.json")
    input_json = fixture.read_text()
    client = Fred(api_key=zg.FRED_API_KEY) if zg.FRED_API_KEY else None
    tk = zg.FredToolkit(client=client)
    print(f"Running synthesis on {fixture} (FRED tool budget={tk.remaining}, key={'yes' if client else 'NO'})...\n")
    result = await zg.synthesizing_agent.run(input_json, deps=tk)

    print("=== FRED series fetched on-demand ===")
    for f in tk.fetched:
        print(f"  - {f['title']}  {f['url']}")
    if not tk.fetched:
        print("  (none — model used only the provided data)")
    print(f"(remaining budget: {tk.remaining}/{zg.MAX_FRED_TOOL_CALLS})")

    out = Path("eval/results/fred_tool_demo.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result.output)
    print(f"\n=== memo ({len(result.output.split())} words) -> {out} ===\n")
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())

"""Controlled A/B for a single prompt-line change.

Renders the current synthesis prompt (with the change) vs the same prompt with
the anchored line stripped (without), runs N draws each on ONE fixture (FRED
tool off, so the only variable is the line), and prints the passage matching
--extract from each draw.

Usage:
  uv run python ab_nudge.py [--fixture F] [--draws N] [--anchor PHRASE] [--extract REGEX]
Defaults reproduce the frequency-vs-trend nudge check on today's fixture.
"""
import argparse
import asyncio
import re
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from mako.lookup import TemplateLookup
from pydantic_ai import Agent

load_dotenv()

DEFAULT_ANCHOR = "Weigh a single high-frequency print against the trend"
DEFAULT_EXTRACT = r"(?:retail|real spend|real income|consumer (?:crack|spend|squeez|fragil|demand)|income squeeze|stagflation)"
MODEL = "anthropic:claude-opus-4-8"
SETTINGS = {"max_tokens": 32768, "timeout": 600,
            "anthropic_thinking": {"type": "adaptive"}, "anthropic_effort": "high"}

ap = argparse.ArgumentParser()
ap.add_argument("--fixture", default="eval/synthesis_fixtures/2026-06-06.json")
ap.add_argument("--draws", type=int, default=2)
ap.add_argument("--anchor", default=DEFAULT_ANCHOR, help="unique phrase in the prompt line to strip for the OLD arm")
ap.add_argument("--extract", default=DEFAULT_EXTRACT, help="regex selecting the passage to compare in each memo")
args = ap.parse_args()

templates = TemplateLookup(directories=["templates"])
fixture = Path(args.fixture).read_text()
new_prompt = templates.get_template("synthesizing_prompt.mako").render(today=date.today())  # fred_tool default False
assert args.anchor in new_prompt, f"anchor not found in rendered prompt: {args.anchor!r}"
old_prompt = "\n".join(l for l in new_prompt.split("\n") if args.anchor not in l)
assert old_prompt != new_prompt and args.anchor not in old_prompt

sem = asyncio.Semaphore(2)


async def draw(prompt: str, label: str):
    async with sem:
        agent = Agent(model=MODEL, output_type=str, system_prompt=prompt, retries=3, model_settings=SETTINGS)
        return label, (await agent.run(fixture)).output


def extract(text: str) -> str:
    hits = [l.strip() for l in text.splitlines() if re.search(args.extract, l, re.I)]
    return "\n".join("  " + h for h in dict.fromkeys(hits)) or "  (no match)"


async def main():
    tasks = [draw(old_prompt, f"OLD#{i+1}") for i in range(args.draws)]
    tasks += [draw(new_prompt, f"NEW#{i+1}") for i in range(args.draws)]
    Path("eval/results").mkdir(parents=True, exist_ok=True)
    for fut in asyncio.as_completed(tasks):
        try:
            label, out = await fut
        except Exception as e:
            print(f"\n!!! draw failed: {e}")
            continue
        Path(f"eval/results/ab_{label.replace('#','_')}.md").write_text(out)
        print(f"\n{'='*72}\n{label}  ({len(out.split())} words)\n{'='*72}")
        print(extract(out))
    print("\n[full memos written to eval/results/ab_*.md]")


if __name__ == "__main__":
    asyncio.run(main())

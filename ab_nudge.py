"""Controlled A/B for the frequency-vs-trend nudge.

Runs N synthesis draws on the SAME fixture with the current prompt (nudged)
vs the prompt with the nudge line stripped (old). FRED tool off so only the
prompt varies. Prints the retail/consumer passage from each draw.

Usage: uv run python ab_nudge.py [fixture.json] [draws_per_arm]
"""
import asyncio
import re
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from mako.lookup import TemplateLookup
from pydantic_ai import Agent

load_dotenv()

FIXTURE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("eval/synthesis_fixtures/2026-06-06.json")
N = int(sys.argv[2]) if len(sys.argv) > 2 else 2
MODEL = "anthropic:claude-opus-4-8"
SETTINGS = {"max_tokens": 32768, "timeout": 600,
            "anthropic_thinking": {"type": "adaptive"}, "anthropic_effort": "high"}
ANCHOR = "Weigh a single high-frequency print against the trend"

templates = TemplateLookup(directories=["templates"])
fixture = FIXTURE.read_text()
new_prompt = templates.get_template("synthesizing_prompt.mako").render(today=date.today())  # fred_tool default False
assert ANCHOR in new_prompt, "nudge line not found in rendered prompt"
old_prompt = "\n".join(l for l in new_prompt.split("\n") if ANCHOR not in l)
assert ANCHOR not in old_prompt and old_prompt != new_prompt

sem = asyncio.Semaphore(2)


async def draw(prompt: str, label: str):
    async with sem:
        agent = Agent(model=MODEL, output_type=str, system_prompt=prompt, retries=3, model_settings=SETTINGS)
        r = await agent.run(fixture)
        return label, r.output


def retail_lines(text: str) -> str:
    pat = r"(?:retail|real spend|real income|consumer (?:crack|spend|squeez|fragil|demand)|income squeeze|stagflation)"
    hits = [l.strip() for l in text.splitlines() if re.search(pat, l, re.I)]
    return "\n".join(dict.fromkeys(hits)) or "(no retail/consumer line matched)"


async def main():
    tasks = [draw(old_prompt, f"OLD#{i+1}") for i in range(N)]
    tasks += [draw(new_prompt, f"NEW#{i+1}") for i in range(N)]
    Path("eval/results").mkdir(parents=True, exist_ok=True)
    for fut in asyncio.as_completed(tasks):
        try:
            label, out = await fut
        except Exception as e:
            print(f"\n!!! draw failed: {e}")
            continue
        Path(f"eval/results/ab_{label.replace('#','_')}.md").write_text(out)
        print(f"\n{'='*72}\n{label}  ({len(out.split())} words)\n{'='*72}")
        print(retail_lines(out))
    print("\n[full memos written to eval/results/ab_*.md]")


if __name__ == "__main__":
    asyncio.run(main())

"""Dry-run the rolling themes ledger (phase 1) on a fixture/memo without touching a real run.

1. Renders the synthesis prompt with ledger=True and prints the <prior_themes> block
   (confirms the hook + the anchoring guard wording).
2. Feeds a crafted prior ledger + the latest local memo to the ledger update pass and
   prints before -> after, so you can eyeball carry-forward, status changes, and pruning.
   The crafted ledger seeds a stale theme (>5 days) and a 'resolved' one to verify the prune.

Usage:
    uv run python validate_ledger.py [memo.html|memo.md]
Cheap: one Sonnet call (the update pass). No Opus synthesis is run.
"""
import asyncio
import html as htmlmod
import json
import re
import sys
from pathlib import Path

import zeitgeist as zg


def html_to_text(p: Path) -> str:
    t = p.read_text()
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", "\n", t)  # block tags -> newlines to keep some structure
    t = htmlmod.unescape(t)
    return "\n".join(l.strip() for l in t.splitlines() if l.strip())


def latest_memo() -> Path | None:
    reports = sorted(Path(".reports").glob("*/*/*/index.html"))
    return reports[-1] if reports else None


# A crafted prior ledger to exercise carry / inflect / add / prune.
# Stale theme (>5 days) and 'resolved' should be dropped relative to today's run.
PRIOR_LEDGER = [
    {"id": "ai-capex-durability", "label": "AI capex durability",
     "first_seen": "2026-06-02", "last_updated": "2026-06-10", "status": "intact",
     "stance": "Hyperscaler capex guides still rising; no demand crack in the data yet.",
     "tell": "A cut to any megacap cloud capex guide, or cloud-revenue decel below ~25% YoY."},
    {"id": "breadth-deterioration", "label": "Narrowing market breadth",
     "first_seen": "2026-06-05", "last_updated": "2026-06-10", "status": "building",
     "stance": "Index gains carried by <10 names; equal-weight lagging cap-weight several sessions.",
     "tell": "RSP/SPY turning up = breadth repair; a new index high on negative breadth = confirmation."},
    {"id": "stale-example-theme", "label": "Stale theme (should prune)",
     "first_seen": "2026-05-20", "last_updated": "2026-06-03", "status": "fading",
     "stance": "Last reinforced 8 days ago; included to confirm the ~5-run prune drops it.",
     "tell": "n/a - prune check."},
    {"id": "resolved-example-theme", "label": "Resolved theme (should drop)",
     "first_seen": "2026-05-28", "last_updated": "2026-06-09", "status": "resolved",
     "stance": "Played out; included to confirm 'resolved' is dropped.",
     "tell": "n/a - prune check."},
]


def show(themes):
    for t in themes:
        print(f"  [{t['status']:>10}] {t['label']} (since {t['first_seen']}, upd {t['last_updated']})")
        print(f"               {t['stance']}")
        print(f"               tell: {t['tell']}")


async def main():
    # 1. Hook render check
    print("=== synthesis <prior_themes> hook (ledger=True) ===")
    rendered = zg.templates.get_template("synthesizing_prompt.mako").render(
        today=zg.today, fred_tool=zg.ENABLE_FRED_TOOL, ledger=True)
    if "<prior_themes>" in rendered:
        block = rendered.split("<prior_themes>")[1].split("</prior_themes>")[0]
        print("<prior_themes>" + block + "</prior_themes>\n")
    else:
        print("(block not found -- hook did not render!)\n")

    # 2. Ledger update dry-run
    memo_path = Path(sys.argv[1]) if len(sys.argv) > 1 else latest_memo()
    if not memo_path or not memo_path.exists():
        print("No memo found (.reports/*/*/*/index.html). Pass one explicitly.")
        return
    memo = html_to_text(memo_path) if memo_path.suffix == ".html" else memo_path.read_text()
    print(f"=== prior ledger ({len(PRIOR_LEDGER)} themes) ===")
    show(PRIOR_LEDGER)
    print(f"\n=== running ledger update on {memo_path} ({len(memo.split())} words) ===")
    ledger_input = json.dumps({"prior_ledger": PRIOR_LEDGER, "memo": memo})
    new_ledger = (await zg.ledger_agent.run(ledger_input)).output
    print(f"\n=== updated ledger (as_of {new_ledger.as_of}, {len(new_ledger.themes)} themes) ===")
    show([t.model_dump() for t in new_ledger.themes])

    kept = {t.id for t in new_ledger.themes}
    print("\n=== prune check ===")
    print(f"  stale-example-theme dropped:    {'stale-example-theme' not in kept}")
    print(f"  resolved-example-theme dropped: {'resolved-example-theme' not in kept}")


if __name__ == "__main__":
    asyncio.run(main())

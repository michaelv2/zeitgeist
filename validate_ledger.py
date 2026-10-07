"""Dry-run the rolling themes ledger (phase 1) on a fixture/memo without touching a real run.

1. Renders the synthesis prompt with ledger=True and prints the <prior_themes> block
   (confirms the hook + the anchoring guard wording).
2. Feeds a crafted prior ledger + the latest local memo to the ledger update pass and
   prints before -> after, so you can eyeball carry-forward, status changes, and pruning.
   The crafted ledger (dated relative to today) checks that last_updated moves only on new
   evidence, and that a stale (> LEDGER_STALE_DAYS) and a 'resolved' theme are dropped and
   listed in the memo footer.

Usage:
    uv run python validate_ledger.py [memo.html|memo.md]
Cheap: one Sonnet call (the update pass). No Opus synthesis is run.
"""
import asyncio
import html as htmlmod
import json
import re
import sys
from datetime import timedelta
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


# A crafted prior ledger to exercise carry / last_updated / prune, dated relative to today.
def _ago(days: int) -> str:
    return (zg.today - timedelta(days=days)).isoformat()

PRIOR_LEDGER = [
    # The memo cites new rates data for this one -> last_updated should move to today.
    {"id": "term-premium-fiscal-supply-rout", "label": "Term premium / fiscal supply rout",
     "first_seen": _ago(12), "last_updated": _ago(5), "status": "building",
     "stance": "Long end is fiscal-supply/term-premium driven, not cycle driven; 10Y holding >5%.",
     "tell": "10Y-2Y sustaining above 0.40 with 10Y >5% = regime deepening; a strong 30Y auction = challenged."},
    # The memo says nothing about this one -> last_updated should stay put (or it is dropped with a reason).
    {"id": "el-nino-soft-commodity-risk", "label": "El Nino soft-commodity risk",
     "first_seen": _ago(20), "last_updated": _ago(5), "status": "building",
     "stance": "A developing El Nino threatens cocoa/coffee/sugar supply; food-inflation tail risk.",
     "tell": "NOAA declaring El Nino conditions, or cocoa futures making new highs."},
    {"id": "stale-example-theme", "label": "Stale theme (should prune)",
     "first_seen": _ago(60), "last_updated": _ago(zg.LEDGER_STALE_DAYS + 9), "status": "fading",
     "stance": f"No new evidence for {zg.LEDGER_STALE_DAYS + 9} days; included to confirm the staleness prune drops it.",
     "tell": "n/a - prune check."},
    {"id": "resolved-example-theme", "label": "Resolved theme (should drop)",
     "first_seen": _ago(20), "last_updated": _ago(2), "status": "resolved",
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
    new_ledger = zg.prune_ledger(PRIOR_LEDGER, (await zg.ledger_agent.run(ledger_input)).output)
    print(f"\n=== updated ledger (as_of {new_ledger.as_of}, {len(new_ledger.themes)} themes) ===")
    show([t.model_dump() for t in new_ledger.themes])
    print("\n=== memo footer ===" + (zg.dropped_themes_md(new_ledger, PRIOR_LEDGER) or "\n(no themes dropped)"))

    kept = {t.id: t for t in new_ledger.themes}
    dropped = {d.id for d in new_ledger.dropped}
    prior_upd = {t["id"]: t["last_updated"] for t in PRIOR_LEDGER}
    quiet = kept.get("el-nino-soft-commodity-risk")
    active = kept.get("term-premium-fiscal-supply-rout")
    print("\n=== checks ===")
    print(f"  stale theme dropped:                 {'stale-example-theme' in dropped}")
    print(f"  resolved theme dropped:              {'resolved-example-theme' in dropped}")
    print(f"  quiet theme's date not bumped:       {quiet is None or quiet.last_updated == prior_upd[quiet.id]}"
          f" ({'dropped' if quiet is None else quiet.last_updated})")
    print(f"  active theme's date moved to today:  {active is not None and active.last_updated == zg.today.isoformat()}"
          f" ({'dropped' if active is None else active.last_updated})")
    print(f"  every left-out prior theme listed:   {set(prior_upd) - set(kept) == dropped}")

if __name__ == "__main__":
    asyncio.run(main())

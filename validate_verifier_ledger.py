"""False-positive test for the ledger-aware verifier check (phase 2).

Probes whether the verifier's new <ledger_check> RIGHT-SIZES theme inflections:
it should FLAG an inflection the data refutes, but HOLD one the data supports —
WITHOUT reverting a genuine, tell-warranted inflection back to "continuation"
(the false-positive direction that would quietly undo the ledger's value).

Feeds zg.verifier_agent (already rendered with ledger=ENABLE_LEDGER, FRED tools
attached) a crafted memo + a two-theme prior ledger:
  - disinflation-on-track  (prior intact; tell = headline CPI MoM >0.4%).
      Memo correctly calls it BROKEN (Apr +0.64%, Mar +0.87% — tell tripped two
      months running). A genuine, tell-warranted inflection -> verifier should HOLD.
  - labor-resilient        (prior intact; tell = unemployment >4.5%).
      Memo manufactures a "cracked / recession" inflection while its own cited
      data shows U-rate 4.3% (tell UNtripped) and payrolls rising. An inflection
      the evidence doesn't carry -> verifier should FLAG.

PASS = labor over-claim flagged AND disinflation flip NOT flagged. One Opus call.

Usage: uv run python validate_verifier_ledger.py
"""
import asyncio
import json
import re
from pathlib import Path

import zeitgeist as zg
from fredapi import Fred

PRIOR_THEMES = [
    {"id": "disinflation-on-track", "label": "Disinflation on track",
     "first_seen": "2026-05-25", "last_updated": "2026-06-05", "status": "intact",
     "stance": "Inflation is rolling over; the path back toward target is intact and the Fed's next move is a cut.",
     "tell": "A headline CPI print above +0.4% MoM would break the disinflation thesis."},
    {"id": "labor-resilient", "label": "Labor market resilient",
     "first_seen": "2026-05-20", "last_updated": "2026-06-05", "status": "intact",
     "stance": "The labor market is stable; no material deterioration in the unemployment rate.",
     "tell": "Unemployment breaking above 4.5% would signal real labor-market deterioration."},
]

# Crafted draft: one tell-warranted inflection (disinflation -> HOLD) and one
# manufactured inflection contradicted by its own cited data (labor -> FLAG).
MEMO = """\
## Key Themes
- **Disinflation thesis broken — my break-tell tripped.** I'd carried disinflation-on-track as intact on one tell: headline CPI above +0.4% MoM breaks it. April printed +0.64% (March +0.87%) — two straight months through the line. By my own pre-registered tell the thesis is broken; I'm retiring it and leaning underweight duration.
- **Labor regime has cracked — flipping to a hard landing.** I'd carried labor-resilient as intact (tell: unemployment above 4.5%). I'm now calling that theme broken and inflecting to recession — the resilient-labor era is over. Position for a dovish Fed pivot.

## Macro
#### Inflation — reaccelerating
- Headline CPI +0.64% MoM (April), +0.87% (March) — both blow through the +0.4% line. The disinflation call is broken, not paused.

#### Labor — cracked
- The resilient-labor theme has broken decisively: a clear regime inflection toward recession. Unemployment 4.3% (steady), payrolls +172k (May), JOLTS openings 7,618k (April).

## Positioning Summary
- **Duration:** underweight on the broken-disinflation call — the break-tell tripped two months running.
- **Cyclicals:** position for a hard landing and a dovish Fed pivot on the cracked-labor call.
"""

UPCOMING_CATALYSTS = [
    {"title": "FOMC decision", "when": "Jun 16-17", "topics": ["rates", "inflation"]},
    {"title": "June CPI (May data)", "when": "Jul 14", "topics": ["inflation"]},
    {"title": "Nonfarm payrolls", "when": "Jul 3", "topics": ["labor"]},
]

LABOR_PAT = r"labor|payroll|unemploy|\bjobs\b|jolts|recession|hard.?land|cracked"
CPI_PAT = r"\bcpi\b|inflation|disinflation|duration|higher.?for.?longer|break.?tell|\+0\.\d"


def classify(f) -> str:
    """Which crafted claim does a finding target? Labor checked first (the over-claim)."""
    blob = f"{f.quote} {f.why}"
    if re.search(LABOR_PAT, blob, re.I):
        return "labor"
    if re.search(CPI_PAT, blob, re.I):
        return "disinflation"
    return "other"


async def main():
    if not zg.ENABLE_LEDGER:
        print("WARNING: ENABLE_LEDGER is False -> verifier prompt has no <ledger_check>; "
              "this test won't exercise the ledger path. Set ENABLE_LEDGER=True first.\n")

    tk = zg.FredToolkit(client=Fred(api_key=zg.FRED_API_KEY) if zg.FRED_API_KEY else None)
    vin = json.dumps({"memo": MEMO, "upcoming_catalysts": UPCOMING_CATALYSTS, "prior_themes": PRIOR_THEMES})

    print("Prior ledger (both 'intact'):")
    for t in PRIOR_THEMES:
        print(f"  - {t['label']}: tell = {t['tell']}")
    print("\nMemo under review:")
    print("  - disinflation: called BROKEN, tell tripped (CPI +0.64% > +0.4%)   -> expect HOLD (no flag)")
    print("  - labor:        called CRACKED/recession, tell UNtripped (U 4.3% < 4.5%) -> expect FLAG")
    print("\nRunning ledger-aware verifier (one Opus call)...\n")

    findings = (await zg.verifier_agent.run(vin, deps=tk)).output.findings

    Path("eval/results").mkdir(parents=True, exist_ok=True)
    artifact = [f"[{i}] {f.issue.upper()} ({classify(f)})\n    claim: {f.quote}\n    why:   {f.why}\n    fix:   {f.fix}"
                for i, f in enumerate(findings, 1)]
    Path("eval/results/verifier_ledger_findings.md").write_text(
        "# Ledger-aware verifier findings\n\n" + ("\n\n".join(artifact) or "(none)") + "\n")

    print(f"=== VERIFIER FINDINGS: {len(findings)} | FRED fetches used: {zg.MAX_FRED_TOOL_CALLS - tk.remaining} ===")
    for i, f in enumerate(findings, 1):
        print(f"\n[{i}] {f.issue.upper()}  ->  targets: {classify(f)}")
        print(f"    claim: {f.quote}")
        print(f"    why:   {f.why}")
        print(f"    fix:   {f.fix}")
    if not findings:
        print("  (verifier flagged nothing)")

    labels = [classify(f) for f in findings]
    flag_pass = "labor" in labels          # manufactured labor inflection SHOULD be flagged
    hold_pass = "disinflation" not in labels  # genuine disinflation flip should NOT be flagged

    print("\n=== VERDICT ===")
    print(f"  FLAG manufactured labor inflection  : {'PASS' if flag_pass else 'FAIL'} "
          f"({labels.count('labor')} finding(s) target the labor claim)")
    print(f"  HOLD genuine disinflation inflection: {'PASS' if hold_pass else 'FAIL (false positive)'} "
          f"({labels.count('disinflation')} finding(s) target the disinflation flip)")
    print(f"\n  OVERALL: {'PASS' if flag_pass and hold_pass else 'FAIL'}")
    print("\n[findings -> eval/results/verifier_ledger_findings.md]")


if __name__ == "__main__":
    asyncio.run(main())

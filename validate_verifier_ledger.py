"""False-positive test for the ledger-aware verifier check (phase 2).

Probes whether the verifier's <ledger_check> RIGHT-SIZES how a memo handles
carried themes: it should FLAG an over-claim, but HOLD a claim the evidence
supports — WITHOUT reverting a genuine, evidence-backed move back to
"continuation" (the false-positive direction that would quietly undo the
ledger's value).

Feeds zg.verifier_agent (already rendered with ledger=ENABLE_LEDGER, FRED tools
attached) a crafted memo + prior ledger per scenario:

  inflection  (crafted, two themes both prior "intact")
    - disinflation-on-track (tell = headline CPI MoM >0.4%). Memo correctly
      calls it BROKEN (Apr +0.64%, Mar +0.87% — tell tripped two months
      running). A genuine, tell-warranted inflection -> verifier should HOLD.
    - labor-resilient (tell = unemployment >4.5%). Memo manufactures a
      "cracked / recession" inflection while its own cited data shows U-rate
      4.3% (tell UNtripped) and payrolls rising -> verifier should FLAG.

  carry  (regression from the real 2026-10-05 run: the 10/02 ledger + a
  trimmed 10/05 memo)
    - ai-trade-bifurcation. Memo restates the 10/02 Broadcom-Anthropic deal as
      live "cracks" with no new evidence — the prior stance only called it a
      circular-financing structure, and the deal is proceeding. Carried
      evidence escalated -> verifier should FLAG.
    - term-premium-fiscal-supply-rout. Memo advances it on genuinely new
      evidence (10Y held >5% through the Oct 2 +29k payrolls print) -> HOLD.

PASS = each scenario's over-claim flagged AND its supported claim NOT flagged.
One Opus call per scenario.

Usage: uv run python validate_verifier_ledger.py [--case inflection|carry]
"""
import argparse
import asyncio
import json
import re
from pathlib import Path

import zeitgeist as zg
from fredapi import Fred

# ── Scenario: inflection ─────────────────────────────────────────────────────

INFLECTION_PRIOR = [
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
INFLECTION_MEMO = """\
## Key Themes
- **Disinflation thesis broken — my break-tell tripped.** I'd carried disinflation-on-track as intact on one tell: headline CPI above +0.4% MoM breaks it. April printed +0.64% (March +0.87%) — two straight months through the line. By my own pre-registered tell the thesis is broken; I'm retiring it and leaning underweight duration.
- **Labor regime has cracked — flipping to a hard landing.** I'd carried labor-resilient as intact (tell: unemployment above 4.5%). I'm now calling that theme broken and inflecting to recession — the resilient-labor era is over. Position for a dovish Fed pivot.

## Macro
#### Inflation — running hot
- Headline CPI +0.64% MoM (April), +0.87% (March) — both blow through the +0.4% line. The disinflation call is broken, not paused.

#### Labor — cracked
- The resilient-labor theme has broken decisively: a clear regime inflection toward recession. Unemployment 4.3% (steady), payrolls +172k (May), JOLTS openings 7,618k (April).

## Positioning Summary
- **Duration:** underweight on the broken-disinflation call — the break-tell tripped two months running.
- **Cyclicals:** position for a hard landing and a dovish Fed pivot on the cracked-labor call.
"""

INFLECTION_CATALYSTS = [
    {"title": "FOMC decision", "when": "Jun 16-17", "topics": ["rates", "inflation"]},
    {"title": "June CPI (May data)", "when": "Jul 14", "topics": ["inflation"]},
    {"title": "Nonfarm payrolls", "when": "Jul 3", "topics": ["labor"]},
]

# ── Scenario: carry (2026-10-05 regression) ──────────────────────────────────

# Verbatim from .reports/2026/10/02/themes_ledger.json.
CARRY_PRIOR = [
    {"id": "term-premium-fiscal-supply-rout",
     "label": "Term Premium / Fiscal Supply Rout — Structural, Nov Refunding the Next Catalyst",
     "first_seen": "2026-09-25", "last_updated": "2026-10-02", "status": "building",
     "stance": "Advancing and now the confirmed dominant cross-asset macro driver. 10Y–2Y ~0.46, 10Y 5.29% — the rout is fiscal-supply/term-premium driven, not recession fear (labor firm). Broad USD at 120.3 (yen weakening, USDJPY ~157) confirms capital is not fleeing to JGBs — BoJ-repatriation-drains-UST sub-thesis dead. Full-Dem Congress base case from Jan 2027 (House 92.5%, Senate 63.5%) means recurring fiscal brinkmanship structurally supportive of term premium. Nov Treasury quarterly refunding is the next major supply catalyst.",
     "tell": "10Y–2Y sustaining above 0.40 with 10Y >5% over multiple sessions = regime deepening. Soft Oct 14 CPI that fails to cap long-end yields = term premium dominant over inflation as driver. Strong Nov 30Y refunding auction (tail <0bp) or credible US fiscal consolidation = term-premium thesis challenged. Oct 27–28 FOMC guidance on balance sheet = supply-side signal."},
    {"id": "ai-trade-bifurcation",
     "label": "AI Trade Bifurcating — Vendor/Debt Financing Cracking at 5.3% 10Y; Moats vs. Buildout",
     "first_seen": "2026-07-31", "last_updated": "2026-10-02", "status": "building",
     "stance": "Crack thesis advancing with new evidence. Broadcom amassing $60B to fund Anthropic's chips (lending up to $42B to lease its own silicon) is textbook circular/vendor financing — struck as the 10Y hits 5.29%. This is the second major vendor-financing headline (after Oracle force-majeure, Blue Owl delay). Debt-funded buildout cohort faces simultaneous discount-rate and credit headwinds. OpenAI firing 3 safety researchers adds governance overhang. NVDA on de-rating watch into Nov 19. Barbell: hold margin-defended moats (MSFT, AMZN), cut vendor/debt-financed buildout names.",
     "tell": "MSFT/AMZN Oct 27–29: capex raised + gross margins intact = moats hold, maintain barbell. Margin warnings or capex cuts = AI de-rating confirmed, press short leg. Third major AI-financing headline or AI-credit spreads widening = cut buildout cohort hard. NVDA Nov 19 guide-down = cohort de-rating confirmed."},
]

# Trimmed from the shipped 10/05 memo. The term-premium bullets cite new data
# (the Oct 2 payrolls print, after the 10/02 memo ran) -> HOLD. Their rates are
# corrected to FRED: the shipped memo quoted Oct 1 levels as the post-print move
# (a real error, but not what this case tests). The AI line cites nothing new
# and restates the deal as "cracks" -> FLAG.
CARRY_MEMO = """\
## Key Themes
- **The long end failed to rally on a soft payroll print — consistent with the term-premium read.** Sept payrolls came in at just +29k (released Oct 2), yet the 10Y edged up to 5.28% that day (from 5.24%) and 10Y–2Y held 0.45. A weak labor print that doesn't pull long yields down reads as a fiscal-supply/term-premium driver rather than a cycle one. Stay structurally UW long duration (ZROZ).

## Macro
#### Rates & Fed — long end structurally heavy
- The long-end call holds: 10Y >5% and 10Y–2Y above 0.40 for a third straight session, now including a weak-payrolls day — the prior tell's "multiple sessions" condition is met. Stay UW long duration with a steepener bias.

## Sectors & Names
- AI — hold the barbell. Vendor/circular-financing cracks (Broadcom-Anthropic) collide with a 5.2% 10Y; the discount-rate + credit squeeze on debt-funded buildout names is live. Hold margin-defended moats (MSFT, AMZN) on the capex/margins thesis; stay cautious on the buildout cohort.

## Positioning Summary
- **Duration:** UW long end (ZROZ) structurally; steepener bias while 10Y–2Y holds above 0.40.
- **Equities:** AI barbell (moats over buildout).
"""

CARRY_CATALYSTS = [
    {"title": "September CPI", "when": "Oct 14", "topics": ["inflation", "rates"]},
    {"title": "FOMC decision", "when": "Oct 27-28", "topics": ["rates"]},
    {"title": "MSFT / AMZN Q3 earnings", "when": "Oct 27-29", "topics": ["AI", "mega-cap tech"]},
]

# Each scenario: patterns are checked in order (the over-claim first), first match wins.
SCENARIOS = {
    "inflection": {
        "prior": INFLECTION_PRIOR, "memo": INFLECTION_MEMO, "catalysts": INFLECTION_CATALYSTS,
        "patterns": [("labor", r"labor|payroll|unemploy|\bjobs\b|jolts|recession|hard.?land|cracked"),
                     ("disinflation", r"\bcpi\b|inflation|disinflation|duration|higher.?for.?longer|break.?tell|\+0\.\d")],
        "flag": ("labor", "manufactured labor inflection"),
        "hold": ("disinflation", "genuine disinflation inflection"),
    },
    "carry": {
        "prior": CARRY_PRIOR, "memo": CARRY_MEMO, "catalysts": CARRY_CATALYSTS,
        # The target is the deal-as-"crack" restatement specifically: a flag elsewhere on the AI
        # line (e.g. only "the squeeze is live") still ships "cracks (Broadcom-Anthropic)".
        "patterns": [("ai-crack", r"broadcom|anthropic|crack"),
                     ("ai-other", r"circular|vendor|buildout|squeeze|\bAI\b"),
                     ("term-premium", r"term.premium|long end|10Y|2Y|steepen|duration|ZROZ|payroll")],
        "flag": ("ai-crack", "carried AI evidence restated as live cracks"),
        "hold": ("term-premium", "term-premium advance on new data"),
    },
}


def classify(f, patterns) -> str:
    """Which crafted claim does a finding target? The flagged quote decides; the why is a fallback
    (a why that merely mentions another claim shouldn't count as flagging it)."""
    for blob in (f.quote, f"{f.quote} {f.why}"):
        for label, pat in patterns:
            if re.search(pat, blob, re.I):
                return label
    return "other"


async def run_scenario(name: str, sc: dict) -> tuple[bool, list[str]]:
    tk = zg.FredToolkit(client=Fred(api_key=zg.FRED_API_KEY) if zg.FRED_API_KEY else None)
    vin = json.dumps({"memo": sc["memo"], "upcoming_catalysts": sc["catalysts"], "prior_themes": sc["prior"]})
    findings = (await zg.verifier_agent.run(vin, deps=tk)).output.findings

    flag_label, flag_desc = sc["flag"]
    hold_label, hold_desc = sc["hold"]
    labels = [classify(f, sc["patterns"]) for f in findings]
    flag_pass = flag_label in labels      # over-claim SHOULD be flagged
    hold_pass = hold_label not in labels  # supported claim should NOT be flagged

    out = [f"=== [{name}] VERIFIER FINDINGS: {len(findings)} | FRED fetches used: {zg.MAX_FRED_TOOL_CALLS - tk.remaining} ==="]
    for i, (f, label) in enumerate(zip(findings, labels), 1):
        out += [f"\n[{i}] {f.issue.upper()}  ->  targets: {label}",
                f"    claim: {f.quote}", f"    why:   {f.why}", f"    fix:   {f.fix}"]
    if not findings:
        out.append("  (verifier flagged nothing)")
    out += [f"\n  FLAG {flag_desc:<44}: {'PASS' if flag_pass else 'FAIL'} "
            f"({labels.count(flag_label)} finding(s))",
            f"  HOLD {hold_desc:<44}: {'PASS' if hold_pass else 'FAIL (false positive)'} "
            f"({labels.count(hold_label)} finding(s))"]
    return flag_pass and hold_pass, out


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", choices=list(SCENARIOS), help="run one scenario (default: all)")
    args = ap.parse_args()

    if not zg.ENABLE_LEDGER:
        print("WARNING: ENABLE_LEDGER is False -> verifier prompt has no <ledger_check>; "
              "this test won't exercise the ledger path. Set ENABLE_LEDGER=True first.\n")

    names = [args.case] if args.case else list(SCENARIOS)
    print(f"Running ledger-aware verifier on {', '.join(names)} (one Opus call each)...\n")
    results = await asyncio.gather(*(run_scenario(n, SCENARIOS[n]) for n in names))

    report = []
    for passed, out in results:
        print("\n".join(out) + "\n")
        report += out + [""]
    overall = all(passed for passed, _ in results)
    print(f"=== OVERALL: {'PASS' if overall else 'FAIL'} ===")

    Path("eval/results").mkdir(parents=True, exist_ok=True)
    Path("eval/results/verifier_ledger_findings.md").write_text(
        "# Ledger-aware verifier findings\n\n" + "\n".join(report) + "\n")
    print("\n[findings -> eval/results/verifier_ledger_findings.md]")


if __name__ == "__main__":
    asyncio.run(main())

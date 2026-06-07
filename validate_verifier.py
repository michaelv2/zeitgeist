"""Validate the flag-then-revise verifier on the saved 2026-06-06 20:08 draft
(the over-bearish, pre-nudge report) at /tmp/index_2008_backup.html.

Runs the flag pass (prints findings + FRED fetches used), then the revise pass
(prints the retail passage before vs after). Usage:
    uv run python validate_verifier.py [draft.html]
"""
import asyncio
import html as htmlmod
import json
import re
import sys
from pathlib import Path

import zeitgeist as zg
from fredapi import Fred


def html_to_text(p: Path) -> str:
    t = p.read_text()
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", "\n", t)  # block tags -> newlines to keep some structure
    t = htmlmod.unescape(t)
    return "\n".join(l.strip() for l in t.splitlines() if l.strip())


def retail_lines(text: str) -> str:
    pat = r"(?:retail|real spend|real income|consumer (?:crack|spend|squeez|fragil|demand)|income squeeze|stagflation)"
    hits = [l.strip() for l in text.splitlines() if re.search(pat, l, re.I)]
    return "\n".join("  " + h for h in dict.fromkeys(hits)) or "  (none matched)"


async def main():
    draft_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/index_2008_backup.html")
    draft = html_to_text(draft_path)
    print(f"Loaded draft from {draft_path} ({len(draft.split())} words)\n")
    print("=== retail passage BEFORE ===")
    print(retail_lines(draft))

    # FLAG pass
    tk = zg.FredToolkit(client=Fred(api_key=zg.FRED_API_KEY) if zg.FRED_API_KEY else None)
    findings = (await zg.verifier_agent.run(draft, deps=tk)).output.findings
    print(f"\n=== VERIFIER FINDINGS: {len(findings)} | FRED fetches used: {zg.MAX_FRED_TOOL_CALLS - tk.remaining} ===")
    for i, f in enumerate(findings, 1):
        print(f"\n[{i}] {f.issue.upper()}")
        print(f"    claim: {f.quote}")
        print(f"    why:   {f.why}")
        print(f"    fix:   {f.fix}")
    if not findings:
        print("  (verifier flagged nothing)")
        return

    # REVISE pass
    revise_input = json.dumps({"memo": draft, "findings": [f.model_dump() for f in findings]})
    revised = (await zg.revise_agent.run(revise_input)).output
    revised = revised.removesuffix("```").removeprefix("```md").removeprefix("```markdown").removeprefix("```")
    Path("eval/results").mkdir(parents=True, exist_ok=True)
    Path("eval/results/verifier_revised.md").write_text(revised)
    print("\n=== retail passage AFTER revise ===")
    print(retail_lines(revised))
    print("\n[full revised memo -> eval/results/verifier_revised.md]")


if __name__ == "__main__":
    asyncio.run(main())

"""
Eval harness for the synthesis model.

Usage:
  # Capture fixture from a live pipeline run:
    ZEITGEIST_DUMP_FIXTURE=1 uv run python zeitgeist.py
    # or:
    uv run python eval_synthesis.py snapshot

  # Generate reports from both models:
    uv run python eval_synthesis.py run

  # Run LLM-as-judge scoring:
    uv run python eval_synthesis.py judge

  # Print summary:
    uv run python eval_synthesis.py report
"""

import argparse
import asyncio
import json
import random
import re
import time
import sys
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from mako.lookup import TemplateLookup
from dotenv import load_dotenv

load_dotenv()

FIXTURES_DIR = Path("eval/synthesis_fixtures")
RESULTS_DIR = Path("eval/results")

templates = TemplateLookup(directories=["templates"])
today = date.today()



# ── Structural metrics (no LLM needed) ──────────────────────────────────────

def compute_structural_metrics(report: str) -> dict:
    lines = report.strip().splitlines()
    non_empty = [l for l in lines if l.strip()]
    words = report.split()

    # Section headers
    headers = [l.strip() for l in lines if re.match(r"^#{1,3}\s", l)]
    h2_headers = [l.strip() for l in lines if re.match(r"^##\s", l)]

    # Bullet lines
    bullet_lines = [l for l in non_empty if re.match(r"^\s*[-*]\s", l)]

    # Required elements
    has_daily_memo = bool(re.search(r"Daily Memo", report))
    has_catalysts = bool(re.search(r"Upcoming Catalysts", report))

    # Catalysts at bottom: check if it's in the last 30% of the report
    catalysts_at_bottom = False
    if has_catalysts:
        pos = report.lower().rfind("upcoming catalysts")
        catalysts_at_bottom = pos > len(report) * 0.7

    return {
        "word_count": len(words),
        "line_count": len(non_empty),
        "section_count": len(headers),
        "h2_sections": len(h2_headers),
        "bullet_lines": len(bullet_lines),
        "bullet_density": len(bullet_lines) / max(len(non_empty), 1),
        "has_daily_memo_title": has_daily_memo,
        "has_catalysts_section": has_catalysts,
        "catalysts_at_bottom": catalysts_at_bottom,
        "h2_header_names": [h.lstrip("#").strip() for h in h2_headers],
    }


def heading_jaccard(runs: list[dict]) -> float:
    """Jaccard similarity of h2 header sets across runs."""
    if len(runs) < 2:
        return 1.0
    jaccards = []
    for i in range(len(runs)):
        for j in range(i + 1, len(runs)):
            a = set(runs[i]["metrics"]["h2_header_names"])
            b = set(runs[j]["metrics"]["h2_header_names"])
            union = len(a | b)
            jaccards.append(len(a & b) / union if union else 1.0)
    return sum(jaccards) / len(jaccards)


# ── Snapshot ─────────────────────────────────────────────────────────────────

def snapshot():
    import subprocess
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    print("Running zeitgeist.py with ZEITGEIST_DUMP_FIXTURE=1 ...")
    import os
    env = {**os.environ, "ZEITGEIST_DUMP_FIXTURE": "1"}
    result = subprocess.run(["uv", "run", "python", "zeitgeist.py"], env=env)
    if result.returncode == 0:
        print(f"Fixture saved to {FIXTURES_DIR}/")
    else:
        print("Pipeline failed — check output above.")
        sys.exit(1)


# ── Run: generate reports ────────────────────────────────────────────────────

def get_latest_fixture() -> Path:
    fixtures = sorted(FIXTURES_DIR.glob("*.json"))
    if not fixtures:
        print(f"No fixtures in {FIXTURES_DIR}/. Run 'snapshot' first.")
        sys.exit(1)
    return fixtures[-1]


async def run_eval(models: list[str], num_runs: int, fixture_path: Path | None):
    if fixture_path is None:
        fixture_path = get_latest_fixture()

    report_input = json.loads(fixture_path.read_text())
    input_json = json.dumps(report_input)
    print(f"Fixture: {fixture_path.name}")
    print(f"Models: {', '.join(models)}")
    print(f"Runs per model: {num_runs}\n")

    system_prompt = templates.get_template("synthesizing_prompt.mako").render(today=today)

    all_results = {}

    for model_name in models:
        print(f"── {model_name} ──")
        agent = Agent(
            model=model_name,
            output_type=str,
            system_prompt=system_prompt,
            retries=3,
        )

        runs = []
        for run_idx in range(num_runs):
            t0 = time.time()
            result = await agent.run(input_json)
            elapsed = time.time() - t0
            output = result.output

            metrics = compute_structural_metrics(output)
            runs.append({
                "output": output,
                "elapsed_seconds": round(elapsed, 1),
                "metrics": metrics,
            })
            print(f"  Run {run_idx+1}: {metrics['word_count']} words, "
                  f"{metrics['section_count']} sections, "
                  f"{metrics['bullet_lines']} bullets, "
                  f"{elapsed:.1f}s")

        # Stability
        if num_runs > 1:
            hj = heading_jaccard(runs)
            print(f"  Heading stability (Jaccard): {hj:.3f}")

        all_results[model_name] = runs
        print()

    # Summary table
    print("── Structural Metrics Summary ──")
    print(f"{'Metric':<30}", end="")
    for model in models:
        short = model.split(":")[-1][:20]
        print(f"  {short:>20}", end="")
    print()

    metric_keys = ["word_count", "bullet_density", "has_daily_memo_title",
                   "has_catalysts_section", "catalysts_at_bottom"]
    for key in metric_keys:
        print(f"  {key:<28}", end="")
        for model in models:
            vals = [r["metrics"][key] for r in all_results[model]]
            if isinstance(vals[0], bool):
                display = f"{sum(vals)}/{len(vals)}"
            elif isinstance(vals[0], float):
                display = f"{sum(vals)/len(vals):.2f}"
            else:
                avg = sum(vals) / len(vals)
                display = f"{avg:.0f}"
            print(f"  {display:>20}", end="")
        print()

    # Save
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output = {
        "fixture": fixture_path.name,
        "date": today.isoformat(),
        "models": {
            model: [{k: v for k, v in r.items()} for r in runs]
            for model, runs in all_results.items()
        },
    }
    outfile = RESULTS_DIR / f"synthesis_{today.isoformat()}.json"
    outfile.write_text(json.dumps(output, indent=2))
    print(f"\nResults saved to {outfile}")


# ── Judge: LLM-as-judge scoring ──────────────────────────────────────────────

class CriterionScore(BaseModel):
    criterion: str
    score_a: int = Field(ge=1, le=5, description="Score for Report A")
    rationale_a: str = Field(description="1-2 sentences explaining score for Report A")
    score_b: int = Field(ge=1, le=5, description="Score for Report B")
    rationale_b: str = Field(description="1-2 sentences explaining score for Report B")


class Judgment(BaseModel):
    criteria: list[CriterionScore]
    preferred: str = Field(description="'A' or 'B' or 'tie'")
    preference_reason: str = Field(description="Why this report is preferred")


async def run_judge(judge_models: list[str], results_path: Path | None):
    if results_path is None:
        results_files = sorted(RESULTS_DIR.glob("synthesis_*.json"))
        results_files = [f for f in results_files if "judge" not in f.name]
        if not results_files:
            print("No synthesis results found. Run 'run' first.")
            sys.exit(1)
        results_path = results_files[-1]

    results = json.loads(results_path.read_text())
    model_names = list(results["models"].keys())
    if len(model_names) < 2:
        print("Need at least 2 models in results to judge.")
        sys.exit(1)

    # Load fixture for fact-checking context
    fixture_path = FIXTURES_DIR / results["fixture"]
    input_data = fixture_path.read_text() if fixture_path.exists() else "(fixture not available)"

    model_a_name = model_names[0]
    model_b_name = model_names[1]
    runs_a = results["models"][model_a_name]
    runs_b = results["models"][model_b_name]
    num_pairs = min(len(runs_a), len(runs_b))

    system_prompt = templates.get_template("synthesis_judge_prompt.mako").render(
        input_data=input_data
    )

    all_judgments = {}

    for judge_model in judge_models:
        print(f"\n{'='*60}")
        print(f"Judge: {judge_model}")
        print(f"{'='*60}")

        agent = Agent(
            model=judge_model,
            output_type=Judgment,
            system_prompt=system_prompt,
            retries=3,
        )

        pair_results = []

        for pair_idx in range(num_pairs):
            report_a_text = runs_a[pair_idx]["output"]
            report_b_text = runs_b[pair_idx]["output"]

            # Randomize A/B assignment per pair to prevent position bias
            swapped = random.random() < 0.5
            if swapped:
                report_a_text, report_b_text = report_b_text, report_a_text
                label_a, label_b = model_b_name, model_a_name
            else:
                label_a, label_b = model_a_name, model_b_name

            user_message = f"""## Report A

{report_a_text}

---

## Report B

{report_b_text}"""

            print(f"\n  ── Pair {pair_idx+1}/{num_pairs} (A={label_a.split(':')[-1][:20]}, B={label_b.split(':')[-1][:20]}) ──")

            result = await agent.run(user_message)
            judgment = result.output

            # Display scores
            print(f"  {'Criterion':<25} {'A':>5} {'B':>5}")
            print(f"  {'-'*35}")
            for c in judgment.criteria:
                print(f"  {c.criterion:<25} {c.score_a:>5} {c.score_b:>5}")

            avg_a = sum(c.score_a for c in judgment.criteria) / len(judgment.criteria)
            avg_b = sum(c.score_b for c in judgment.criteria) / len(judgment.criteria)
            print(f"  {'Average':<25} {avg_a:>5.1f} {avg_b:>5.1f}")

            # Map preference back to real model name
            if judgment.preferred == "A":
                preferred_model = label_a
            elif judgment.preferred == "B":
                preferred_model = label_b
            else:
                preferred_model = "tie"

            print(f"  Preferred: {preferred_model} — {judgment.preference_reason}")

            pair_results.append({
                "pair": pair_idx,
                "label_a": label_a,
                "label_b": label_b,
                "criteria": [c.model_dump() for c in judgment.criteria],
                "preferred": judgment.preferred,
                "preferred_model": preferred_model,
                "preference_reason": judgment.preference_reason,
            })

        # Aggregate across pairs for this judge
        pref_counts: dict[str, int] = {}
        score_totals: dict[str, list[float]] = {model_a_name: [], model_b_name: []}
        for pr in pair_results:
            pref_counts[pr["preferred_model"]] = pref_counts.get(pr["preferred_model"], 0) + 1
            for c in pr["criteria"]:
                # Map scores back to real model names
                if pr["label_a"] == model_a_name:
                    score_totals[model_a_name].append(c["score_a"])
                    score_totals[model_b_name].append(c["score_b"])
                else:
                    score_totals[model_b_name].append(c["score_a"])
                    score_totals[model_a_name].append(c["score_b"])

        print(f"\n  ── {judge_model} Summary ({num_pairs} pairs) ──")
        for model in [model_a_name, model_b_name]:
            scores = score_totals[model]
            avg = sum(scores) / len(scores) if scores else 0
            wins = pref_counts.get(model, 0)
            print(f"  {model.split(':')[-1][:25]}: avg score {avg:.2f}, preferred {wins}/{num_pairs}")
        ties = pref_counts.get("tie", 0)
        if ties:
            print(f"  Ties: {ties}/{num_pairs}")

        all_judgments[judge_model] = {
            "model_a": model_a_name,
            "model_b": model_b_name,
            "pairs": pair_results,
            "preference_counts": pref_counts,
        }

    # Cross-judge agreement
    if len(judge_models) > 1:
        print(f"\n{'='*60}")
        print("Cross-judge agreement")
        print(f"{'='*60}")
        for j in judge_models:
            counts = all_judgments[j]["preference_counts"]
            short = j.split(":")[-1][:25]
            summary = ", ".join(f"{m.split(':')[-1][:20]}={c}" for m, c in sorted(counts.items()))
            print(f"  {short}: {summary}")

    # Save
    outfile = RESULTS_DIR / f"synthesis_judge_{today.isoformat()}.json"
    outfile.write_text(json.dumps(all_judgments, indent=2))
    print(f"\nJudgments saved to {outfile}")


# ── Report: summary of all results ──────────────────────────────────────────

def print_report(results_path: Path | None):
    if results_path is None:
        results_files = sorted(RESULTS_DIR.glob("synthesis_*.json"))
        results_files = [f for f in results_files if "judge" not in f.name]
        if not results_files:
            print("No results found.")
            return
        results_path = results_files[-1]

    results = json.loads(results_path.read_text())
    print(f"Results from: {results_path.name}")
    print(f"Fixture: {results['fixture']}\n")

    for model, runs in results["models"].items():
        print(f"── {model} ──")
        for i, run in enumerate(runs):
            m = run["metrics"]
            print(f"  Run {i+1}: {m['word_count']} words, {m['section_count']} sections, "
                  f"{m['bullet_lines']} bullets, {run['elapsed_seconds']}s")
            if not m["has_daily_memo_title"]:
                print("    ⚠ Missing 'Daily Memo' title")
            if not m["has_catalysts_section"]:
                print("    ⚠ Missing 'Upcoming Catalysts' section")
            if not m["catalysts_at_bottom"]:
                print("    ⚠ Catalysts not at bottom")
        print()

    # Check for judge results
    judge_files = sorted(RESULTS_DIR.glob("synthesis_judge_*.json"))
    if judge_files:
        judge_results = json.loads(judge_files[-1].read_text())
        print("── Judge Scores ──")
        for judge, j in judge_results.items():
            short_judge = judge.split(":")[-1][:25]
            print(f"\n  Judge: {short_judge}")
            print(f"  {'Criterion':<25} {j['report_a_model'].split(':')[-1][:15]:>15} {j['report_b_model'].split(':')[-1][:15]:>15}")
            for c in j["criteria"]:
                print(f"  {c['criterion']:<25} {c['score_a']:>15} {c['score_b']:>15}")
            print(f"  Preferred: {j['preferred_model']}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Eval harness for synthesis model")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("snapshot", help="Run pipeline and capture synthesis fixture")

    run_parser = sub.add_parser("run", help="Generate reports from multiple models")
    run_parser.add_argument(
        "--models", nargs="+",
        default=["openai:gpt-4.1-2025-04-14", "anthropic:claude-sonnet-4-6"],
    )
    run_parser.add_argument("--runs", type=int, default=3)
    run_parser.add_argument("--fixture", type=Path, default=None)

    judge_parser = sub.add_parser("judge", help="Run LLM-as-judge scoring")
    judge_parser.add_argument(
        "--judge-models", nargs="+",
        default=["openai:o3-2025-04-16", "anthropic:claude-opus-4-6"],
    )
    judge_parser.add_argument("--results", type=Path, default=None)

    report_parser = sub.add_parser("report", help="Print summary of results")
    report_parser.add_argument("--results", type=Path, default=None)

    args = parser.parse_args()

    if args.command == "snapshot":
        snapshot()
    elif args.command == "run":
        asyncio.run(run_eval(args.models, args.runs, args.fixture))
    elif args.command == "judge":
        asyncio.run(run_judge(args.judge_models, args.results))
    elif args.command == "report":
        print_report(args.results)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

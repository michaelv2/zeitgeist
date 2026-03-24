"""
Eval harness for the prediction relevance classifier.

Measures:
  1. Accuracy — agreement with human labels (precision, recall, F1)
  2. Stability — self-agreement across repeated runs (Jaccard similarity)

Usage:
  # Label fixtures first (interactive):
    uv run python eval_classifier.py label

  # Run eval (defaults to 3 runs of each model):
    uv run python eval_classifier.py run

  # Run with custom settings:
    uv run python eval_classifier.py run --models openai:gpt-5-mini-2025-08-07 anthropic:claude-sonnet-4-6 --runs 5

  # Compare classification strategies (news-aware vs coarse-filter):
    uv run python eval_classifier.py compare
    uv run python eval_classifier.py compare --model anthropic:claude-haiku-4-5-20251001
"""

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

import polars as pl
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from mako.lookup import TemplateLookup
from dotenv import load_dotenv

load_dotenv()

FIXTURES_PATH = Path("eval/classifier_fixtures.json")
LABELS_PATH = Path("eval/classifier_labels.json")
RESULTS_DIR = Path("eval/results")

templates = TemplateLookup(directories=["templates"])
today = date.today()


class RelevantPrediction(BaseModel):
    id: str = Field(description="original id from input")
    topics: str = Field(description="Very short phrase (1-3 words): public companies or investment sectors or broad alternatives impacted")


def load_fixtures() -> list[dict]:
    if not FIXTURES_PATH.exists():
        print(f"No fixtures found at {FIXTURES_PATH}.")
        print("Run the main script once, then use 'eval_classifier.py snapshot' to capture predictions.")
        sys.exit(1)
    return json.loads(FIXTURES_PATH.read_text())


def load_labels() -> dict[str, bool]:
    if not LABELS_PATH.exists():
        return {}
    return json.loads(LABELS_PATH.read_text())


def save_labels(labels: dict[str, bool]):
    LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    LABELS_PATH.write_text(json.dumps(labels, indent=2))


# ── Snapshot: capture live predictions for labeling ──────────────────────────

async def snapshot_fixtures(n: int = 50):
    """Fetch predictions from Polymarket via tagged event categories, then sample n for labeling.

    Pulls from investment-relevant tags (economy, finance, geopolitics, etc.) and
    a smaller share of irrelevant tags (sports, culture) to create a balanced fixture set.
    """
    import httpx as _httpx

    POLYMARKET_API = "https://gamma-api.polymarket.com"
    LIMIT = 100

    # Tags likely to contain investment-relevant predictions
    RELEVANT_TAGS = [
        "economy", "finance", "business", "geopolitics", "middle-east", "ukraine",
        "china", "russia", "foreign-policy", "taxes", "tech", "big-tech", "ai",
        "crypto", "ipos", "ipo", "stocks", "pre-market", "trump-presidency",
        "elon-musk", "openai", "south-korea", "gaza", "ukraine-peace-deal",
    ]
    # Tags that should be classified as NOT relevant (negative examples)
    IRRELEVANT_TAGS = ["sports", "nba", "nhl", "soccer", "pop-culture", "awards"]

    seen_ids: set[str] = set()
    relevant_pool: list[dict] = []
    irrelevant_pool: list[dict] = []

    async with _httpx.AsyncClient() as client:
        async def fetch_tag(tag: str) -> list[dict]:
            preds = []
            offset = 0
            while True:
                params = {"active": "true", "closed": "false", "limit": LIMIT,
                          "offset": offset, "tag_slug": tag}
                resp = await client.get(f"{POLYMARKET_API}/events", params=params)
                resp.raise_for_status()
                events = resp.json()
                if not events:
                    break
                for event in events:
                    for m in event.get("markets", []):
                        mid = f"pm-{m['id']}"
                        if mid in seen_ids:
                            continue
                        seen_ids.add(mid)
                        bets = []
                        for prompt, prob in zip(
                            json.loads(m["outcomes"]),
                            json.loads(m.get("outcomePrices", "[]")),
                        ):
                            bets.append({"prompt": prompt, "probability": float(prob)})
                        preds.append({"id": mid, "title": m["question"], "bets": bets})
                offset += LIMIT
            return preds

        for tag in RELEVANT_TAGS:
            print(f"Fetching tag: {tag}...")
            relevant_pool.extend(await fetch_tag(tag))

        for tag in IRRELEVANT_TAGS:
            print(f"Fetching tag: {tag}...")
            irrelevant_pool.extend(await fetch_tag(tag))

    print(f"Pool sizes — relevant tags: {len(relevant_pool)}, irrelevant tags: {len(irrelevant_pool)}")

    # Sample: ~60% from relevant tags, ~40% from irrelevant tags
    import random
    random.shuffle(relevant_pool)
    random.shuffle(irrelevant_pool)
    n_relevant = min(int(n * 0.6), len(relevant_pool))
    n_irrelevant = min(n - n_relevant, len(irrelevant_pool))
    fixtures = relevant_pool[:n_relevant] + irrelevant_pool[:n_irrelevant]
    random.shuffle(fixtures)

    FIXTURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURES_PATH.write_text(json.dumps(fixtures, indent=2))
    print(f"Saved {len(fixtures)} predictions to {FIXTURES_PATH}")
    print(f"Next step: run 'uv run python eval_classifier.py label' to label them.")


# ── Label: interactive labeling CLI ──────────────────────────────────────────

def label_fixtures():
    """Interactive CLI to label fixtures as relevant (y) or not (n)."""
    fixtures = load_fixtures()
    labels = load_labels()

    unlabeled = [f for f in fixtures if f["id"] not in labels]
    if not unlabeled:
        print(f"All {len(fixtures)} fixtures are labeled. Re-run with 'eval_classifier.py relabel' to start over.")
        return

    print(f"\n{len(unlabeled)} unlabeled predictions (of {len(fixtures)} total).")
    print("For each prediction, enter: y (relevant) / n (not relevant) / s (skip) / q (quit)\n")

    for i, pred in enumerate(unlabeled):
        bets_str = ", ".join(
            f"{b['prompt']}: {b['probability']:.0%}" for b in pred["bets"][:3]
        )
        if len(pred["bets"]) > 3:
            bets_str += f" ... (+{len(pred['bets']) - 3} more)"

        print(f"[{i+1}/{len(unlabeled)}] {pred['title']}")
        print(f"  Bets: {bets_str}")

        while True:
            choice = input("  Relevant? (y/n/s/q): ").strip().lower()
            if choice in ("y", "n", "s", "q"):
                break
            print("  Invalid input.")

        if choice == "q":
            break
        elif choice == "s":
            continue
        else:
            labels[pred["id"]] = (choice == "y")

    save_labels(labels)
    labeled_count = sum(1 for f in fixtures if f["id"] in labels)
    print(f"\nSaved {labeled_count}/{len(fixtures)} labels to {LABELS_PATH}")


# ── Run: evaluate models ─────────────────────────────────────────────────────

async def run_eval(models: list[str], num_runs: int):
    """Run each model N times against labeled fixtures and report metrics."""
    fixtures = load_fixtures()
    labels = load_labels()

    labeled_fixtures = [f for f in fixtures if f["id"] in labels]
    if len(labeled_fixtures) < 10:
        print(f"Only {len(labeled_fixtures)} labeled fixtures. Label at least 10 for meaningful results.")
        print("Run: uv run python eval_classifier.py label")
        sys.exit(1)

    print(f"\nEvaluating {len(models)} model(s) x {num_runs} run(s) on {len(labeled_fixtures)} labeled predictions\n")

    ground_truth = {f["id"]: labels[f["id"]] for f in labeled_fixtures}
    batch_json = pl.DataFrame(labeled_fixtures).select("id", "title", "bets").write_json()

    all_results = {}

    for model_name in models:
        print(f"── {model_name} ──")
        # gpt-5-mini doesn't support temperature override; only set for models that do
        settings = {} if "gpt-5-mini" in model_name else {"temperature": 0}
        agent = Agent(
            model=model_name,
            output_type=list[RelevantPrediction],
            system_prompt=templates.get_template("relevant_prediction_prompt.mako").render(today=today),
            retries=3,
            model_settings=settings,
        )

        run_selections: list[set[str]] = []

        for run_idx in range(num_runs):
            result = await agent.run(batch_json)
            selected_ids = {r.id for r in result.output}
            run_selections.append(selected_ids)

            # Accuracy vs labels
            tp = sum(1 for id, rel in ground_truth.items() if rel and id in selected_ids)
            fp = sum(1 for id, rel in ground_truth.items() if not rel and id in selected_ids)
            fn = sum(1 for id, rel in ground_truth.items() if rel and id not in selected_ids)
            tn = sum(1 for id, rel in ground_truth.items() if not rel and id not in selected_ids)

            precision = tp / (tp + fp) if (tp + fp) > 0 else 0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

            print(f"  Run {run_idx+1}: selected {len(selected_ids)}/{len(labeled_fixtures)}  "
                  f"P={precision:.2f} R={recall:.2f} F1={f1:.2f}  (TP={tp} FP={fp} FN={fn} TN={tn})")

        # Stability: pairwise Jaccard across runs
        if num_runs > 1:
            jaccards = []
            for i in range(num_runs):
                for j in range(i + 1, num_runs):
                    intersection = len(run_selections[i] & run_selections[j])
                    union = len(run_selections[i] | run_selections[j])
                    jaccards.append(intersection / union if union > 0 else 1.0)
            avg_jaccard = sum(jaccards) / len(jaccards)
            print(f"  Stability (avg pairwise Jaccard): {avg_jaccard:.3f}")

            # Show which predictions flip between runs
            all_selected = set().union(*run_selections)
            unstable = [
                id for id in all_selected
                if any(id in s for s in run_selections) and not all(id in s for s in run_selections)
            ]
            if unstable:
                titles = {f["id"]: f["title"] for f in labeled_fixtures}
                print(f"  Unstable predictions ({len(unstable)}):")
                for id in sorted(unstable):
                    times = sum(1 for s in run_selections if id in s)
                    print(f"    {id}: selected {times}/{num_runs} — {titles.get(id, '?')}")

        all_results[model_name] = run_selections
        print()

    # Cross-model comparison
    if len(models) > 1:
        print("── Cross-model agreement ──")
        model_names = list(all_results.keys())
        for i in range(len(model_names)):
            for j in range(i + 1, len(model_names)):
                # Compare the first run of each
                a = all_results[model_names[i]][0]
                b = all_results[model_names[j]][0]
                intersection = len(a & b)
                union = len(a | b)
                jaccard = intersection / union if union > 0 else 1.0
                only_a = a - b
                only_b = b - a
                print(f"  {model_names[i]} vs {model_names[j]}: "
                      f"Jaccard={jaccard:.3f}, shared={intersection}, "
                      f"only-first={len(only_a)}, only-second={len(only_b)}")

    # Save raw results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output = {
        model: [[sorted(s) for s in runs]]
        for model, runs in all_results.items()
    }
    outfile = RESULTS_DIR / f"eval_{today.isoformat()}.json"
    outfile.write_text(json.dumps(output, indent=2))
    print(f"\nRaw results saved to {outfile}")


# ── Compare: test classification strategies side-by-side ─────────────────────

def fetch_news_headlines() -> list[str]:
    """Fetch today's top news headlines via GNews."""
    from gnews import GNews
    try:
        news = GNews().get_top_news()
        headlines = [item["title"] for item in news if "title" in item]
        print(f"Fetched {len(headlines)} news headlines")
        return headlines
    except Exception as e:
        print(f"Failed to fetch news: {e}")
        return []


STRATEGIES = {
    "baseline": {
        "description": "Current prompt — static relevance filter (no news context)",
        "template": "relevant_prediction_prompt.mako",
        "needs_news": False,
    },
    "news-aware": {
        "description": "Option 1 — classifier sees today's headlines as context",
        "template": "classifier_news_aware_prompt.mako",
        "needs_news": True,
    },
    "coarse-filter": {
        "description": "Option 3 — only remove obvious noise (sports, celebrity, memes)",
        "template": "classifier_coarse_filter_prompt.mako",
        "needs_news": False,
    },
}


async def compare_strategies(model: str, strategies: list[str], num_runs: int):
    """Run multiple classification strategies against the same predictions and compare."""
    fixtures = load_fixtures()

    print(f"Fetching news headlines for context...")
    headlines = fetch_news_headlines()

    batch_json = pl.DataFrame(fixtures).select("id", "title", "bets").write_json()
    titles = {f["id"]: f["title"] for f in fixtures}

    settings = {} if "gpt-5-mini" in model else {"temperature": 0}

    all_results: dict[str, list[set[str]]] = {}

    for strategy_name in strategies:
        strategy = STRATEGIES[strategy_name]
        print(f"\n{'='*60}")
        print(f"Strategy: {strategy_name} — {strategy['description']}")
        print(f"Model: {model}")
        print(f"{'='*60}")

        template_kwargs = {"today": today}
        if strategy["needs_news"]:
            template_kwargs["headlines"] = headlines

        system_prompt = templates.get_template(strategy["template"]).render(**template_kwargs)

        agent = Agent(
            model=model,
            output_type=list[RelevantPrediction],
            system_prompt=system_prompt,
            retries=3,
            model_settings=settings,
        )

        run_selections: list[set[str]] = []

        for run_idx in range(num_runs):
            result = await agent.run(batch_json)
            selected_ids = {r.id for r in result.output}
            run_selections.append(selected_ids)
            print(f"  Run {run_idx+1}: selected {len(selected_ids)}/{len(fixtures)}")

        # Stability
        if num_runs > 1:
            jaccards = []
            for i in range(num_runs):
                for j in range(i + 1, num_runs):
                    inter = len(run_selections[i] & run_selections[j])
                    union = len(run_selections[i] | run_selections[j])
                    jaccards.append(inter / union if union > 0 else 1.0)
            print(f"  Stability (avg Jaccard): {sum(jaccards)/len(jaccards):.3f}")

        # Show what was selected (using first run)
        print(f"\n  Selected predictions (run 1):")
        for pred_id in sorted(run_selections[0]):
            title = titles.get(pred_id, "?")
            print(f"    {pred_id}: {title[:90]}")

        all_results[strategy_name] = run_selections

    # Cross-strategy comparison
    if len(strategies) > 1:
        print(f"\n{'='*60}")
        print("Cross-strategy comparison (run 1 of each)")
        print(f"{'='*60}")
        strategy_names = list(all_results.keys())
        for i in range(len(strategy_names)):
            for j in range(i + 1, len(strategy_names)):
                a_name, b_name = strategy_names[i], strategy_names[j]
                a, b = all_results[a_name][0], all_results[b_name][0]
                shared = a & b
                only_a = a - b
                only_b = b - a
                print(f"\n  {a_name} vs {b_name}:")
                print(f"    Shared ({len(shared)}): {', '.join(titles.get(x, x)[:50] for x in sorted(shared)) or '(none)'}")
                if only_a:
                    print(f"    Only {a_name} ({len(only_a)}):")
                    for x in sorted(only_a):
                        print(f"      {titles.get(x, x)[:90]}")
                if only_b:
                    print(f"    Only {b_name} ({len(only_b)}):")
                    for x in sorted(only_b):
                        print(f"      {titles.get(x, x)[:90]}")

    # Show news headlines for reference
    if headlines:
        print(f"\n{'='*60}")
        print(f"Today's news headlines (for reference)")
        print(f"{'='*60}")
        for h in headlines[:15]:
            print(f"  - {h[:100]}")
        if len(headlines) > 15:
            print(f"  ... and {len(headlines) - 15} more")

    # Save
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output = {
        "model": model,
        "headlines": headlines[:20],
        "strategies": {
            name: {"selected": [sorted(s) for s in runs]}
            for name, runs in all_results.items()
        },
    }
    outfile = RESULTS_DIR / f"compare_{today.isoformat()}.json"
    outfile.write_text(json.dumps(output, indent=2))
    print(f"\nResults saved to {outfile}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Eval harness for prediction classifier")
    sub = parser.add_subparsers(dest="command")

    snap_parser = sub.add_parser("snapshot", help="Fetch live predictions and save as fixtures")
    snap_parser.add_argument("-n", type=int, default=50, help="Number of predictions to sample")
    sub.add_parser("label", help="Interactively label fixtures")
    sub.add_parser("relabel", help="Clear labels and start over")

    run_parser = sub.add_parser("run", help="Run eval against labeled fixtures")
    run_parser.add_argument(
        "--models", nargs="+",
        default=["openai:gpt-5-mini-2025-08-07", "anthropic:claude-sonnet-4-6"],
        help="Models to evaluate",
    )
    run_parser.add_argument("--runs", type=int, default=3, help="Number of runs per model")

    cmp_parser = sub.add_parser("compare", help="Compare classification strategies side-by-side")
    cmp_parser.add_argument(
        "--model", default="openai:gpt-5-mini-2025-08-07",
        help="Model to use for comparison",
    )
    cmp_parser.add_argument(
        "--strategies", nargs="+",
        default=["baseline", "news-aware", "coarse-filter"],
        choices=list(STRATEGIES.keys()),
        help="Strategies to compare",
    )
    cmp_parser.add_argument("--runs", type=int, default=2, help="Number of runs per strategy")

    args = parser.parse_args()

    if args.command == "snapshot":
        asyncio.run(snapshot_fixtures(args.n))
    elif args.command == "label":
        label_fixtures()
    elif args.command == "relabel":
        if LABELS_PATH.exists():
            LABELS_PATH.unlink()
            print("Labels cleared.")
        label_fixtures()
    elif args.command == "run":
        asyncio.run(run_eval(args.models, args.runs))
    elif args.command == "compare":
        asyncio.run(compare_strategies(args.model, args.strategies, args.runs))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

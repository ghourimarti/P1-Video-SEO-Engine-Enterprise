"""RAGAS offline evaluation runner.

Loads golden QA pairs from packages/eval/golden/golden_set.json,
runs the full RAG pipeline against each question, and scores using
RAGAS metrics: faithfulness, answer_relevancy, context_recall.

Implemented in M8 — this is the scaffold stub.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# M8: import actual pipeline + RAGAS metrics

GOLDEN_PATH = Path(__file__).parent.parent.parent / "golden" / "golden_set.json"
PASS_THRESHOLD = 0.75  # CI fails if any metric drops below this


def load_golden_set() -> list[dict]:
    if not GOLDEN_PATH.exists():
        print(f"[eval] Golden set not found at {GOLDEN_PATH}. Skipping.", flush=True)
        return []
    with GOLDEN_PATH.open() as f:
        return json.load(f)


def run_eval() -> dict[str, float]:
    """Run RAGAS evaluation and return metric scores."""
    golden = load_golden_set()
    if not golden:
        return {}

    # M8: wire in the real pipeline + ragas Dataset + evaluate()
    print(f"[eval] Running RAGAS on {len(golden)} golden samples (stub — M8).")
    scores: dict[str, float] = {
        "faithfulness": 0.0,
        "answer_relevancy": 0.0,
        "context_recall": 0.0,
    }
    return scores


def main() -> None:
    scores = run_eval()
    if not scores:
        print("[eval] No scores produced — golden set missing.")
        sys.exit(0)

    print("\n── RAGAS Results ──────────────────────────────")
    failed = False
    for metric, score in scores.items():
        status = "PASS" if score >= PASS_THRESHOLD else "FAIL"
        if status == "FAIL":
            failed = True
        print(f"  {metric:<22} {score:.4f}  [{status}]")
    print("──────────────────────────────────────────────\n")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

"""RAGAS offline evaluation runner.

Loads golden QA pairs from packages/eval/golden/golden_set.json, calls the
live /api/v1/recommend endpoint for each question, then scores the results
using RAGAS metrics.

Metrics evaluated
-----------------
- faithfulness       : Is the answer grounded in the retrieved context?
- answer_relevancy   : Does the answer address the question?
- context_recall     : Are the reference docs present in the retrieved context?

Usage
-----
    # Against local stack (make up first)
    python -m eval.ragas_runner

    # Against a specific endpoint
    API_URL=https://staging.example.com python -m eval.ragas_runner

    # Produce a JSON report
    python -m eval.ragas_runner --report eval_report.json

CI integration
--------------
Exit code 0 → all metrics ≥ PASS_THRESHOLD.
Exit code 1 → one or more metrics below threshold (CI gate fails).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests
import structlog

log = structlog.get_logger(__name__)

GOLDEN_PATH   = Path(__file__).parent.parent.parent / "golden" / "golden_set.json"
PASS_THRESHOLD = 0.75   # any metric below this fails the CI gate
API_URL        = os.getenv("API_URL", "http://localhost:8000")
API_KEY        = os.getenv("EVAL_API_KEY", "")   # Bearer token for Clerk-protected API
REQUEST_TIMEOUT = 60    # seconds per request


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_golden_set() -> list[dict]:
    if not GOLDEN_PATH.exists():
        log.error("golden_set_missing", path=str(GOLDEN_PATH))
        sys.exit(1)
    with GOLDEN_PATH.open() as f:
        data = json.load(f)
    log.info("golden_set_loaded", n=len(data))
    return data


def call_api(question: str, top_n: int = 5) -> dict:
    """POST to /api/v1/recommend and return the response dict."""
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    resp = requests.post(
        f"{API_URL}/api/v1/recommend",
        json={"query": question, "top_n": top_n},
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def build_ragas_dataset(golden: list[dict]) -> tuple[list, list, list, list]:
    """
    Call the API for each golden sample and collect:
        questions, answers, contexts (retrieved titles+synopsis), ground_truths
    """
    questions:    list[str]       = []
    answers:      list[str]       = []
    contexts:     list[list[str]] = []
    ground_truths: list[str]      = []

    for i, sample in enumerate(golden):
        q  = sample["question"]
        gt = sample.get("ground_truth", "")
        log.info("eval_calling_api", n=i + 1, total=len(golden), question=q[:60])
        try:
            result = call_api(q, top_n=sample.get("top_n", 5))
        except Exception as exc:
            log.warning("api_call_failed", question=q[:60], error=str(exc))
            continue

        ctx = [
            f"Title: {s['name']}\nGenres: {', '.join(s.get('genres', []))}"
            for s in result.get("sources", [])
        ]

        questions.append(q)
        answers.append(result.get("answer", ""))
        contexts.append(ctx)
        ground_truths.append(gt)

        time.sleep(0.5)   # gentle on the local API

    return questions, answers, contexts, ground_truths


# ── RAGAS evaluation ──────────────────────────────────────────────────────────

def run_ragas(
    questions:     list[str],
    answers:       list[str],
    contexts:      list[list[str]],
    ground_truths: list[str],
) -> dict[str, float]:
    try:
        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import faithfulness, answer_relevancy, context_recall
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    except ImportError as exc:
        log.error("ragas_import_failed", error=str(exc))
        sys.exit(1)

    dataset = Dataset.from_dict({
        "question":     questions,
        "answer":       answers,
        "contexts":     contexts,
        "ground_truth": ground_truths,
    })

    llm        = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

    result = evaluate(
        dataset,
        metrics=[faithfulness, answer_relevancy, context_recall],
        llm=llm,
        embeddings=embeddings,
        raise_exceptions=False,
    )

    return {
        "faithfulness":      float(result["faithfulness"]),
        "answer_relevancy":  float(result["answer_relevancy"]),
        "context_recall":    float(result["context_recall"]),
    }


# ── Entry point ───────────────────────────────────────────────────────────────

def _print_results(scores: dict[str, float]) -> bool:
    """Print table; return True if all metrics pass."""
    print("\n── RAGAS Evaluation Results ────────────────────────────────")
    all_pass = True
    for metric, score in scores.items():
        status = "PASS" if score >= PASS_THRESHOLD else "FAIL"
        if status == "FAIL":
            all_pass = False
        flag = "✅" if status == "PASS" else "❌"
        print(f"  {flag}  {metric:<22}  {score:.4f}  (threshold ≥ {PASS_THRESHOLD})")
    print("─────────────────────────────────────────────────────────────\n")
    return all_pass


def main() -> None:
    parser = argparse.ArgumentParser(description="RAGAS eval runner")
    parser.add_argument("--report", metavar="FILE", help="Write JSON report to FILE")
    parser.add_argument(
        "--sample", metavar="N", type=int, default=0,
        help="Evaluate only first N samples (0 = all)",
    )
    args = parser.parse_args()

    golden = load_golden_set()
    if args.sample:
        golden = golden[: args.sample]
        log.info("eval_sample_mode", n=args.sample)

    questions, answers, contexts, ground_truths = build_ragas_dataset(golden)

    if not questions:
        log.error("no_samples_collected")
        sys.exit(1)

    log.info("running_ragas", n=len(questions))
    scores = run_ragas(questions, answers, contexts, ground_truths)

    all_pass = _print_results(scores)

    if args.report:
        report = {
            "threshold":   PASS_THRESHOLD,
            "n_samples":   len(questions),
            "all_pass":    all_pass,
            "scores":      scores,
        }
        Path(args.report).write_text(json.dumps(report, indent=2))
        log.info("report_written", path=args.report)

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()

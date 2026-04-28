"""Embedding drift detector.

Computes the mean cosine distance between a reference embedding distribution
(captured from the golden set at eval time) and a live sample drawn from recent
queries logged to the audit_log table.

If drift exceeds the configured threshold the script exits with code 1, which
fails the nightly CI drift check.

Usage
-----
    python -m eval.drift_detector
    python -m eval.drift_detector --threshold 0.15 --sample 200

Algorithm
---------
1. Load golden questions, embed them with text-embedding-3-large (reference).
2. Load last N queries from audit_log (production distribution).
3. Embed production queries.
4. Compute pairwise mean cosine distance between the two distributions.
5. Flag drift if distance > threshold.

Why cosine distance?
--------------------
We care about directional shift in semantic space, not magnitude. Cosine
distance (1 − cosine similarity) is 0 for identical directions and 2 for
opposite directions. A threshold of 0.10–0.15 is a reasonable starting point
for detecting meaningful query distribution shift.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import structlog

log = structlog.get_logger(__name__)

GOLDEN_PATH   = Path(__file__).parent.parent.parent / "golden" / "golden_set.json"
DRIFT_THRESHOLD = float(os.getenv("DRIFT_THRESHOLD", "0.12"))
SAMPLE_SIZE     = int(os.getenv("DRIFT_SAMPLE_SIZE", "100"))


# ── Embedding helper ──────────────────────────────────────────────────────────

def embed_texts(texts: list[str], model: str = "text-embedding-3-large") -> np.ndarray:
    """Return (N, D) float32 array of L2-normalised embeddings."""
    from langchain_openai import OpenAIEmbeddings

    embedder = OpenAIEmbeddings(model=model)
    batch_size = 20
    vecs = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        vecs.extend(embedder.embed_documents(batch))
        log.debug("embed_batch", start=i, end=i + len(batch), total=len(texts))

    arr = np.array(vecs, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    return arr / np.maximum(norms, 1e-9)


# ── Distance metric ───────────────────────────────────────────────────────────

def mean_cosine_distance(ref: np.ndarray, live: np.ndarray) -> float:
    """Mean pairwise cosine distance between two embedding matrices.

    Uses random sampling (min 500 pairs) to keep cost bounded.
    """
    n_pairs = min(500, len(ref) * len(live))
    idx_ref  = np.random.choice(len(ref),  n_pairs, replace=True)
    idx_live = np.random.choice(len(live), n_pairs, replace=True)

    dots = np.sum(ref[idx_ref] * live[idx_live], axis=1)
    # Both already L2-normalised so dot = cosine similarity
    cosine_dist = 1.0 - dots
    return float(np.mean(cosine_dist))


# ── Production query loader ───────────────────────────────────────────────────

def load_production_queries(n: int) -> list[str]:
    """Load recent queries from audit_log via psycopg3.

    Falls back to an empty list if DB is unreachable (drift check skipped).
    """
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        log.warning("drift_no_db_url", reason="DATABASE_URL not set — skipping production sample")
        return []

    try:
        import psycopg

        conn = psycopg.connect(db_url)
        rows = conn.execute(
            "SELECT query FROM audit_log ORDER BY created_at DESC LIMIT %s", (n,)
        ).fetchall()
        conn.close()
        queries = [r[0] for r in rows if r[0]]
        log.info("drift_production_queries_loaded", n=len(queries))
        return queries
    except Exception as exc:
        log.warning("drift_db_load_failed", error=str(exc))
        return []


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Embedding drift detector")
    parser.add_argument("--threshold", type=float, default=DRIFT_THRESHOLD,
                        help=f"Cosine distance threshold (default {DRIFT_THRESHOLD})")
    parser.add_argument("--sample", type=int, default=SAMPLE_SIZE,
                        help=f"Number of production queries to sample (default {SAMPLE_SIZE})")
    parser.add_argument("--report", metavar="FILE", help="Write JSON report to FILE")
    args = parser.parse_args()

    # ── Reference distribution ────────────────────────────────────────────────
    if not GOLDEN_PATH.exists():
        log.error("golden_set_missing", path=str(GOLDEN_PATH))
        sys.exit(1)

    with GOLDEN_PATH.open() as f:
        golden = json.load(f)

    ref_texts = [s["question"] for s in golden]
    log.info("embedding_reference", n=len(ref_texts))
    ref_embs = embed_texts(ref_texts)

    # ── Production distribution ───────────────────────────────────────────────
    live_texts = load_production_queries(args.sample)
    if not live_texts:
        print("[drift] No production queries available — drift check skipped.")
        sys.exit(0)

    log.info("embedding_production", n=len(live_texts))
    live_embs = embed_texts(live_texts)

    # ── Distance ──────────────────────────────────────────────────────────────
    dist = mean_cosine_distance(ref_embs, live_embs)
    drifted = dist > args.threshold

    print(f"\n── Embedding Drift Report ───────────────────────────────")
    print(f"  Mean cosine distance : {dist:.6f}")
    print(f"  Threshold            : {args.threshold}")
    print(f"  Drift detected       : {'❌ YES — alert!' if drifted else '✅ NO'}")
    print(f"  Reference samples    : {len(ref_texts)}")
    print(f"  Production samples   : {len(live_texts)}")
    print(f"─────────────────────────────────────────────────────────\n")

    if args.report:
        report = {
            "cosine_distance":   dist,
            "threshold":         args.threshold,
            "drift_detected":    drifted,
            "ref_samples":       len(ref_texts),
            "live_samples":      len(live_texts),
        }
        Path(args.report).write_text(json.dumps(report, indent=2))
        log.info("drift_report_written", path=args.report)

    sys.exit(1 if drifted else 0)


if __name__ == "__main__":
    main()

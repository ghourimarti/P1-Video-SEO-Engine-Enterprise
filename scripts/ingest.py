"""Ingest anime CSV into pgvector.

Reads data/anime_with_synopsis.csv, embeds each synopsis with
OpenAI text-embedding-3-large, and bulk-upserts into the
anime_documents table via psycopg3.

Usage:
    python scripts/ingest.py --csv data/anime_with_synopsis.csv
    python scripts/ingest.py --csv data/anime_with_synopsis.csv --batch-size 16 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# Must happen before importing settings so .env is loaded
import os
import psycopg
from pgvector.psycopg import register_vector
from langchain_openai import OpenAIEmbeddings

# ── CLI ───────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest anime CSV into pgvector")
    p.add_argument("--csv", required=True, type=Path)
    p.add_argument("--batch-size", default=32, type=int, help="Embeddings per API call")
    p.add_argument("--dry-run", action="store_true", help="Validate CSV only; no DB writes")
    return p.parse_args()


# ── Data loading ──────────────────────────────────────────────────────────────


def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = {"MAL_ID", "Name", "sypnopsis"}
    missing = required - set(df.columns)
    if missing:
        print(f"[ingest] ERROR: Missing columns: {missing}", file=sys.stderr)
        sys.exit(1)

    before = len(df)
    df = df.dropna(subset=["sypnopsis"]).reset_index(drop=True)
    df = df[df["sypnopsis"].str.strip() != ""].reset_index(drop=True)
    print(f"[ingest] {len(df)} rows (dropped {before - len(df)} with empty synopsis)")

    # Normalise genres: "Action, Adventure" → ["Action", "Adventure"]
    if "Genres" in df.columns:
        df["genres_arr"] = df["Genres"].fillna("").apply(
            lambda g: [x.strip() for x in g.split(",") if x.strip()]
        )
    else:
        df["genres_arr"] = [[] for _ in range(len(df))]

    # Score — coerce to float, keep NaN
    if "Score" in df.columns:
        df["score"] = pd.to_numeric(df["Score"], errors="coerce")
    else:
        df["score"] = float("nan")

    return df


# ── Embedding ─────────────────────────────────────────────────────────────────


async def embed_batches(
    texts: list[str],
    embedder: OpenAIEmbeddings,
    batch_size: int,
) -> list[list[float]]:
    all_vecs: list[list[float]] = []
    total = len(texts)
    for i in range(0, total, batch_size):
        batch = texts[i : i + batch_size]
        vecs = await embedder.aembed_documents(batch)
        all_vecs.extend(vecs)
        print(f"[ingest] Embedded {min(i + batch_size, total)}/{total}", end="\r", flush=True)
    print()
    return all_vecs


# ── DB upsert ─────────────────────────────────────────────────────────────────

_UPSERT_SQL = """
INSERT INTO anime_documents (mal_id, name, score, genres, synopsis, embedding)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (mal_id) DO UPDATE SET
    name      = EXCLUDED.name,
    score     = EXCLUDED.score,
    genres    = EXCLUDED.genres,
    synopsis  = EXCLUDED.synopsis,
    embedding = EXCLUDED.embedding,
    updated_at = NOW()
"""


def upsert(conn, rows: list[tuple]) -> int:
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_SQL, rows)
    conn.commit()
    return len(rows)


# ── Main ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    args = parse_args()

    if not args.csv.exists():
        print(f"[ingest] CSV not found: {args.csv}", file=sys.stderr)
        sys.exit(1)

    df = load_csv(args.csv)

    if args.dry_run:
        print("[ingest] Dry-run — skipping embedding and DB writes.")
        print(f"[ingest] Would process {len(df)} rows in batches of {args.batch_size}.")
        return

    # ── Embed ──────────────────────────────────────────────────────────────────
    openai_key = os.getenv("OPENAI_API_KEY", "")
    if not openai_key:
        print("[ingest] ERROR: OPENAI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large")
    embedder = OpenAIEmbeddings(model=embedding_model, openai_api_key=openai_key)

    texts = [
        f"{row['Name']}. {row['sypnopsis']}"
        for _, row in df.iterrows()
    ]

    t0 = time.perf_counter()
    print(f"[ingest] Embedding {len(texts)} documents using {embedding_model}...")
    vectors = await embed_batches(texts, embedder, args.batch_size)
    print(f"[ingest] Embedding done in {time.perf_counter() - t0:.1f}s")

    # ── Connect ────────────────────────────────────────────────────────────────
    conninfo = (
        f"host={os.getenv('POSTGRES_HOST', 'localhost')} "
        f"port={os.getenv('POSTGRES_PORT', '5432')} "
        f"dbname={os.getenv('POSTGRES_DB', 'anime_rag')} "
        f"user={os.getenv('POSTGRES_USER', 'anime_rag')} "
        f"password={os.getenv('POSTGRES_PASSWORD', 'dev_password')}"
    )

    with psycopg.connect(conninfo) as conn:
        register_vector(conn)

        rows: list[tuple] = []
        for idx, (_, row) in enumerate(df.iterrows()):
            score = None if pd.isna(row["score"]) else float(row["score"])
            vec = np.array(vectors[idx], dtype=np.float32)
            rows.append((
                int(row["MAL_ID"]),
                str(row["Name"]),
                score,
                row["genres_arr"],
                str(row["sypnopsis"]),
                vec,
            ))

        print(f"[ingest] Upserting {len(rows)} rows...")
        t1 = time.perf_counter()
        upserted = upsert(conn, rows)
        print(f"[ingest] Upserted {upserted} rows in {time.perf_counter() - t1:.1f}s")

    print("[ingest] Done.")


if __name__ == "__main__":
    asyncio.run(main())

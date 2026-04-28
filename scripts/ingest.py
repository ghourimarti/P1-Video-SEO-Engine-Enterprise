"""Ingest anime CSV into pgvector.

Usage:
    python scripts/ingest.py --csv data/anime_with_synopsis.csv

Full implementation in M2. This stub validates the CSV and prints stats.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest anime data into pgvector")
    p.add_argument("--csv", required=True, type=Path, help="Path to CSV file")
    p.add_argument("--batch-size", default=32, type=int)
    p.add_argument("--dry-run", action="store_true", help="Validate only, no DB writes")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if not args.csv.exists():
        print(f"[ingest] CSV not found: {args.csv}", file=sys.stderr)
        sys.exit(1)

    df = pd.read_csv(args.csv)
    required_cols = {"MAL_ID", "Name", "sypnopsis"}
    missing = required_cols - set(df.columns)
    if missing:
        print(f"[ingest] Missing columns: {missing}", file=sys.stderr)
        sys.exit(1)

    df = df.dropna(subset=["sypnopsis"]).reset_index(drop=True)
    print(f"[ingest] {len(df)} rows after dropping null synopses.")
    print(f"[ingest] Columns: {list(df.columns)}")

    if args.dry_run:
        print("[ingest] Dry-run mode — no DB writes.")
        return

    # M2: connect to Postgres, embed in batches, upsert with pgvector
    print("[ingest] Full ingestion implemented in M2.")


if __name__ == "__main__":
    main()

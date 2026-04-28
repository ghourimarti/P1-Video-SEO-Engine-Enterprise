"""Reciprocal Rank Fusion (RRF) — merges multiple ranked doc lists.

RRF score for document d across N ranked lists:
    RRF(d) = Σ_i  1 / (k + rank_i(d))

k=60 is the standard constant from the original Cormack et al. 2009 paper.
Higher k reduces the influence of top-ranked documents; 60 is a good default.
"""

from __future__ import annotations


def reciprocal_rank_fusion(
    ranked_id_lists: list[list[int]],
    k: int = 60,
) -> dict[int, float]:
    """Compute RRF scores for all document IDs across ranked lists.

    Args:
        ranked_id_lists: Each inner list is a sequence of mal_id values
                         ordered from most to least relevant (rank 1 first).
        k: RRF smoothing constant (default 60).

    Returns:
        Dict mapping mal_id → RRF score (higher = more relevant).
    """
    scores: dict[int, float] = {}
    for ranked in ranked_id_lists:
        for rank, mal_id in enumerate(ranked, start=1):
            scores[mal_id] = scores.get(mal_id, 0.0) + 1.0 / (k + rank)
    return scores


def merge_results(
    doc_lists: list[list[dict]],
    rrf_scores: dict[int, float],
) -> list[dict]:
    """Merge doc dicts from multiple retrieval results, ordered by RRF score.

    Takes the union of all docs (deduped by mal_id) and sorts by RRF score.
    Sets doc['similarity'] to the RRF score for downstream use.
    """
    doc_map: dict[int, dict] = {}
    for docs in doc_lists:
        for d in docs:
            if d["mal_id"] not in doc_map:
                doc_map[d["mal_id"]] = d

    merged = list(doc_map.values())
    for d in merged:
        d["similarity"] = rrf_scores.get(d["mal_id"], 0.0)

    merged.sort(key=lambda d: d["similarity"], reverse=True)
    return merged

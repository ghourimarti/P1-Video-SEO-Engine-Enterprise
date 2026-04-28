"""Unit tests for RRF merge — pure Python, no infrastructure required."""

import pytest
from anime_rag.rag.retrieval.rrf import reciprocal_rank_fusion, merge_results


class TestReciprocalRankFusion:
    def test_single_list(self):
        scores = reciprocal_rank_fusion([[10, 20, 30]], k=60)
        # doc 10 has rank 1, highest score
        assert scores[10] > scores[20] > scores[30]

    def test_two_lists_boosted_overlap(self):
        # doc 99 appears first in both lists — should outscore all others
        scores = reciprocal_rank_fusion([[99, 1, 2], [99, 3, 4]], k=60)
        assert scores[99] > scores[1]
        assert scores[99] > scores[3]

    def test_doc_in_one_list_only(self):
        scores = reciprocal_rank_fusion([[1, 2], [3, 4]], k=60)
        # All docs appear only once — rank-1 docs from each list get 1/(60+1)
        assert scores[1] == scores[3]
        assert scores[2] == scores[4]

    def test_standard_k60_formula(self):
        scores = reciprocal_rank_fusion([[42]], k=60)
        assert abs(scores[42] - 1 / 61) < 1e-10

    def test_empty_lists(self):
        assert reciprocal_rank_fusion([[], []], k=60) == {}

    def test_union_of_lists(self):
        scores = reciprocal_rank_fusion([[1, 2], [2, 3]], k=60)
        assert set(scores.keys()) == {1, 2, 3}
        # doc 2 appears in both lists — should have higher score than 1 or 3
        assert scores[2] > scores[1]
        assert scores[2] > scores[3]


class TestMergeResults:
    def _doc(self, mal_id: int, similarity: float = 0.5) -> dict:
        return {
            "mal_id": mal_id,
            "name": f"Anime {mal_id}",
            "score": 8.0,
            "genres": ["Action"],
            "synopsis": "A great show.",
            "similarity": similarity,
            "cohere_score": None,
        }

    def test_deduplication(self):
        docs_a = [self._doc(1), self._doc(2)]
        docs_b = [self._doc(2), self._doc(3)]  # doc 2 appears in both
        scores = {1: 0.030, 2: 0.040, 3: 0.025}
        merged = merge_results([docs_a, docs_b], scores)
        mal_ids = [d["mal_id"] for d in merged]
        assert mal_ids.count(2) == 1  # deduplicated

    def test_sorted_by_rrf_score(self):
        docs_a = [self._doc(1), self._doc(2), self._doc(3)]
        scores = {1: 0.010, 2: 0.050, 3: 0.030}
        merged = merge_results([docs_a], scores)
        assert [d["mal_id"] for d in merged] == [2, 3, 1]

    def test_similarity_set_to_rrf_score(self):
        docs_a = [self._doc(5)]
        scores = {5: 0.0164}
        merged = merge_results([docs_a], scores)
        assert abs(merged[0]["similarity"] - 0.0164) < 1e-9

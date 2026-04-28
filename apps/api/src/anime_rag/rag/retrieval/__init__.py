"""Retrieval primitives — dense, BM25, RRF merge, Cohere reranker."""

from anime_rag.rag.retrieval.dense import retrieve_dense
from anime_rag.rag.retrieval.bm25 import retrieve_bm25
from anime_rag.rag.retrieval.rrf import reciprocal_rank_fusion
from anime_rag.rag.retrieval.reranker import cohere_rerank

__all__ = [
    "retrieve_dense",
    "retrieve_bm25",
    "reciprocal_rank_fusion",
    "cohere_rerank",
]

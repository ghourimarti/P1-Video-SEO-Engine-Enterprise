"""Unit tests for citation extraction in the generator node."""

from anime_rag.rag.nodes.generator import _extract_citations
from anime_rag.rag.state import AnimeDoc


def _doc(mal_id: int, name: str) -> AnimeDoc:
    return AnimeDoc(
        mal_id=mal_id,
        name=name,
        score=8.5,
        genres=["Action"],
        synopsis="A synopsis.",
        similarity=0.9,
        cohere_score=0.8,
    )


def test_exact_title_match():
    docs = [_doc(1, "Fullmetal Alchemist: Brotherhood")]
    answer = "I recommend **Fullmetal Alchemist: Brotherhood** for its themes."
    cited = _extract_citations(answer, docs)
    assert 1 in cited


def test_case_insensitive_match():
    docs = [_doc(2, "Death Note")]
    answer = "death note is perfect for thriller fans."
    assert 2 in _extract_citations(answer, docs)


def test_no_match():
    docs = [_doc(3, "Naruto")]
    answer = "I recommend Attack on Titan instead."
    assert 3 not in _extract_citations(answer, docs)


def test_multiple_citations():
    docs = [_doc(1, "Steins;Gate"), _doc(2, "Code Geass"), _doc(3, "Bleach")]
    answer = "steins;gate and Code Geass are both excellent choices."
    cited = _extract_citations(answer, docs)
    assert 1 in cited
    assert 2 in cited
    assert 3 not in cited


def test_empty_docs():
    assert _extract_citations("any answer", []) == set()


def test_empty_answer():
    docs = [_doc(1, "One Piece")]
    assert _extract_citations("", docs) == set()

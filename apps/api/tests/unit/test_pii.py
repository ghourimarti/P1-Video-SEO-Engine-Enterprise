"""Unit tests for PII scrubbing.

Presidio is an optional heavy dependency. Tests are skipped gracefully if it is
not installed so the CI suite does not require NLP models in the fast lane.
"""

import pytest

try:
    from presidio_analyzer import AnalyzerEngine  # noqa: F401
    PRESIDIO_AVAILABLE = True
except ImportError:
    PRESIDIO_AVAILABLE = False

skip_no_presidio = pytest.mark.skipif(
    not PRESIDIO_AVAILABLE, reason="presidio-analyzer not installed"
)

from anime_rag.core.pii import scrub


def test_scrub_no_pii():
    text = "I want a dark psychological thriller set in feudal Japan"
    cleaned, count = scrub(text)
    assert count == 0
    assert cleaned == text


@skip_no_presidio
def test_scrub_email():
    text = "My email is john.doe@example.com, recommend me isekai anime"
    cleaned, count = scrub(text)
    assert count >= 1
    assert "john.doe@example.com" not in cleaned
    assert "<EMAIL_ADDRESS>" in cleaned


@skip_no_presidio
def test_scrub_phone():
    text = "Call me at 555-867-5309 for anime suggestions"
    cleaned, count = scrub(text)
    assert count >= 1
    assert "555-867-5309" not in cleaned


@skip_no_presidio
def test_scrub_preserves_rest_of_text():
    text = "John Smith at john@example.com loves mecha anime"
    cleaned, count = scrub(text)
    assert "mecha anime" in cleaned
    assert count >= 1


def test_scrub_returns_tuple():
    result = scrub("some anime query")
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], str)
    assert isinstance(result[1], int)

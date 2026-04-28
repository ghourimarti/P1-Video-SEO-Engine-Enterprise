"""PII detection and anonymisation using Microsoft Presidio.

Scrubs PII from user queries before they hit the LLM and from LLM answers
before they are returned to the client. Operates lazily: the Presidio engine
is initialised on first call and reused thereafter (thread-safe singleton).

Anonymised format: <ENTITY_TYPE> e.g. <PERSON>, <EMAIL_ADDRESS>, <PHONE_NUMBER>.
"""

from __future__ import annotations

import structlog
from functools import lru_cache

log = structlog.get_logger(__name__)


@lru_cache(maxsize=1)
def _get_engines():
    """Return (AnalyzerEngine, AnonymizerEngine) — initialised once."""
    from presidio_analyzer import AnalyzerEngine
    from presidio_anonymizer import AnonymizerEngine

    analyzer   = AnalyzerEngine()
    anonymizer = AnonymizerEngine()
    log.info("presidio_engines_ready")
    return analyzer, anonymizer


_ENTITIES = [
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "IBAN_CODE",
    "IP_ADDRESS",
    "US_SSN",
    "US_PASSPORT",
    # LOCATION intentionally excluded: country/city names appear constantly in
    # anime queries (e.g. "set in feudal Japan") and are not PII.
]


def scrub(text: str, language: str = "en") -> tuple[str, int]:
    """Return (scrubbed_text, n_redactions).

    If Presidio is not installed this is a no-op — the original text is
    returned unchanged so the rest of the pipeline is unaffected.
    """
    try:
        analyzer, anonymizer = _get_engines()
    except ImportError:
        log.debug("presidio_unavailable", reason="not installed")
        return text, 0

    results = analyzer.analyze(text=text, entities=_ENTITIES, language=language)
    if not results:
        return text, 0

    from presidio_anonymizer.entities import OperatorConfig
    operators = {
        entity: OperatorConfig("replace", {"new_value": f"<{entity}>"})
        for entity in _ENTITIES
    }
    scrubbed = anonymizer.anonymize(
        text=text, analyzer_results=results, operators=operators
    ).text

    log.info("pii_scrubbed", n=len(results), entities=[r.entity_type for r in results])
    return scrubbed, len(results)

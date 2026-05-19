import pytest
from pydantic import ValidationError
from src.api.models import RAGRequest, RAGResponse, RAGStrategy, Source, IngestRequest


def test_rag_request_defaults():
    req = RAGRequest(query="What is the vacation policy?")
    assert req.strategy == RAGStrategy.hybrid
    assert req.top_k == 5
    assert req.namespace == "default"


def test_rag_request_valid_strategies():
    for s in ["naive", "advanced", "hybrid", "graph", "agentic", "fusion"]:
        req = RAGRequest(query="test query here", strategy=s)
        assert req.strategy == s


def test_rag_request_query_too_short():
    with pytest.raises(ValidationError):
        RAGRequest(query="Hi")


def test_rag_request_query_too_long():
    with pytest.raises(ValidationError):
        RAGRequest(query="x" * 2001)


def test_rag_request_top_k_bounds():
    with pytest.raises(ValidationError):
        RAGRequest(query="valid query here", top_k=0)
    with pytest.raises(ValidationError):
        RAGRequest(query="valid query here", top_k=21)


def test_rag_response_cached_default():
    resp = RAGResponse(
        answer="12 holidays",
        strategy="naive",
        sources=[],
        latency_ms=100.0,
        tokens_used=50,
    )
    assert resp.cached is False
    assert resp.confidence_score is None
    assert resp.unsupported_claims == []


def test_ingest_request_gcs_uri():
    req = IngestRequest(gcs_uri="gs://my-bucket/doc.pdf")
    assert req.namespace == "default"
    assert req.gcs_uri.startswith("gs://")

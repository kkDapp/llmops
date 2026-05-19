import pytest
from src.ingestion.chunkers import (
    FixedSizeChunker,
    RecursiveChunker,
    SemanticChunker,
    ChunkerFactory,
    Chunk,
)

DOC_ID = "test-doc-001"
PAGES = [
    "The quick brown fox jumps over the lazy dog. " * 20,
    "Section two begins here.\n\nThis is a new paragraph.\n\nAnd another one.",
]


def test_fixed_chunker_produces_chunks():
    chunks = FixedSizeChunker(chunk_size=20, overlap=5).chunk(PAGES, DOC_ID)
    assert len(chunks) > 0
    assert all(isinstance(c, Chunk) for c in chunks)


def test_fixed_chunker_unique_ids():
    chunks = FixedSizeChunker(chunk_size=20, overlap=5).chunk(PAGES, DOC_ID)
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))


def test_fixed_chunker_metadata_tag():
    chunks = FixedSizeChunker().chunk(PAGES, DOC_ID)
    assert all(c.metadata["chunker"] == "fixed" for c in chunks)


def test_recursive_chunker_produces_chunks():
    chunks = RecursiveChunker(chunk_size=200).chunk(PAGES, DOC_ID)
    assert len(chunks) > 0


def test_recursive_chunker_metadata_tag():
    chunks = RecursiveChunker().chunk(PAGES, DOC_ID)
    assert all(c.metadata["chunker"] == "recursive" for c in chunks)


def test_semantic_chunker_produces_chunks():
    chunks = SemanticChunker().chunk(PAGES, DOC_ID)
    assert len(chunks) > 0


def test_chunker_factory_returns_correct_type():
    assert isinstance(ChunkerFactory.get("fixed"), FixedSizeChunker)
    assert isinstance(ChunkerFactory.get("recursive"), RecursiveChunker)
    assert isinstance(ChunkerFactory.get("semantic"), SemanticChunker)


def test_chunker_factory_unknown_raises():
    with pytest.raises(ValueError, match="Unknown chunker"):
        ChunkerFactory.get("unknown")


def test_chunk_index_sequential():
    chunks = FixedSizeChunker(chunk_size=10, overlap=0).chunk(["word " * 50], DOC_ID)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))

import re
import uuid
from dataclasses import dataclass, field


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    text: str
    chunk_index: int
    metadata: dict = field(default_factory=dict)


class FixedSizeChunker:
    """Split by token count with overlap."""

    def __init__(self, chunk_size: int = 512, overlap: int = 64):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, pages: list[str], doc_id: str, metadata: dict = {}) -> list[Chunk]:
        full_text = " ".join(pages)
        words = full_text.split()
        chunks = []
        i = 0
        idx = 0
        while i < len(words):
            chunk_words = words[i : i + self.chunk_size]
            chunks.append(
                Chunk(
                    chunk_id=str(uuid.uuid4()),
                    document_id=doc_id,
                    text=" ".join(chunk_words),
                    chunk_index=idx,
                    metadata={**metadata, "chunker": "fixed"},
                )
            )
            i += self.chunk_size - self.overlap
            idx += 1
        return chunks


class RecursiveChunker:
    """Split by paragraph > sentence > word, respecting natural boundaries."""

    def __init__(self, chunk_size: int = 800, overlap: int = 100):
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.separators = ["\n\n", "\n", ". ", " "]

    def chunk(self, pages: list[str], doc_id: str, metadata: dict = {}) -> list[Chunk]:
        full_text = " ".join(pages)
        raw_chunks = self._split(full_text)
        return [
            Chunk(
                chunk_id=str(uuid.uuid4()),
                document_id=doc_id,
                text=c,
                chunk_index=i,
                metadata={**metadata, "chunker": "recursive"},
            )
            for i, c in enumerate(raw_chunks)
        ]

    def _split(self, text: str) -> list[str]:
        for sep in self.separators:
            if sep in text:
                parts = text.split(sep)
                merged = []
                current = ""
                for part in parts:
                    if len(current) + len(part) < self.chunk_size:
                        current += sep + part
                    else:
                        if current:
                            merged.append(current.strip())
                        current = part
                if current:
                    merged.append(current.strip())
                return [m for m in merged if m]
        return [text[i : i + self.chunk_size] for i in range(0, len(text), self.chunk_size - self.overlap)]


class SemanticChunker:
    """Split at semantic boundaries using sentence embeddings (cosine distance)."""

    def __init__(self, breakpoint_threshold: float = 0.3):
        self.threshold = breakpoint_threshold

    def chunk(self, pages: list[str], doc_id: str, metadata: dict = {}) -> list[Chunk]:
        sentences = []
        for page in pages:
            sentences.extend(re.split(r"(?<=[.!?])\s+", page))
        sentences = [s.strip() for s in sentences if len(s.strip()) > 20]

        # Group sentences (simplified — real impl uses cosine distance between embeddings)
        groups = []
        current = []
        for s in sentences:
            current.append(s)
            if len(" ".join(current)) > 600:
                groups.append(" ".join(current))
                current = current[-2:]  # carry last 2 sentences as overlap
        if current:
            groups.append(" ".join(current))

        return [
            Chunk(
                chunk_id=str(uuid.uuid4()),
                document_id=doc_id,
                text=g,
                chunk_index=i,
                metadata={**metadata, "chunker": "semantic"},
            )
            for i, g in enumerate(groups)
        ]


class ChunkerFactory:
    _registry = {
        "fixed": FixedSizeChunker,
        "recursive": RecursiveChunker,
        "semantic": SemanticChunker,
    }

    @classmethod
    def get(cls, strategy: str = "recursive"):
        cls_ = cls._registry.get(strategy)
        if not cls_:
            raise ValueError(f"Unknown chunker: {strategy}. Choose from {list(cls._registry)}")
        return cls_()

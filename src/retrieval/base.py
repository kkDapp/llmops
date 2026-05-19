from abc import ABC, abstractmethod
from src.api.models import Source


class BaseRetriever(ABC):
    def __init__(self, namespace: str = "default"):
        self.namespace = namespace

    @abstractmethod
    async def retrieve(self, query: str, top_k: int = 5) -> list[Source]:
        """Return ranked list of relevant chunks."""
        ...

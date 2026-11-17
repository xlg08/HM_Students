"""Structural retrieval contract consumed by the existing RAG pipeline."""
from typing import Protocol, Any
from langchain_core.documents import Document


class Retriever(Protocol):
    config: Any

    def hybrid_search_with_rerank(self, query: str, k: int | None = None,
                                 source_filter: str | None = None) -> list[Document]: ...

"""Embedding service and search index for spec documents."""

from __future__ import annotations

from .embed import EmbeddingAPIError, EmbeddingClient, EmbeddingUnavailableError
from .index import SearchIndex, SearchResult
from .indexer import flatten_sections, index_spec

__all__ = [
    "EmbeddingAPIError",
    "EmbeddingClient",
    "EmbeddingUnavailableError",
    "SearchIndex",
    "SearchResult",
    "flatten_sections",
    "index_spec",
]

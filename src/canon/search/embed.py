"""Vertex AI embedding service using google-genai SDK."""

from __future__ import annotations

import json
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

MODEL = "gemini-embedding-001"
DIMENSIONS = 1024
MAX_BATCH_SIZE = 250


class EmbeddingUnavailableError(Exception):
    """Raised when the embedding client has no credentials configured."""

    def __init__(self) -> None:
        super().__init__("GCP credentials not configured — embedding service unavailable")


class EmbeddingAPIError(Exception):
    """Raised when the Vertex AI API returns an error."""


class EmbeddingClient:
    """Wraps google-genai for Vertex AI embeddings."""

    def __init__(
        self,
        *,
        project: str = "",
        location: str = "us-central1",
        service_account_key: str = "",
    ) -> None:
        self._client = None

        if not project or not service_account_key:
            return

        try:
            parsed = json.loads(service_account_key)
            fd, path = tempfile.mkstemp(suffix=".json", prefix="gcp_sa_")
            with os.fdopen(fd, "w") as f:
                json.dump(parsed, f)

            os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
            os.environ["GOOGLE_CLOUD_PROJECT"] = project
            os.environ["GOOGLE_CLOUD_LOCATION"] = location
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path

            from google import genai

            self._client = genai.Client()
        except Exception:
            logger.warning("Failed to initialise embedding client", exc_info=True)

    @property
    def is_available(self) -> bool:
        """Whether the embedding client is configured and ready."""
        return self._client is not None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed texts for document storage (RETRIEVAL_DOCUMENT task type)."""
        if not self._client:
            raise EmbeddingUnavailableError

        from google.genai.types import EmbedContentConfig

        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), MAX_BATCH_SIZE):
            batch = texts[i : i + MAX_BATCH_SIZE]
            try:
                response = self._client.models.embed_content(
                    model=MODEL,
                    contents=batch,
                    config=EmbedContentConfig(
                        task_type="RETRIEVAL_DOCUMENT",
                        output_dimensionality=DIMENSIONS,
                    ),
                )
                all_embeddings.extend(e.values for e in response.embeddings)
            except Exception as exc:
                raise EmbeddingAPIError(str(exc)) from exc

        return all_embeddings

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query text (RETRIEVAL_QUERY task type)."""
        if not self._client:
            raise EmbeddingUnavailableError

        from google.genai.types import EmbedContentConfig

        try:
            response = self._client.models.embed_content(
                model=MODEL,
                contents=[text],
                config=EmbedContentConfig(
                    task_type="RETRIEVAL_QUERY",
                    output_dimensionality=DIMENSIONS,
                ),
            )
            return response.embeddings[0].values
        except Exception as exc:
            raise EmbeddingAPIError(str(exc)) from exc

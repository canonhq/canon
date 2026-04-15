"""Tests for the Vertex AI embedding client."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from canon.search.embed import (
    DIMENSIONS,
    MAX_BATCH_SIZE,
    MODEL,
    EmbeddingAPIError,
    EmbeddingClient,
    EmbeddingUnavailableError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeEmbedding:
    values: list[float]


@dataclass
class FakeEmbedResponse:
    embeddings: list[FakeEmbedding]


def _make_client_with_mock() -> tuple[EmbeddingClient, MagicMock]:
    """Create an EmbeddingClient with a mocked genai client injected."""
    client = EmbeddingClient()  # no creds → _client is None
    mock_genai = MagicMock()
    client._client = mock_genai  # bypass __init__ credential setup
    return client, mock_genai


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


class TestAvailability:
    def test_unavailable_without_credentials(self):
        client = EmbeddingClient()
        assert client.is_available is False

    def test_unavailable_with_empty_project(self):
        client = EmbeddingClient(project="", service_account_key='{"key": "val"}')
        assert client.is_available is False

    def test_unavailable_with_empty_key(self):
        client = EmbeddingClient(project="my-project", service_account_key="")
        assert client.is_available is False

    def test_available_with_mock_client(self):
        client, _ = _make_client_with_mock()
        assert client.is_available is True

    @patch.dict("os.environ", {}, clear=False)
    def test_init_with_valid_credentials(self):
        """Initialising with valid JSON credentials sets up the client."""
        mock_genai_module = MagicMock()
        mock_client_instance = MagicMock()
        mock_genai_module.Client.return_value = mock_client_instance

        with patch.dict("sys.modules", {"google": MagicMock(), "google.genai": mock_genai_module}):
            client = EmbeddingClient(
                project="test-project",
                location="us-east1",
                service_account_key='{"type": "service_account"}',
            )

        assert client.is_available is True

    def test_init_with_invalid_json_stays_unavailable(self):
        """Invalid JSON key should not crash, just stay unavailable."""
        client = EmbeddingClient(
            project="test-project",
            service_account_key="not-valid-json",
        )
        assert client.is_available is False


# ---------------------------------------------------------------------------
# embed_documents
# ---------------------------------------------------------------------------


class TestEmbedDocuments:
    def test_raises_when_unavailable(self):
        client = EmbeddingClient()
        with pytest.raises(EmbeddingUnavailableError):
            client.embed_documents(["hello"])

    def test_single_batch(self):
        client, mock_genai = _make_client_with_mock()
        mock_genai.models.embed_content.return_value = FakeEmbedResponse(
            embeddings=[FakeEmbedding(values=[0.1, 0.2])]
        )

        result = client.embed_documents(["text one"])

        assert result == [[0.1, 0.2]]
        mock_genai.models.embed_content.assert_called_once()
        call_kwargs = mock_genai.models.embed_content.call_args
        assert call_kwargs.kwargs["model"] == MODEL
        assert call_kwargs.kwargs["contents"] == ["text one"]

    def test_multi_batch(self):
        """Texts exceeding MAX_BATCH_SIZE are split into batches."""
        client, mock_genai = _make_client_with_mock()
        num_texts = MAX_BATCH_SIZE + 5

        def _side_effect(**kwargs):
            batch_size = len(kwargs["contents"])
            return FakeEmbedResponse(
                embeddings=[FakeEmbedding(values=[1.0]) for _ in range(batch_size)]
            )

        mock_genai.models.embed_content.side_effect = _side_effect

        result = client.embed_documents([f"text {i}" for i in range(num_texts)])

        assert len(result) == num_texts
        assert mock_genai.models.embed_content.call_count == 2

    def test_api_error_wrapped(self):
        client, mock_genai = _make_client_with_mock()
        mock_genai.models.embed_content.side_effect = RuntimeError("API quota exceeded")

        with pytest.raises(EmbeddingAPIError, match="API quota exceeded"):
            client.embed_documents(["text"])

    def test_uses_retrieval_document_task_type(self):
        client, mock_genai = _make_client_with_mock()
        mock_genai.models.embed_content.return_value = FakeEmbedResponse(
            embeddings=[FakeEmbedding(values=[0.5])]
        )

        # Need to mock the EmbedContentConfig import
        mock_config_class = MagicMock()
        with patch("canon.search.embed.EmbedContentConfig", mock_config_class, create=True):
            # The actual function imports EmbedContentConfig locally, so we
            # just verify the call args instead
            client.embed_documents(["test"])

        call_kwargs = mock_genai.models.embed_content.call_args.kwargs
        config = call_kwargs["config"]
        assert config.task_type == "RETRIEVAL_DOCUMENT"
        assert config.output_dimensionality == DIMENSIONS


# ---------------------------------------------------------------------------
# embed_query
# ---------------------------------------------------------------------------


class TestEmbedQuery:
    def test_raises_when_unavailable(self):
        client = EmbeddingClient()
        with pytest.raises(EmbeddingUnavailableError):
            client.embed_query("hello")

    def test_returns_single_embedding(self):
        client, mock_genai = _make_client_with_mock()
        mock_genai.models.embed_content.return_value = FakeEmbedResponse(
            embeddings=[FakeEmbedding(values=[0.3, 0.4, 0.5])]
        )

        result = client.embed_query("search query")

        assert result == [0.3, 0.4, 0.5]
        call_kwargs = mock_genai.models.embed_content.call_args.kwargs
        assert call_kwargs["contents"] == ["search query"]

    def test_api_error_wrapped(self):
        client, mock_genai = _make_client_with_mock()
        mock_genai.models.embed_content.side_effect = RuntimeError("network timeout")

        with pytest.raises(EmbeddingAPIError, match="network timeout"):
            client.embed_query("query")

    def test_uses_retrieval_query_task_type(self):
        client, mock_genai = _make_client_with_mock()
        mock_genai.models.embed_content.return_value = FakeEmbedResponse(
            embeddings=[FakeEmbedding(values=[0.1])]
        )

        client.embed_query("test")

        call_kwargs = mock_genai.models.embed_content.call_args.kwargs
        config = call_kwargs["config"]
        assert config.task_type == "RETRIEVAL_QUERY"
        assert config.output_dimensionality == DIMENSIONS

"""Tests for the AssemblyAI token endpoint.

Tests cover:
- successful temporary-token generation
- AssemblyAI failure (non-200 response)
- missing API key
- correct v3 token URL and request format
- API key not exposed except in the outbound server-side Authorization header
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app


def _clear_settings_cache():
    from backend.config import get_settings
    get_settings.cache_clear()


@pytest.fixture()
def assemblyai_client(monkeypatch) -> TestClient:
    """Client with AssemblyAI key configured - patches get_settings to return test settings."""
    settings = Settings(
        environment="test",
        use_mock_engines=True,
        log_level="WARNING",
        log_json=False,
        assemblyai_api_key="test-assemblyai-key-12345",
    )
    # Patch get_settings where it's used in the route
    monkeypatch.setattr("backend.routes.assemblyai.get_settings", lambda: settings)
    app = create_app(settings=settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def no_api_key_client(monkeypatch) -> TestClient:
    """Client without AssemblyAI API key configured - patches get_settings."""
    settings = Settings(
        environment="test",
        use_mock_engines=True,
        log_level="WARNING",
        log_json=False,
        assemblyai_api_key=None,
    )
    monkeypatch.setattr("backend.routes.assemblyai.get_settings", lambda: settings)
    app = create_app(settings=settings)
    with TestClient(app) as test_client:
        yield test_client


def create_mock_response(status_code=200, json_data=None, text=""):
    """Create a proper mock response for AsyncClient."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    if json_data is not None:
        mock_response.json = MagicMock(return_value=json_data)
    else:
        mock_response.json = MagicMock(return_value={})
    mock_response.text = text
    return mock_response


class TestAssemblyAITokenEndpoint:
    """Tests for POST /assemblyai/token."""

    @patch("backend.routes.assemblyai.httpx.AsyncClient")
    def test_token_success(self, mock_async_client_class, assemblyai_client):
        """Successful temporary token generation returns token and expires_in."""
        # Create mock response
        mock_response = create_mock_response(
            status_code=200,
            json_data={"token": "temp-token-abc123", "expires_in": 60}
        )
        
        # Set up the async context manager
        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_async_client_class.return_value.__aenter__.return_value = mock_client_instance

        response = assemblyai_client.post("/assemblyai/token")
        assert response.status_code == 200

        data = response.json()
        assert data["token"] == "temp-token-abc123"
        assert data["expires_in"] == 60

        # Verify the correct v3 endpoint was called with expires_in_seconds=60
        mock_client_instance.get.assert_called_once_with(
            "https://streaming.assemblyai.com/v3/token?expires_in_seconds=60",
            headers={"Authorization": "test-assemblyai-key-12345"},
        )

    @patch("backend.routes.assemblyai.httpx.AsyncClient")
    def test_token_uses_v3_endpoint_not_v2(self, mock_async_client_class, assemblyai_client):
        """Verify the v3 endpoint is used, not the deprecated v2 endpoint."""
        mock_response = create_mock_response(
            status_code=200,
            json_data={"token": "temp-token-xyz", "expires_in": 60}
        )
        
        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_async_client_class.return_value.__aenter__.return_value = mock_client_instance

        response = assemblyai_client.post("/assemblyai/token")
        assert response.status_code == 200

        # Ensure v3 endpoint was called
        call_args = mock_client_instance.get.call_args[0][0]
        assert "streaming.assemblyai.com/v3/token" in call_args
        assert "api.assemblyai.com/v2/realtime/token" not in call_args

    @patch("backend.routes.assemblyai.httpx.AsyncClient")
    def test_token_passes_authorization_header(self, mock_async_client_class, assemblyai_client):
        """API key is sent in Authorization header to AssemblyAI, not exposed to client."""
        mock_response = create_mock_response(
            status_code=200,
            json_data={"token": "temp-token", "expires_in": 60}
        )
        
        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_async_client_class.return_value.__aenter__.return_value = mock_client_instance

        response = assemblyai_client.post("/assemblyai/token")
        assert response.status_code == 200

        # Check Authorization header was passed to AssemblyAI
        call_kwargs = mock_client_instance.get.call_args[1]
        assert "headers" in call_kwargs
        assert call_kwargs["headers"]["Authorization"] == "test-assemblyai-key-12345"

        # Check response does NOT contain the server-side API key
        response_data = response.json()
        assert "assemblyai-key" not in str(response_data).lower()
        assert "Authorization" not in str(response_data)

    @patch("backend.routes.assemblyai.httpx.AsyncClient")
    def test_token_assemblyai_failure_401(self, mock_async_client_class, assemblyai_client):
        """AssemblyAI 401 returns 502 with ASSEMBLYAI_TOKEN_FAILED code."""
        mock_response = create_mock_response(
            status_code=401,
            text="Unauthorized: Invalid API key"
        )
        
        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_async_client_class.return_value.__aenter__.return_value = mock_client_instance

        response = assemblyai_client.post("/assemblyai/token")
        assert response.status_code == 502

        data = response.json()
        assert data["detail"]["code"] == "ASSEMBLYAI_TOKEN_FAILED"
        assert "Failed to generate AssemblyAI streaming token" in data["detail"]["message"]

    @patch("backend.routes.assemblyai.httpx.AsyncClient")
    def test_token_assemblyai_failure_500(self, mock_async_client_class, assemblyai_client):
        """AssemblyAI 500 returns 502 with ASSEMBLYAI_TOKEN_FAILED code."""
        mock_response = create_mock_response(
            status_code=500,
            text="Internal Server Error"
        )
        
        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_async_client_class.return_value.__aenter__.return_value = mock_client_instance

        response = assemblyai_client.post("/assemblyai/token")
        assert response.status_code == 502

        data = response.json()
        assert data["detail"]["code"] == "ASSEMBLYAI_TOKEN_FAILED"

    def test_token_missing_api_key_returns_503(self, no_api_key_client):
        """Missing AssemblyAI API key returns 503 with ASSEMBLYAI_NOT_CONFIGURED code."""
        response = no_api_key_client.post("/assemblyai/token")
        assert response.status_code == 503

        data = response.json()
        assert data["detail"]["code"] == "ASSEMBLYAI_NOT_CONFIGURED"
        assert "AssemblyAI API key is not configured" in data["detail"]["message"]

    def test_token_empty_api_key_returns_503(self):
        """Empty AssemblyAI API key returns 503."""
        _clear_settings_cache()
        os.environ["ASSEMBLYAI_API_KEY"] = ""
        settings = Settings(
            environment="test",
            use_mock_engines=True,
            log_level="WARNING",
            log_json=False,
        )
        with TestClient(create_app(settings=settings)) as client:
            response = client.post("/assemblyai/token")
            assert response.status_code == 503
            data = response.json()
            assert data["detail"]["code"] == "ASSEMBLYAI_NOT_CONFIGURED"
        _clear_settings_cache()
        os.environ["ASSEMBLYAI_API_KEY"] = ""

    @patch("backend.routes.assemblyai.httpx.AsyncClient")
    def test_token_returns_only_token_and_expires_in(self, mock_async_client_class, assemblyai_client):
        """Response contains only token and expires_in, no extra fields."""
        mock_response = create_mock_response(
            status_code=200,
            json_data={
                "token": "temp-token-only",
                "expires_in": 60,
                "extra_field": "should-not-be-in-response",
            }
        )
        
        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_async_client_class.return_value.__aenter__.return_value = mock_client_instance

        response = assemblyai_client.post("/assemblyai/token")
        assert response.status_code == 200

        data = response.json()
        assert set(data.keys()) == {"token", "expires_in"}
        assert data["token"] == "temp-token-only"
        assert data["expires_in"] == 60

    @patch("backend.routes.assemblyai.httpx.AsyncClient")
    def test_token_expires_in_seconds_60(self, mock_async_client_class, assemblyai_client):
        """Request uses expires_in_seconds=60 query parameter."""
        mock_response = create_mock_response(
            status_code=200,
            json_data={"token": "temp-token", "expires_in": 60}
        )
        
        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_async_client_class.return_value.__aenter__.return_value = mock_client_instance

        assemblyai_client.post("/assemblyai/token")

        # Verify the URL includes expires_in_seconds=60
        call_args = mock_client_instance.get.call_args
        call_url = call_args[0][0]
        assert "expires_in_seconds=60" in call_url
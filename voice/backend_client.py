import os
import asyncio
from typing import Optional
import httpx
from voice.events import TranscriptEvent


class BackendClient:
    """HTTP client for communicating with the backend API."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:8000")
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, connect=5.0),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
        return self._client

    async def close(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def start_session(self) -> str:
        """Create a new session and return the sessionId."""
        client = await self._get_client()
        response = await client.post(
            f"{self.base_url}/session/start",
            json={"startMockPipeline": False},
        )
        response.raise_for_status()
        data = response.json()
        return data["sessionId"]

    async def stop_session(self, session_id: str) -> None:
        """Stop a running session."""
        client = await self._get_client()
        response = await client.post(
            f"{self.base_url}/session/stop",
            params={"sessionId": session_id},
        )
        response.raise_for_status()

    async def post_transcript(self, session_id: str, event: TranscriptEvent) -> bool:
        """Post a transcript event to the backend."""
        client = await self._get_client()
        payload = dict(event)
        payload["sessionId"] = session_id
        response = await client.post(
            f"{self.base_url}/events/transcript",
            json=payload,
        )
        response.raise_for_status()
        return True
"""HTTP client for the backend API.

Supports two modes:

- **create** the default. The backend mints a fresh ``sessionId`` via
  ``POST /session/start`` and the voice module owns it.
- **join** an existing ``sessionId`` supplied by another client, typically the
  browser dashboard. No session is created, and the browser and the voice module
  then share one session, so live speech reaches the dashboard's WebSocket.

Joining adds no backend endpoint and changes no event contract: the voice module
simply addresses events to a ``sessionId`` that already exists. An invalid id is
still rejected by the backend with its existing ``404 SESSION_NOT_FOUND``, and
this client never falls back to creating a replacement session.
"""

import os
from typing import Optional

import httpx

from voice.events import TranscriptEvent


class BackendSessionNotFound(Exception):
    """Raised when a supplied sessionId does not exist on the backend."""


class BackendClient:
    """HTTP client for communicating with the backend API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        self.base_url = base_url or os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:8000")
        #: When set, this client joins that session instead of creating one.
        self._joined_session_id: Optional[str] = session_id or None
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def joined_session_id(self) -> Optional[str]:
        """The externally supplied sessionId, if this client is joining one."""
        return self._joined_session_id

    @property
    def owns_session(self) -> bool:
        """True when this client created the session and may stop it."""
        return self._joined_session_id is None

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

    async def verify_session(self, session_id: str) -> None:
        """Confirm a session exists and is still accepting events.

        Failing here is deliberate: it turns a typo, or a session that has
        already been stopped, into an immediate, clear message instead of a
        stream that silently goes nowhere. A stopped session still answers
        ``GET`` with ``200`` and ``status="stopped"``, so the status is checked
        as well as the status code.
        """
        client = await self._get_client()
        try:
            response = await client.get(f"{self.base_url}/session/{session_id}")
        except httpx.HTTPError as exc:
            raise BackendSessionNotFound(
                f"Cannot reach the backend at {self.base_url}: {exc}"
            ) from exc

        if response.status_code == httpx.codes.NOT_FOUND:
            raise BackendSessionNotFound(
                f"No session '{session_id}' on the backend. Start a session in the "
                f"browser, then pass its id via --session-id or BACKEND_SESSION_ID."
            )
        if response.status_code != httpx.codes.OK:
            raise BackendSessionNotFound(
                f"Backend rejected session '{session_id}' with HTTP {response.status_code}."
            )

        status = str(response.json().get("status", ""))
        if status == "stopped":
            raise BackendSessionNotFound(
                f"Session '{session_id}' has been stopped and will not accept events. "
                f"Start a new session and pass its id."
            )

    async def start_session(self) -> str:
        """Return the sessionId this client should use.

        Creates a new session only when none was supplied. When joining, the
        supplied id is returned as-is and no request is made, so the browser and
        the voice module necessarily agree on one session.
        """
        if self._joined_session_id is not None:
            return self._joined_session_id

        client = await self._get_client()
        response = await client.post(
            f"{self.base_url}/session/start",
            json={"startMockPipeline": False},
        )
        response.raise_for_status()
        data = response.json()
        return data["sessionId"]

    async def stop_session(self, session_id: str) -> None:
        """Stop a running session. Only valid for a session this client created."""
        client = await self._get_client()
        response = await client.post(
            f"{self.base_url}/session/stop",
            params={"sessionId": session_id},
        )
        response.raise_for_status()

    async def post_transcript(self, session_id: str, event: TranscriptEvent) -> bool:
        """Post a transcript event to the backend.

        Raises ``httpx.HTTPStatusError`` if the session is gone, so a stopped or
        unknown session surfaces rather than being papered over with a new one.
        """
        client = await self._get_client()
        payload = dict(event)
        payload["sessionId"] = session_id
        response = await client.post(
            f"{self.base_url}/events/transcript",
            json=payload,
        )
        response.raise_for_status()
        return True

"""WebSocket connection registry and broadcast fan-out.

The backend is the WebSocket **server**. The frontend (Rupan) and any
non-browser producers connect to ``/ws/session/{session_id}`` and receive
``transcript``, ``claim``, ``verification``, ``error`` and ``session``
events.

A single session may have several clients (e.g. two judges watching the same
demo). Every send is individually guarded so one dead socket can never abort
a broadcast to the remaining clients or propagate an exception into the
request handler.
"""

import asyncio
from typing import Any, Dict, Iterable, Optional, Set

from starlette.websockets import WebSocket, WebSocketState

from backend.logging_config import (
    FRONTEND_BROADCAST,
    WS_CLIENT_CONNECTED,
    WS_CLIENT_DISCONNECTED,
    get_logger,
    log_trace,
)
from backend.schemas import AnyEvent

logger = get_logger("websocket_manager")


class WebSocketManager:
    """Tracks live WebSocket clients per session and fans out events."""

    def __init__(self) -> None:
        # sessionId -> set of sockets. A socket may only belong to one session,
        # so the mapping is one-directional and unambiguous.
        self._connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    # -- connection lifecycle --------------------------------------------
    async def connect(
        self, websocket: WebSocket, session_id: str, send_session_event: bool = True
    ) -> None:
        """Accept a socket and register it under ``session_id``."""
        await websocket.accept()
        async with self._lock:
            self._connections.setdefault(session_id, set()).add(websocket)
        log_trace(
            WS_CLIENT_CONNECTED,
            sessionId=session_id,
            clientCount=self.connection_count(session_id),
        )

    async def disconnect(self, websocket: WebSocket, session_id: str) -> None:
        """Remove a socket from the registry, tolerating a double disconnect."""
        async with self._lock:
            sockets = self._connections.get(session_id)
            if sockets is not None:
                sockets.discard(websocket)
                if not sockets:
                    self._connections.pop(session_id, None)
        log_trace(
            WS_CLIENT_DISCONNECTED,
            sessionId=session_id,
            clientCount=self.connection_count(session_id),
        )

    async def disconnect_all(self, session_id: str) -> int:
        """Close and forget every socket of a session. Returns the count closed."""
        async with self._lock:
            sockets = self._connections.pop(session_id, set())
        for socket in list(sockets):
            await self._safe_close(socket)
        return len(sockets)

    # -- sending ----------------------------------------------------------
    async def send_to_client(
        self, websocket: WebSocket, event: AnyEvent
    ) -> bool:
        """Send one event to one client. Returns ``False`` if the send failed."""
        return await self._send(websocket, event)

    async def send_to_session(
        self, session_id: str, event: AnyEvent
    ) -> int:
        """Send one event to every client of a session.

        Returns the number of clients that received it. Dead sockets are
        dropped and never raise.
        """
        async with self._lock:
            sockets = list(self._connections.get(session_id, ()))

        delivered = 0
        dead: List[WebSocket] = []
        for socket in sockets:
            if await self._send(socket, event):
                delivered += 1
            else:
                dead.append(socket)

        if dead:
            async with self._lock:
                registered = self._connections.get(session_id)
                if registered is not None:
                    for socket in dead:
                        registered.discard(socket)
                    if not registered:
                        self._connections.pop(session_id, None)
            log_trace(
                WS_CLIENT_DISCONNECTED,
                sessionId=session_id,
                reason="send_failed",
                clientCount=self.connection_count(session_id),
            )

        log_trace(
            FRONTEND_BROADCAST,
            sessionId=session_id,
            eventType=event.type,
            delivered=delivered,
            dropped=len(dead),
        )
        return delivered

    async def broadcast(
        self, session_id: str, events: Iterable[Any]
    ) -> int:
        """Send several events in order to a session. Returns total deliveries."""
        total = 0
        for event in events:
            total += await self.send_to_session(session_id, event)
        return total

    # -- introspection ----------------------------------------------------
    def connection_count(self, session_id: Optional[str] = None) -> int:
        """Number of live clients, for one session or across all sessions."""
        if session_id is not None:
            return len(self._connections.get(session_id, ()))
        return sum(len(sockets) for sockets in self._connections.values())

    async def clear(self) -> None:
        """Forget every socket. Intended for tests."""
        async with self._lock:
            self._connections.clear()

    # -- internals --------------------------------------------------------
    async def _send(self, websocket: WebSocket, event: AnyEvent) -> bool:
        """Send to one socket, converting any failure into ``False``."""
        if websocket.client_state is not WebSocketState.CONNECTED:
            return False
        try:
            await websocket.send_json(event.to_wire())
            return True
        except Exception as exc:  # noqa: BLE001 - a dead peer must not propagate
            logger.debug(
                "WebSocket send failed; dropping client: %s",
                type(exc).__name__,
                extra={"trace": "WS_SEND_FAILED", "errorType": type(exc).__name__},
            )
            return False

    @staticmethod
    async def _safe_close(websocket: WebSocket) -> None:
        try:
            await websocket.close()
        except Exception as exc:  # noqa: BLE001 - closing must never raise
            logger.debug(
                "WebSocket close failed: %s",
                type(exc).__name__,
                extra={"trace": "WS_CLOSE_FAILED", "errorType": type(exc).__name__},
            )

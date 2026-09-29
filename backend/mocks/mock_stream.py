"""Deterministic mock engines and mock stream for local development and tests.

The mock pipeline runs with **no** AssemblyAI key, **no** LLM key and **no**
search key. It exists so the backend can be developed, demoed and tested
standalone, exactly as the team plan requires.

Reference flow (matches the contracts in the project documentation)::

    "India won the 2011 Cricket World Cup."   (Speaker 1, t=12.4)
      -> claim_001      claimType=historical_fact
      -> TRUE           "India defeated Sri Lanka in the 2011 final."
"""

import asyncio
import re
from typing import Dict, List, Optional, Sequence

from backend.adapters.claim_engine import ClaimEngine
from backend.adapters.verification import VerificationEngine
from backend.logging_config import get_logger
from backend.schemas import ClaimEvent, TranscriptEvent, Verdict, VerificationEvent
from backend.session_manager import SessionManager

logger = get_logger("mocks")

#: Canonical demonstration sentence used by the mock pipeline and the tests.
REFERENCE_CLAIM_TEXT = "India won the 2011 Cricket World Cup."
REFERENCE_SPEAKER = "Speaker 1"
REFERENCE_TIMESTAMP = 12.4

#: Verdict, reason and source used when the mock has no rule for a claim. The
#: offline mock cannot invent evidence, so an unknown claim is honestly reported
#: as UNVERIFIABLE rather than raised as an engine failure.
NO_RULE_VERDICT = Verdict.UNVERIFIABLE
NO_RULE_REASON = "The offline mock has no evidence rule for this claim."
NO_RULE_SOURCE = "https://example.com/no-evidence"

#: Transcript segments replayed by :func:`stream_mock_transcripts`.
MOCK_TRANSCRIPT_SCRIPT: List[Dict[str, object]] = [
    {
        "speaker": "Speaker 1",
        "text": "Good evening, and welcome to the show.",
        "timestamp": 1.2,
        "isFinal": True,
    },
    {
        "speaker": "Speaker 1",
        "text": REFERENCE_CLAIM_TEXT,
        "timestamp": REFERENCE_TIMESTAMP,
        "isFinal": True,
    },
    {
        "speaker": "Speaker 2",
        "text": "Mount Everest is the highest mountain peak in Africa.",
        "timestamp": 31.8,
        "isFinal": True,
    },
]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower().rstrip(".!?")


class MockClaimEngine(ClaimEngine):
    """Rule-based claim extraction with no model call.

    Known sentences produce a claim; anything else produces none, so greeting
    and filler segments correctly yield no claim.
    """

    name = "mock-claim-engine"

    def __init__(self, claim_type: str = "historical_fact") -> None:
        self._claim_type = claim_type
        self._counter = 0
        self._rules: Dict[str, str] = {
            _normalize(REFERENCE_CLAIM_TEXT): REFERENCE_CLAIM_TEXT,
            _normalize("Mount Everest is the highest mountain peak in Africa."): (
                "Mount Everest is the highest mountain peak in Africa."
            ),
        }

    def register(self, spoken_text: str, claim_text: str, claim_type: Optional[str] = None) -> None:
        """Teach the mock a new spoken-text -> claim-text mapping."""
        self._rules[_normalize(spoken_text)] = claim_text
        if claim_type is not None:
            self._claim_type = claim_type

    def next_claim_id(self) -> str:
        """Mint the next deterministic claim id (``claim_001``, ...)."""
        self._counter += 1
        return f"claim_{self._counter:03d}"

    async def extract_claims(self, transcript: TranscriptEvent) -> List[ClaimEvent]:
        if not transcript.isFinal:
            return []
        claim_text = self._rules.get(_normalize(transcript.text))
        if claim_text is None:
            return []
        return [
            ClaimEvent(
                type="claim",
                claimId=self.next_claim_id(),
                sessionId=transcript.sessionId,
                speaker=transcript.speaker or REFERENCE_SPEAKER,
                timestamp=transcript.timestamp,
                claim=claim_text,
                claimType=self._claim_type,
            )
        ]


class MockVerificationEngine(VerificationEngine):
    """Rule-based verification with no search call.

    Returns the documented ``TRUE`` verdict for the reference claim and
    ``UNVERIFIABLE`` for anything it has no rule for. It never fabricates a
    source: the fallback reason and ``source`` say so explicitly. An unknown
    claim is therefore a real verdict, not an engine failure.
    """

    name = "mock-verification-engine"

    def __init__(self) -> None:
        self._rules: Dict[str, Dict[str, object]] = {
            _normalize(REFERENCE_CLAIM_TEXT): {
                "verdict": Verdict.TRUE,
                "reason": "India defeated Sri Lanka in the 2011 final.",
                "source": "https://example.com/source",
            },
            _normalize("Mount Everest is the highest mountain peak in Africa."): {
                "verdict": Verdict.FALSE,
                "reason": "Mount Everest is in Asia; Kilimanjaro is Africa's highest peak.",
                "source": "https://example.com/source",
            },
        }

    def register(
        self,
        claim_text: str,
        verdict: Verdict,
        reason: str,
        source: str,
    ) -> None:
        """Teach the mock a new claim -> verdict mapping."""
        self._rules[_normalize(claim_text)] = {
            "verdict": verdict,
            "reason": reason,
            "source": source,
        }

    async def verify(self, claim: ClaimEvent) -> VerificationEvent:
        rule = self._rules.get(_normalize(claim.claim))
        return VerificationEvent(
            type="verification",
            claimId=claim.claimId,
            sessionId=claim.sessionId,
            speaker=claim.speaker,
            timestamp=claim.timestamp,
            verdict=rule["verdict"] if rule else NO_RULE_VERDICT,
            reason=rule["reason"] if rule else NO_RULE_REASON,
            source=rule["source"] if rule else NO_RULE_SOURCE,
        )


def build_mock_transcript(
    session_id: str, index: int = 1
) -> TranscriptEvent:
    """Build the ``index``-th scripted transcript event for a session."""
    segments = MOCK_TRANSCRIPT_SCRIPT
    segment = segments[min(index, len(segments)) - 1]
    return TranscriptEvent(
        type="transcript",
        sessionId=session_id,
        speaker=str(segment["speaker"]),
        text=str(segment["text"]),
        timestamp=float(segment["timestamp"]),
        isFinal=bool(segment["isFinal"]),
    )


def build_mock_transcripts(
    session_id: str, count: Optional[int] = None
) -> List[TranscriptEvent]:
    """Build the scripted transcript events for a session.

    Args:
        session_id: Session the events belong to.
        count: How many segments to build. Defaults to the whole script.
    """
    total = len(MOCK_TRANSCRIPT_SCRIPT) if count is None else count
    return [build_mock_transcript(session_id, i + 1) for i in range(total)]


async def _await_first_client(
    websocket_manager,
    session_id: str,
    timeout: float,
    poll_interval: float = 0.025,
) -> bool:
    """Wait until a WebSocket client attaches, up to ``timeout`` seconds.

    The browser learns its ``sessionId`` from the ``POST /session/start``
    response and can only open its socket afterwards, so a pipeline that starts
    emitting immediately races that handshake and loses its first events. This
    closes the race by holding the first event until a viewer is listening.

    Returns ``True`` once a client is attached, ``False`` on timeout or if the
    session ends first. A timeout is not an error: the stream still runs, so a
    headless test that never opens a socket is unaffected.
    """
    if websocket_manager is None or timeout <= 0:
        return True

    waited = 0.0
    while waited < timeout:
        if websocket_manager.connection_count(session_id) > 0:
            logger.info(
                "Mock pipeline has a viewer for %s after %.3fs",
                session_id,
                waited,
                extra={"trace": "MOCK_PIPELINE_VIEWER", "sessionId": session_id},
            )
            return True
        await asyncio.sleep(poll_interval)
        waited += poll_interval

    logger.info(
        "Mock pipeline started without a viewer for %s after %.1fs; events may be missed",
        session_id,
        timeout,
        extra={"trace": "MOCK_PIPELINE_NO_VIEWER", "sessionId": session_id},
    )
    return False


async def stream_mock_transcripts(
    router,
    session_manager: SessionManager,
    session_id: str,
    delay: float = 0.35,
    websocket_manager=None,
    wait_for_client_timeout: float = 5.0,
) -> None:
    """Push the scripted transcript script through the router with pacing.

    Used by ``POST /session/start`` with ``startMockPipeline=true`` so a
    frontend sees the full pipeline live. The stream belongs to the session:
    it stops emitting as soon as the session is gone or stopped, and it
    re-raises :class:`asyncio.CancelledError` so the owner can await a clean
    cancellation instead of a task destroyed while pending.

    When ``websocket_manager`` is supplied the first event is held until a
    client attaches (or ``wait_for_client_timeout`` elapses), so a browser that
    opens its socket a moment after ``/session/start`` still receives the whole
    script. No event contract changes; only the emission timing does.
    """
    try:
        if websocket_manager is not None:
            await _await_first_client(websocket_manager, session_id, wait_for_client_timeout)

        for index in range(len(MOCK_TRANSCRIPT_SCRIPT)):
            if delay:
                await asyncio.sleep(delay)
            session = await session_manager.get(session_id)
            if session is None or not session.is_active():
                logger.info(
                    "Mock pipeline stopped for %s",
                    session_id,
                    extra={"trace": "MOCK_PIPELINE_STOPPED", "sessionId": session_id},
                )
                return
            await router.handle_transcript(build_mock_transcript(session_id, index + 1))
    except asyncio.CancelledError:
        logger.info(
            "Mock pipeline cancelled for %s",
            session_id,
            extra={"trace": "MOCK_PIPELINE_CANCELLED", "sessionId": session_id},
        )
        raise

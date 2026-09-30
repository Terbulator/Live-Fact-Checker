"""Claim engine adapter boundary and implementations.

The backend never runs a claim-extraction model directly in router logic. 
It defines the interface Atif's claim intelligence must satisfy and hands it a validated
:class:`~backend.schemas.TranscriptEvent`.
"""

import json
import logging
import asyncio
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional, Sequence, Dict, Any

import httpx

from backend.config import get_settings
from backend.schemas import ClaimEvent, TranscriptEvent

logger = logging.getLogger(__name__)

#: How many times a 429 is retried after the initial attempt. Bounded on
#: purpose: a live demo must fail visibly rather than stall on a wedged gateway.
GATEWAY_MAX_RETRIES = 2

#: First backoff step when the gateway sends no usable ``Retry-After``.
#: Doubles per attempt: 0.5s then 1.0s for GATEWAY_MAX_RETRIES = 2.
GATEWAY_RETRY_BASE_SECONDS = 0.5

#: Ceiling for any single wait, including a ``Retry-After`` the gateway asks
#: for. Without this a header like ``Retry-After: 3600`` would park a live
#: transcript request for an hour.
GATEWAY_RETRY_MAX_SECONDS = 8.0

#: Punctuation and symbols are the only characters dropped when normalizing a
#: transcript for pre-gateway deduplication. Letters and digits are preserved,
#: so genuinely different wording never collapses into a duplicate.
_TRANSCRIPT_NOISE = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+", re.UNICODE)


class ClaimEngineError(RuntimeError):
    """Raised when claim extraction fails."""


class LLMRateLimitError(ClaimEngineError):
    """The LLM Gateway answered 429 and the bounded retries ran out.

    Subclasses :class:`ClaimEngineError` so existing generic handling still
    applies, while :class:`~backend.router.EventRouter` can catch it first and
    report ``LLM_RATE_LIMITED`` instead of ``CLAIM_EXTRACTION_FAILED``.

    Carries no credential: only the attempt count, the status and the wait the
    gateway asked for, all of which are safe to put in an ``ErrorEvent.detail``.
    """

    def __init__(
        self,
        message: str,
        *,
        attempts: int,
        status_code: int = 429,
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.status_code = status_code
        self.retry_after = retry_after


def normalize_transcript(text: str) -> str:
    """Return a comparison key for a transcript segment.

    Case, punctuation and whitespace are noise when deciding whether the same
    thing was already sent to the gateway, so they are folded away. Everything
    that carries meaning — the words and the numbers — is kept, so two
    different sentences never collapse into one key.
    """
    stripped = text.strip()
    key = _WHITESPACE.sub(" ", _TRANSCRIPT_NOISE.sub(" ", stripped.lower())).strip()
    # Punctuation-only text normalizes to nothing; fall back to the literal so
    # such segments cannot all collide on a single empty key.
    return key or stripped


class ClaimEngine(ABC):
    """Interface between the backend and the claim intelligence module."""

    name: str = "claim-engine"

    @abstractmethod
    async def extract_claims(
        self, transcript: TranscriptEvent
    ) -> List[ClaimEvent]:
        """Return the checkable claims contained in one transcript event."""
        raise NotImplementedError


class UnavailableClaimEngine(ClaimEngine):
    """Placeholder used when no claim engine is wired in yet."""

    name = "unavailable-claim-engine"

    async def extract_claims(
        self, transcript: TranscriptEvent
    ) -> List[ClaimEvent]:
        raise ClaimEngineError(
            "No claim engine is configured. Set USE_MOCK_ENGINES=true for the "
            "mock pipeline, or integrate Atif's claim intelligence module."
        )


class StaticClaimEngine(ClaimEngine):
    """Test double that maps transcripts to preconfigured claims."""

    name = "static-claim-engine"

    def __init__(self, claims: Optional[Sequence[ClaimEvent]] = None) -> None:
        self._claims = list(claims or [])

    async def extract_claims(
        self, transcript: TranscriptEvent
    ) -> List[ClaimEvent]:
        return [
            claim.model_copy(
                update={
                    "sessionId": transcript.sessionId,
                    "speaker": transcript.speaker or claim.speaker,
                    "timestamp": transcript.timestamp,
                }
            )
            for claim in self._claims
        ]


class LLMClaimEngine(ClaimEngine):
    """Concrete claim engine implementation using an OpenAI-compatible LLM Gateway.

    Configuration is read from the application settings (environment variables):
    - LLM_GATEWAY_API_KEY: API key for the LLM Gateway
    - LLM_GATEWAY_BASE_URL: Base URL for the OpenAI-compatible API
    - LLM_GATEWAY_MODEL: Model name to use
    """

    name = "llm-claim-engine"

    def __init__(self, settings=None, strict: bool = False) -> None:
        # Session-scoped state. Both are keyed by session id: two concurrent
        # sessions must never share deduplication state or a claim counter, or
        # one session's claim would suppress another's and ids would collide.
        self.seen_claims: Dict[str, set] = {}
        self.claim_counter: Dict[str, int] = {}
        # Normalized transcript keys already handed to the gateway, per session.
        # Checked before the request so a repeated segment costs nothing.
        self.seen_transcripts: Dict[str, set] = {}
        # One in-flight gateway request per session. Concurrent finals for one
        # session queue on their own gate, so sessions never contend with each
        # other and no global queue is introduced.
        self._session_gates: Dict[str, asyncio.Semaphore] = {}
        # In strict mode the engine refuses to answer from the offline
        # rule-based extractor and reports a clear error instead. The router
        # turns that into a structured CLAIM_EXTRACTION_FAILED event. Set by
        # the production wiring; left off for offline tests and demos.
        self.strict = strict
        self._settings = settings or get_settings()

        # Build the API key from settings (SecretStr -> str)
        api_key_obj = self._settings.llm_gateway_api_key
        self.api_key = api_key_obj.get_secret_value() if api_key_obj else None

        # Use configurable base URL and model
        self.base_url = self._settings.llm_gateway_base_url.rstrip("/")
        self.model = self._settings.llm_gateway_model

    def is_configured(self) -> bool:
        """Check if the engine has a valid API key configured."""
        return bool(self.api_key and self.api_key != "your_key_here")

    def configuration_error(self) -> Optional[str]:
        """Return why the LLM Gateway is unusable, or ``None`` when it is usable.

        The message names the missing variable but never its value, so it is
        safe to log and to place in an ``ErrorEvent.detail``.
        """
        if not self.is_configured():
            return (
                "LLM_GATEWAY_API_KEY is not configured, so LLMClaimEngine cannot "
                f"call {self.base_url}/chat/completions. Set it server-side, or "
                "set USE_MOCK_ENGINES=true to use the offline mock pipeline."
            )
        if not self.base_url or not self.model:
            return "LLM_GATEWAY_BASE_URL and LLM_GATEWAY_MODEL must both be set."
        return None

    def _get_session_claims(self, session_id: str) -> set:
        """Return this session's dedup set, creating it on first use."""
        if session_id not in self.seen_claims:
            self.seen_claims[session_id] = set()
        return self.seen_claims[session_id]

    def _get_session_counter(self, session_id: str) -> int:
        """Return the next claim number for this session, starting at 1."""
        if session_id not in self.claim_counter:
            self.claim_counter[session_id] = 1
        return self.claim_counter[session_id]

    def _increment_session_counter(self, session_id: str) -> None:
        self.claim_counter[session_id] = self._get_session_counter(session_id) + 1

    def _generate_claim_id(self, session_id: str) -> str:
        """Return the deterministic, session-scoped id for the next claim."""
        counter = self._get_session_counter(session_id)
        self._increment_session_counter(session_id)
        return f"{session_id}_claim_{counter:03d}"

    def _get_session_gate(self, session_id: str) -> asyncio.Semaphore:
        """Return this session's single-slot gateway gate, creating it once.

        ``asyncio.Semaphore`` waits FIFO, so finals are extracted in arrival
        order. Nothing is buffered here: a caller simply parks until the slot
        frees, which is the backpressure the gateway needs.
        """
        gate = self._session_gates.get(session_id)
        if gate is None:
            gate = asyncio.Semaphore(1)
            self._session_gates[session_id] = gate
        return gate

    def _get_session_transcripts(self, session_id: str) -> set:
        """Return this session's set of already-gateway-processed transcripts."""
        if session_id not in self.seen_transcripts:
            self.seen_transcripts[session_id] = set()
        return self.seen_transcripts[session_id]


    def _validate_llm_response(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        # Accept both {"claims": [...]} and a top-level array of claims.
        if isinstance(data, list):
            claims = data
        elif isinstance(data, dict):
            claims = data.get("claims")
            if not isinstance(claims, list):
                return []
        else:
            return []

        validated = []
        for item in claims:
            if not isinstance(item, dict):
                continue

            # Accept common claim text keys.
            claim_text = (
                item.get("claim")
                or item.get("text")
                or item.get("statement")
            )
            if not isinstance(claim_text, str) or not claim_text.strip():
                continue

            # Accept both claimType (camelCase) and claim_type (snake_case).
            # Default to "other_checkable_fact" when missing or empty.
            claim_type = item.get("claimType") or item.get("claim_type")
            if not isinstance(claim_type, str) or not claim_type.strip():
                claim_type = "other_checkable_fact"

            validated.append({
                "claim": claim_text.strip(),
                "claimType": claim_type.strip()
            })

        # Debug: a non-empty LLM payload that yields zero claims is a contract
        # mismatch we want visibility into. Never log the API key or full response.
        if claims and not validated:
            logger.debug(
                "LLM Gateway response had %d claim object(s) but none passed "
                "validation (missing 'claim'/'text'/'statement' or all were "
                "empty). First raw item keys: %s",
                len(claims),
                list(claims[0].keys()) if claims and isinstance(claims[0], dict) else "N/A",
            )

        return validated

    async def extract_claims(self, transcript: TranscriptEvent) -> List[ClaimEvent]:
        text = transcript.text.strip()
        if not text:
            return []

        if self.strict:
            problem = self.configuration_error()
            if problem:
                raise ClaimEngineError(problem)

        session_id = transcript.sessionId

        # Held across the duplicate check and the gateway call together, so two
        # finals arriving at once cannot both pass the check and both call out.
        async with self._get_session_gate(session_id):
            processed = self._get_session_transcripts(session_id)
            key = normalize_transcript(text)
            if key in processed:
                logger.info(
                    "Skipping duplicate transcript for session %s; "
                    "already sent to the LLM Gateway.",
                    session_id,
                )
                return []

            # Reserved before awaiting the gateway so a concurrent duplicate
            # cannot slip through the check above.
            processed.add(key)
            try:
                raw_claims = await self._extract_raw_claims(text)
            except BaseException:
                # A segment that never produced claims is not "processed". Drop
                # the reservation so a genuine retry is not suppressed forever.
                processed.discard(key)
                raise

        claim_events = []
        session_claims = self._get_session_claims(session_id)

        for item in raw_claims:
            claim_text = item.get("claim", "").strip()
            if not claim_text:
                continue

            # Second safety layer: the gateway may restate a claim it already
            # returned earlier in the session. Deduping here costs nothing and
            # is what keeps claim ids dense.
            normalized_key = claim_text.lower()
            if normalized_key in session_claims:
                continue
            session_claims.add(normalized_key)

            claim_id = self._generate_claim_id(session_id)

            claim_events.append(
                ClaimEvent(
                    type="claim",
                    claimId=claim_id,
                    sessionId=session_id,
                    speaker=transcript.speaker,
                    timestamp=transcript.timestamp,
                    claim=claim_text,
                    claimType=item.get("claimType", "other_checkable_fact")
                )
            )

        return claim_events

    async def _extract_raw_claims(self, text: str) -> List[Dict[str, Any]]:
        """Return the gateway's raw claim dicts for one segment.

        Split out of :meth:`extract_claims` so the transcript reservation can be
        released on any failure without duplicating the fallback rules.
        """
        if not self.is_configured():
            return self._get_fallback_claims(text)

        try:
            return await self._call_llm_gateway(text)
        except LLMRateLimitError:
            # Rate limiting is never a reason to answer from the rule-based
            # extractor, and it is already a specific, credential-free error.
            # Re-raised unwrapped so the router can report LLM_RATE_LIMITED.
            raise
        except Exception as exc:  # noqa: BLE001 - gateway shape is untrusted
            if self.strict:
                # Falling back here would silently broadcast a fabricated
                # rule-based claim as if the model had extracted it.
                raise ClaimEngineError(
                    f"LLM Gateway call to {self.base_url}/chat/completions "
                    f"failed: {type(exc).__name__}: {exc}"
                ) from exc
            logger.warning(
                "LLM Gateway call failed (%s). Falling back to rule-based extraction.",
                type(exc).__name__,
            )
            return self._get_fallback_claims(text)

    async def _call_llm_gateway(self, text: str) -> List[Dict[str, Any]]:
        """Call the LLM Gateway using httpx (OpenAI-compatible chat completions).

        A 429 is retried up to :data:`GATEWAY_MAX_RETRIES` times, honouring a
        usable ``Retry-After`` and otherwise backing off exponentially. Every
        other status, 4xx or 5xx, fails immediately: a bad key or a wrong path
        will not fix itself, and retrying them only deepens the rate limit.
        """
        if not self.api_key:
            raise RuntimeError("LLM Gateway API key not configured")

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": self._build_prompt(text)}],
            "max_tokens": 500,
            "temperature": 0.0,
        }

        attempts = GATEWAY_MAX_RETRIES + 1
        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(attempts):
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code != 429:
                    # 401/403/404 and every 5xx surface here, unretried.
                    response.raise_for_status()
                    return self._parse_gateway_response(response)

                if attempt == attempts - 1:
                    raise LLMRateLimitError(
                        f"LLM Gateway rate limited at "
                        f"{self.base_url}/chat/completions after {attempts} "
                        f"attempt(s) (HTTP 429). No claims were extracted for "
                        f"this segment.",
                        attempts=attempts,
                    )

                delay = self._retry_delay(response, attempt)
                logger.warning(
                    "LLM Gateway returned 429; retrying in %.2fs (attempt %d/%d).",
                    delay,
                    attempt + 1,
                    attempts,
                )
                await asyncio.sleep(delay)

        # Unreachable: the loop always returns or raises on its final iteration.
        raise LLMRateLimitError(  # pragma: no cover - defensive
            "LLM Gateway rate limiting did not resolve.",
            attempts=attempts,
        )

    def _retry_delay(self, response: Any, attempt: int) -> float:
        """Seconds to wait before retrying, from ``Retry-After`` or backoff."""
        requested = self._parse_retry_after(response.headers.get("Retry-After"))
        if requested is not None:
            return min(requested, GATEWAY_RETRY_MAX_SECONDS)
        backoff = GATEWAY_RETRY_BASE_SECONDS * (2**attempt)
        return min(backoff, GATEWAY_RETRY_MAX_SECONDS)

    @staticmethod
    def _parse_retry_after(value: Optional[str]) -> Optional[float]:
        """Parse a ``Retry-After`` header into non-negative seconds.

        Accepts both forms from RFC 9110: delta-seconds and an HTTP-date. An
        unparsable or negative value yields ``None`` so the caller falls back to
        exponential backoff rather than trusting a malformed header.
        """
        if value is None:
            return None
        candidate = str(value).strip()
        if not candidate:
            return None

        try:
            seconds = float(candidate)
        except (TypeError, ValueError):
            pass
        else:
            return seconds if seconds >= 0 else None

        try:
            when = parsedate_to_datetime(candidate)
        except (TypeError, ValueError, IndexError):
            return None
        if when is None:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        delta = (when - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, delta)

    def _parse_gateway_response(self, response: Any) -> List[Dict[str, Any]]:
        """Turn a gateway response into validated claim dicts.

        The payload is untrusted: a missing choice, a null content or non-JSON
        text must degrade to "no claims", never raise through here.
        """
        data = response.json()

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.warning("LLM Gateway response had no message content: %s", exc)
            return []
        if not isinstance(content, str):
            logger.warning("LLM Gateway message content was not a string.")
            return []

        # Strip markdown code fences if present
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]

        try:
            parsed = json.loads(content.strip())
        except (TypeError, ValueError) as exc:
            logger.warning("LLM Gateway returned unparsable JSON: %s", exc)
            return []

        return self._validate_llm_response(parsed)

    def _build_prompt(self, text: str) -> str:
        return f"""
Analyze the following transcript segment and identify ONLY discrete, objectively checkable factual claims (such as statistics, dates, names, historical events, quantities).
Ignore opinions, preferences, jokes, greetings, filler text, future predictions, or subjective feelings.
Return valid JSON matching this schema:
{{
  "claims": [
    {{
      "claim": "string",
      "claimType": "historical_fact | statistic | date | person | location | scientific_fact | quote | other_checkable_fact"
    }}
  ]
}}
If there are no checkable claims, return {{"claims": []}}.

Transcript: "{text}"
"""

    def _get_fallback_claims(self, text: str) -> List[Dict[str, Any]]:
        text_lower = text.lower()
        extracted = []
        if "2011 cricket world cup" in text_lower or "india won" in text_lower:
            extracted.append({
                "claim": "India won the 2011 Cricket World Cup.",
                "claimType": "historical_fact"
            })
        elif "company sold two million units" in text_lower:
            extracted.append({
                "claim": "The company sold two million units.",
                "claimType": "statistic"
            })
        return extracted
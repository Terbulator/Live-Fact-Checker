"""Claim engine adapter boundary and implementations.

The backend never runs a claim-extraction model directly in router logic. 
It defines the interface Atif's claim intelligence must satisfy and hands it a validated
:class:`~backend.schemas.TranscriptEvent`.
"""

import json
import logging
import asyncio
from abc import ABC, abstractmethod
from typing import List, Optional, Sequence, Dict, Any

import httpx

from backend.config import get_settings
from backend.schemas import ClaimEvent, TranscriptEvent

logger = logging.getLogger(__name__)


class ClaimEngineError(RuntimeError):
    """Raised when claim extraction fails."""


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

    def _validate_llm_response(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not isinstance(data, dict):
            return []
        claims = data.get("claims")
        if not isinstance(claims, list):
            return []
        validated = []
        for item in claims:
            if not isinstance(item, dict):
                continue
            claim_text = item.get("claim")
            claim_type = item.get("claimType")
            if not isinstance(claim_text, str) or not claim_text.strip():
                continue
            if not isinstance(claim_type, str) or not claim_type.strip():
                continue
            validated.append({
                "claim": claim_text.strip(),
                "claimType": claim_type.strip()
            })
        return validated

    async def extract_claims(self, transcript: TranscriptEvent) -> List[ClaimEvent]:
        text = transcript.text.strip()
        if not text:
            return []

        if self.strict:
            problem = self.configuration_error()
            if problem:
                raise ClaimEngineError(problem)

        raw_claims = []

        if self.is_configured():
            try:
                raw_claims = await self._call_llm_gateway(text)
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
                raw_claims = self._get_fallback_claims(text)
        else:
            raw_claims = self._get_fallback_claims(text)

        claim_events = []
        session_claims = self._get_session_claims(transcript.sessionId)

        for item in raw_claims:
            claim_text = item.get("claim", "").strip()
            if not claim_text:
                continue

            # Deduplication check (case-insensitive)
            normalized_key = claim_text.lower()
            if normalized_key in session_claims:
                continue
            session_claims.add(normalized_key)

            claim_id = self._generate_claim_id(transcript.sessionId)

            claim_events.append(
                ClaimEvent(
                    type="claim",
                    claimId=claim_id,
                    sessionId=transcript.sessionId,
                    speaker=transcript.speaker,
                    timestamp=transcript.timestamp,
                    claim=claim_text,
                    claimType=item.get("claimType", "other_checkable_fact")
                )
            )

        return claim_events

    async def _call_llm_gateway(self, text: str) -> List[Dict[str, Any]]:
        """Call the LLM Gateway using httpx (OpenAI-compatible chat completions)."""
        if not self.api_key:
            raise RuntimeError("LLM Gateway API key not configured")

        prompt = self._build_prompt(text)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 500,
                    "temperature": 0.0,
                },
            )

        response.raise_for_status()
        data = response.json()

        # The gateway payload is untrusted: a missing choice, a null content or
        # non-JSON text must degrade to "no claims", never raise through here.
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
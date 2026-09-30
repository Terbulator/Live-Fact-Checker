"""Persistent storage for the Live Fact-Checker.

Two concerns live here:

* :class:`SupabaseStore` -- a thin ``asyncpg`` wrapper providing a read-through
  cache of verification verdicts and an append-only session history.
* :class:`NullStore` -- the same interface with every method a no-op, used when
  persistence is not configured or must not run.

Two rules govern everything in this module.

**Nothing here may ever serve or store a fabricated answer.** The cache is
disabled outright in mock mode, and only enabled when the claim engine is
strict -- the one configuration in which the rule-based fallback extractor
cannot run. That is a structural guarantee, not a convention: with the
fallback unreachable there is no code path that can put a hardcoded fact into
``verification_cache``.

**Persistence is an optimisation, never a dependency.** Every method swallows
its own failures and logs at WARNING. If Supabase is down, misconfigured or
slow, callers fall back to live retrieval and the live pipeline keeps working.

Nothing in ``verification/`` imports this module: that package stays standalone
and runnable without a database.
"""

from dataclasses import dataclass, field
import json
from typing import Any, Dict, List, Optional, Protocol

from backend.adapters.claim_engine import normalize_transcript
from backend.logging_config import get_logger
from backend.schemas import ClaimEvent, VerificationEvent, Verdict

logger = get_logger("persistence")


def normalize_claim_key(claim: str) -> str:
    """Return the cache key for a claim's text.

    Case, punctuation and whitespace are noise when deciding whether two claims
    are the same assertion, so they fold away. Every word and digit is kept, so
    genuinely different claims never collide.
    """
    return normalize_transcript(claim)


def decode_sources(raw: Any) -> List[Dict[str, Any]]:
    """Return a stored ``sources`` column as a list of citation dicts.

    Accepts either the JSON text ``asyncpg`` hands back for a ``jsonb`` column or
    an already-decoded list, and tolerates ``None``. Anything that is not a list
    of objects yields ``[]``, so a malformed row degrades to "no extra citations"
    rather than failing a verification. It never raises: the cache is an
    optimisation, and a row it cannot read is a miss, not an outage.
    """
    if raw is None:
        return []
    if isinstance(raw, (str, bytes, bytearray)):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return []
    if not isinstance(raw, list):
        return []
    return [dict(entry) for entry in raw if isinstance(entry, dict)]


def encode_sources(sources: Optional[List[Dict[str, Any]]]) -> str:
    """Serialise a ``sources`` list for a ``jsonb`` column.

    ``asyncpg`` is handed JSON text rather than a Python object, which is the
    documented way to fill a ``jsonb`` parameter without installing a custom
    codec. Anything unserialisable is stored as an empty list: losing the
    citation list is recoverable, whereas a failed cache write would lose the
    verdict with it.
    """
    if not sources:
        return "[]"
    try:
        return json.dumps([dict(entry) for entry in sources])
    except (TypeError, ValueError):
        return "[]"


@dataclass(frozen=True)
class CachedVerification:
    """A previously retrieved verdict, ready to be replayed for a claim.

    The whole evidence trail travels with the verdict. Storing only the verdict
    would let a replay answer a claim while hiding *why* -- a cached result would
    show no supporting statement and no citations, so the same claim looked
    better evidenced when freshly retrieved than when served from cache. These
    fields default to empty so a row written before migration 002 still reads.
    """

    claim_key: str
    verdict: Verdict
    reason: str
    source: str
    confidence: Optional[float]
    provider: str
    #: Evidence-grounded explanation, or None when retrieval produced nothing
    #: citable. Never reconstructed on replay.
    supporting_statement: Optional[str] = None
    #: Ranked citations behind the verdict, decoded from the stored JSON.
    sources: List[Dict[str, Any]] = field(default_factory=list)


class PersistenceStore(Protocol):
    """The surface the application depends on. Both implementations satisfy it."""

    @property
    def enabled(self) -> bool: ...

    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    async def get_cached_verification(
        self, claim_key: str
    ) -> Optional[CachedVerification]: ...

    async def put_cached_verification(
        self,
        *,
        claim_key: str,
        verdict: Verdict,
        reason: str,
        source: str,
        confidence: Optional[float],
        provider: str,
        session_id: Optional[str],
        supporting_statement: Optional[str] = None,
        sources: Optional[List[Dict[str, Any]]] = None,
    ) -> None: ...

    async def record_session(
        self,
        *,
        session_id: str,
        status: str,
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
        ended_at: Optional[str] = None,
        transcript_count: int = 0,
        claim_count: int = 0,
        verification_count: int = 0,
        error_count: int = 0,
    ) -> None: ...

    async def record_claim(self, claim: ClaimEvent) -> None: ...

    async def record_verification(
        self, verification: VerificationEvent, *, from_cache: bool = False
    ) -> None: ...

    async def purge_expired(self) -> int: ...


class NullStore:
    """Disabled persistence. Every operation is a no-op.

    Used when no database URL is configured, and whenever mock engines are
    selected. Keeping the same interface means no caller needs a null check.
    """

    def __init__(self, reason: str = "persistence disabled") -> None:
        self.reason = reason

    @property
    def enabled(self) -> bool:
        return False

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def get_cached_verification(
        self, claim_key: str
    ) -> Optional[CachedVerification]:
        return None

    async def put_cached_verification(self, **kwargs: Any) -> None:
        return None

    async def record_session(self, **kwargs: Any) -> None:
        return None

    async def record_claim(self, claim: ClaimEvent) -> None:
        return None

    async def record_verification(
        self, verification: VerificationEvent, *, from_cache: bool = False
    ) -> None:
        return None

    async def purge_expired(self) -> int:
        return 0


class SupabaseStore:
    """``asyncpg``-backed cache and session history.

    The pool is created lazily by :meth:`connect` so that importing this module
    never requires a database or a driver.
    """

    def __init__(
        self,
        database_url: str,
        *,
        ttl_seconds: int = 604_800,
        min_pool_size: int = 1,
        max_pool_size: int = 4,
        command_timeout_seconds: float = 2.0,
    ) -> None:
        self._database_url = database_url
        self._ttl_seconds = int(ttl_seconds)
        self._min_pool_size = min_pool_size
        self._max_pool_size = max_pool_size
        self._command_timeout = command_timeout_seconds
        self._pool: Any = None

    @property
    def enabled(self) -> bool:
        return True

    # -- lifecycle ---------------------------------------------------------

    async def connect(self) -> None:
        """Open the connection pool. Failure is logged, never raised."""
        if self._pool is not None:
            return
        try:
            import asyncpg

            self._pool = await asyncpg.create_pool(
                self._database_url,
                min_size=self._min_pool_size,
                max_size=self._max_pool_size,
                command_timeout=self._command_timeout,
            )
        except Exception as exc:  # noqa: BLE001 - any import/connect fault is fatal here
            self._pool = None
            logger.warning(
                "Supabase pool unavailable; running without persistence. "
                "Live retrieval is unaffected. Cause: %s",
                type(exc).__name__,
            )

    async def close(self) -> None:
        pool, self._pool = self._pool, None
        if pool is None:
            return
        try:
            await pool.close()
        except Exception as exc:  # noqa: BLE001 - shutdown must not raise
            logger.warning("Supabase pool close failed: %s", type(exc).__name__)

    # -- cache -------------------------------------------------------------

    async def get_cached_verification(
        self, claim_key: str
    ) -> Optional[CachedVerification]:
        """Return a live cached verdict, or ``None`` on miss or any failure."""
        if self._pool is None or not claim_key:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    update verification_cache
                       set hit_count = hit_count + 1,
                           last_used_at = now()
                     where claim_key = $1 and expires_at > now()
                 returning claim_key, verdict, reason, source,
                           confidence, provider,
                           supporting_statement, sources
                    """,
                    claim_key,
                )
        except Exception as exc:  # noqa: BLE001 - fail open to live retrieval
            logger.warning(
                "Cache lookup failed; falling back to live retrieval. Cause: %s",
                type(exc).__name__,
            )
            return None
        if row is None:
            return None
        return CachedVerification(
            claim_key=row["claim_key"],
            verdict=Verdict(row["verdict"]),
            reason=row["reason"],
            source=row["source"],
            confidence=row["confidence"],
            provider=row["provider"],
            supporting_statement=row["supporting_statement"],
            sources=decode_sources(row["sources"]),
        )

    async def put_cached_verification(
        self,
        *,
        claim_key: str,
        verdict: Verdict,
        reason: str,
        source: str,
        confidence: Optional[float],
        provider: str,
        session_id: Optional[str],
        supporting_statement: Optional[str] = None,
        sources: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Store a freshly retrieved verdict with its full evidence trail.

        Never raises.
        """
        if self._pool is None or not claim_key:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    insert into verification_cache (
                        claim_key, verdict, reason, source, confidence,
                        provider, session_id, supporting_statement, sources,
                        expires_at
                    )
                    values ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb,
                            now() + ($10 || ' seconds')::interval)
                    on conflict (claim_key) do update set
                        verdict    = excluded.verdict,
                        reason     = excluded.reason,
                        source     = excluded.source,
                        confidence = excluded.confidence,
                        provider   = excluded.provider,
                        session_id = excluded.session_id,
                        supporting_statement = excluded.supporting_statement,
                        sources    = excluded.sources,
                        created_at = now(),
                        last_used_at = now(),
                        expires_at = excluded.expires_at
                    """,
                    claim_key,
                    Verdict(verdict).value,
                    reason,
                    source,
                    confidence,
                    provider,
                    session_id,
                    supporting_statement,
                    encode_sources(sources),
                    str(self._ttl_seconds),
                )
        except Exception as exc:  # noqa: BLE001 - a cache write must never fail a request
            logger.warning("Cache write failed (ignored): %s", type(exc).__name__)

    async def purge_expired(self) -> int:
        """Delete rows past their expiry. Never raises; returns rows removed."""
        if self._pool is None:
            return 0
        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    "delete from verification_cache where expires_at <= now()"
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cache purge failed (ignored): %s", type(exc).__name__)
            return 0
        return _rows_affected(result)

    # -- session history ---------------------------------------------------

    async def record_session(
        self,
        *,
        session_id: str,
        status: str,
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
        ended_at: Optional[str] = None,
        transcript_count: int = 0,
        claim_count: int = 0,
        verification_count: int = 0,
        error_count: int = 0,
    ) -> None:
        """Insert or refresh a session row. Never raises."""
        if self._pool is None:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    insert into sessions (
                        session_id, status, created_at, updated_at, ended_at,
                        transcript_count, claim_count,
                        verification_count, error_count
                    )
                    values ($1, $2, coalesce($3::timestamptz, now()),
                            coalesce($4::timestamptz, now()),
                            $5::timestamptz, $6, $7, $8, $9)
                    on conflict (session_id) do update set
                        status             = excluded.status,
                        updated_at         = excluded.updated_at,
                        ended_at           = excluded.ended_at,
                        transcript_count   = excluded.transcript_count,
                        claim_count        = excluded.claim_count,
                        verification_count = excluded.verification_count,
                        error_count        = excluded.error_count
                    """,
                    session_id,
                    status,
                    created_at,
                    updated_at,
                    ended_at,
                    transcript_count,
                    claim_count,
                    verification_count,
                    error_count,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Session history write failed (ignored): %s", type(exc).__name__)

    async def record_claim(self, claim: ClaimEvent) -> None:
        """Append a claim. Never raises."""
        if self._pool is None:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    insert into session_claims (
                        claim_id, session_id, speaker, timestamp, claim, claim_type
                    )
                    values ($1, $2, $3, $4, $5, $6)
                    on conflict (claim_id) do nothing
                    """,
                    claim.claimId,
                    claim.sessionId,
                    claim.speaker,
                    claim.timestamp,
                    claim.claim,
                    claim.claimType,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Claim history write failed (ignored): %s", type(exc).__name__)

    async def record_verification(
        self, verification: VerificationEvent, *, from_cache: bool = False
    ) -> None:
        """Append a verification, with its evidence trail, to session history.

        The stored history is the audit record for a session, so it keeps the
        supporting statement and ranked citations alongside the verdict: a review
        of a past session must be able to show *why* a claim was called true,
        which the verdict and primary source alone do not say. Never raises.
        """
        if self._pool is None:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    insert into session_verifications (
                        claim_id, session_id, verdict, reason, source,
                        confidence, from_cache, supporting_statement, sources
                    )
                    values ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                    on conflict (claim_id) do update set
                        verdict     = excluded.verdict,
                        reason      = excluded.reason,
                        source      = excluded.source,
                        confidence  = excluded.confidence,
                        from_cache  = excluded.from_cache,
                        supporting_statement = excluded.supporting_statement,
                        sources     = excluded.sources,
                        created_at  = now()
                    """,
                    verification.claimId,
                    verification.sessionId,
                    Verdict(verification.verdict).value,
                    verification.reason,
                    verification.source,
                    verification.confidence,
                    from_cache,
                    verification.supportingStatement,
                    encode_sources(verification.sources),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Verification history write failed (ignored): %s", type(exc).__name__
            )


def _rows_affected(result: Any) -> int:
    """Parse ``DELETE n`` from asyncpg's command tag."""
    try:
        return int(str(result).rsplit(" ", 1)[-1])
    except (TypeError, ValueError):
        return 0


def build_store(settings: Any, *, strict: bool) -> PersistenceStore:
    """Return a store only when persisting is safe and configured.

    Persistence is refused in three cases, and each is a deliberate guard
    rather than a configuration preference:

    * **mock engines selected** -- mock claims and verdicts must never be
      written to a shared store, let alone replayed later as if they had been
      retrieved.
    * **no database URL** -- nothing to connect to.
    * **a non-strict claim engine** -- only a strict engine rules out the
      rule-based fallback extractor, which is the one path that can produce a
      hardcoded answer. Without strict mode the fallback verdict could reach
      ``verification_cache`` and later be served to a different user as though
      it had been retrieved from a source.

    Every refusal returns :class:`NullStore`, whose methods are no-ops, so
    callers never branch on whether persistence exists.
    """
    if getattr(settings, "use_mock_engines", False):
        return NullStore("mock engines selected; persistence is disabled")
    if not strict:
        return NullStore(
            "claim engine is not strict; persistence is disabled so a "
            "rule-based fallback verdict can never be stored or replayed"
        )
    url_obj = getattr(settings, "supabase_database_url", None)
    if url_obj is None:
        return NullStore("SUPABASE_DATABASE_URL is not set")
    url = url_obj.get_secret_value() if hasattr(url_obj, "get_secret_value") else str(url_obj)
    if not url.strip():
        return NullStore("SUPABASE_DATABASE_URL is empty")
    return SupabaseStore(
        url.strip(),
        ttl_seconds=int(getattr(settings, "fact_cache_ttl_seconds", 604_800)),
        command_timeout_seconds=float(
            getattr(settings, "persistence_timeout_seconds", 2.0)
        ),
    )

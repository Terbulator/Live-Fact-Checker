"""Integration adapter boundaries for the backend.

The backend owns routing, not algorithms. Every downstream capability is
reached through an interface declared here:

* :mod:`backend.adapters.claim_engine` — Atif's claim intelligence
* :mod:`backend.adapters.verification` — Nayanika's verification engine,
  plus the bridge to the existing ``verification`` package
"""

from backend.adapters.claim_engine import (
    ClaimEngine,
    ClaimEngineError,
    StaticClaimEngine,
    UnavailableClaimEngine,
)
from backend.adapters.verification import (
    VERDICT_TO_WIRE,
    WIRE_TO_VERDICT,
    UnavailableVerificationEngine,
    VerificationEngine,
    VerificationEngineError,
    VerificationServiceEngine,
    to_internal_claim_payload,
    to_internal_verdict,
    to_wire_verdict,
)

__all__ = [
    "ClaimEngine",
    "ClaimEngineError",
    "StaticClaimEngine",
    "UnavailableClaimEngine",
    "VerificationEngine",
    "VerificationEngineError",
    "VerificationServiceEngine",
    "UnavailableVerificationEngine",
    "VERDICT_TO_WIRE",
    "WIRE_TO_VERDICT",
    "to_wire_verdict",
    "to_internal_verdict",
    "to_internal_claim_payload",
]

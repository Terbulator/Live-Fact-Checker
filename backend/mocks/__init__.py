"""Mock components for offline backend development and testing.

Nothing in this package requires an AssemblyAI, LLM or search API key.
"""

from backend.mocks.mock_stream import (
    MOCK_TRANSCRIPT_SCRIPT,
    REFERENCE_CLAIM_TEXT,
    REFERENCE_SPEAKER,
    REFERENCE_TIMESTAMP,
    MockClaimEngine,
    MockVerificationEngine,
    build_mock_transcript,
    stream_mock_transcripts,
)

__all__ = [
    "MockClaimEngine",
    "MockVerificationEngine",
    "MOCK_TRANSCRIPT_SCRIPT",
    "REFERENCE_CLAIM_TEXT",
    "REFERENCE_SPEAKER",
    "REFERENCE_TIMESTAMP",
    "build_mock_transcript",
    "stream_mock_transcripts",
]

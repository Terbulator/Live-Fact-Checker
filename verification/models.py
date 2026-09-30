"""Data models for the Verification module.

Defines strict contracts for ClaimEvent inputs and VerificationEvent outputs.
"""

from enum import Enum
from typing import Literal, Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator


class VerdictType(str, Enum):
    """Allowed verdicts for verification results."""
    TRUE = "True"
    FALSE = "False"
    UNVERIFIABLE = "Unverifiable"
    AMBIGUOUS = "Ambiguous"


class ClaimEvent(BaseModel):
    """Input contract representing a claim extracted from speech/transcript.
    
    Example:
    {
      "type": "claim",
      "claimId": "claim_001",
      "speaker": "Speaker 1",
      "claim": "The company sold two million units.",
      "timestamp": 12.4
    }
    """
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["claim"] = Field(
        default="claim",
        description="Event type indicator, must be 'claim'"
    )
    claimId: str = Field(
        ...,
        min_length=1,
        description="Unique identifier for the claim, preserved through the pipeline"
    )
    speaker: str = Field(
        default="Speaker 1",
        min_length=1,
        description="Identifier of the speaker who made the claim"
    )
    claim: str = Field(
        ...,
        min_length=1,
        description="The extracted factual statement to be verified"
    )
    timestamp: float = Field(
        ...,
        ge=0.0,
        description="Timestamp in seconds when the claim was uttered"
    )

    @field_validator("claim", "claimId", "speaker")
    @classmethod
    def validate_non_whitespace(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Field cannot be empty or pure whitespace.")
        return trimmed


class VerificationEvent(BaseModel):
    """Output contract representing the verification verdict and evidence.
    
    Example:
    {
      "type": "verification",
      "claimId": "claim_001",
      "verdict": "False",
      "reason": "The available source reports a different figure.",
      "source": "https://example.com",
      "sources": [
        {"url": "https://example.com", "title": "Article Title", "snippet": "..."}
      ]
    }
    """
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["verification"] = Field(
        default="verification",
        description="Event type indicator, must be 'verification'"
    )
    claimId: str = Field(
        ...,
        min_length=1,
        description="Original claim identifier matching the input ClaimEvent"
    )
    verdict: VerdictType = Field(
        ...,
        description="Verdict determination: 'True', 'False', or 'Unverifiable'"
    )
    reason: str = Field(
        ...,
        min_length=1,
        description="Concise rationale explaining the verdict"
    )
    source: str = Field(
        ...,
        description="Primary evidence URL or authoritative source reference"
    )
    # Backward-compatible extension: multiple evidence sources.
    # Each entry: {"url": str, "title": str|None, "snippet": str|None}
    sources: List[Dict[str, Any]] = Field(default_factory=list)

    @field_validator("reason")
    @classmethod
    def validate_reason_non_empty(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Reason cannot be empty or pure whitespace.")
        return trimmed

    def to_dict(self) -> dict:
        """Serializes VerificationEvent to standard dictionary."""
        return self.model_dump()


class EvidenceItem(BaseModel):
    """Internal model representing an evidence snippet retrieved from a source."""
    model_config = ConfigDict(extra="ignore", frozen=True)

    snippet: str = Field(..., description="Text excerpt from the source")
    source_url: str = Field(..., description="URL or name of the source")
    title: Optional[str] = Field(default=None, description="Title of the article or publication")
    stance: Optional[Literal["supports", "refutes", "neutral", "conflicting"]] = Field(
        default=None,
        description="Stance indicator relative to the claim, if pre-tagged or evaluated"
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Reliability / relevance score between 0.0 and 1.0"
    )

    # Wire shape lives in ``verification.sources.to_source_dict``. A second copy
    # here drifted from it (it dropped ``confidence`` and the snippet
    # truncation), so there is exactly one definition to keep correct.

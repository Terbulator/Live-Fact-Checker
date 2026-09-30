"""Internal ingestion models.

This module defines the common internal representation used across all
ingestion adapters (audio, video, URL). The existing pipeline consumes
TranscriptEvent -> ClaimEvent -> VerificationEvent, so ingestion only needs
to produce a transcript (with optional timestamps/speakers) that feeds into
the existing claim engine.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
import secrets

from backend.scorecard import VideoClaimResult, VideoScorecard

__all__ = [
    "InputType",
    "ProcessingStatus",
    "InputSource",
    "IngestionRequest",
    "AudioUploadRequest",
    "VideoUploadRequest",
    "VideoURLRequest",
    "IngestionResponse",
    "IngestionError",
    "VideoClaimResult",
    "VideoScorecard",
]


def _generate_event_id() -> str:
    return secrets.token_urlsafe(16)


class InputType(str, Enum):
    """Type of input source."""

    AUDIO_UPLOAD = "audio_upload"
    VIDEO_UPLOAD = "video_upload"
    VIDEO_URL = "video_url"


class ProcessingStatus(str, Enum):
    """Processing status of an ingestion job."""

    PENDING = "pending"
    UPLOADING = "uploading"
    EXTRACTING_AUDIO = "extracting_audio"
    TRANSCRIBING = "transcribing"
    COMPLETED = "completed"
    FAILED = "failed"


class InputSource(BaseModel):
    """Common internal representation of an ingested media source.

    This is produced by ingestion adapters and fed into the existing
    claim extraction pipeline. The pipeline only needs the transcript text
    (and optionally timestamps/speaker info).
    """

    model_config = ConfigDict(extra="ignore")

    # Identity
    source_id: str = Field(default_factory=_generate_event_id)
    type: InputType
    filename: Optional[str] = None
    url: Optional[str] = None
    media_type: Optional[str] = None

    # Transcript output (what the claim engine consumes)
    transcript: Optional[str] = None
    transcript_segments: List[Dict[str, Any]] = Field(default_factory=list)

    # Optional metadata
    duration_seconds: Optional[float] = None
    speaker_info: Optional[Dict[str, Any]] = None
    timestamps: Optional[List[Dict[str, Any]]] = None

    # Processing tracking
    status: ProcessingStatus = ProcessingStatus.PENDING
    error: Optional[str] = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: Optional[str] = None


class IngestionRequest(BaseModel):
    """Base request model for ingestion endpoints."""

    model_config = ConfigDict(extra="ignore")

    session_id: str = Field(..., min_length=1)


class AudioUploadRequest(IngestionRequest):
    """Request for audio file upload (multipart handled separately)."""


class VideoUploadRequest(IngestionRequest):
    """Request for video file upload (multipart handled separately)."""


class VideoURLRequest(IngestionRequest):
    """Request for video URL ingestion."""

    url: str = Field(..., min_length=1)


class IngestionResponse(BaseModel):
    """Response for ingestion endpoints.

    The original aggregate counters are unchanged, so any existing consumer keeps
    working. Two additive fields carry what a person actually needs out of a
    recorded run:

    * ``claims`` -- every claim the pipeline extracted, with its verdict, the
      evidence behind it, and the speaker and timestamp it was made at.
    * ``scorecard`` -- the deterministic summary derived from those claims.

    Both default to empty, so a response built without them is still valid.
    """

    model_config = ConfigDict(extra="ignore")

    source_id: str
    status: ProcessingStatus
    message: str
    transcript: Optional[str] = None
    transcript_segments: List[Dict[str, Any]] = Field(default_factory=list)
    claims_extracted: int = 0
    verifications_completed: int = 0
    # Additive: per-claim results and the scorecard derived from them. See
    # backend/scorecard.py for why a failed check is never counted as a verdict.
    claims: List[VideoClaimResult] = Field(default_factory=list)
    scorecard: Optional[VideoScorecard] = None
    #: Length of the source media in seconds, when the ingestor measured it.
    duration_seconds: Optional[float] = None


class IngestionError(Exception):
    """Custom exception for ingestion failures."""

    def __init__(self, message: str, code: str = "INGESTION_FAILED"):
        self.message = message
        self.code = code
        super().__init__(message)
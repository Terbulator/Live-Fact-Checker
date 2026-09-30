"""Ingestion routes for audio/video/URL uploads.

These routes accept uploads, process them through the ingestion pipeline,
and feed the resulting transcript into the existing claim/verification pipeline.
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse

from backend.ingestion.models import (
    AudioUploadRequest,
    IngestionResponse,
    ProcessingStatus,
    VideoURLRequest,
    VideoUploadRequest,
)
from backend.ingestion.audio import process_audio_upload, AudioIngestionError
from backend.ingestion.video import process_video_upload, VideoIngestionError
from backend.ingestion.url import process_video_url, URLError
from backend.persistence.store import normalize_claim_key
from backend.router import EventRouter
from backend.schemas import ErrorCode, PipelineCounts, VerificationEvent
from backend.scorecard import (
    ClaimCheckStatus,
    VideoClaimResult,
    build_claim_result,
    build_scorecard,
)
from backend.session_manager import SessionNotFoundError

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


async def _require_active_session(request: Request, session_id: str) -> None:
    """Reject ingestion for unknown or stopped sessions."""
    session_manager = request.app.state.session_manager
    router_instance = request.app.state.router
    try:
        session = await session_manager.require(session_id)
    except SessionNotFoundError:
        await router_instance.emit_error(
            session_id,
            ErrorCode.SESSION_NOT_FOUND,
            f"No active session with id {session_id}.",
            recoverable=False,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": ErrorCode.SESSION_NOT_FOUND.value, "message": "Session not found."},
        )

    if not session.is_active():
        await router_instance.emit_error(
            session_id,
            ErrorCode.SESSION_STOPPED,
            f"Session {session_id} has been stopped.",
            recoverable=False,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": ErrorCode.SESSION_STOPPED.value, "message": "Session has been stopped."},
        )


def _segments_to_transcript_events(segments: list, session_id: str) -> list:
    """Convert transcript segments to TranscriptEvent-like dicts for the pipeline."""
    from backend.schemas import TranscriptEvent
    events = []
    for seg in segments:
        events.append(TranscriptEvent(
            sessionId=session_id,
            speaker=seg.get("speaker", "Speaker 1"),
            text=seg.get("text", ""),
            timestamp=seg.get("start", 0.0),
            isFinal=True,
        ))
    return events


async def _run_pipeline_on_source(
    request: Request,
    session_id: str,
    source,
) -> IngestionResponse:
    """Run the existing claim/verification pipeline on an ingested source.

    Each transcript segment is pushed through the unchanged
    ``transcript -> claim -> verification`` pipeline, so a recorded video is
    fact-checked by exactly the same code path as live speech and its verdicts
    reach the frontend over the WebSocket as they resolve.

    On top of that, every claim and verdict is collected so the response can
    carry the per-claim evidence and the scorecard. Collection is deliberately
    separate from processing: the pipeline is the source of truth and is not
    modified to report anything extra, so this only reads what it already
    produced.
    """
    router_instance: EventRouter = request.app.state.router

    transcript_events = _segments_to_transcript_events(source.transcript_segments, session_id)

    total_claims = 0
    total_verifications = 0
    total_errors = 0
    results: list[VideoClaimResult] = []
    # Claims already verified earlier in this session, so a claim repeated later
    # in the video resolves to the verdict it got the first time instead of being
    # reported as an unchecked failure. This matters for a long video, where the
    # same claim is often restated.
    verified_by_claim_id: dict[str, VerificationEvent] = {}
    # Results indexed by the claim's normalised text, so a restated claim is only
    # reported once.
    #
    # The claim engine already collapses identical claim text within a session,
    # but a report that silently depended on that would report a video as having
    # more claims than it contains whenever the engine let a repeat through --
    # and it would weight the scorecard toward whatever the speaker restated
    # most. Keying on the normalised text makes the dedup a property of the
    # report itself rather than of whichever engine is wired in, and it reuses
    # the same normalisation the fact cache uses to decide two claims are the
    # same assertion.
    result_index_by_key: dict[str, int] = {}

    for transcript_event in transcript_events:
        counts, claims, verifications = await router_instance.handle_transcript(transcript_event)
        total_claims += counts.claims
        total_verifications += counts.verifications
        total_errors += counts.errors

        for verification in verifications:
            verified_by_claim_id[verification.claimId] = verification

        for claim in claims:
            verification = verified_by_claim_id.get(claim.claimId)
            if verification is None:
                # Either this claim's check failed, or its id was already
                # verified earlier in the session and the pipeline deliberately
                # skipped re-verifying it. Both mean no *new* verdict, and both
                # are recorded as such rather than as a verdict about the video.
                verification = await router_instance.sessions.get_verification(
                    session_id, claim.claimId
                )
            result = build_claim_result(claim, verification)

            key = normalize_claim_key(claim.claim)
            existing_index = result_index_by_key.get(key)
            if existing_index is None:
                result_index_by_key[key] = len(results)
                results.append(result)
                continue

            # Already reported. Keep the existing entry unless this occurrence
            # carries a verdict and the one on file does not: the same claim
            # failing once and succeeding later is still a claim that was
            # checked, and reporting the failure would hide evidence that exists.
            existing = results[existing_index]
            if existing.status is ClaimCheckStatus.FAILED and result.status is not ClaimCheckStatus.FAILED:
                results[existing_index] = result

    scorecard = build_scorecard(results)

    return IngestionResponse(
        source_id=source.source_id,
        status=source.status,
        message="Ingestion complete. Transcript processed through claim/verification pipeline.",
        transcript=source.transcript,
        transcript_segments=source.transcript_segments,
        claims_extracted=total_claims,
        verifications_completed=total_verifications,
        claims=results,
        scorecard=scorecard,
        duration_seconds=source.duration_seconds,
    )


@router.post(
    "/audio",
    response_model=IngestionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_audio(
    request: Request,
    session_id: str = Form(...),
    file: UploadFile = File(...),
) -> IngestionResponse:
    """Upload and process an audio file (MP3, WAV, M4A, etc.)."""
    await _require_active_session(request, session_id)

    # Read file content
    file_content = await file.read()
    filename = file.filename or "audio"
    content_type = file.content_type or "application/octet-stream"

    try:
        # Process through audio ingestion
        source = await process_audio_upload(file_content, filename, content_type, session_id)

        # Run through existing pipeline
        return await _run_pipeline_on_source(request, session_id, source)

    except AudioIngestionError as e:
        await request.app.state.router.emit_error(
            session_id,
            ErrorCode.INTERNAL_ERROR,
            e.message,
            detail=e.code,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": e.code, "message": e.message},
        )
    except Exception as e:
        await request.app.state.router.emit_error(
            session_id,
            ErrorCode.INTERNAL_ERROR,
            f"Audio ingestion failed: {type(e).__name__}: {e}",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "AUDIO_INGESTION_FAILED", "message": str(e)},
        )


@router.post(
    "/video",
    response_model=IngestionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_video(
    request: Request,
    session_id: str = Form(...),
    file: UploadFile = File(...),
) -> IngestionResponse:
    """Upload and process a video file (MP4, MOV, WebM, etc.)."""
    await _require_active_session(request, session_id)

    file_content = await file.read()
    filename = file.filename or "video"
    content_type = file.content_type or "application/octet-stream"

    try:
        source = await process_video_upload(file_content, filename, content_type, session_id)
        return await _run_pipeline_on_source(request, session_id, source)

    except VideoIngestionError as e:
        await request.app.state.router.emit_error(
            session_id,
            ErrorCode.INTERNAL_ERROR,
            e.message,
            detail=e.code,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": e.code, "message": e.message},
        )
    except Exception as e:
        await request.app.state.router.emit_error(
            session_id,
            ErrorCode.INTERNAL_ERROR,
            f"Video ingestion failed: {type(e).__name__}: {e}",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "VIDEO_INGESTION_FAILED", "message": str(e)},
        )


@router.post(
    "/video-url",
    response_model=IngestionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_video_url(
    request: Request,
    body: VideoURLRequest,
) -> IngestionResponse:
    """Process a public video URL (YouTube, direct video links)."""
    await _require_active_session(request, body.session_id)

    try:
        source = await process_video_url(body.url, body.session_id)
        return await _run_pipeline_on_source(request, body.session_id, source)

    except URLError as e:
        await request.app.state.router.emit_error(
            body.session_id,
            ErrorCode.INTERNAL_ERROR,
            e.message,
            detail=e.code,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": e.code, "message": e.message},
        )
    except Exception as e:
        await request.app.state.router.emit_error(
            body.session_id,
            ErrorCode.INTERNAL_ERROR,
            f"Video URL ingestion failed: {type(e).__name__}: {e}",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "URL_INGESTION_FAILED", "message": str(e)},
        )
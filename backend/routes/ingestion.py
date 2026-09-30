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
from backend.router import EventRouter
from backend.schemas import ErrorCode, PipelineCounts
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
    """Run the existing claim/verification pipeline on an ingested source."""
    router_instance: EventRouter = request.app.state.router

    # Convert segments to transcript events and process through pipeline
    transcript_events = _segments_to_transcript_events(source.transcript_segments, session_id)

    total_claims = 0
    total_verifications = 0
    total_errors = 0

    for transcript_event in transcript_events:
        counts, claims, verifications = await router_instance.handle_transcript(transcript_event)
        total_claims += counts.claims
        total_verifications += counts.verifications
        total_errors += counts.errors

    return IngestionResponse(
        source_id=source.source_id,
        status=source.status,
        message="Ingestion complete. Transcript processed through claim/verification pipeline.",
        transcript=source.transcript,
        transcript_segments=source.transcript_segments,
        claims_extracted=total_claims,
        verifications_completed=total_verifications,
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
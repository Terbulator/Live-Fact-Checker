/**
 * Recorded-media ingestion.
 *
 * One state machine for all three recorded inputs -- audio file, video file and
 * video link -- so the composer and the standalone controls cannot drift apart.
 * It owns validation, session resolution and the upload itself; presentation
 * belongs to whatever renders it.
 *
 * NO INVENTED PROGRESS
 * A browser reports upload progress only through a streaming request body, which
 * this API client does not use, so there is no real byte count to show and this
 * hook deliberately reports no percentage. The two states it does report --
 * uploading, then the backend working -- are both observed, not estimated.
 */

import { useCallback, useState } from 'react'

import { ApiError, ingestAudio, ingestVideo, ingestVideoUrl } from '../lib/api'
import type { IngestionResponse } from '../lib/api'
import { completionMessage } from '../lib/videoReport'
import { validateFile, validateUrl, type MediaKind } from '../lib/media'

export type IngestionStatus = 'idle' | 'uploading' | 'processing' | 'complete' | 'error'

export interface IngestionState {
  kind: MediaKind | null
  status: IngestionStatus
  /** What is being analysed, for the progress note. */
  label: string
  /** Plain-language outcome. Only meaningful once complete or errored. */
  message: string
  error: string | null
}

/** What the caller is told is being analysed, before any work starts. */
export interface IngestionTarget {
  kind: MediaKind
  /** Filename, or the URL that was submitted. */
  label: string
  /**
   * Object URL for a locally chosen file, so the conversation can show the media
   * that was actually submitted. Null for remote sources.
   */
  previewUrl: string | null
  /** The file itself, when the submission came from the picker. */
  file: File | null
}

export interface UseMediaIngestionOptions {
  /**
   * The session to ingest into, created on demand if necessary. Returns null
   * when no session could be obtained, and the submission is then refused rather
   * than sent against a session that does not exist.
   */
  resolveSession: () => Promise<string | null>
  onStart?: (target: IngestionTarget) => void
  onComplete?: (result: IngestionResponse) => void
  onError?: (message: string) => void
}

export interface UseMediaIngestionResult {
  state: IngestionState
  /** True while bytes are moving or the backend is working. */
  busy: boolean
  /** Clear a finished or failed run. */
  reset: () => void
  /** Validate and upload a picked file. Resolves to null when refused or failed. */
  submitFile: (
    kind: Exclude<MediaKind, 'url'>,
    file: File,
    previewUrl: string | null,
  ) => Promise<IngestionResponse | null>
  /** Validate and process a link. Resolves to null when refused or failed. */
  submitUrl: (url: string) => Promise<IngestionResponse | null>
}

const IDLE: IngestionState = { kind: null, status: 'idle', label: '', message: '', error: null }

function describe(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message
  return fallback
}

/** A revocable object URL, or null where the browser refuses to make one. */
export function createPreviewUrl(file: File): string | null {
  try {
    return URL.createObjectURL(file)
  } catch {
    // A browser that refuses object URLs still ingests the file; the
    // conversation simply has no local preview to show.
    return null
  }
}

export function useMediaIngestion({
  resolveSession,
  onStart,
  onComplete,
  onError,
}: UseMediaIngestionOptions): UseMediaIngestionResult {
  const [state, setState] = useState<IngestionState>(IDLE)

  const reset = useCallback(() => setState(IDLE), [])

  const fail = useCallback(
    (message: string) => {
      setState((current) => ({
        kind: current.kind,
        status: 'error',
        label: current.label,
        message,
        error: message,
      }))
      onError?.(message)
    },
    [onError],
  )

  const submitFile = useCallback(
    async (
      kind: Exclude<MediaKind, 'url'>,
      file: File,
      previewUrl: string | null,
    ): Promise<IngestionResponse | null> => {
      const rejection = validateFile(file, kind)
      if (rejection !== null) {
        fail(rejection)
        return null
      }

      const sessionId = await resolveSession()
      if (sessionId === null) {
        fail('No active session. Start a session first.')
        return null
      }

      const target: IngestionTarget = { kind, label: file.name, previewUrl, file }
      setState({
        kind,
        status: 'uploading',
        label: file.name,
        message: `Uploading ${file.name}…`,
        error: null,
      })
      onStart?.(target)

      try {
        const result =
          kind === 'audio'
            ? await ingestAudio(sessionId, file)
            : await ingestVideo(sessionId, file)
        setState({
          kind,
          status: 'processing',
          label: file.name,
          message: 'Transcribing and fact-checking…',
          error: null,
        })
        setState({
          kind,
          status: 'complete',
          label: file.name,
          message: completionMessage(result),
          error: null,
        })
        onComplete?.(result)
        return result
      } catch (error) {
        fail(describe(error, 'Ingestion failed'))
        return null
      }
    },
    [fail, onComplete, onStart, resolveSession],
  )

  const submitUrl = useCallback(
    async (url: string): Promise<IngestionResponse | null> => {
      const rejection = validateUrl(url)
      if (rejection !== null) {
        fail(rejection)
        return null
      }

      const sessionId = await resolveSession()
      if (sessionId === null) {
        fail('No active session. Start a session first.')
        return null
      }

      const trimmed = url.trim()
      setState({
        kind: 'url',
        status: 'processing',
        label: trimmed,
        message: 'Downloading and fact-checking the video…',
        error: null,
      })
      onStart?.({ kind: 'url', label: trimmed, previewUrl: null, file: null })

      try {
        const result = await ingestVideoUrl(sessionId, trimmed)
        setState({
          kind: 'url',
          status: 'complete',
          label: trimmed,
          message: completionMessage(result),
          error: null,
        })
        onComplete?.(result)
        return result
      } catch (error) {
        fail(describe(error, 'URL ingestion failed'))
        return null
      }
    },
    [fail, onComplete, onStart, resolveSession],
  )

  return {
    state,
    busy: state.status === 'uploading' || state.status === 'processing',
    reset,
    submitFile,
    submitUrl,
  }
}

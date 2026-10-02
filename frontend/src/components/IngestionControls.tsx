/**
 * Ingestion controls for recorded media.
 *
 * The standalone row: audio file, video file and video link, each feeding the
 * existing transcript -> claim -> verification pipeline.
 *
 * The dashboard's composer owns the same three inputs, and both surfaces drive
 * the identical `useMediaIngestion` state machine, so validation, session
 * resolution and upload behaviour cannot diverge between them. This component is
 * presentation over that hook: it renders buttons and a note, and reports
 * progress, which is all it ever did.
 *
 * Accessible names are unchanged from the original controls, so assistive
 * technology and the tests describe the same three actions wherever they are
 * rendered.
 */

import { useRef } from 'react'

import { useMediaIngestion, createPreviewUrl } from '../hooks/useMediaIngestion'
import type { IngestionTarget } from '../hooks/useMediaIngestion'
import type { IngestionResponse } from '../lib/api'
import { TechnicalDetails } from './TechnicalDetails'

export type { IngestionTarget } from '../hooks/useMediaIngestion'

export interface IngestionControlsProps {
  /** Current session ID from useSession */
  sessionId: string | null
  /** Whether a session is active */
  isActive: boolean
  /**
   * Start a session on demand and return its id, or null if one could not be
   * created.
   *
   * Only used when there is no active session to ingest into. Ingestion never
   * runs without a session: either one already exists, or one is created here
   * first. Omitting it keeps the original behaviour of offering no controls at
   * all while idle.
   */
  ensureSession?: () => Promise<string | null>
  onIngestionStart?: (target?: IngestionTarget) => void
  onIngestionComplete?: (result: IngestionResponse) => void
  onError?: (error: string) => void
  /** Markup decoration only. Defaults to the standalone row. */
  variant?: 'bar' | 'composer'
  /** In the composer, promote the URL field to the primary input. */
  urlPrimary?: boolean
}

export function IngestionControls({
  sessionId,
  isActive,
  ensureSession,
  onIngestionStart,
  onIngestionComplete,
  onError,
  variant = 'bar',
  urlPrimary = false,
}: IngestionControlsProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const urlInputRef = useRef<HTMLInputElement>(null)
  /** Which button opened the file dialog, read back when a file arrives. */
  const pendingModeRef = useRef<'audio' | 'video'>('audio')

  const isComposer = variant === 'composer'

  const hasSession = isActive && sessionId !== null && sessionId !== ''
  const { state, busy, reset, submitFile, submitUrl } = useMediaIngestion({
    resolveSession: async () => {
      if (hasSession) return sessionId
      if (ensureSession !== undefined) return await ensureSession()
      return null
    },
    onStart: (target) => onIngestionStart?.(target),
    onComplete: onIngestionComplete,
    onError,
  })

  // A session to ingest into, or a way to obtain one. With neither, there is
  // nothing these controls could do, so they are not offered at all.
  if (!hasSession && ensureSession === undefined) {
    return null
  }

  const handlePick = (kind: 'audio' | 'video') => {
    // Recorded before the dialog opens. The run state cannot do this job: it is
    // only set once a file has been chosen, so reading it would treat every
    // selection -- including an .mp3 -- as a video.
    pendingModeRef.current = kind
    fileInputRef.current?.click()
  }

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file !== undefined) {
      const preview = createPreviewUrl(file)
      void submitFile(pendingModeRef.current, file, preview)
      // Reset input so the same file can be chosen again.
      event.target.value = ''
    }
  }

  const handleUrlKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      void submitUrl(event.currentTarget.value)
      event.currentTarget.value = ''
    }
  }

  const classes = [
    'ingestion-controls',
    isComposer ? 'ingestion-controls--composer' : '',
    urlPrimary ? 'ingestion-controls--url' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <section className={classes} aria-label="Recorded media ingestion">
      <div className="controls__group ingestion-row">
        <button
          type="button"
          className="button ingestion-upload ingestion-upload--video"
          onClick={() => handlePick('video')}
          disabled={busy}
          aria-label="Upload Video"
          title="Upload a video file (MP4, MOV, WebM, AVI, MKV)"
        >
          {isComposer ? '+ Add video' : 'Upload Video'}
        </button>
        <button
          type="button"
          className="button ingestion-upload ingestion-upload--audio"
          onClick={() => handlePick('audio')}
          disabled={busy}
          aria-label="Upload Audio"
          title="Upload an audio file (MP3, WAV, M4A, OGG, WebM, FLAC)"
        >
          {isComposer ? '+ Add audio' : 'Upload Audio'}
        </button>
        <span className="ingestion-url">
          <input
            ref={urlInputRef}
            type="url"
            placeholder="Paste YouTube or video URL..."
            className="ingestion-url-input"
            onKeyDown={handleUrlKeyDown}
            disabled={busy}
            title="Paste a YouTube URL or direct video link"
          />
          <button
            type="button"
            className="button ingestion-url-go"
            onClick={() => void submitUrl(urlInputRef.current?.value ?? '')}
            disabled={busy}
            aria-label="Analyze URL"
            title="Analyze video URL"
          >
            {isComposer ? 'Analyze ➤' : 'Analyze URL'}
          </button>
        </span>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        style={{ display: 'none' }}
        onChange={handleFileChange}
        accept="audio/*,video/*"
      />

      {state.status !== 'idle' && (
        <div className="ingestion-progress" role="status" aria-live="polite">
          <div className="ingestion-progress__header">
            <span className="ingestion-progress__file">{state.label || 'Processing…'}</span>
            <span className="ingestion-progress__status">{state.message}</span>
          </div>
          {state.status === 'error' && (
            <div className="ingestion-progress__error">
              <span className="ingestion-progress__errorText">{state.message}</span>
              {state.error !== null && state.error.length > 140 && (
                <TechnicalDetails summary="Technical details">{state.error}</TechnicalDetails>
              )}
              <button type="button" className="button button--small" onClick={reset}>
                Dismiss
              </button>
            </div>
          )}
          {state.status === 'complete' && (
            <div className="ingestion-progress__success">
              {state.message}
              <button type="button" className="button button--small" onClick={reset}>
                Done
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  )
}

/**
 * Ingestion controls for recorded media.
 *
 * Provides three additional input modes alongside the existing "Go Live":
 * - Upload Audio: MP3, WAV, M4A, etc.
 * - Upload Video: MP4, MOV, WebM, etc.
 * - Video URL: YouTube and direct video links
 *
 * Each mode uploads/processes media and feeds the transcript into the
 * existing claim -> verification pipeline.
 */

import { useCallback, useRef, useState } from 'react'
import { ingestAudio, ingestVideo, ingestVideoUrl, ApiError } from '../lib/api'

export interface IngestionControlsProps {
  /** Current session ID from useSession */
  sessionId: string | null
  /** Whether a session is active */
  isActive: boolean
  /** Callback when ingestion starts (to show loading state) */
  onIngestionStart?: () => void
  /** Callback when ingestion completes */
  onIngestionComplete?: (result: { claims: number; verifications: number }) => void
  /** Callback for errors */
  onError?: (error: string) => void
}

type IngestionMode = 'audio' | 'video' | 'url'
type IngestionStatus = 'idle' | 'uploading' | 'processing' | 'complete' | 'error'

interface IngestionState {
  mode: IngestionMode | null
  status: IngestionStatus
  progress: number
  message: string
  fileName?: string
  error?: string
}

export function IngestionControls({
  sessionId,
  isActive,
  onIngestionStart,
  onIngestionComplete,
  onError,
}: IngestionControlsProps) {
  const [state, setState] = useState<IngestionState>({
    mode: null,
    status: 'idle',
    progress: 0,
    message: '',
  })
  const fileInputRef = useRef<HTMLInputElement>(null)
  const urlInputRef = useRef<HTMLInputElement>(null)
  const progressIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const resetState = useCallback(() => {
    setState({
      mode: null,
      status: 'idle',
      progress: 0,
      message: '',
    })
  }, [])

  const handleFileSelect = useCallback(
    async (mode: 'audio' | 'video', file: File) => {
      if (!sessionId || !isActive) {
        onError?.('No active session. Start a session first.')
        return
      }

      // Validate file type
      const validAudioTypes = ['audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav', 'audio/mp4', 'audio/m4a', 'audio/x-m4a', 'audio/ogg', 'audio/webm', 'audio/flac']
      const validVideoTypes = ['video/mp4', 'video/quicktime', 'video/x-msvideo', 'video/x-matroska', 'video/webm', 'video/x-webm']
      const validAudioExts = ['.mp3', '.wav', '.m4a', '.ogg', '.webm', '.flac']
      const validVideoExts = ['.mp4', '.mov', '.avi', '.mkv', '.webm']
      const ext = '.' + file.name.split('.').pop()?.toLowerCase()

      if (mode === 'audio') {
        const isValidType = validAudioTypes.includes(file.type) || validAudioExts.includes(ext)
        if (!isValidType) {
          onError?.(`Unsupported audio format. Supported: MP3, WAV, M4A, OGG, WebM, FLAC`)
          return
        }
      } else {
        const isValidType = validVideoTypes.includes(file.type) || validVideoExts.includes(ext)
        if (!isValidType) {
          onError?.(`Unsupported video format. Supported: MP4, MOV, AVI, MKV, WebM`)
          return
        }
      }

      // Check file size (100MB for audio, 500MB for video)
      const maxSize = mode === 'audio' ? 100 * 1024 * 1024 : 500 * 1024 * 1024
      if (file.size > maxSize) {
        onError?.(`File too large. Maximum: ${mode === 'audio' ? '100MB' : '500MB'}`)
        return
      }

      setState({
        mode,
        status: 'uploading',
        progress: 0,
        message: `Uploading ${file.name}...`,
        fileName: file.name,
      })
      onIngestionStart?.()

      try {
        // Simulate upload progress
        progressIntervalRef.current = setInterval(() => {
          setState((s) => ({
            ...s,
            progress: Math.min(s.progress + 10, 90),
          }))
        }, 200)

        let result
        if (mode === 'audio') {
          result = await ingestAudio(sessionId, file)
        } else {
          result = await ingestVideo(sessionId, file)
        }

        if (progressIntervalRef.current) {
          clearInterval(progressIntervalRef.current)
          progressIntervalRef.current = null
        }
        setState((s) => ({ ...s, status: 'processing', progress: 95, message: 'Transcribing and fact-checking...' }))

        // Brief delay to show processing
        await new Promise((r) => setTimeout(r, 500))

        setState((s) => ({
          ...s,
          status: 'complete',
          progress: 100,
          message: `Complete! Found ${result.claims_extracted} claims, verified ${result.verifications_completed}.`,
        }))
        onIngestionComplete?.({ claims: result.claims_extracted, verifications: result.verifications_completed })
      } catch (error) {
        if (progressIntervalRef.current) {
          clearInterval(progressIntervalRef.current)
          progressIntervalRef.current = null
        }
        const message = error instanceof ApiError ? error.message : 'Ingestion failed'
        setState((s) => ({
          ...s,
          status: 'error',
          progress: 0,
          message,
          error: message,
        }))
        onError?.(message)
      }
    },
    [sessionId, isActive, onIngestionStart, onIngestionComplete, onError]
  )

  const handleUrlSubmit = useCallback(
    async (url: string) => {
      if (!sessionId || !isActive) {
        onError?.('No active session. Start a session first.')
        return
      }

      // Basic URL validation
      if (!url.trim()) {
        onError?.('Please enter a URL')
        return
      }

      try {
        new URL(url)
      } catch {
        onError?.('Invalid URL format')
        return
      }

      // Check if supported URL
      const isYouTube = /^https?:\/\/(?:www\.)?(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/shorts\/)[\w-]+/.test(url)
      const isDirectVideo = /\.(mp4|webm|mov|mkv|avi)($|\?)/i.test(url)
      if (!isYouTube && !isDirectVideo) {
        onError?.('Unsupported URL. Supported: YouTube videos and direct video links (.mp4, .webm, .mov, .mkv, .avi)')
        return
      }

      setState({
        mode: 'url',
        status: 'processing',
        progress: 10,
        message: 'Downloading and processing video...',
        fileName: url,
      })
      onIngestionStart?.()

      try {
        progressIntervalRef.current = setInterval(() => {
          setState((s) => ({
            ...s,
            progress: Math.min(s.progress + 5, 90),
          }))
        }, 500)

        const result = await ingestVideoUrl(sessionId, url.trim())

        if (progressIntervalRef.current) {
          clearInterval(progressIntervalRef.current)
          progressIntervalRef.current = null
        }
        setState((s) => ({ ...s, progress: 95, message: 'Fact-checking complete...' }))

        await new Promise((r) => setTimeout(r, 500))

        setState((s) => ({
          ...s,
          status: 'complete',
          progress: 100,
          message: `Complete! Found ${result.claims_extracted} claims, verified ${result.verifications_completed}.`,
        }))
        onIngestionComplete?.({ claims: result.claims_extracted, verifications: result.verifications_completed })
      } catch (error) {
        if (progressIntervalRef.current) {
          clearInterval(progressIntervalRef.current)
          progressIntervalRef.current = null
        }
        const message = error instanceof ApiError ? error.message : 'URL ingestion failed'
        setState((s) => ({
          ...s,
          status: 'error',
          progress: 0,
          message,
          error: message,
        }))
        onError?.(message)
      }
    },
    [sessionId, isActive, onIngestionStart, onIngestionComplete, onError]
  )

  const handleAudioClick = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  const handleVideoClick = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>, mode: 'audio' | 'video') => {
      const file = e.target.files?.[0]
      if (file) {
        handleFileSelect(mode, file)
        // Reset input so same file can be selected again
        e.target.value = ''
      }
    },
    [handleFileSelect]
  )

  const handleUrlKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter') {
        handleUrlSubmit(e.currentTarget.value)
        e.currentTarget.value = ''
      }
    },
    [handleUrlSubmit]
  )

  if (!isActive || !sessionId) {
    return null
  }

  return (
    <section className="ingestion-controls" aria-label="Recorded media ingestion">
      <div className="controls__group">
        <button
          type="button"
          className="button"
          onClick={handleAudioClick}
          disabled={state.status === 'uploading' || state.status === 'processing'}
          title="Upload an audio file (MP3, WAV, M4A, OGG, WebM, FLAC)"
        >
          Upload Audio
        </button>
        <button
          type="button"
          className="button"
          onClick={handleVideoClick}
          disabled={state.status === 'uploading' || state.status === 'processing'}
          title="Upload a video file (MP4, MOV, WebM, AVI, MKV)"
        >
          Upload Video
        </button>
        <input
          ref={urlInputRef}
          type="url"
          placeholder="Paste YouTube or video URL..."
          className="ingestion-url-input"
          onKeyDown={handleUrlKeyDown}
          disabled={state.status === 'uploading' || state.status === 'processing'}
          title="Paste a YouTube URL or direct video link"
        />
        <button
          type="button"
          className="button"
          onClick={() => handleUrlSubmit(urlInputRef.current?.value || '')}
          disabled={state.status === 'uploading' || state.status === 'processing'}
          title="Analyze video URL"
        >
          Analyze URL
        </button>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        style={{ display: 'none' }}
        onChange={(e) => handleFileChange(e, state.mode === 'audio' ? 'audio' : 'video')}
        accept="audio/*,video/*"
      />

      {state.status !== 'idle' && (
        <div className="ingestion-progress" role="status" aria-live="polite">
          <div className="ingestion-progress__header">
            <span className="ingestion-progress__file">{state.fileName || 'Processing...'}</span>
            <span className="ingestion-progress__status">{state.message}</span>
          </div>
          <div className="ingestion-progress__bar">
            <div
              className="ingestion-progress__fill"
              style={{ width: `${state.progress}%` }}
            />
          </div>
          {state.status === 'error' && (
            <div className="ingestion-progress__error">
              Error: {state.error}
              <button
                type="button"
                className="button button--small"
                onClick={resetState}
              >
                Dismiss
              </button>
            </div>
          )}
          {state.status === 'complete' && (
            <div className="ingestion-progress__success">
              {state.message}
              <button
                type="button"
                className="button button--small"
                onClick={resetState}
              >
                Done
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
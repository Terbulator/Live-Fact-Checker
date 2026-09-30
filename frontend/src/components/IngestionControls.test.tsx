/**
 * Tushar's ingestion controls, as the dashboard actually mounts them.
 *
 * The regression these guard against is a wiring one, not a logic one. When
 * the application shell was replaced by the router, the dashboard moved into
 * `LiveCheckerApp` and `IngestionControls` -- which had only ever been mounted
 * by the old shell -- stopped rendering, so audio, video and URL ingestion
 * silently disappeared from the product while every file stayed in the repo.
 *
 * So these tests deliberately render `LiveCheckerApp` (what `/dashboard`
 * renders) rather than `IngestionControls` in isolation: rendering the
 * component on its own would keep passing even while nothing on screen could
 * reach it.
 *
 * The microphone flow is asserted present in the same render, because
 * reconnecting ingestion must never cost us the live path.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { IngestionControls } from './IngestionControls'
import LiveCheckerApp from './LiveCheckerApp'
import { ingestAudio, ingestVideo, ingestVideoUrl } from '../lib/api'
import { initialLiveView } from '../types/model'

vi.mock('../lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/api')>()),
  ingestAudio: vi.fn(),
  ingestVideo: vi.fn(),
  ingestVideoUrl: vi.fn(),
}))

const sessionState = {
  sessionId: 'session-1',
  status: 'active' as const,
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:01Z',
  connectedClients: 1,
  transcriptCount: 0,
  claimCount: 0,
  verificationCount: 0,
  errorCount: 0,
  wsUrl: 'ws://localhost/ws/session/session-1',
}

const activeSession = vi.hoisted(() => ({
  current: true,
}))

vi.mock('../hooks/useSession', () => ({
  useSession: () =>
    activeSession.current
      ? {
          phase: 'active',
          connection: 'open',
          session: sessionState,
          view: initialLiveView,
          fault: null,
          start: vi.fn(),
          stop: vi.fn(),
          reconnect: vi.fn(),
          dismissFault: vi.fn(),
          clearErrors: vi.fn(),
        }
      : {
          phase: 'idle',
          connection: 'closed',
          session: null,
          view: initialLiveView,
          fault: null,
          start: vi.fn(),
          stop: vi.fn(),
          reconnect: vi.fn(),
          dismissFault: vi.fn(),
          clearErrors: vi.fn(),
        },
}))

vi.mock('../hooks/useVoiceSession', () => ({
  useVoiceSession: () => ({
    status: 'idle',
    error: null,
    start: vi.fn(),
    stop: vi.fn(),
  }),
}))

const okResponse = {
  source_id: 'src-1',
  status: 'completed',
  message: 'ok',
  claims_extracted: 2,
  verifications_completed: 2,
}

beforeEach(() => {
  activeSession.current = true
  vi.mocked(ingestAudio).mockResolvedValue(okResponse)
  vi.mocked(ingestVideo).mockResolvedValue(okResponse)
  vi.mocked(ingestVideoUrl).mockResolvedValue(okResponse)
})

afterEach(() => {
  vi.clearAllMocks()
})

/** The hidden file input both upload buttons share. */
function fileInput(): HTMLInputElement {
  const input = document.querySelector('input[type="file"]')
  if (!input) throw new Error('no file input rendered')
  return input as HTMLInputElement
}

function selectFile(name: string, type: string) {
  const file = new File(['binary'], name, { type })
  fireEvent.change(fileInput(), { target: { files: [file] } })
  return file
}

// ---------------------------------------------------------------------------
// 1. Wiring: the dashboard mounts it
// ---------------------------------------------------------------------------

describe('IngestionControls wiring', () => {
  it('is reachable from the dashboard surface, alongside the microphone flow', () => {
    render(<LiveCheckerApp />)

    expect(screen.getByRole('button', { name: 'Upload Audio' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upload Video' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Analyze URL' })).toBeInTheDocument()

    // The live microphone path must survive the reconnection. While a session
    // is active the same control reads "Live now".
    expect(screen.getByRole('button', { name: /live now/i })).toBeInTheDocument()
  })

  it('still asks for a session before offering ingestion', () => {
    activeSession.current = false
    render(<LiveCheckerApp />)

    // No active session means no upload controls at all, exactly as before.
    expect(screen.queryByRole('button', { name: 'Upload Audio' })).not.toBeInTheDocument()
    // The live microphone control must survive alongside ingestion. This one
    // renders with no active session, where the button reads "Go live"; the
    // test above, with a session running, reads "Live now". The label is
    // state-dependent, so each test matches its own state.
    expect(screen.getByRole('button', { name: /go live/i })).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// 2-4. Each mode calls the existing API function, and only that one
// ---------------------------------------------------------------------------

describe('IngestionControls API calls', () => {
  it('uploads audio through the existing ingestAudio()', async () => {
    render(<IngestionControls sessionId="session-1" isActive />)

    const file = selectFile('interview.mp3', 'audio/mpeg')

    await waitFor(() => expect(ingestAudio).toHaveBeenCalledTimes(1))
    expect(ingestAudio).toHaveBeenCalledWith('session-1', file)
    expect(ingestVideo).not.toHaveBeenCalled()
    expect(ingestVideoUrl).not.toHaveBeenCalled()
  })

  it('uploads video through the existing ingestVideo()', async () => {
    render(<IngestionControls sessionId="session-1" isActive />)

    // "Upload Video" and "Upload Audio" share one hidden input; the mode is
    // whatever the component last selected, so drive it through the buttons.
    fireEvent.click(screen.getByRole('button', { name: 'Upload Video' }))
    const file = selectFile('clip.mp4', 'video/mp4')

    await waitFor(() => expect(ingestVideo).toHaveBeenCalledTimes(1))
    expect(ingestVideo).toHaveBeenCalledWith('session-1', file)
    expect(ingestAudio).not.toHaveBeenCalled()
    expect(ingestVideoUrl).not.toHaveBeenCalled()
  })

  it('sends a video URL through the existing ingestVideoUrl()', async () => {
    render(<IngestionControls sessionId="session-1" isActive />)

    const url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
    fireEvent.change(screen.getByPlaceholderText(/paste youtube/i), { target: { value: url } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze URL' }))

    await waitFor(() => expect(ingestVideoUrl).toHaveBeenCalledTimes(1))
    expect(ingestVideoUrl).toHaveBeenCalledWith('session-1', url)
    expect(ingestAudio).not.toHaveBeenCalled()
    expect(ingestVideo).not.toHaveBeenCalled()
  })

  it('reports how many claims the ingestion produced', async () => {
    render(<IngestionControls sessionId="session-1" isActive />)

    const url = 'https://youtu.be/dQw4w9WgXcQ'
    fireEvent.change(screen.getByPlaceholderText(/paste youtube/i), { target: { value: url } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze URL' }))

    await waitFor(() =>
      // The summary line is rendered in both the status header and the success
      // block, so assert on all matches rather than a single node.
      expect(screen.getAllByText(/found 2 claims, verified 2/i).length).toBeGreaterThan(0),
    )
  })

  it('refuses to ingest without a session rather than calling the API', () => {
    const onError = vi.fn()
    render(<IngestionControls sessionId={null} isActive onError={onError} />)

    expect(screen.queryByRole('button', { name: 'Upload Audio' })).not.toBeInTheDocument()
    expect(ingestAudio).not.toHaveBeenCalled()
    expect(onError).not.toHaveBeenCalled()
  })
})

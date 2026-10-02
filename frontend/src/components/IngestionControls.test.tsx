/**
 * Recorded-media ingestion, as the dashboard actually mounts it.
 *
 * The regression these guard against is a wiring one, not a logic one. When the
 * application shell was replaced by the router, the dashboard moved into
 * `LiveCheckerApp` and `IngestionControls` -- which had only ever been mounted
 * by the old shell -- stopped rendering, so audio, video and URL ingestion
 * silently disappeared from the product while every file stayed in the repo.
 *
 * So these tests deliberately render `LiveCheckerApp` (what `/dashboard`
 * renders) rather than the ingestion component in isolation: rendering the
 * component on its own would keep passing even while nothing on screen could
 * reach it.
 *
 * The surface has since become a conversation with one composer, so the three
 * recorded inputs are attachments inside it and are submitted by the single Send
 * rather than by their own buttons. What must not change is that a submission
 * carries a session that really exists.
 *
 * The microphone flow is asserted in the same render, because reconnecting
 * ingestion must never cost us the live path.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import LiveCheckerApp from './LiveCheckerApp'
import { ingestAudio, ingestVideo, ingestVideoUrl, submitClaim } from '../lib/api'
import { initialLiveView } from '../types/model'

vi.mock('../lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/api')>()),
  ingestAudio: vi.fn(),
  ingestVideo: vi.fn(),
  ingestVideoUrl: vi.fn(),
  submitClaim: vi.fn(),
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

const activeSession = vi.hoisted(() => ({ current: true }))
const startSession = vi.hoisted(() => vi.fn())

vi.mock('../hooks/useSession', () => ({
  useSession: () =>
    activeSession.current
      ? {
          phase: 'active',
          connection: 'open',
          session: sessionState,
          view: initialLiveView,
          fault: null,
          start: startSession,
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
          start: startSession,
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
    isMicrophoneActive: false,
    start: vi.fn(),
    stop: vi.fn(),
  }),
}))

/**
 * Stubbed as a guest. The sidebar's account card reads the auth provider, and
 * these cases are about ingestion rather than about who is signed in.
 */
vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({
    status: 'anonymous',
    user: null,
    configured: true,
    ready: true,
    signUp: vi.fn(),
    signIn: vi.fn(),
    signOut: vi.fn(),
  }),
  displayName: () => 'Guest',
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
  vi.mocked(submitClaim).mockResolvedValue({
    accepted: true,
    sessionId: 'session-1',
    claim: {
      type: 'claim',
      eventId: 'e1',
      claimId: 'c1',
      sessionId: 'session-1',
      speaker: 'Speaker 1',
      timestamp: 0,
      claim: 'A claim.',
      claimType: 'unspecified',
    },
    counts: { claims: 1, verifications: 0, transcripts: 0, errors: 0 },
    verifications: [],
    idempotent: false,
  })
})

afterEach(() => {
  vi.clearAllMocks()
})

/**
 * `/dashboard` always renders inside the router, and the shell's sidebar links
 * home and to login, so a render of it needs the same context the real route
 * provides.
 */
function renderDashboard() {
  return render(
    <MemoryRouter>
      <LiveCheckerApp />
    </MemoryRouter>,
  )
}

/** The composer's hidden file input for one kind of media. */
function fileInput(kind: 'video' | 'audio'): HTMLInputElement {
  const input = document.querySelector(`input[type="file"][accept="${kind}/*"]`)
  if (!input) throw new Error(`no ${kind} file input rendered`)
  return input as HTMLInputElement
}

function chooseFile(kind: 'video' | 'audio', name: string, type: string) {
  const file = new File(['binary'], name, { type })
  fireEvent.change(fileInput(kind), { target: { files: [file] } })
  return file
}

function send() {
  fireEvent.click(screen.getByRole('button', { name: /^send$/i }))
}

// ---------------------------------------------------------------------------
// 1. Wiring: the dashboard reaches all three recorded inputs
// ---------------------------------------------------------------------------

describe('recorded media is reachable from the dashboard', () => {
  it('offers video, audio and voice in the composer', () => {
    renderDashboard()

    expect(screen.getByRole('button', { name: /add video/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /add audio/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /voice/i })).toBeInTheDocument()

    // One composer, one Send. The old per-mode buttons are gone on purpose.
    expect(screen.getAllByRole('button', { name: /^send$/i })).toHaveLength(1)
    expect(screen.queryByRole('button', { name: /^analyze url$/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^go live$/i })).not.toBeInTheDocument()
  })

  it('uploads a video through the existing ingestVideo()', async () => {
    renderDashboard()

    const file = chooseFile('video', 'clip.mp4', 'video/mp4')
    send()

    await waitFor(() => expect(ingestVideo).toHaveBeenCalledTimes(1))
    expect(ingestVideo).toHaveBeenCalledWith('session-1', file)
    expect(ingestAudio).not.toHaveBeenCalled()
    expect(ingestVideoUrl).not.toHaveBeenCalled()
  })

  it('uploads audio through the existing ingestAudio()', async () => {
    renderDashboard()

    const file = chooseFile('audio', 'interview.mp3', 'audio/mpeg')
    send()

    await waitFor(() => expect(ingestAudio).toHaveBeenCalledTimes(1))
    expect(ingestAudio).toHaveBeenCalledWith('session-1', file)
    expect(ingestVideo).not.toHaveBeenCalled()
  })

  it('sends a video link through the existing ingestVideoUrl()', async () => {
    renderDashboard()

    const url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
    fireEvent.change(screen.getByRole('textbox'), { target: { value: url } })
    send()

    await waitFor(() => expect(ingestVideoUrl).toHaveBeenCalledTimes(1))
    expect(ingestVideoUrl).toHaveBeenCalledWith('session-1', url)
    expect(ingestVideo).not.toHaveBeenCalled()
  })

  it('posts a typed claim through the existing claim ingress', async () => {
    renderDashboard()

    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'Water boils at 100C at sea level.' },
    })
    send()

    await waitFor(() => expect(submitClaim).toHaveBeenCalledTimes(1))
    expect(vi.mocked(submitClaim).mock.calls[0]?.[0]).toMatchObject({
      sessionId: 'session-1',
      claim: 'Water boils at 100C at sea level.',
    })
    expect(ingestVideoUrl).not.toHaveBeenCalled()
  })

  it('shows the attachment in the composer before anything is sent', () => {
    renderDashboard()

    chooseFile('video', 'clip.mp4', 'video/mp4')

    expect(screen.getByText('clip.mp4')).toBeInTheDocument()
    // Nothing has been uploaded yet: selecting a file is not submitting it.
    expect(ingestVideo).not.toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// 2. The invariant: nothing is ingested without a session
// ---------------------------------------------------------------------------

describe('a session is required before anything is ingested', () => {
  it('creates one on demand and ingests into it', async () => {
    activeSession.current = false
    startSession.mockResolvedValue(sessionState)
    renderDashboard()

    const file = chooseFile('video', 'clip.mp4', 'video/mp4')
    send()

    await waitFor(() => expect(ingestVideo).toHaveBeenCalledTimes(1))
    expect(startSession).toHaveBeenCalled()
    expect(ingestVideo).toHaveBeenCalledWith('session-1', file)
  })

  it('never ingests when the session cannot be created', async () => {
    activeSession.current = false
    startSession.mockResolvedValue(null)
    renderDashboard()

    chooseFile('video', 'clip.mp4', 'video/mp4')
    send()

    await waitFor(() => expect(startSession).toHaveBeenCalled())
    // The session never existed, so nothing may be sent against it.
    expect(ingestVideo).not.toHaveBeenCalled()
  })

  it('refuses an unsupported file before any upload is attempted', async () => {
    renderDashboard()

    chooseFile('video', 'notes.txt', 'text/plain')
    send()

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(ingestVideo).not.toHaveBeenCalled()
  })
})

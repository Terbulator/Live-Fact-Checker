/**
 * The conversation, end to end.
 *
 * These render `/dashboard` with a real event stream behind it and assert the
 * shape a reader actually meets: their message, the pipeline, the answer, and
 * then everything else folded away behind four rows.
 *
 * The property worth guarding is progressive disclosure. The claims, the sources,
 * the transcript and the processing steps must all be *present* and *reachable*
 * while being absent from the default screen -- a reader should never have to
 * scroll past evidence to find the verdict, and should never lose the evidence
 * either.
 */

import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import LiveCheckerApp from './LiveCheckerApp'
import { submitClaim } from '../lib/api'
import type { ClaimCard, TranscriptLine } from '../types/model'
import type { VerificationEvent, Verdict } from '../types/events'

vi.mock('../lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/api')>()),
  submitClaim: vi.fn(),
  ingestAudio: vi.fn(),
  ingestVideo: vi.fn(),
  ingestVideoUrl: vi.fn(),
}))

/**
 * The account card in the sidebar reads the auth provider, and the provider is
 * the app's one source of who is signed in. These tests are about the
 * conversation, not about authentication, so the account is stubbed as a guest
 * rather than standing up a real session behind every case. `displayName` is
 * re-exported here because the component imports both from this module.
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
  displayName: (user: { user_metadata?: { name?: string } } | null) => user?.user_metadata?.name ?? 'Guest',
}))

function verification(overrides: Partial<VerificationEvent> = {}): VerificationEvent {
  return {
    type: 'verification',
    eventId: 'e1',
    claimId: 'c1',
    sessionId: 'session-1',
    speaker: 'Speaker 1',
    timestamp: 12.4,
    verdict: 'TRUE' as Verdict,
    reason: 'Authoritative sources corroborate the key facts.',
    source: 'https://icc-cricket.com/archive',
    supportingStatement: 'icc-cricket.com states: “India won the 2011 World Cup.”',
    confidence: 0.92,
    sources: [
      {
        url: 'https://icc-cricket.com/archive',
        title: 'ICC Archive',
        snippet: 'India defeated Sri Lanka to win the 2011 World Cup.',
      },
    ],
    ...overrides,
  }
}

function claim(overrides: Partial<ClaimCard> = {}): ClaimCard {
  return {
    claimId: 'c1',
    speaker: 'Speaker 1',
    timestamp: 12.4,
    claim: 'India won the 2011 Cricket World Cup.',
    claimType: 'historical_fact',
    pending: false,
    verification: verification(),
    transcriptKey: 'Speaker 1@12.40',
    ...overrides,
  }
}

const lines: TranscriptLine[] = [
  {
    key: 'Speaker 1@12.40',
    speaker: 'Speaker 1',
    text: 'India won the 2011 Cricket World Cup.',
    timestamp: 12.4,
    isFinal: true,
    claimId: 'c1',
  },
  {
    key: 'Speaker 2@28.10',
    speaker: 'Speaker 2',
    text: 'The Eiffel Tower is in India.',
    timestamp: 28.1,
    isFinal: true,
    claimId: 'c2',
  },
]

const claims: ClaimCard[] = [
  claim(),
  claim({
    claimId: 'c2',
    speaker: 'Speaker 2',
    timestamp: 28.1,
    claim: 'The Eiffel Tower is in India.',
    verification: verification({
      eventId: 'e2',
      claimId: 'c2',
      verdict: 'FALSE' as Verdict,
      reason: 'The Eiffel Tower stands in Paris.',
      source: 'https://en.wikipedia.org/wiki/Eiffel_Tower',
      sources: [],
    }),
    transcriptKey: 'Speaker 2@28.10',
  }),
]

const sessionState = {
  sessionId: 'session-1',
  status: 'active' as const,
  createdAt: new Date().toISOString(),
  updatedAt: new Date().toISOString(),
  connectedClients: 1,
  transcriptCount: 2,
  claimCount: 2,
  verificationCount: 2,
  errorCount: 0,
  wsUrl: 'ws://localhost/ws/session/session-1',
}

vi.mock('../hooks/useSession', () => ({
  useSession: () => ({
    phase: 'active',
    connection: 'open',
    session: sessionState,
    view: {
      transcripts: lines,
      claims,
      errors: [],
      status: 'active',
      lastSpeechAt: null,
      lastSpeaker: null,
      processedEventIds: new Set<string>(),
    },
    fault: null,
    start: vi.fn(),
    stop: vi.fn(),
    reconnect: vi.fn(),
    dismissFault: vi.fn(),
    clearErrors: vi.fn(),
  }),
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

beforeEach(() => {
  window.localStorage.clear()
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
      claim: 'India won the 2011 Cricket World Cup.',
      claimType: 'unspecified',
    },
    counts: { claims: 2, verifications: 2, transcripts: 2, errors: 0 },
    verifications: [],
    idempotent: false,
  })
})

function open() {
  return render(
    <MemoryRouter>
      <LiveCheckerApp />
    </MemoryRouter>,
  )
}

/** Send a claim through the single composer. */
function sendClaim(text: string) {
  fireEvent.change(screen.getByRole('textbox'), { target: { value: text } })
  fireEvent.click(screen.getByRole('button', { name: /^send$/i }))
}

describe('the conversation', () => {
  it('opens on an empty promise rather than on results', () => {
    open()

    expect(screen.getByRole('heading', { name: /fact-check anything/i })).toBeInTheDocument()
    expect(screen.getByText(/send a claim, video, url, audio, or start listening/i)).toBeInTheDocument()
    // Nothing is claimed before anything has been checked.
    expect(screen.queryByText('TRUE')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /claims/i })).not.toBeInTheDocument()
  })

  it('shows the reader their own message, then the answer', () => {
    open()
    sendClaim('India won the 2011 Cricket World Cup.')

    const message = within(screen.getByRole('article', { name: /your message/i }))
    expect(message.getByText('India won the 2011 Cricket World Cup.')).toBeInTheDocument()
    expect(screen.getByText(/live fact checker/i)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /fact-check complete/i })).toBeInTheDocument()
    // The sentence names what was checked and where it came from, not a score.
    expect(screen.getByText(/checked 2 claims from that claim/i)).toBeInTheDocument()
  })

  it('counts the verdicts it actually received', () => {
    open()
    sendClaim('India won the 2011 Cricket World Cup.')

    const result = within(screen.getByRole('region', { name: /fact-check result/i }))
    // One TRUE, one FALSE, and two buckets that were measured and found empty.
    expect(result.getByText('TRUE')).toBeInTheDocument()
    expect(result.getByText('FALSE')).toBeInTheDocument()
    expect(result.getByText('UNVERIFIABLE')).toBeInTheDocument()
    expect(result.getByText('AMBIGUOUS')).toBeInTheDocument()
    expect(result.getAllByText('1')).toHaveLength(2)
    expect(result.getAllByText('0')).toHaveLength(2)
  })

  it('collapses every detail behind a row, and keeps it reachable', () => {
    open()
    sendClaim('India won the 2011 Cricket World Cup.')

    const rows = [
      screen.getByRole('button', { name: /^claims/i }),
      screen.getByRole('button', { name: /^sources/i }),
      screen.getByRole('button', { name: /^transcript/i }),
      screen.getByRole('button', { name: /^processing details/i }),
    ]
    for (const row of rows) expect(row).toHaveAttribute('aria-expanded', 'false')

    // The evidence is present but not shown until it is asked for.
    expect(screen.queryByText('The Eiffel Tower stands in Paris.')).not.toBeInTheDocument()

    fireEvent.click(rows[0] as HTMLElement)
    expect(rows[0]).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('The Eiffel Tower stands in Paris.')).toBeInTheDocument()
    // The supporting statement and the citation come with the claim.
    expect(screen.getByText(/India defeated Sri Lanka/)).toBeInTheDocument()
  })

  it('lists the sources with their real links and provider scores', () => {
    open()
    sendClaim('India won the 2011 Cricket World Cup.')

    fireEvent.click(screen.getByRole('button', { name: /^sources/i }))

    const sources = within(screen.getByRole('region', { name: /^sources/i }))
    const link = sources.getByRole('link', { name: /icc archive/i })
    expect(link).toHaveAttribute('href', 'https://icc-cricket.com/archive')
    expect(sources.getByText('icc-cricket.com')).toBeInTheDocument()
    expect(sources.getAllByText(/provider relevance 0\.92/i).length).toBe(2)
    // The snippet survives being cited both as the primary source and as an
    // evidence row, which is how the backend usually sends it.
    expect(sources.getByText(/India defeated Sri Lanka/)).toBeInTheDocument()
  })

  it('shows the transcript with its timestamps and speakers', () => {
    open()
    sendClaim('India won the 2011 Cricket World Cup.')

    fireEvent.click(screen.getByRole('button', { name: /^transcript/i }))

    const transcript = within(screen.getByRole('region', { name: /^transcript/i }))
    expect(transcript.getByText('The Eiffel Tower is in India.')).toBeInTheDocument()
    expect(transcript.getAllByText('Speaker 1').length).toBeGreaterThan(0)
    expect(transcript.getByText('0:28.1')).toBeInTheDocument()
  })

  it('reports only the stages the backend actually reached', () => {
    open()
    sendClaim('India won the 2011 Cricket World Cup.')

    fireEvent.click(screen.getByRole('button', { name: /^processing details/i }))

    const steps = within(screen.getByRole('region', { name: /^processing details/i }))
      .getAllByRole('listitem')
      .map((node) => node.textContent ?? '')

    expect(steps.length).toBeGreaterThan(0)
    // A typed claim has no audio to extract, so no stage claims one was.
    expect(steps.some((step) => /audio extracted/i.test(step))).toBe(false)
    expect(steps.every((step) => /done/i.test(step))).toBe(true)
  })

  it('records a real conversation in the history, titled from the message', () => {
    open()

    // Nothing has been sent, so there is nothing to list.
    expect(screen.getByText(/no conversations yet/i)).toBeInTheDocument()

    sendClaim('India won the 2011 Cricket World Cup.')

    const history = screen.getByRole('navigation', { name: /conversation history/i })
    expect(within(history).getByText(/india won the 2011/i)).toBeInTheDocument()
    expect(within(history).getByText(/2 claims/i)).toBeInTheDocument()
  })

  it('records the conversation once, even though the run keeps streaming', () => {
    open()
    sendClaim('India won the 2011 Cricket World Cup.')

    const history = screen.getByRole('navigation', { name: /conversation history/i })
    expect(within(history).getAllByRole('button')).toHaveLength(1)
  })

  it('never shows a percentage the backend did not report', () => {
    open()
    sendClaim('India won the 2011 Cricket World Cup.')

    expect(screen.queryByText(/%/)).not.toBeInTheDocument()
  })
})

/**
 * Connection and session status.
 *
 * Answers the two questions a viewer has before trusting anything on screen:
 * is the backend reachable, and is this browser actually receiving its stream.
 *
 * The speech indicator is deliberately loud while audio is arriving and quiet
 * afterwards, so "someone is talking right now" is legible from across a room.
 */

import type { ConnectionState } from '../hooks/useSessionSocket'
import type { SessionPhase } from '../hooks/useSession'
import { displaySpeaker } from '../lib/format'

/** How recently speech must have arrived to still read as "talking". */
const SPEAKING_WINDOW_MS = 1800

const CONNECTION_LABELS: Record<ConnectionState, string> = {
  idle: 'Offline',
  connecting: 'Connecting…',
  open: 'Live',
  closed: 'Reconnecting…',
  error: 'Connection lost',
}

const CONNECTION_HINTS: Record<ConnectionState, string> = {
  idle: 'No session running',
  connecting: 'Opening the session stream',
  open: 'Receiving events',
  closed: 'Reopening the session stream',
  error: 'Cannot reach the backend',
}

export interface StatusBarProps {
  phase: SessionPhase
  connection: ConnectionState
  backendUrl: string
  sessionId: string | null
  connectedClients: number | null
  /** Wall-clock for the speech indicator. */
  now: number
  /** Timestamp of the last transcript event, or null. */
  lastSpeechAt: number | null
  lastSpeaker: string | null
  /** Whether the current session is replaying the scripted mock pipeline. */
  isDemo: boolean
}

export function StatusBar({
  phase,
  connection,
  backendUrl,
  sessionId,
  connectedClients,
  now,
  lastSpeechAt,
  lastSpeaker,
  isDemo,
}: StatusBarProps) {
  const isLive = connection === 'open'
  const speaking =
    isLive &&
    lastSpeechAt !== null &&
    now - lastSpeechAt < SPEAKING_WINDOW_MS

  // The pill is the single place that says what the pipeline is doing, so it
  // absorbs the session phase too: while a session is being created there is
  // nothing on the socket yet, and saying "Listening" would be a lie.
  let pillLabel: string
  if (phase === 'starting') pillLabel = 'Starting session…'
  else if (isLive) pillLabel = speaking ? displaySpeaker(lastSpeaker) : 'Listening'
  else pillLabel = CONNECTION_LABELS[connection]

  const isDegraded = connection === 'error' || connection === 'closed'

  return (
    <header className="topbar">
      <div className="topbar__brand">
        <span className="topbar__mark" aria-hidden="true" />
        <div>
          <h1 className="topbar__title">
            Live Fact-Checker
            {isDemo && <span className="topbar__badge">Demo feed</span>}
          </h1>
          <p className="topbar__tagline">Claims checked as the debate happens</p>
        </div>
      </div>

      <div className="topbar__status">
        <span
          className={[
            'livepill',
            isLive ? 'livepill--on' : '',
            speaking ? 'livepill--speaking' : '',
            isDegraded ? 'livepill--degraded' : '',
          ]
            .filter(Boolean)
            .join(' ')}
          title={CONNECTION_HINTS[connection]}
        >
          <span className="livepill__dot" aria-hidden="true" />
          {pillLabel}
        </span>

        <dl className="topbar__facts">
          <div className="topbar__fact">
            <dt>Session</dt>
            <dd title={sessionId ?? undefined}>{sessionId ?? '—'}</dd>
          </div>
          <div className="topbar__fact">
            <dt>Judges</dt>
            <dd title="WebSocket clients watching this session">
              {connectedClients ?? 0}
            </dd>
          </div>
          <div className="topbar__fact">
            <dt>Backend</dt>
            <dd title={backendUrl}>{backendUrl.replace(/^https?:\/\//, '')}</dd>
          </div>
        </dl>
      </div>
    </header>
  )
}

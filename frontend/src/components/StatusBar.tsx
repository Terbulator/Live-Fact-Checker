/**
 * Connection and session status bar.
 *
 * Surfaces the two states a user actually needs to trust the demo:
 *
 * - is the backend reachable at all
 * - is this browser receiving its live event stream
 */

import type { ConnectionState } from '../hooks/useSessionSocket'
import type { SessionPhase } from '../hooks/useSession'

const CONNECTION_LABELS: Record<ConnectionState, string> = {
  idle: 'Not connected',
  connecting: 'Connecting',
  open: 'Live',
  closed: 'Disconnected',
  error: 'Connection error',
}

export interface StatusBarProps {
  phase: SessionPhase
  connection: ConnectionState
  backendUrl: string
  sessionId: string | null
  connectedClients: number | null
}

export function StatusBar({
  phase,
  connection,
  backendUrl,
  sessionId,
  connectedClients,
}: StatusBarProps) {
  const isLive = connection === 'open'

  return (
    <header className="status-bar">
      <div className="status-bar__brand">
        <h1 className="status-bar__title">Live Fact-Checker</h1>
        <p className="status-bar__subtitle">Real-time claim verification</p>
      </div>

      <dl className="status-bar__facts">
        <div className="status-bar__fact">
          <dt>Backend</dt>
          <dd>{backendUrl}</dd>
        </div>
        <div className="status-bar__fact">
          <dt>Session</dt>
          <dd>{sessionId ?? '—'}</dd>
        </div>
        <div className="status-bar__fact">
          <dt>Clients</dt>
          <dd>{connectedClients ?? 0}</dd>
        </div>
        <div className="status-bar__fact">
          <dt>Stream</dt>
          <dd>
            <span
              className={`pill pill--${isLive ? 'live' : 'idle'}`}
              aria-live="polite"
            >
              {CONNECTION_LABELS[connection]}
            </span>
          </dd>
        </div>
      </dl>

      {phase === 'starting' && (
        <span className="status-bar__phase">Starting session…</span>
      )}
    </header>
  )
}

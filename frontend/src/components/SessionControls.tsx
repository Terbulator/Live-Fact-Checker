/**
 * Session controls.
 *
 * Two entry points, because the project has two very different situations:
 *
 * - **Go live** starts an empty session for real microphone input. The
 *   `voice/` module posts transcripts into it; this frontend only watches.
 * - **Run demo** starts a session with the backend's scripted mock pipeline,
 *   which exercises transcript -> claim -> verification end to end with no
 *   AssemblyAI, LLM or search credentials configured.
 */

import type { SessionPhase } from '../hooks/useSession'

export interface SessionControlsProps {
  phase: SessionPhase
  onStart: (options?: { demo?: boolean }) => void
  onStop: () => void
  onReconnect: () => void
}

export function SessionControls({
  phase,
  onStart,
  onStop,
  onReconnect,
}: SessionControlsProps) {
  const isStarting = phase === 'starting'
  const isStopping = phase === 'stopping'
  const isActive = phase === 'active'

  return (
    <section className="controls" aria-label="Session controls">
      <button
        type="button"
        className="button button--primary"
        onClick={() => onStart({ demo: false })}
        disabled={isStarting || isActive}
      >
        Go live
      </button>

      <button
        type="button"
        className="button"
        onClick={() => onStart({ demo: true })}
        disabled={isStarting || isActive}
        title="Replays the backend's scripted mock pipeline. Needs no API keys."
      >
        Run demo
      </button>

      <button
        type="button"
        className="button"
        onClick={onReconnect}
        disabled={!isActive}
        title="Reopen the WebSocket for the current session."
      >
        Reconnect
      </button>

      <button
        type="button"
        className="button button--danger"
        onClick={onStop}
        disabled={!isActive && !isStopping}
      >
        Stop session
      </button>
    </section>
  )
}

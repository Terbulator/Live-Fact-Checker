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
 *
 * The demo button is the one to press on stage: it is the only path that works
 * without any credential, so it cannot fail silently in front of a judge.
 *
 * The bar is only shown once a session exists. Before that, the actions live in
 * the introduction screen, where they are the only thing on the page.
 */

import type { SessionPhase } from '../hooks/useSession'

export interface SessionControlsProps {
  phase: SessionPhase
  onStart: (options?: { demo?: boolean }) => void
  onStop: () => void
  onReconnect: () => void
}

const HINTS: Partial<Record<SessionPhase, string>> = {
  idle: 'Nothing is running. Pick a mode to begin.',
  active: 'Listening for events on this session.',
  stopping: 'Closing the session and its clients…',
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
      <div className="controls__group">
        <button
          type="button"
          className="button button--primary"
          onClick={() => onStart({ demo: false })}
          disabled={isStarting || isActive}
        >
          {isActive ? 'Live now' : 'Go live'}
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
      </div>

      <div className="controls__group controls__group--end">
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
          {isStopping ? 'Stopping…' : 'Stop session'}
        </button>
      </div>

      {HINTS[phase] !== undefined && <span className="controls__hint">{HINTS[phase]}</span>}
    </section>
  )
}

/**
 * Session lifecycle for the live view.
 *
 * Owns the one piece of shared state the UI needs: which session is active,
 * where its WebSocket lives, and the reduced view of everything the backend
 * has broadcast.
 *
 * The frontend never posts transcripts or claims. Those ingress paths exist
 * for the `voice/` module and for externally produced verifications. This hook
 * only *starts*, *watches* and *stops*.
 */

import { useCallback, useMemo, useReducer, useState } from 'react'

import { ApiError, startSession, stopSession } from '../lib/api'
import { resolveWsUrl } from '../lib/config'
import { liveViewReducer } from '../lib/reducer'
import { initialLiveView, type LiveView } from '../types/model'
import type { ServerEvent, SessionState } from '../types/events'
import { useSessionSocket, type ConnectionState } from './useSessionSocket'

export type SessionPhase = 'idle' | 'starting' | 'active' | 'stopping'

export interface UseSessionResult {
  phase: SessionPhase
  connection: ConnectionState
  session: SessionState | null
  /** The reduced view of everything the backend has broadcast. */
  view: LiveView
  /** Transport-level or API failure, distinct from backend `error` events. */
  fault: string | null
  /** Start a session. `demo` replays the backend's scripted mock pipeline. */
  start: (options?: { demo?: boolean }) => Promise<void>
  /** Stop the session and close the socket. */
  stop: () => Promise<void>
  /** Reopen the socket against the same session. */
  reconnect: () => void
  /** Clear the fault banner. */
  dismissFault: () => void
  /** Discard the accumulated backend `error` events. */
  clearErrors: () => void
}

function describe(error: unknown): string {
  if (error instanceof ApiError) return `${error.code}: ${error.message}`
  if (error instanceof Error) return error.message
  return 'Unexpected error.'
}

export function useSession(): UseSessionResult {
  const [session, setSession] = useState<SessionState | null>(null)
  const [phase, setPhase] = useState<SessionPhase>('idle')
  const [fault, setFault] = useState<string | null>(null)
  const [view, dispatch] = useReducer(liveViewReducer, initialLiveView)

  const handleEvent = useCallback((event: ServerEvent) => {
    dispatch({ type: 'event', event })
  }, [])

  const wsUrl = useMemo(() => {
    if (session === null) return null
    return resolveWsUrl(session.sessionId, session.wsUrl)
  }, [session])

  const { state: connection, error: socketError, reconnect } = useSessionSocket({
    url: wsUrl,
    onEvent: handleEvent,
    // Hold the socket open only while a session is meant to be watched.
    enabled: phase === 'active' || phase === 'stopping',
  })

  const start = useCallback(
    async (options?: { demo?: boolean }) => {
      setPhase('starting')
      setFault(null)
      try {
        const created = await startSession(options?.demo ?? false)
        setSession(created)
        setPhase('active')
      } catch (error) {
        setPhase('idle')
        setSession(null)
        setFault(describe(error))
      }
    },
    [],
  )

  const stop = useCallback(async () => {
    if (session === null) return
    setPhase('stopping')
    try {
      await stopSession(session.sessionId)
    } catch (error) {
      setFault(describe(error))
    } finally {
      setSession(null)
      setPhase('idle')
    }
  }, [session])

  const dismissFault = useCallback(() => setFault(null), [])

  const clearErrors = useCallback(() => {
    dispatch({ type: 'clearErrors' })
  }, [])

  return {
    phase,
    connection,
    session,
    view,
    fault: fault ?? socketError,
    start,
    stop,
    reconnect,
    dismissFault,
    clearErrors,
  }
}

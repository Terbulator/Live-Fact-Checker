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

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { ApiError, getSession, startSession, stopSession } from '../lib/api'
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
  const processedEventIdsRef = useRef<Set<string>>(new Set())

  const handleEvent = useCallback((event: ServerEvent) => {
    if (event.type === 'pong') {
      dispatch({ type: 'event', event })
      return
    }

    if (processedEventIdsRef.current.has(event.eventId)) {
      return
    }

    processedEventIdsRef.current.add(event.eventId)
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
      // Clear the previous session's transcript, claims and verdicts before the
      // new stream arrives, so repeated demos never show merged results.
      // Results stay visible while idle, and are replaced on the next start.
      processedEventIdsRef.current.clear()
      dispatch({ type: 'reset' })
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

  /**
   * Refresh the session snapshot once the socket is open.
   *
   * `POST /session/start` reports `connectedClients` as 0, because at that
   * moment this browser has not attached yet. The backend counts connections
   * live on `GET /session/{id}`, so one refresh on connect makes the count
   * accurate. This is a single request per connection, not a poll: the backend
   * pushes no session-state updates and the event contract is unchanged.
   */
  useEffect(() => {
    if (connection !== 'open' || session === null) return

    let cancelled = false
    void (async () => {
      try {
        const fresh = await getSession(session.sessionId)
        if (!cancelled) setSession(fresh)
      } catch (error) {
        // The stream is already working; a failed count refresh must not
        // disturb it or raise a fault the user cannot act on.
        if (error instanceof ApiError) {
          // Session gone server-side: stop reporting it as active.
          if (error.code === 'SESSION_NOT_FOUND') {
            setSession(null)
            setPhase('idle')
          }
        }
      }
    })()

    return () => {
      cancelled = true
    }
  }, [connection, session?.sessionId])

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

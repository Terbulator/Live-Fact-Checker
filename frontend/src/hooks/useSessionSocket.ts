/**
 * WebSocket connection to the backend's session stream.
 *
 * Uses the browser's native `WebSocket` API only, with no reconnect library.
 *
 * Behaviours the backend requires of a client:
 *
 * - On connect the server immediately sends one `session` event with status
 *   `connected`. That frame is not a duplicate of anything else, so it is
 *   passed straight through to the reducer.
 * - The client may send `{"type":"ping"}` and receives `{"type":"pong"}`,
 *   which keeps intermediaries from idling the socket out during a long
 *   debate.
 * - Connecting to an unknown `sessionId` yields an `error` event
 *   (`SESSION_NOT_FOUND`) and then nothing further, so the hook surfaces that
 *   rather than reconnecting forever.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { isServerEvent, type ServerEvent } from '../types/events'

/** Connection state of the socket, independent of session status. */
export type ConnectionState = 'idle' | 'connecting' | 'open' | 'closed' | 'error'

/** Interval between liveness pings, in milliseconds. */
const PING_INTERVAL_MS = 20_000

/** Backoff bounds for automatic reconnection, in milliseconds. */
const RECONNECT_MIN_MS = 500
const RECONNECT_MAX_MS = 10_000

export interface UseSessionSocketOptions {
  /** Absolute WebSocket URL, or null to stay disconnected. */
  url: string | null
  /** Called for every valid server event, in arrival order. */
  onEvent: (event: ServerEvent) => void
  /** Set false to stop reconnecting (e.g. the session was stopped). */
  enabled?: boolean
}

export interface UseSessionSocketResult {
  state: ConnectionState
  /** Latest transport-level message, for the status bar. */
  error: string | null
  /** Drop the socket and reconnect immediately. */
  reconnect: () => void
}

export function useSessionSocket({
  url,
  onEvent,
  enabled = true,
}: UseSessionSocketOptions): UseSessionSocketResult {
  const [state, setState] = useState<ConnectionState>('idle')
  const [error, setError] = useState<string | null>(null)
  /**
   * Bumped by `reconnect()` to force the connection effect to re-run, since a
   * reconnect to the same URL is not expressible as a dependency change.
   */
  const [nonce, setNonce] = useState(0)

  const socketRef = useRef<WebSocket | null>(null)
  const pingTimerRef = useRef<number | null>(null)
  const retryTimerRef = useRef<number | null>(null)
  const attemptRef = useRef(0)
  const closedByUsRef = useRef(false)

  /**
   * `onEvent` is stored in a ref so a new inline callback on every render does
   * not tear down and rebuild the socket.
   */
  const onEventRef = useRef(onEvent)
  useEffect(() => {
    onEventRef.current = onEvent
  }, [onEvent])

  const clearTimers = useCallback(() => {
    if (pingTimerRef.current !== null) {
      window.clearInterval(pingTimerRef.current)
      pingTimerRef.current = null
    }
    if (retryTimerRef.current !== null) {
      window.clearTimeout(retryTimerRef.current)
      retryTimerRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!enabled || url === null) {
      setState('idle')
      return
    }

    let disposed = false
    closedByUsRef.current = false

    const connect = () => {
      if (disposed) return
      setState('connecting')

      let socket: WebSocket
      try {
        socket = new WebSocket(url)
      } catch (cause) {
        setState('error')
        setError(cause instanceof Error ? cause.message : 'Could not open the WebSocket.')
        return
      }
      socketRef.current = socket

      socket.onopen = () => {
        attemptRef.current = 0
        setState('open')
        setError(null)

        pingTimerRef.current = window.setInterval(() => {
          if (socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: 'ping' }))
          }
        }, PING_INTERVAL_MS)
      }

      socket.onmessage = (message: MessageEvent<string>) => {
        let parsed: unknown
        try {
          parsed = JSON.parse(message.data)
        } catch {
          // A frame that is not JSON cannot be a contract event; ignore it
          // rather than tearing down a healthy socket.
          return
        }
        if (isServerEvent(parsed)) {
          onEventRef.current(parsed)
        }
      }

      socket.onerror = () => {
        // `onclose` always follows, and carries the retry decision.
        setState('error')
        setError('Lost connection to the backend event stream.')
      }

      socket.onclose = () => {
        if (pingTimerRef.current !== null) {
          window.clearInterval(pingTimerRef.current)
          pingTimerRef.current = null
        }
        if (disposed || closedByUsRef.current) {
          setState('closed')
          return
        }

        setState('closed')
        attemptRef.current += 1
        const delay = Math.min(
          RECONNECT_MIN_MS * 2 ** (attemptRef.current - 1),
          RECONNECT_MAX_MS,
        )
        retryTimerRef.current = window.setTimeout(connect, delay)
      }
    }

    connect()

    return () => {
      disposed = true
      clearTimers()
      const socket = socketRef.current
      socketRef.current = null
      if (socket !== null) {
        // Detach handlers first so our own close does not schedule a retry.
        socket.onopen = null
        socket.onmessage = null
        socket.onerror = null
        socket.onclose = null
        if (
          socket.readyState === WebSocket.OPEN ||
          socket.readyState === WebSocket.CONNECTING
        ) {
          socket.close()
        }
      }
    }
  }, [url, enabled, clearTimers, nonce])

  const reconnect = useCallback(() => {
    // Incrementing `nonce` tears the socket down through the effect cleanup and
    // opens a fresh one, which also resets the backoff attempt counter.
    attemptRef.current = 0
    setError(null)
    setNonce((current) => current + 1)
  }, [])

  return { state, error, reconnect }
}

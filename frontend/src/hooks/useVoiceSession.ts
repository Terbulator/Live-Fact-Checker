/**
 * Voice Session Hook
 *
 * Integrates microphone capture, AssemblyAI realtime STT, and backend transcript posting.
 * This is the main integration point for the "Go Live" flow.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { AssemblyAIClient, postTranscriptToBackend, type AssemblyAITranscriptEvent } from '../lib/assemblyai';
import { startSession, stopSession, type SessionState } from '../lib/api';
import { BACKEND_URL } from '../lib/config';

export type VoiceSessionStatus = 'idle' | 'starting' | 'active' | 'stopping' | 'error';

export interface VoiceSessionState {
  status: VoiceSessionStatus;
  session: SessionState | null;
  error: string | null;
  isMicrophoneActive: boolean;
  isAssemblyAIConnected: boolean;
}

export interface UseVoiceSessionOptions {
  /** Called when a transcript event is received (for UI updates) */
  onTranscript?: (event: AssemblyAITranscriptEvent) => void;
  /** Called when session status changes */
  onStatusChange?: (status: VoiceSessionStatus) => void;
  /** Called when an error occurs */
  onError?: (error: Error) => void;
  /** External sessionId to use (from useSession). If not provided, creates its own session. */
  externalSessionId?: string | null;
  /**
   * Called with the new id after a backend restart invalidated the old
   * session, so the UI can re-point any WebSocket subscription at it.
   */
  onSessionRecreated?: (sessionId: string) => void;
}

export function useVoiceSession(options: UseVoiceSessionOptions = {}) {
  const [state, setState] = useState<VoiceSessionState>({
    status: 'idle',
    session: null,
    error: null,
    isMicrophoneActive: false,
    isAssemblyAIConnected: false,
  });

  const clientRef = useRef<AssemblyAIClient | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const isShuttingDownRef = useRef(false);
  const ownsSessionRef = useRef(false);
  // Guards against concurrent recovery: a burst of 404s from queued transcripts
  // must produce exactly one rebuild, not one per transcript.
  const isRecoveringRef = useRef(false);
  // Lets each callback reach the other without the two `const` bindings having
  // to be mutually referential, which would be a temporal dead zone error.
  const handleTranscriptRef = useRef<((e: AssemblyAITranscriptEvent) => Promise<void>) | undefined>(undefined);
  const recoverFromStaleSessionRef = useRef<(() => Promise<void>) | undefined>(undefined);

  const updateStatus = useCallback((status: VoiceSessionStatus) => {
    setState((prev) => {
      if (prev.status === status) return prev;
      return { ...prev, status };
    });
    options.onStatusChange?.(status);
  }, [options]);

  const setError = useCallback((error: string | null) => {
    setState((prev) => ({ ...prev, error }));
    if (error) options.onError?.(new Error(error));
  }, [options]);

  /** Fetch AssemblyAI token from backend */
  const fetchAssemblyAIToken = useCallback(async (): Promise<string> => {
    const response = await fetch(`${BACKEND_URL}/assemblyai/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.message || 'Failed to get AssemblyAI token');
    }

    const data = await response.json();
    return data.token;
  }, []);

  /**
   * Recover from a backend restart that destroyed this session.
   *
   * Ordered deliberately: stop posting, tear down the dead realtime connection,
   * obtain a fresh session, then reconnect AssemblyAI so the next transcript
   * carries the new id. A historical row in Supabase is not an active session,
   * so the old id is discarded rather than recreated.
   */
  const recoverFromStaleSession = useCallback(async () => {
    if (isRecoveringRef.current) return;
    isRecoveringRef.current = true;

    try {
      // 1. Stop the dead realtime connection.
      const client = clientRef.current;
      if (client) {
        client.disconnect();
        clientRef.current = null;
      }
      setState((prev) => ({
        ...prev,
        isAssemblyAIConnected: false,
        isMicrophoneActive: false,
      }));

      // 2. A fresh backend session.
      const session = await startSession(false);
      sessionIdRef.current = session.sessionId;
      ownsSessionRef.current = true;
      setState((prev) => ({ ...prev, session }));

      // 3. Reconnect AssemblyAI against the new session id.
      const token = await fetchAssemblyAIToken();
      const reconnected = new AssemblyAIClient({
        token,
        sessionId: session.sessionId,
        onTranscript: (event) => handleTranscriptRef.current?.(event),
        onError: (err) => {
          console.error('[VoiceSession] AssemblyAI error after recovery:', err);
          setError(err.message);
        },
        onClose: () => {
          setState((prev) => ({ ...prev, isAssemblyAIConnected: false }));
        },
        getToken: fetchAssemblyAIToken,
      });

      clientRef.current = reconnected;
      await reconnected.connect();

      let attempts = 0;
      while (!reconnected.connected && attempts < 50) {
        await new Promise((r) => setTimeout(r, 100));
        attempts++;
      }

      if (!reconnected.connected) {
        throw new Error('AssemblyAI connection timeout after session recovery');
      }

      setState((prev) => ({ ...prev, isAssemblyAIConnected: true }));
      await reconnected.startMicrophone();
      setState((prev) => ({ ...prev, isMicrophoneActive: true }));

      console.log(`[VoiceSession] Recovered with new session: ${session.sessionId}`);
      options.onSessionRecreated?.(session.sessionId);
    } catch (err) {
      console.error('[VoiceSession] Session recovery failed:', err);
      setError(err instanceof Error ? err.message : 'Failed to recover session');
      updateStatus('error');
    } finally {
      isRecoveringRef.current = false;
    }
  }, [fetchAssemblyAIToken, options, setError, updateStatus]);

  // Handle transcript from AssemblyAI - post to backend and call the UI callback.
  // Reads the recovery path through a ref rather than the binding directly, so
  // the two callbacks do not have to be mutually referential.
  const handleTranscript = useCallback(
    async (event: AssemblyAITranscriptEvent) => {
      const result = await postTranscriptToBackend(event);

      if (result.staleSession) {
        // The backend lost this session (restart, deploy, idle eviction). Posting
        // again with the dead id would 404 forever, so stop, rebuild the
        // session and reconnect instead of hammering a dead endpoint.
        console.warn('[VoiceSession] Stale session detected; recovering.');
        await recoverFromStaleSessionRef.current?.();
        return;
      }

      if (!result.ok) {
        console.error('[VoiceSession] Failed to post transcript to backend');
      }

      options.onTranscript?.(event);
    },
    [options],
  );

  // Point the refs at the current callbacks. Both are assigned only after every
  // binding they could read exists; reading earlier would be a TDZ error.
  handleTranscriptRef.current = handleTranscript;
  recoverFromStaleSessionRef.current = recoverFromStaleSession;

  /** Start the voice session: create backend session (if needed), get AssemblyAI token, connect mic */
  const start = useCallback(async () => {
    if (state.status !== 'idle') return;

    isShuttingDownRef.current = false;
    updateStatus('starting');
    setError(null);

    try {
      let sessionId: string;
      let session: SessionState | null = null;

      // 1. Get or create backend session
      if (options.externalSessionId) {
        // Use existing session from useSession
        sessionId = options.externalSessionId;
        ownsSessionRef.current = false;
        console.log(`[VoiceSession] Using external session: ${sessionId}`);
      } else {
        // Create our own session (for standalone usage)
        session = await startSession(false);
        sessionId = session.sessionId;
        ownsSessionRef.current = true;
        console.log(`[VoiceSession] Created new session: ${sessionId}`);
      }

      sessionIdRef.current = sessionId;

      // 2. Get AssemblyAI token
      const token = await fetchAssemblyAIToken();
      console.log('[VoiceSession] AssemblyAI token obtained');

      // 3. Create and connect AssemblyAI client
      const client = new AssemblyAIClient({
        token,
        sessionId,
        onTranscript: handleTranscript,
        onError: (err) => {
          console.error('[VoiceSession] AssemblyAI error:', err);
          setError(err.message);
        },
        onClose: () => {
          console.log('[VoiceSession] AssemblyAI disconnected');
          setState((prev) => ({ ...prev, isAssemblyAIConnected: false }));
        },
        // Provide a callback to fetch fresh tokens on reconnect
        getToken: fetchAssemblyAIToken,
      });

      clientRef.current = client;
      await client.connect();

      // Wait for connection
      let attempts = 0;
      while (!client.connected && attempts < 50) {
        await new Promise((r) => setTimeout(r, 100));
        attempts++;
      }

      if (!client.connected) {
        throw new Error('AssemblyAI connection timeout');
      }

      setState((prev) => ({ ...prev, isAssemblyAIConnected: true }));

      // 4. Start microphone
      await client.startMicrophone();
      setState((prev) => ({ ...prev, isMicrophoneActive: true }));

      // 5. Update state to active
      setState((prev) => ({ ...prev, session, status: 'active' }));
      updateStatus('active');

      console.log('[VoiceSession] Go Live - fully active');
    } catch (err) {
      console.error('[VoiceSession] Start failed:', err);
      const message = err instanceof Error ? err.message : 'Failed to start voice session';
      setError(message);
      updateStatus('error');

      // Cleanup on failure
      await stop();
    }
  }, [state.status, updateStatus, setError, fetchAssemblyAIToken, handleTranscript, options.externalSessionId]);

  /** Stop the voice session: stop mic, disconnect AssemblyAI, stop backend session (if we own it) */
  const stop = useCallback(async () => {
    if (state.status === 'idle' || state.status === 'stopping') return;
    if (isShuttingDownRef.current) return;

    isShuttingDownRef.current = true;
    updateStatus('stopping');

    try {
      // 1. Stop microphone and disconnect AssemblyAI
      const client = clientRef.current;
      if (client) {
        client.disconnect();
        clientRef.current = null;
      }
      setState((prev) => ({
        ...prev,
        isMicrophoneActive: false,
        isAssemblyAIConnected: false,
      }));

      // 2. Stop backend session ONLY if we created it
      const sessionId = sessionIdRef.current;
      if (sessionId && ownsSessionRef.current) {
        try {
          await stopSession(sessionId);
          console.log(`[VoiceSession] Backend session stopped: ${sessionId}`);
        } catch (err) {
          console.error('[VoiceSession] Failed to stop backend session:', err);
        }
      }
      sessionIdRef.current = null;
      ownsSessionRef.current = false;

      // 3. Reset state
      setState({
        status: 'idle',
        session: null,
        error: null,
        isMicrophoneActive: false,
        isAssemblyAIConnected: false,
      });
      updateStatus('idle');

      console.log('[VoiceSession] Stopped completely');
    } catch (err) {
      console.error('[VoiceSession] Stop error:', err);
      setError(err instanceof Error ? err.message : 'Failed to stop voice session');
      updateStatus('error');
    } finally {
      isShuttingDownRef.current = false;
    }
  }, [state.status, updateStatus, setError]);

  /** Cleanup on unmount */
  useEffect(() => {
    return () => {
      // Clean up AssemblyAI client
      if (clientRef.current) {
        clientRef.current.disconnect();
        clientRef.current = null;
      }
      // If we own the session, stop it on the backend
      // Note: this is fire-and-forget on unmount since we can't await in cleanup
      if (sessionIdRef.current && ownsSessionRef.current) {
        const stopPromise = fetch(`${BACKEND_URL}/session/stop?sessionId=${encodeURIComponent(sessionIdRef.current)}`, {
          method: 'POST',
          // Use keepalive to ensure request completes even during unmount
          // (not supported in all environments, e.g. jsdom)
          keepalive: typeof window !== 'undefined' && 'keepalive' in Request.prototype ? true : false,
        });
        if (stopPromise && typeof stopPromise.catch === 'function') {
          stopPromise.catch(() => {
            // Ignore errors during unmount
          });
        }
      }
    };
  }, []);

  return {
    ...state,
    start,
    stop,
    sessionId: sessionIdRef.current,
  };
}
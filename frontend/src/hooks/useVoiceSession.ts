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

  /** Handle transcript from AssemblyAI - post to backend and call callback */
  const handleTranscript = useCallback(
    async (event: AssemblyAITranscriptEvent) => {
      // Post to backend
      const success = await postTranscriptToBackend(event);
      if (!success) {
        console.error('[VoiceSession] Failed to post transcript to backend');
      }

      // Call UI callback
      options.onTranscript?.(event);
    },
    [options]
  );

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
      if (clientRef.current) {
        clientRef.current.disconnect();
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
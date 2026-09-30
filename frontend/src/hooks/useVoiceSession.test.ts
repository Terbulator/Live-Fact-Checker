/**
 * Tests for useVoiceSession hook
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import { useVoiceSession } from './useVoiceSession';
import { BACKEND_URL } from '../lib/config';

// Mock fetch globally
const mockFetch = vi.fn();
global.fetch = mockFetch;

// Mock the api module
vi.mock('../lib/api', () => ({
  startSession: vi.fn().mockResolvedValue({ sessionId: 'test-session-123' }),
  stopSession: vi.fn().mockResolvedValue(undefined),
}));

// Mock AssemblyAIClient
vi.mock('../lib/assemblyai', () => {
  class MockAssemblyAIClient {
    connected = true;
    connect = vi.fn().mockResolvedValue(undefined);
    disconnect = vi.fn();
    startMicrophone = vi.fn().mockResolvedValue(undefined);
    stopMicrophone = vi.fn();
  }

  return {
    AssemblyAIClient: MockAssemblyAIClient,
    // Mirrors the real return contract. Returning a bare boolean left the hook
    // reading `.staleSession` off `true`, which is undefined rather than false
    // and would silently skip the stale-session path under test.
    postTranscriptToBackend: vi.fn().mockResolvedValue({
      ok: true,
      status: 202,
      staleSession: false,
    }),
  };
});

describe('useVoiceSession', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFetch.mockReset();
  });

  it('starts in idle state', () => {
    const { result } = renderHook(() => useVoiceSession());
    expect(result.current.status).toBe('idle');
    expect(result.current.sessionId).toBeNull();
    expect(result.current.isMicrophoneActive).toBe(false);
    expect(result.current.isAssemblyAIConnected).toBe(false);
  });

  it('fetches AssemblyAI token and starts session', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ token: 'test-token', expires_in: 600 }),
    });

    const { result } = renderHook(() => useVoiceSession());

    await act(async () => {
      await result.current.start();
    });

    expect(mockFetch).toHaveBeenCalledWith(`${BACKEND_URL}/assemblyai/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });

    // Should transition through starting to active
    expect(result.current.status).toBe('active');
    expect(result.current.sessionId).toBeTruthy();
  });

  it('uses external sessionId when provided', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ token: 'test-token', expires_in: 600 }),
    });

    const { result, rerender } = renderHook(
      ({ sessionId }) => useVoiceSession({ externalSessionId: sessionId }),
      { initialProps: { sessionId: 'external-session-123' } }
    );

    await act(async () => {
      await result.current.start();
    });

    expect(result.current.sessionId).toBe('external-session-123');
  });

  it('stops voice session and cleans up', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ token: 'test-token', expires_in: 600 }),
    });

    const { result } = renderHook(() => useVoiceSession());

    await act(async () => {
      await result.current.start();
    });

    expect(result.current.status).toBe('active');

    await act(async () => {
      await result.current.stop();
    });

    expect(result.current.status).toBe('idle');
    expect(result.current.sessionId).toBeNull();
    expect(result.current.isMicrophoneActive).toBe(false);
    expect(result.current.isAssemblyAIConnected).toBe(false);
  });

  it('handles AssemblyAI token fetch failure', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 503,
      json: () => Promise.resolve({ message: 'AssemblyAI not configured' }),
    });

    const { result } = renderHook(() => useVoiceSession());

    await act(async () => {
      await result.current.start();
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error).toContain('AssemblyAI not configured');
  });

  it('does not stop backend session when using external sessionId', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ token: 'test-token', expires_in: 600 }),
    });

    const { result } = renderHook(
      () => useVoiceSession({ externalSessionId: 'external-session-123' })
    );

    await act(async () => {
      await result.current.start();
    });

    // Import stopSession to verify it's NOT called
    const apiModule = await import('../lib/api');
    const stopSessionSpy = vi.spyOn(apiModule, 'stopSession');

    await act(async () => {
      await result.current.stop();
    });

    expect(stopSessionSpy).not.toHaveBeenCalled();
  });
});
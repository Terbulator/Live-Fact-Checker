/**
 * Tests for AssemblyAI client (v3 streaming API)
 */

import { AssemblyAIClient, postTranscriptToBackend } from './assemblyai';
import { BACKEND_URL } from './config';
import { vi } from 'vitest';

// Store sent messages globally for testing
const sentMessages: Array<{ data: string | ArrayBuffer; isBinary: boolean }> = [];

// Mock WebSocket globally
class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  readyState = MockWebSocket.CONNECTING;
  url = '';
  binaryType = 'arraybuffer';
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;

  constructor(public urlString: string) {
    this.url = urlString;
    sentMessages.length = 0;
    // Simulate async connection
    setTimeout(() => {
      this.readyState = MockWebSocket.OPEN;
      this.onopen?.();
    }, 0);
  }

  send(data: string | ArrayBuffer | Blob | ArrayBufferView) {
    if (typeof data === 'string') {
      sentMessages.push({ data, isBinary: false });
    } else if (data instanceof ArrayBuffer) {
      sentMessages.push({ data, isBinary: true });
    } else if (ArrayBuffer.isView(data)) {
      sentMessages.push({ data: data.buffer, isBinary: true });
    }
  }

  close(code?: number, reason?: string) {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.(new CloseEvent('close', { code, reason }));
  }

  simulateMessage(data: object) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(data) }));
  }

  simulateError() {
    this.onerror?.(new Event('error'));
  }
}

global.WebSocket = MockWebSocket as any;

// Mock fetch
const mockFetch = vi.fn();
global.fetch = mockFetch;

describe('AssemblyAIClient (v3)', () => {
  let client: AssemblyAIClient;

  beforeEach(() => {
    vi.clearAllMocks();
    mockFetch.mockReset();
    sentMessages.length = 0;
    
    client = new AssemblyAIClient({
      token: 'test-token',
      sessionId: 'test-session',
      onTranscript: vi.fn(),
      onError: vi.fn(),
      onClose: vi.fn(),
    });
  });

  it('connects to AssemblyAI v3 streaming WebSocket', async () => {
    await client.connect();
    
    // Wait for connection
    await new Promise(r => setTimeout(r, 10));
    
    expect(client.connected).toBe(true);
  });

  it('connects to correct v3 streaming endpoint with required query params', async () => {
    await client.connect();
    await new Promise(r => setTimeout(r, 10));
    
    const ws = (client as any).ws;
    expect(ws.url).toContain('wss://streaming.assemblyai.com/v3/ws');
    expect(ws.url).toContain('token=test-token');
    expect(ws.url).toContain('sample_rate=16000');
    expect(ws.url).toContain('speech_model=universal-3-5-pro');
  });

  it('does NOT send Configure message on connect', async () => {
    await client.connect();
    await new Promise(r => setTimeout(r, 10));
    
    // Find any Configure message
    const configMsg = sentMessages.find(m => 
      !m.isBinary && JSON.parse(m.data as string).type === 'Configure'
    );
    expect(configMsg).toBeUndefined();
  });

  it('handles Turn message (partial transcript) with v3 format', async () => {
    const onTranscript = vi.fn();
    client = new AssemblyAIClient({
      token: 'test-token',
      sessionId: 'test-session',
      onTranscript,
      onError: vi.fn(),
      onClose: vi.fn(),
    });

    await client.connect();
    await new Promise(r => setTimeout(r, 10));

    // Get the actual WebSocket instance
    const ws = (client as any).ws;
    if (ws && ws.simulateMessage) {
      ws.simulateMessage({
        type: 'Turn',
        transcript: 'Hello',
        end_of_turn: false,
        turn_is_formatted: false,
        speaker: 'A',
        words: [{ start: 1000, end: 2000, text: 'Hello', confidence: 0.9, word_is_final: true }],
      });
    }

    expect(onTranscript).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: 'test-session',
        speaker: 'Speaker 1',
        text: 'Hello',
        isFinal: false,
      })
    );
  });

  it('handles Turn message (final transcript) with v3 format', async () => {
    const onTranscript = vi.fn();
    client = new AssemblyAIClient({
      token: 'test-token',
      sessionId: 'test-session',
      onTranscript,
      onError: vi.fn(),
      onClose: vi.fn(),
    });

    await client.connect();
    await new Promise(r => setTimeout(r, 10));

    const ws = (client as any).ws;
    if (ws && ws.simulateMessage) {
      ws.simulateMessage({
        type: 'Turn',
        transcript: 'Hello world',
        end_of_turn: true,
        turn_is_formatted: true,
        speaker: 'A',
        words: [
          { start: 1000, end: 2000, text: 'Hello', confidence: 0.9, word_is_final: true },
          { start: 2000, end: 3400, text: 'world', confidence: 0.95, word_is_final: true },
        ],
      });
    }

    expect(onTranscript).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: 'test-session',
        speaker: 'Speaker 1',
        text: 'Hello world',
        isFinal: true,
        timestamp: 3.4,
      })
    );
  });

  it('maps speaker labels correctly with v3 format', async () => {
    const onTranscript = vi.fn();
    client = new AssemblyAIClient({
      token: 'test-token',
      sessionId: 'test-session',
      onTranscript,
      onError: vi.fn(),
      onClose: vi.fn(),
    });

    await client.connect();
    await new Promise(r => setTimeout(r, 10));

    const ws = (client as any).ws;
    if (ws && ws.simulateMessage) {
      // First speaker A
      ws.simulateMessage({
        type: 'Turn',
        transcript: 'Hello',
        end_of_turn: true,
        turn_is_formatted: true,
        speaker: 'A',
        words: [{ start: 1000, end: 2000, text: 'Hello', confidence: 0.9, word_is_final: true }],
      });

      // Second speaker B
      ws.simulateMessage({
        type: 'Turn',
        transcript: 'Hi there',
        end_of_turn: true,
        turn_is_formatted: true,
        speaker: 'B',
        words: [{ start: 1000, end: 2000, text: 'Hi there', confidence: 0.9, word_is_final: true }],
      });

      // Third speaker A again
      ws.simulateMessage({
        type: 'Turn',
        transcript: 'How are you',
        end_of_turn: true,
        turn_is_formatted: true,
        speaker: 'A',
        words: [{ start: 1000, end: 2000, text: 'How are you', confidence: 0.9, word_is_final: true }],
      });
    }

    expect(onTranscript).toHaveBeenCalledTimes(3);
    expect(onTranscript).toHaveBeenNthCalledWith(1, expect.objectContaining({ speaker: 'Speaker 1' }));
    expect(onTranscript).toHaveBeenNthCalledWith(2, expect.objectContaining({ speaker: 'Speaker 2' }));
    expect(onTranscript).toHaveBeenNthCalledWith(3, expect.objectContaining({ speaker: 'Speaker 1' }));
  });

  it('deduplicates final transcripts', async () => {
    const onTranscript = vi.fn();
    client = new AssemblyAIClient({
      token: 'test-token',
      sessionId: 'test-session',
      onTranscript,
      onError: vi.fn(),
      onClose: vi.fn(),
    });

    await client.connect();
    await new Promise(r => setTimeout(r, 10));

    const ws = (client as any).ws;
    if (ws && ws.simulateMessage) {
      // Send same final transcript twice
      ws.simulateMessage({
        type: 'Turn',
        transcript: 'Hello world',
        end_of_turn: true,
        turn_is_formatted: true,
        speaker: 'A',
        words: [{ start: 1000, end: 2000, text: 'Hello world', confidence: 0.9, word_is_final: true }],
      });

      ws.simulateMessage({
        type: 'Turn',
        transcript: 'Hello world',
        end_of_turn: true,
        turn_is_formatted: true,
        speaker: 'A',
        words: [{ start: 1000, end: 2000, text: 'Hello world', confidence: 0.9, word_is_final: true }],
      });
    }

    // Should only be called once due to deduplication
    expect(onTranscript).toHaveBeenCalledTimes(1);
  });

  it('sends audio as binary PCM16 ArrayBuffer', async () => {
    await client.connect();
    await new Promise(r => setTimeout(r, 10));

    // Send some audio
    const audioChunk = new Float32Array([0.1, 0.2, -0.1, -0.2, 0.5, -0.5]);
    client.streamAudio(audioChunk);

    // Find binary message sent
    const binaryMsg = sentMessages.find(m => m.isBinary);
    expect(binaryMsg).toBeDefined();
    expect(binaryMsg!.data).toBeInstanceOf(ArrayBuffer);
    
    // Verify it's PCM16 (Int16Array)
    const buffer = binaryMsg!.data as ArrayBuffer;
    const int16 = new Int16Array(buffer);
    expect(int16.length).toBe(audioChunk.length);
    // Check conversion: 0.1 * 0x7fff ≈ 3276, -0.1 * 0x8000 ≈ -3277
    expect(int16[0]).toBeCloseTo(3276, -2);
    expect(int16[2]).toBeCloseTo(-3277, -2);
  });

  it('sends Terminate message on disconnect', async () => {
    await client.connect();
    await new Promise(r => setTimeout(r, 10));

    client.disconnect();

    // Find Terminate message (sent as JSON string before close)
    const terminateMsg = sentMessages.find(m => 
      !m.isBinary && JSON.parse(m.data as string).type === 'Terminate'
    );
    expect(terminateMsg).toBeDefined();
    expect(JSON.parse(terminateMsg!.data as string)).toEqual({ type: 'Terminate' });
  });

  it('disconnects cleanly', async () => {
    await client.connect();
    await new Promise(r => setTimeout(r, 10));
    
    client.disconnect();
    
    expect(client.connected).toBe(false);
  });
});

describe('postTranscriptToBackend', () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it('posts transcript to backend', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true });

    const result = await postTranscriptToBackend({
      sessionId: 'test-session',
      speaker: 'Speaker 1',
      text: 'Hello world',
      timestamp: 1.5,
      isFinal: true,
    });

    expect(result.ok).toBe(true);
    expect(result.staleSession).toBe(false);
    // Derived from the shared config rather than hardcoded: the base URL is
    // supplied by VITE_BACKEND_URL and differs between a developer's machine
    // and CI, so a literal here would pass or fail on environment alone.
    expect(mockFetch).toHaveBeenCalledWith(
      `${BACKEND_URL}/events/transcript`,
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: 'transcript',
          sessionId: 'test-session',
          speaker: 'Speaker 1',
          text: 'Hello world',
          timestamp: 1.5,
          isFinal: true,
        }),
      })
    );
  });

  it('returns ok=false on backend error', async () => {
    mockFetch.mockResolvedValueOnce({ 
      ok: false, 
      json: () => Promise.resolve({ detail: 'error' }) 
    });

    const result = await postTranscriptToBackend({
      sessionId: 'test-session',
      speaker: 'Speaker 1',
      text: 'Hello world',
      timestamp: 1.5,
      isFinal: true,
    });

    expect(result.ok).toBe(false);
  });

  it('flags a 404 session as stale so the caller stops retrying', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: () => Promise.resolve({ code: 'SESSION_NOT_FOUND' }),
    });

    const result = await postTranscriptToBackend({
      sessionId: 'dead-session',
      speaker: 'Speaker 1',
      text: 'Hello world',
      timestamp: 1.5,
      isFinal: true,
    });

    expect(result.ok).toBe(false);
    expect(result.staleSession).toBe(true);
  });

  it('does not treat a network failure as a stale session', async () => {
    mockFetch.mockRejectedValueOnce(new Error('network down'));

    const result = await postTranscriptToBackend({
      sessionId: 'test-session',
      speaker: 'Speaker 1',
      text: 'Hello world',
      timestamp: 1.5,
      isFinal: true,
    });

    expect(result.ok).toBe(false);
    expect(result.status).toBe(0);
    expect(result.staleSession).toBe(false);
  });
});
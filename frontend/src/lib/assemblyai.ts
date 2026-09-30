/**
 * AssemblyAI Streaming WebSocket Client (TypeScript) - v3 API
 *
 * Mirrors the logic from voice/assemblyai_client.py:
 * - Connects to AssemblyAI v3 streaming WebSocket using a temporary token
 * - Handles interim and final transcripts
 * - Maps AssemblyAI speaker labels (A, B, C) to Speaker 1, Speaker 2, etc.
 * - Deduplicates final transcripts per speaker
 * - Emits transcript events via callback
 */

import { BACKEND_URL } from './config';

export interface AssemblyAITranscriptEvent {
  sessionId: string;
  speaker: string;
  text: string;
  timestamp: number;
  isFinal: boolean;
}

export type TranscriptCallback = (event: AssemblyAITranscriptEvent) => void;

export interface AssemblyAIClientOptions {
  token: string;
  sessionId: string;
  onTranscript: TranscriptCallback;
  onError?: (error: Error) => void;
  onClose?: () => void;
  sampleRate?: number;
  /** Optional callback to fetch a fresh token before reconnecting.
   *  If provided, this will be called before each reconnection attempt.
   *  This is important because AssemblyAI tokens are short-lived and single-use. */
  getToken?: () => Promise<string>;
}

/** AssemblyAI v3 streaming message types */
interface AssemblyAIMessage {
  type: string;
}

interface BeginMessage extends AssemblyAIMessage {
  type: 'Begin';
  id: string;
  expires_at: string;
}

interface TurnMessage extends AssemblyAIMessage {
  type: 'Turn';
  transcript: string;
  end_of_turn: boolean;
  turn_is_formatted: boolean;
  speaker?: string; // v3 uses "speaker" instead of "speaker_label"
  words?: Array<{
    start: number;
    end: number;
    text: string;
    confidence: number;
    word_is_final: boolean;
  }>;
}

interface TerminationMessage extends AssemblyAIMessage {
  type: 'Termination';
  audio_duration: number;
  session_duration: number;
}

interface ErrorMessage extends AssemblyAIMessage {
  type: 'Error';
  error: string;
}

type IncomingMessage = BeginMessage | TurnMessage | TerminationMessage | ErrorMessage;

interface TerminateMessage {
  type: 'Terminate';
}

/**
 * AssemblyAI Streaming Client (v3)
 *
 * Handles WebSocket connection, audio streaming, and transcript processing.
 * v3 protocol: https://www.assemblyai.com/docs/api-reference/streaming
 * - Connection parameters sent as query params in WebSocket URL
 * - Audio sent as binary PCM16 frames
 * - Terminate message sent to flush final transcription
 */
export class AssemblyAIClient {
  private ws: WebSocket | null = null;
  private readonly options: AssemblyAIClientOptions;
  private readonly speakerMap: Map<string, string> = new Map();
  private nextSpeakerNum = 1;
  private readonly lastFinalTranscript: Map<string, string> = new Map();
  private audioContext: AudioContext | null = null;
  private mediaStream: MediaStream | null = null;
  private processor: ScriptProcessorNode | null = null;
  private isConnected = false;
  private reconnectAttempts = 0;
  private readonly maxReconnectAttempts = 5;
  private reconnectDelay = 1000;

  constructor(options: AssemblyAIClientOptions) {
    this.options = {
      sampleRate: 16000,
      ...options,
    };
  }

  /** Connect to AssemblyAI v3 streaming WebSocket */
  async connect(): Promise<void> {
    // Allow fetching a fresh token before connecting (especially for reconnect)
    let token = this.options.token;
    if (this.options.getToken) {
      try {
        token = await this.options.getToken();
      } catch (err) {
        console.error('[AssemblyAI] Failed to fetch fresh token:', err);
        this.options.onError?.(new Error('Failed to fetch AssemblyAI token'));
        return;
      }
    }

    // v3 streaming endpoint. Config is passed as query params; sample_rate is
    // required for raw PCM16 audio, and must match the rate the microphone is
    // captured at (see startMicrophone).
    const sampleRate = this.options.sampleRate ?? 16000;
    const wsUrl =
      `wss://streaming.assemblyai.com/v3/ws?token=${encodeURIComponent(token)}` +
      `&sample_rate=${sampleRate}` +
      `&speech_model=universal-3-5-pro`;
    this.ws = new WebSocket(wsUrl);

    this.ws.binaryType = 'arraybuffer';

    this.ws.onopen = () => {
      console.log('[AssemblyAI] Connected to v3 streaming');
      this.isConnected = true;
      this.reconnectAttempts = 0;
      // v3 does NOT accept a Configure message - config is in URL query params
    };

    this.ws.onmessage = (event) => {
      try {
        if (typeof event.data === 'string') {
          const message = JSON.parse(event.data) as IncomingMessage;
          this.handleMessage(message);
        } else {
          // Binary data not expected from AssemblyAI v3 (transcripts are JSON)
          console.warn('[AssemblyAI] Received unexpected binary data');
        }
      } catch (err) {
        console.error('[AssemblyAI] Failed to parse message:', err);
      }
    };

    this.ws.onerror = (err) => {
      console.error('[AssemblyAI] WebSocket error:', err);
      this.options.onError?.(new Error('WebSocket error'));
    };

    this.ws.onclose = (event) => {
      console.log(`[AssemblyAI] Disconnected: ${event.code} ${event.reason}`);
      this.isConnected = false;
      this.options.onClose?.();

      // Attempt reconnection if not intentionally closed
      if (this.reconnectAttempts < this.maxReconnectAttempts && this.ws) {
        this.reconnectAttempts++;
        const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
        console.log(`[AssemblyAI] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
        setTimeout(() => this.connect(), delay);
      }
    };
  }

  /** Disconnect from AssemblyAI */
  disconnect(): void {
    this.stopMicrophone();
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      // Send Terminate message to flush final transcription before closing
      const terminateMsg: TerminateMessage = { type: 'Terminate' };
      this.ws.send(JSON.stringify(terminateMsg));
      // Give a brief moment for the terminate to be processed
      setTimeout(() => {
        if (this.ws) {
          this.ws.close(1000, 'Client disconnect');
          this.ws = null;
        }
      }, 100);
    }
    this.isConnected = false;
  }

  /** Stream audio chunk to AssemblyAI as binary PCM16 */
  streamAudio(audioChunk: Float32Array): void {
    if (!this.isConnected || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;

    // Convert Float32Array to Int16Array (PCM16)
    const pcm16 = new Int16Array(audioChunk.length);
    for (let i = 0; i < audioChunk.length; i++) {
      const sample = audioChunk[i];
      if (sample === undefined) continue;
      const s = Math.max(-1, Math.min(1, sample));
      pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }

    // Send binary PCM16 data directly (not base64, not JSON)
    this.ws.send(pcm16.buffer);
  }

  /** Start microphone capture */
  async startMicrophone(): Promise<void> {
    if (this.mediaStream) return;

    const sampleRate = this.options.sampleRate ?? 16000;

    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      // Create AudioContext and ScriptProcessor for real-time processing
      this.audioContext = new AudioContext({ sampleRate });
      const source = this.audioContext.createMediaStreamSource(this.mediaStream);

      // Use ScriptProcessorNode (deprecated but widely supported) for real-time audio
      // Buffer size of 4096 gives ~256ms at 16kHz, good balance
      this.processor = this.audioContext.createScriptProcessor(4096, 1, 1);
      this.processor.onaudioprocess = (event) => {
        const inputData = event.inputBuffer.getChannelData(0);
        // Copy to new Float32Array to avoid issues with buffer reuse
        const chunk = new Float32Array(inputData.length);
        chunk.set(inputData);
        this.streamAudio(chunk);
      };

      source.connect(this.processor);
      this.processor.connect(this.audioContext.destination);

      console.log('[AssemblyAI] Microphone started');
    } catch (err) {
      console.error('[AssemblyAI] Failed to start microphone:', err);
      this.options.onError?.(err instanceof Error ? err : new Error('Microphone access denied'));
      throw err;
    }
  }

  /** Stop microphone capture */
  stopMicrophone(): void {
    if (this.processor) {
      this.processor.disconnect();
      this.processor.onaudioprocess = null;
      this.processor = null;
    }
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((track) => track.stop());
      this.mediaStream = null;
    }
    console.log('[AssemblyAI] Microphone stopped');
  }

  /** Handle incoming AssemblyAI message */
  private handleMessage(message: IncomingMessage): void {
    switch (message.type) {
      case 'Begin':
        console.log(`[AssemblyAI] Session started: ${message.id}`);
        break;

      case 'Turn':
        this.handleTurn(message);
        break;

      case 'Termination':
        console.log('[AssemblyAI] Session terminated', message);
        break;

      case 'Error':
        console.error('[AssemblyAI] Error:', message.error);
        this.options.onError?.(new Error(message.error));
        break;
    }
  }

  /** Handle a transcript turn (interim or final) */
  private handleTurn(message: TurnMessage): void {
    if (!message.transcript) return;

    // v3 uses end_of_turn for finality (same as v2)
    const isFinal = message.end_of_turn === true;

    // Map AssemblyAI speaker label to Speaker 1, Speaker 2, etc.
    // v3 uses "speaker" field instead of "speaker_label"
    let speaker = 'Speaker 1';
    const rawSpeaker = message.speaker;
    if (rawSpeaker && rawSpeaker !== 'PENDING') {
      if (!this.speakerMap.has(rawSpeaker)) {
        this.speakerMap.set(rawSpeaker, `Speaker ${this.nextSpeakerNum}`);
        this.nextSpeakerNum++;
      }
      speaker = this.speakerMap.get(rawSpeaker)!;
    }

    // Extract timestamp from words (milliseconds -> seconds)
    let timestamp = 0;
    if (message.words && message.words.length > 0) {
      const lastWord = message.words[message.words.length - 1];
      if (lastWord) {
        timestamp = lastWord.end / 1000;
      }
    }

    // Deduplication: skip duplicate final transcripts for the same speaker
    if (isFinal) {
      const lastText = this.lastFinalTranscript.get(speaker);
      if (lastText !== undefined && lastText === message.transcript) {
        return; // Skip duplicate
      }
      this.lastFinalTranscript.set(speaker, message.transcript);
    }

    const event: AssemblyAITranscriptEvent = {
      sessionId: this.options.sessionId,
      speaker,
      text: message.transcript.trim(),
      timestamp,
      isFinal,
    };

    console.log(`[${speaker}] ${isFinal ? 'FINAL' : 'PARTIAL'} ${message.transcript}`);
    this.options.onTranscript(event);
  }

  /** Check if currently connected */
  get connected(): boolean {
    return this.isConnected;
  }
}

/** Result of posting one transcript to the backend. */
export interface TranscriptPostResult {
  ok: boolean;
  status: number;
  /**
   * The backend no longer knows this session id. Set on 404 / SESSION_NOT_FOUND,
   * which happens after a backend restart destroys its in-memory session
   * registry. The caller must stop posting and start a fresh session rather
   * than retrying with the dead id.
   */
  staleSession: boolean;
}

/**
 * Post a transcript event to the backend
 */
export async function postTranscriptToBackend(event: AssemblyAITranscriptEvent): Promise<TranscriptPostResult> {
  let response: Response;
  try {
    response = await fetch(`${BACKEND_URL}/events/transcript`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type: 'transcript',
        sessionId: event.sessionId,
        speaker: event.speaker,
        text: event.text,
        timestamp: event.timestamp,
        isFinal: event.isFinal,
      }),
    });
  } catch (err) {
    // A network failure is not evidence that the session is dead, so it is
    // deliberately not reported as stale.
    console.error('[Backend] Failed to post transcript:', err);
    return { ok: false, status: 0, staleSession: false };
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    console.error('[Backend] Failed to post transcript:', error);
    const code = (error as { code?: string })?.code;
    return {
      ok: false,
      status: response.status,
      staleSession: response.status === 404 || code === 'SESSION_NOT_FOUND',
    };
  }

  return { ok: true, status: response.status, staleSession: false };
}
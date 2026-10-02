/**
 * The composer: the only input on the page.
 *
 * A claim, a link, a video, an audio file and the microphone are the same act --
 * sending something to be checked -- so they share one field and one Send. What
 * was attached is shown inside the field as a chip, the way a mail draft shows
 * its attachments, and nothing is submitted until the reader presses Send.
 *
 * A link is recognised from the text as it is typed rather than asked for in a
 * second field, so pasting a URL and hitting Send is the whole interaction.
 *
 * Voice is the same action in a different mode, so it stays a button here rather
 * than becoming a control of its own elsewhere. While the microphone is open the
 * field says so, and the indicator reflects the real microphone and AssemblyAI
 * state reported by `useVoiceSession`.
 */

import { useRef } from 'react'
import { ArrowUp, FileAudio, Film, Link2, LoaderCircle, Mic, Square, X } from 'lucide-react'

import { createPreviewUrl } from '../../hooks/useMediaIngestion'
import type { VoiceSessionStatus } from '../../hooks/useVoiceSession'
import { formatBytes, isBareUrl, urlLabel, type MediaKind } from '../../lib/media'
import type { Attachment } from './thread'

export interface ComposerProps {
  value: string
  onChange: (value: string) => void
  attachment: Attachment | null
  onAttach: (attachment: Attachment | null) => void
  onSubmit: () => void
  canSubmit: boolean
  busy: boolean
  /** Replaces the hint while a run is working. */
  busyText: string | null
  voiceStatus: VoiceSessionStatus
  microphoneActive: boolean
  onToggleVoice: () => void
}

type VoiceLabel = { label: string; hint: string; live: boolean; pending: boolean }

function voiceState(status: VoiceSessionStatus): VoiceLabel {
  switch (status) {
    case 'starting':
      return { label: 'Connecting…', hint: 'Opening the microphone', live: false, pending: true }
    case 'active':
      return { label: 'Listening…', hint: 'Stop listening', live: true, pending: false }
    case 'stopping':
      return { label: 'Stopping…', hint: 'Closing the microphone', live: false, pending: true }
    case 'error':
      return {
        label: 'Voice unavailable',
        hint: 'Check microphone permission',
        live: false,
        pending: false,
      }
    case 'idle':
    default:
      return { label: 'Voice', hint: 'Listen and check claims live', live: false, pending: false }
  }
}

const ATTACHMENT_ICON: Record<MediaKind, typeof Film> = {
  video: Film,
  audio: FileAudio,
  url: Link2,
}

export function Composer({
  value,
  onChange,
  attachment,
  onAttach,
  onSubmit,
  canSubmit,
  busy,
  busyText,
  voiceStatus,
  microphoneActive,
  onToggleVoice,
}: ComposerProps) {
  const videoInputRef = useRef<HTMLInputElement>(null)
  const audioInputRef = useRef<HTMLInputElement>(null)
  const voice = voiceState(voiceStatus)

  const stage = (kind: Exclude<MediaKind, 'url'>) => (file: File | undefined) => {
    if (file === undefined) return
    const preview = createPreviewUrl(file)
    onAttach({ kind, label: file.name, previewUrl: preview, file, size: file.size })
  }

  const remove = () => {
    if (attachment?.previewUrl != null) URL.revokeObjectURL(attachment.previewUrl)
    onAttach(null)
  }

  // A pasted link that is the entire message is shown as an attachment, so the
  // reader can see what will be fetched before it is.
  const linkedUrl = attachment === null && isBareUrl(value) ? value.trim() : null

  const classes = [
    'composer',
    voice.live ? 'composer--listening' : '',
    attachment !== null || linkedUrl !== null ? 'composer--filled' : '',
  ]
    .filter(Boolean)
    .join(' ')

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends, Shift+Enter is a newline: the convention every chat composer
    // uses, so a multi-line claim is still possible.
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      if (canSubmit && !busy) onSubmit()
    }
  }

  return (
    <section className={classes} aria-label="Send something to fact-check">
      {(attachment !== null || linkedUrl !== null) && (
        <div className="composer__attachment">
          {attachment !== null ? (
            <span className="attachcard">
              {attachment.kind === 'video' && attachment.previewUrl !== null ? (
                <video className="attachcard__thumb" src={attachment.previewUrl} muted />
              ) : (
                <span className="attachcard__glyph" aria-hidden="true">
                  {(() => {
                    const Icon = ATTACHMENT_ICON[attachment.kind]
                    return <Icon size={15} />
                  })()}
                </span>
              )}
              <span className="attachcard__body">
                <span className="attachcard__name">{attachment.label}</span>
                {attachment.size !== null && (
                  <span className="attachcard__meta">{formatBytes(attachment.size)}</span>
                )}
              </span>
              <button
                type="button"
                className="attachcard__remove"
                onClick={remove}
                aria-label={`Remove ${attachment.label}`}
              >
                <X size={14} aria-hidden="true" />
              </button>
            </span>
          ) : (
            <span className="attachcard attachcard--url">
              <span className="attachcard__glyph" aria-hidden="true">
                <Link2 size={15} />
              </span>
              <span className="attachcard__body">
                <span className="attachcard__name">{urlLabel(linkedUrl ?? '')}</span>
                <span className="attachcard__meta">{linkedUrl}</span>
              </span>
            </span>
          )}
        </div>
      )}

      <textarea
        className="composer__input"
        rows={attachment === null && linkedUrl === null ? 2 : 1}
        value={value}
        placeholder="Type a claim, paste a URL, or add media…"
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
      />

      <input
        ref={videoInputRef}
        type="file"
        accept="video/*"
        hidden
        onChange={(event) => {
          stage('video')(event.target.files?.[0])
          event.target.value = ''
        }}
      />
      <input
        ref={audioInputRef}
        type="file"
        accept="audio/*"
        hidden
        onChange={(event) => {
          stage('audio')(event.target.files?.[0])
          event.target.value = ''
        }}
      />

      <div className="composer__bar">
        <div className="composer__tools">
          <button
            type="button"
            className="composer__tool"
            onClick={() => videoInputRef.current?.click()}
            disabled={busy || voice.pending}
            aria-label="Add video"
          >
            <Film size={15} aria-hidden="true" />
            Video
          </button>
          <button
            type="button"
            className="composer__tool"
            onClick={() => audioInputRef.current?.click()}
            disabled={busy || voice.pending}
            aria-label="Add audio"
          >
            <FileAudio size={15} aria-hidden="true" />
            Audio
          </button>
          <button
            type="button"
            className={`composer__tool${voice.live ? ' composer__voice--live' : ''}`}
            onClick={onToggleVoice}
            disabled={voice.pending}
            aria-pressed={voice.live}
            aria-label={voice.live ? 'Stop listening' : 'Voice'}
            title={voice.hint}
          >
            {voice.pending ? (
              <LoaderCircle size={15} className="spin" aria-hidden="true" />
            ) : voice.live ? (
              <Square size={13} aria-hidden="true" />
            ) : (
              <Mic size={15} aria-hidden="true" />
            )}
            {voice.label}
            {voice.live && microphoneActive && (
              <span className="composer__voiceDot" aria-hidden="true" />
            )}
          </button>
        </div>

        <div className="composer__actions">
          {!voice.live && (
            <p className="composer__hint" role="status" aria-live="polite">
              {busyText ?? 'Enter to send · Shift+Enter for a new line'}
            </p>
          )}
          <button
            type="button"
            className="composer__send"
            onClick={onSubmit}
            disabled={!canSubmit || busy || voice.live}
            aria-label="Send"
            title="Send this to be fact-checked"
          >
            {busy ? (
              <LoaderCircle size={16} className="spin" aria-hidden="true" />
            ) : (
              <ArrowUp size={17} aria-hidden="true" />
            )}
          </button>
        </div>
      </div>
    </section>
  )
}

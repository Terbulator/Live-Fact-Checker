/**
 * Live transcript.
 *
 * Four behaviours matter for reading a live debate:
 *
 * 1. **Interim segments** arrive with `isFinal: false` and are revised in place
 *    by the reducer, so a growing line is rendered dimmed and italic to make it
 *    obvious the recogniser is still working on it. Only a finalized line is
 *    claim-checked by the backend.
 * 2. **Claimed lines** carry the verdict of the claim they produced, so the
 *    transcript itself shows which sentences were checked and how they landed.
 *    The tone is passed in by the parent as a lookup keyed on `claimId`; the
 *    transcript never inspects the claim list itself.
 * 3. **Selecting a claim** scrolls its originating line into view and holds it
 *    highlighted, which is what ties the two columns together.
 * 4. **The newest line** is marked so a glance at the panel is enough to see
 *    that the feed is still moving.
 */

import { useEffect, useRef } from 'react'

import { displaySpeaker, formatClock, speakerIndex, speakerInitials } from '../lib/format'
import type { VerdictDescriptor } from '../lib/verdicts'
import type { TranscriptLine } from '../types/model'

export interface TranscriptPanelProps {
  lines: TranscriptLine[]
  /** Key of the line to highlight, usually the selected claim's origin. */
  activeKey: string | null
  /**
   * Verdict presentation for each checked line, keyed by `claimId`.
   *
   * Derived by the parent from the claim list. A line whose claim is still
   * being verified maps to the checking descriptor, so the transcript shows the
   * same word the claim card does.
   */
  verdicts?: ReadonlyMap<string, VerdictDescriptor>
}

export function TranscriptPanel({ lines, activeKey, verdicts }: TranscriptPanelProps) {
  const endRef = useRef<HTMLDivElement | null>(null)
  const activeRef = useRef<HTMLLIElement | null>(null)

  // Speaker colours are assigned by order of first appearance, so Speaker 1 is
  // always the same colour within a session.
  const speakerOrder: string[] = []
  for (const line of lines) {
    const label = displaySpeaker(line.speaker)
    if (!speakerOrder.includes(label)) speakerOrder.push(label)
  }

  // Follow the live edge, unless a claim selection has taken priority.
  useEffect(() => {
    if (activeKey !== null) {
      activeRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' })
      return
    }
    endRef.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
  }, [lines.length, activeKey])

  const newestKey = lines[lines.length - 1]?.key ?? null

  return (
    <section className="panel panel--transcript" aria-label="Live transcript">
      <h2 className="panel__title">
        Live transcript
        {lines.length > 0 && (
          <span className="panel__count">{lines.length} segments</span>
        )}
      </h2>

      {lines.length === 0 ? (
        <p className="empty">
          Waiting for speech. The microphone module posts each transcript
          segment here as soon as it is finalised.
        </p>
      ) : (
        <ol className="transcript">
          {lines.map((line) => {
            const isActive = line.key === activeKey
            const isNewest = line.key === newestKey && !line.isFinal
            const descriptor =
              line.claimId !== null && verdicts !== undefined
                ? verdicts.get(line.claimId)
                : undefined

            return (
              <li
                key={line.key}
                ref={isActive ? activeRef : undefined}
                className={[
                  'line',
                  line.isFinal ? 'line--final' : 'line--interim',
                  line.claimId !== null ? 'line--claimed' : '',
                  descriptor !== undefined ? `line--${descriptor.tone}` : '',
                  isActive ? 'line--active' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
                data-claim-id={line.claimId ?? undefined}
              >
                <span
                  className="line__avatar"
                  data-tone={speakerIndex(line.speaker, speakerOrder)}
                  aria-hidden="true"
                >
                  {speakerInitials(line.speaker)}
                </span>
                <span className="line__meta">
                  <span className="line__clock">{formatClock(line.timestamp)}</span>
                  <span className="line__speaker">{displaySpeaker(line.speaker)}</span>
                </span>
                <span className="line__text">{line.text}</span>
                {line.claimId !== null && (
                  <span
                    className={`line__flag${
                      descriptor !== undefined ? ` line__flag--${descriptor.tone}` : ''
                    }`}
                    title={
                      descriptor !== undefined
                        ? `Checked as ${line.claimId}: ${descriptor.description}`
                        : `Checked as ${line.claimId}`
                    }
                  >
                    <span className="line__flagGlyph" aria-hidden="true">
                      {descriptor?.glyph ?? '✓'}
                    </span>
                    {descriptor?.short ?? 'checked'}
                  </span>
                )}
                {isNewest && <span className="line__live" aria-hidden="true" />}
              </li>
            )
          })}
          <div ref={endRef} />
        </ol>
      )}
    </section>
  )
}

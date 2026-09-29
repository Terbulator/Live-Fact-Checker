/**
 * Live transcript.
 *
 * Interim AssemblyAI segments arrive with `isFinal: false` and are revised in
 * place by the reducer, so a growing line is rendered as provisional and the
 * finalized line replaces it. Only finalized lines are claim-checked by the
 * backend, which is why a claim badge appears on the final line.
 */

import { useEffect, useRef } from 'react'

import type { TranscriptLine } from '../types/model'

export interface TranscriptPanelProps {
  lines: TranscriptLine[]
}

function formatTimestamp(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds - minutes * 60
  return `${minutes}:${remainder.toFixed(1).padStart(4, '0')}`
}

export function TranscriptPanel({ lines }: TranscriptPanelProps) {
  const endRef = useRef<HTMLDivElement | null>(null)

  // Follow the live edge as new lines land.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
  }, [lines])

  return (
    <section className="panel" aria-label="Live transcript">
      <h2 className="panel__title">Live transcript</h2>

      {lines.length === 0 ? (
        <p className="empty">
          No speech yet. Start a session, then have the microphone module post a
          transcript — or use <strong>Run demo</strong> to replay the scripted
          pipeline.
        </p>
      ) : (
        <ol className="transcript">
          {lines.map((line) => (
            <li
              key={line.key}
              className={`transcript__line${line.isFinal ? '' : ' transcript__line--interim'}`}
            >
              <span className="transcript__time">{formatTimestamp(line.timestamp)}</span>
              <span className="transcript__speaker">{line.speaker ?? 'Speaker'}</span>
              <span className="transcript__text">{line.text}</span>
              {line.claimId !== null && (
                <span className="transcript__claim" title={`Claim ${line.claimId}`}>
                  under check
                </span>
              )}
            </li>
          ))}
          <div ref={endRef} />
        </ol>
      )}
    </section>
  )
}

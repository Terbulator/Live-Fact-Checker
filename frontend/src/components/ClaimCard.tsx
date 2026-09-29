/**
 * A single claim and its verdict.
 *
 * Three states a judge cares about, each unmistakable without relying on hue:
 *
 * - **checking** — an animated ring and the word CHECKING, so an unresolved
 *   claim never reads as a grey or failed verdict
 * - **resolved** — a glyph, the verdict word, the reason, and the source
 *
 * The card is a button so selecting it highlights the transcript line the claim
 * came from, which is what makes the two-column layout legible. Selecting is
 * also the only way to reach a claim's evidence in context, so the button keeps
 * a visible pressed state rather than looking identical when selected.
 */

import { displaySpeaker, formatClock, isLinkableSource, sourceDomain } from '../lib/format'
import { describeCard } from '../lib/verdicts'
import type { ClaimCard as ClaimCardModel } from '../types/model'

export interface ClaimCardProps {
  card: ClaimCardModel
  selected: boolean
  onSelect: (claimId: string) => void
}

export function ClaimCard({ card, selected, onSelect }: ClaimCardProps) {
  const descriptor = describeCard(card)
  const verification = card.verification
  const source = verification?.source ?? ''

  return (
    <li
      className={`card card--${descriptor.tone}${selected ? ' card--selected' : ''}`}
      data-claim-id={card.claimId}
    >
      <button
        type="button"
        className="card__button"
        onClick={() => onSelect(card.claimId)}
        aria-pressed={selected}
      >
        <span className="card__head">
          <span className="card__speaker">{displaySpeaker(card.speaker)}</span>
          <span className="card__clock">{formatClock(card.timestamp)}</span>
          {card.claimType !== 'unspecified' && (
            <span className="card__type">{card.claimType.replace(/_/g, ' ')}</span>
          )}
          <span className={`verdict verdict--${descriptor.tone}`} title={descriptor.description}>
            {card.pending ? (
              <>
                <span className="verdict__spinner" aria-hidden="true" />
                CHECKING
              </>
            ) : (
              <>
                <span className="verdict__glyph" aria-hidden="true">
                  {descriptor.glyph}
                </span>
                {descriptor.short}
              </>
            )}
          </span>
        </span>

        <span className="card__claim">
          {card.claim !== '' ? card.claim : 'Claim text not seen by this client'}
        </span>
      </button>

      {verification !== null && (
        <div className="card__result">
          <p className="card__reason">{verification.reason}</p>
          {source !== '' && (
            <p className="card__source">
              <span className="card__sourceLabel">Source</span>
              {isLinkableSource(source) ? (
                <a
                  className="card__link"
                  href={source}
                  target="_blank"
                  rel="noreferrer noopener"
                  title={source}
                >
                  {sourceDomain(source)}
                  <span className="card__external" aria-hidden="true">
                    ↗
                  </span>
                </a>
              ) : (
                <span className="card__sourceText">{source}</span>
              )}
            </p>
          )}
        </div>
      )}
    </li>
  )
}

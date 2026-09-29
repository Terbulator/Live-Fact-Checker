/**
 * Claim cards with their verdicts.
 *
 * A `claim` event arrives before its `verification`, so each card renders in a
 * pending state and is filled in when the matching `claimId` verdict lands.
 * Cards correlate on `claimId`, which the backend preserves end to end.
 */

import { describeVerdict } from '../lib/verdicts'
import type { ClaimCard } from '../types/model'

export interface ClaimPanelProps {
  claims: ClaimCard[]
}

function formatClock(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${(seconds - minutes * 60).toFixed(1).padStart(4, '0')}`
}

/** Only render a source as a link when it is genuinely a URL. */
function isLinkableSource(source: string): boolean {
  return /^https?:\/\/\S+$/i.test(source)
}

function ClaimCardView({ card }: { card: ClaimCard }) {
  const verification = card.verification
  const descriptor = verification ? describeVerdict(verification.verdict) : null

  return (
    <li className={`claim${card.pending ? ' claim--pending' : ''}`}>
      <div className="claim__head">
        <span className="claim__speaker">{card.speaker ?? 'Speaker'}</span>
        <span className="claim__clock">{formatClock(card.timestamp)}</span>
        {descriptor !== null ? (
          <span
            className={`verdict verdict--${descriptor.tone}`}
            title={descriptor.description}
          >
            {descriptor.short}
          </span>
        ) : (
          <span className="verdict verdict--unknown" aria-live="polite">
            CHECKING
          </span>
        )}
      </div>

      <p className="claim__text">
        {card.claim !== '' ? card.claim : '(claim text not seen by this client)'}
      </p>

      {verification !== null && (
        <div className="claim__result">
          <p className="claim__reason">{verification.reason}</p>
          <p className="claim__source">
            Source:{' '}
            {isLinkableSource(verification.source) ? (
              <a href={verification.source} target="_blank" rel="noreferrer noopener">
                {verification.source}
              </a>
            ) : (
              <span>{verification.source}</span>
            )}
          </p>
        </div>
      )}
    </li>
  )
}

export function ClaimPanel({ claims }: ClaimPanelProps) {
  const verdicts = {
    true: claims.filter((card) => card.verification?.verdict === 'TRUE').length,
    false: claims.filter((card) => card.verification?.verdict === 'FALSE').length,
    unverifiable: claims.filter(
      (card) => card.verification?.verdict === 'UNVERIFIABLE',
    ).length,
  }

  return (
    <section className="panel" aria-label="Claims under check">
      <h2 className="panel__title">
        Claims under check
        {claims.length > 0 && (
          <span className="panel__tally">
            {verdicts.true} true · {verdicts.false} false · {verdicts.unverifiable}{' '}
            unverifiable
          </span>
        )}
      </h2>

      {claims.length === 0 ? (
        <p className="empty">
          No claims extracted yet. The backend only checks finalized transcript
          lines, so claims appear once a speaker states something checkable.
        </p>
      ) : (
        <ul className="claims">
          {claims.map((card) => (
            <ClaimCardView key={card.claimId} card={card} />
          ))}
        </ul>
      )}
    </section>
  )
}

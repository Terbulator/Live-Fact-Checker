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

import {
  collectSources,
  displaySpeaker,
  formatClock,
  formatConfidence,
  hasConfidence,
  isLinkableSource,
  sourceDomain,
} from '../lib/format'
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
  const sources = verification === null ? [] : collectSources(verification)
  const statement = verification?.supportingStatement ?? null
  const reported = hasConfidence(verification?.confidence)

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
          {statement !== null && statement !== '' && (
            <p className="card__statement">{statement}</p>
          )}
          <p
            className={`card__confidence${reported ? '' : ' card__confidence--absent'}`}
            title={
              reported
                ? 'Relevance score reported by the search provider for the lead source.'
                : 'The search provider reported no relevance score for this claim.'
            }
          >
            <span className="card__confidenceLabel">Confidence</span>
            <span>{formatConfidence(verification.confidence)}</span>
          </p>
          {sources.length > 0 && (
            <div className="card__sources">
              {sources.length > 1 && (
                <p className="card__sourceLabel">
                  Sources ({sources.length})
                </p>
              )}
              <ul className="card__sourceList">
                {sources.map((entry) => (
                  <li key={entry.url} className="card__sourceItem">
                    <span className="card__source">
                      {sources.length === 1 ? (
                        <span className="card__sourceLabel">Source</span>
                      ) : (
                        <span className="card__sourceLabel">
                          {entry.primary ? 'Primary' : 'Also'}
                        </span>
                      )}
                      {isLinkableSource(entry.url) ? (
                        <a
                          className="card__link"
                          href={entry.url}
                          target="_blank"
                          rel="noreferrer noopener"
                          title={entry.url}
                        >
                          {entry.title ?? sourceDomain(entry.url)}
                          <span className="card__external" aria-hidden="true">
                            ↗
                          </span>
                        </a>
                      ) : (
                        <span className="card__sourceText">{entry.url}</span>
                      )}
                      {entry.title !== null && (
                        <span className="card__sourceDomain">
                          {sourceDomain(entry.url)}
                        </span>
                      )}
                    </span>
                    {entry.snippet !== null && (
                      <p className="card__snippet">{entry.snippet}</p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </li>
  )
}

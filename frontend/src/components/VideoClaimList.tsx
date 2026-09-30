/**
 * The detailed per-claim results of an ingested video.
 *
 * Each row shows what was claimed, who said it, when in the video, the verdict,
 * and the evidence behind it. This is the layer that makes a verdict checkable:
 * a scorecard tells you how many claims were false, this tells you which, said
 * by whom, at what timestamp, and on what evidence.
 *
 * Two states are kept visibly distinct throughout:
 *
 * - **verified** -- a verdict was reached. Its reason, supporting statement and
 *   citations are shown, and absent evidence renders as absent.
 * - **could not check** -- the check did not complete. There is no verdict, so no
 *   verdict-shaped row is drawn at all; the row says plainly that nothing was
 *   checked. Drawing an "unverifiable"-looking row here would be a lie about
 *   what the system found.
 */

import {
  collectSourceRows,
  displaySpeaker,
  formatClock,
  formatConfidence,
  hasConfidence,
  isLinkableSource,
  sourceDomain,
} from '../lib/format'
import { describeVerdict } from '../lib/verdicts'
import type { VideoClaimResult } from '../lib/api'
import { describeOutcome, isVerified, orderResultsForReview } from '../lib/videoReport'

export interface VideoClaimListProps {
  results: ReadonlyArray<VideoClaimResult>
}

export function VideoClaimList({ results }: VideoClaimListProps) {
  const ordered = orderResultsForReview(results)

  if (ordered.length === 0) {
    return (
      <section className="vclaims" aria-label="Claim details">
        <h2 className="vclaims__title">Claims</h2>
        <p className="empty">
          No checkable claims were found in this video. Claims are only extracted
          from finalized transcript lines, so a video with no factual statements
          produces no rows here.
        </p>
      </section>
    )
  }

  return (
    <section className="vclaims" aria-label="Claim details">
      <h2 className="vclaims__title">
        Claims
        <span className="vclaims__count">{ordered.length}</span>
      </h2>

      <ul className="vclaims__list">
        {ordered.map((result) => (
          <VideoClaimRow key={result.claim_id} result={result} />
        ))}
      </ul>
    </section>
  )
}

function VideoClaimRow({ result }: { result: VideoClaimResult }) {
  const verified = isVerified(result)
  const descriptor =
    verified && result.verdict !== null ? describeVerdict(result.verdict) : null
  const tone = descriptor?.tone ?? 'unknown'
  const sources = verified ? collectSourceRows(result.source, result.sources) : []
  const statement = verified ? result.supporting_statement : null
  const reported = hasConfidence(result.confidence)

  return (
    <li
      className={`vclaim vclaim--${verified ? tone : 'unchecked'}`}
      data-claim-id={result.claim_id}
      data-status={result.status}
    >
      <div className="vclaim__head">
        <span className="vclaim__speaker">{displaySpeaker(result.speaker)}</span>
        <span className="vclaim__clock">{formatClock(result.timestamp)}</span>
        <span className={`verdict verdict--${tone}`} title={descriptor?.description ?? 'The check did not complete.'}>
          <span className="verdict__glyph" aria-hidden="true">
            {verified ? descriptor?.glyph : '!'}
          </span>
          {verified ? descriptor?.short : 'NOT CHECKED'}
        </span>
      </div>

      <p className="vclaim__text">{result.claim}</p>

      {verified ? (
        <div className="vclaim__result">
          {result.reason !== null && result.reason !== '' && (
            <p className="vclaim__reason">{result.reason}</p>
          )}
          {statement !== null && statement !== '' && (
            <p className="vclaim__statement">{statement}</p>
          )}
          <p
            className={`vclaim__confidence${reported ? '' : ' vclaim__confidence--absent'}`}
            title={
              reported
                ? 'Relevance score reported by the search provider for the lead source.'
                : 'The search provider reported no relevance score for this claim.'
            }
          >
            <span className="vclaim__confidenceLabel">Confidence</span>
            <span>{formatConfidence(result.confidence)}</span>
          </p>
          {result.from_cache && (
            <p className="vclaim__cache" title="Served from the backend's persistent fact cache.">
              From cache
            </p>
          )}
          {sources.length > 0 && (
            <ul className="vclaim__sources">
              {sources.map((entry) => (
                <li key={entry.url} className="vclaim__sourceItem">
                  <span className="vclaim__source">
                    <span className="vclaim__sourceLabel">
                      {sources.length === 1 ? 'Source' : entry.primary ? 'Primary' : 'Also'}
                    </span>
                    {isLinkableSource(entry.url) ? (
                      <a
                        className="vclaim__link"
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
                      <span className="vclaim__sourceText">{entry.url}</span>
                    )}
                  </span>
                  {entry.snippet !== null && (
                    <p className="vclaim__snippet">{entry.snippet}</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <p className="vclaim__failure">
          {result.error ?? 'This claim was not checked; no verdict was reached.'}
        </p>
      )}

      <span className="vclaim__srStatus">{describeOutcome(result)}</span>
    </li>
  )
}

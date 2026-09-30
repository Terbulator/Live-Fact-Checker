/**
 * The result zone: the newest verdict, enlarged.
 *
 * During a live debate this is the only thing a judge actually came to see, so
 * it is given the largest type on the page and sits above the working columns.
 * Everything else in the layout answers the question it raises: the pipeline
 * below shows how the verdict was reached, the claim card shows it in context,
 * and the transcript shows the words it came from.
 *
 * Three states share this space:
 *
 * - **idle** — nothing has been checked yet, so the zone states the promise
 * - **checking** — a claim is being verified, shown as active work rather than
 *   as a blank or a spinner with no context
 * - **resolved** — verdict, claim, reason and source together
 *
 * `UNVERIFIABLE` is presented as its own outcome rather than folded into a
 * pass or a fail, which matches the verification module's principle that
 * missing evidence is never a confirmation.
 */

import {
  formatClock,
  formatConfidence,
  hasConfidence,
  isLinkableSource,
  sourceDomain,
  tallyVerdicts,
} from '../lib/format'
import { CHECKING_DESCRIPTOR, describeVerdict } from '../lib/verdicts'
import type { ClaimCard } from '../types/model'

export interface VerdictScoreboardProps {
  claims: ClaimCard[]
  /** True while a session is active, used to word the idle state. */
  isLive: boolean
}

export function VerdictScoreboard({ claims, isLive }: VerdictScoreboardProps) {
  const tally = tallyVerdicts(claims)
  const checked = tally.true + tally.false + tally.unverifiable + tally.ambiguous
  const pending = claims.length - checked

  const resolved = claims.filter((card) => card.verification !== null)
  const latest = resolved[resolved.length - 1]
  const pendingCard = claims.find((card) => card.pending)

  const latestVerification = latest?.verification ?? null
  const latestDescriptor =
    latestVerification !== null ? describeVerdict(latestVerification.verdict) : null
  const source = latestVerification?.source ?? ''
  const confidenceReported = hasConfidence(latestVerification?.confidence)

  return (
    <section className="scoreboard" aria-label="Verdict summary">
      <div className="scoreboard__head">
        <h2 className="scoreboard__title">Latest verdict</h2>
        {claims.length === 0 ? (
          <span className="scoreboard__idle">
            {isLive ? 'Listening for the first claim…' : 'No claims yet'}
          </span>
        ) : (
          <span className="scoreboard__total">
            <strong>{checked}</strong> checked
            {pending > 0 && <> · {pending} in flight</>}
          </span>
        )}
      </div>

      {latestDescriptor !== null && latestVerification !== null ? (
        <div className={`scoreboard__hero scoreboard__hero--${latestDescriptor.tone}`}>
          <span className="scoreboard__heroGlyph" aria-hidden="true">
            {latestDescriptor.glyph}
          </span>
          <span className="scoreboard__heroBody">
            <span className="scoreboard__heroVerdict">{latestDescriptor.short}</span>
            <span
              className={`card__confidence${confidenceReported ? '' : ' card__confidence--absent'}`}
              title={
                confidenceReported
                  ? 'Relevance score reported by the search provider for the lead source.'
                  : 'The search provider reported no relevance score for this claim.'
              }
            >
              <span className="card__confidenceLabel">Confidence</span>
              <span>{formatConfidence(latestVerification.confidence)}</span>
            </span>
            <span className="scoreboard__heroClaim">
              “{latest?.claim !== '' ? latest?.claim : latestVerification.reason}”
            </span>
            <span className="scoreboard__heroMeta">
              {latest?.speaker !== undefined && latest !== undefined && (
                <span className="scoreboard__heroWho">
                  {latest.speaker} · {formatClock(latest.timestamp)}
                </span>
              )}
              <span className="scoreboard__heroReason">{latestVerification.reason}</span>
              {latestVerification.supportingStatement != null &&
                latestVerification.supportingStatement !== '' && (
                  <span className="scoreboard__heroStatement">
                    {latestVerification.supportingStatement}
                  </span>
                )}
            </span>
            {source !== '' && (
              <span className="scoreboard__heroSource">
                <span className="scoreboard__heroSourceLabel">Source</span>
                {isLinkableSource(source) ? (
                  <a
                    className="scoreboard__heroLink"
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
                  <span className="scoreboard__heroSourceText">{source}</span>
                )}
              </span>
            )}
          </span>
        </div>
      ) : pendingCard !== undefined ? (
        <div className="scoreboard__hero scoreboard__hero--checking">
          <span className="scoreboard__heroGlyph" aria-hidden="true">
            <span className="verdict__spinner" />
          </span>
          <span className="scoreboard__heroBody">
            <span className="scoreboard__heroVerdict">{CHECKING_DESCRIPTOR.short}</span>
            <span className="scoreboard__heroClaim">“{pendingCard.claim}”</span>
            <span className="scoreboard__heroMeta">
              <span className="scoreboard__heroWho">
                {pendingCard.speaker ?? 'Unknown speaker'} ·{' '}
                {formatClock(pendingCard.timestamp)}
              </span>
              <span className="scoreboard__heroReason">
                Gathering evidence and deciding whether the claim holds.
              </span>
            </span>
          </span>
        </div>
      ) : (
        <div className="scoreboard__hero scoreboard__hero--empty">
          <span className="scoreboard__heroGlyph" aria-hidden="true">
            ·
          </span>
          <span className="scoreboard__heroBody">
            <span className="scoreboard__heroVerdict">AWAITING</span>
            <span className="scoreboard__heroClaim">
              {isLive
                ? 'Watching the live feed for a checkable claim'
                : 'No verdict yet'}
            </span>
            <span className="scoreboard__heroMeta">
              {isLive
                ? 'A claim appears the moment a speaker states something verifiable.'
                : 'Start a session to check claims as they are spoken.'}
            </span>
          </span>
        </div>
      )}

      <dl className="scoreboard__stats">
        <div className="scoreboard__stat scoreboard__stat--supported">
          <dt>True</dt>
          <dd>{tally.true}</dd>
        </div>
        <div className="scoreboard__stat scoreboard__stat--refuted">
          <dt>False</dt>
          <dd>{tally.false}</dd>
        </div>
        <div className="scoreboard__stat scoreboard__stat--unknown">
          <dt>Unverifiable</dt>
          <dd>{tally.unverifiable}</dd>
        </div>
        <div className="scoreboard__stat scoreboard__stat--unknown">
          <dt>Ambiguous</dt>
          <dd>{tally.ambiguous}</dd>
        </div>
        <div className="scoreboard__stat scoreboard__stat--pending">
          <dt>Checking</dt>
          <dd>{pending}</dd>
        </div>
      </dl>
    </section>
  )
}

/**
 * The scorecard for one ingested video.
 *
 * Answers "how did this video do?" in one block: what fraction of it was checked,
 * how the checked claims came out, and -- kept visually separate -- how many
 * could not be checked at all.
 *
 * That last number is the one most easily lost. A run where retrieval failed on
 * every claim produces no verdicts, and showing only the verdict distribution
 * would render an empty box that reads like "nothing false was found". So the
 * scorecard always states coverage, and a failed check is never given a share of
 * the verdict distribution to sum.
 */

import type { VideoScorecard as VideoScorecardModel } from '../lib/api'
import { coverageSentence, formatShare, scorecardRows } from '../lib/videoReport'

export interface VideoScorecardProps {
  scorecard: VideoScorecardModel
  /** Length of the source video, when the backend measured it. */
  durationSeconds?: number | null
}

export function VideoScorecard({ scorecard, durationSeconds }: VideoScorecardProps) {
  const rows = scorecardRows(scorecard)
  const coverage = formatShare(scorecard.coverage_ratio)
  const duration =
    typeof durationSeconds === 'number' && Number.isFinite(durationSeconds)
      ? formatDuration(durationSeconds)
      : null

  return (
    <section className="vscore" aria-label="Video fact-check scorecard">
      <header className="vscore__head">
        <h2 className="vscore__title">Video report</h2>
        <span className="vscore__source">
          {scorecard.total_claims} claim{scorecard.total_claims === 1 ? '' : 's'}
          {duration !== null && <span className="vscore__duration"> · {duration}</span>}
        </span>
      </header>

      <p className="vscore__coverage">{coverageSentence(scorecard)}</p>

      {coverage !== null && (
        <div
          className="vscore__coverageBar"
          role="img"
          aria-label={`${coverage} of claims were checked`}
        >
          <div className="vscore__coverageFill" style={{ width: coverage }} />
        </div>
      )}

      <dl className="vscore__rows">
        {rows.map((row) => (
          <div
            key={row.isFailure ? 'failure' : row.verdict}
            className={`vscore__row${row.isFailure ? ' vscore__row--failure' : ''}`}
          >
            <dt className="vscore__rowLabel">
              {row.isFailure && (
                <span className="vscore__rowNote" title="The check did not complete, so there is no verdict.">
                  (not a verdict)
                </span>
              )}
              {row.label}
            </dt>
            <dd className="vscore__rowValue">
              <span className="vscore__rowCount">{row.count}</span>
              <span className="vscore__rowShare">
                {row.share ?? (row.isFailure ? '—' : 'N/A')}
              </span>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

/** Render a duration in seconds as `m:ss`, or `h:mm:ss` past an hour. */
function formatDuration(seconds: number): string {
  const total = Math.round(seconds)
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const remainder = total % 60
  const mm = hours > 0 ? String(minutes).padStart(2, '0') : String(minutes)
  const ss = String(remainder).padStart(2, '0')
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`
}

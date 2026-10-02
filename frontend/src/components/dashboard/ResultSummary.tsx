/**
 * The answer.
 *
 * The one thing in the conversation the reader came for, so it gets the largest
 * type and no frame at all: a result that sits inside a bordered card reads as
 * one more panel, when it is in fact the message itself. A heading, a sentence,
 * the distribution, and a line of quiet metadata is enough.
 *
 * The four verdicts are inline pills rather than tiles. Each carries its own
 * family, a glyph and a word, so the distribution survives a colourblind reader
 * and a washed-out projector, at tints weak enough that they colour the
 * sentence rather than competing with it.
 *
 * `AMBIGUOUS` is a finding in its own right and takes lavender rather than
 * borrowing the attention yellow of `UNVERIFIABLE`, because "the sources
 * disagree" and "the sources say nothing" are different conclusions.
 */

import { Check, CircleAlert, LoaderCircle, Minus } from 'lucide-react'

import { VERDICTS } from '../landing/tone'
import type { TurnOutcome } from './thread'

export interface ResultSummaryProps {
  outcome: TurnOutcome
  /** True while more claims are still being verified. */
  pending: boolean
  /** What was submitted, so the sentence can name it. */
  subject: string
  /** Length of the source media, when there is any. */
  duration: string | null
  /** The backend's own completion note, when it reported one. */
  note?: string | null
}

export function ResultSummary({ outcome, pending, subject, duration, note }: ResultSummaryProps) {
  const claims = outcome.claims
  const claimWord = claims === 1 ? 'claim' : 'claims'

  const sentence =
    claims === 0
      ? `No checkable claims were found in ${subject}.`
      : pending
        ? `Checking ${claims} ${claimWord} from ${subject}…`
        : `I checked ${claims} ${claimWord} from ${subject}.`

  const pills: Array<{
    key: keyof typeof VERDICTS
    count: number
    Icon: typeof Check
  }> = [
    { key: 'true', count: outcome.true, Icon: Check },
    { key: 'false', count: outcome.false, Icon: Minus },
    { key: 'unverifiable', count: outcome.unverifiable, Icon: Minus },
    { key: 'ambiguous', count: outcome.ambiguous, Icon: Minus },
  ]

  const facts = [
    `${outcome.checked} ${outcome.checked === 1 ? 'claim' : 'claims'} checked`,
    outcome.sources > 0
      ? `${outcome.sources} ${outcome.sources === 1 ? 'source' : 'sources'}`
      : null,
    duration,
  ].filter((part): part is string => part !== null)

  return (
    <section className="result" aria-label="Fact-check result">
      <h3 className="result__heading">
        {pending ? (
          <LoaderCircle size={16} className="spin" aria-hidden="true" />
        ) : (
          <Check size={16} aria-hidden="true" />
        )}
        {pending ? 'Fact-checking in progress' : 'Fact-check complete'}
      </h3>

      <p className="result__sentence">{sentence}</p>

      <ul className="pills">
        {pills.map((pill) => (
          <li key={pill.key} className={`pill pill--${pill.key}`} data-empty={pill.count === 0}>
            <pill.Icon size={13} aria-hidden="true" />
            <span className="pill__count">{pill.count}</span>
            <span className="pill__label">{VERDICTS[pill.key].label}</span>
          </li>
        ))}
      </ul>

      <p className="result__facts">{facts.join('  ·  ')}</p>

      {outcome.failed && (
        <p className="result__failed">
          <CircleAlert size={13} aria-hidden="true" />
          {claims - outcome.checked === 1
            ? '1 claim could not be checked at all.'
            : `${claims - outcome.checked} claims could not be checked at all.`}{' '}
          A failed check is not a verdict.
        </p>
      )}

      {note !== undefined && note !== null && note !== '' && (
        <p className="result__note">{note}</p>
      )}
    </section>
  )
}

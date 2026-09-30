/**
 * The video report: scorecard and per-claim results.
 *
 * The property under test throughout is that an unmeasured number is never shown
 * as a number. The scorecard has to be able to say "nothing could be checked"
 * without that reading as "nothing was true", and the claim list has to keep a
 * failed check visibly distinct from a claim that was checked and found
 * unverifiable -- because those are completely different findings.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { VideoClaimList } from './VideoClaimList'
import { VideoScorecard } from './VideoScorecard'
import type { VideoClaimResult, VideoScorecard as VideoScorecardModel } from '../lib/api'
import { completionMessage, coverageSentence, formatShare } from '../lib/videoReport'
import type { Verdict } from '../types/events'

function scorecard(overrides: Partial<VideoScorecardModel> = {}): VideoScorecardModel {
  return {
    total_claims: 4,
    checked_claims: 3,
    failed_claims: 1,
    true_claims: 1,
    false_claims: 1,
    ambiguous_claims: 0,
    unverifiable_claims: 1,
    true_ratio: 1 / 3,
    false_ratio: 1 / 3,
    ambiguous_ratio: 0,
    unverifiable_ratio: 1 / 3,
    coverage_ratio: 0.75,
    ...overrides,
  }
}

function result(overrides: Partial<VideoClaimResult> = {}): VideoClaimResult {
  return {
    claim_id: 'c1',
    claim: 'Water boils at 100 degrees Celsius at sea level.',
    speaker: 'Host',
    timestamp: 12.4,
    status: 'verified',
    verdict: 'TRUE' as Verdict,
    reason: 'Authoritative sources agree.',
    supporting_statement: 'example.com states: “Water boils at 100 °C.”',
    source: 'https://example.com/water',
    sources: [
      {
        url: 'https://example.com/water',
        title: 'Boiling point',
        snippet: 'Water boils at 100 °C at sea level.',
        confidence: 0.9,
      },
    ],
    confidence: 0.9,
    from_cache: false,
    error: null,
    ...overrides,
  }
}

describe('formatShare', () => {
  it('renders a real ratio as a percentage', () => {
    expect(formatShare(0.25)).toBe('25%')
    expect(formatShare(1)).toBe('100%')
    expect(formatShare(0)).toBe('0%')
  })

  it('returns null when nothing was measured', () => {
    // The distinction that matters: null is "no basis for a number", not zero.
    expect(formatShare(null)).toBeNull()
    expect(formatShare(undefined)).toBeNull()
    expect(formatShare(Number.NaN)).toBeNull()
  })
})

describe('coverageSentence', () => {
  it('says so plainly when nothing could be checked', () => {
    const sentence = coverageSentence(scorecard({ checked_claims: 0, true_ratio: null, false_ratio: null, unverifiable_ratio: null, coverage_ratio: 0 }))

    // The component's wording is "None of the N claims could be checked",
    // so match that rather than the inverted phrase this test used to expect.
    expect(sentence).toContain('could be checked')
  })

  it('states coverage alongside the verdict distribution', () => {
    expect(coverageSentence(scorecard())).toContain('75% (3 of 4)')
  })
})

describe('VideoScorecard', () => {
  it('shows each verdict count with its share', () => {
    render(<VideoScorecard scorecard={scorecard()} />)

    expect(screen.getByText('True')).toBeInTheDocument()
    expect(screen.getByText('False')).toBeInTheDocument()
    expect(screen.getByText('Unverifiable')).toBeInTheDocument()
    // Three of the four rows are a third each (1 of 3 produced a verdict), so
    // the share legitimately appears three times.
    expect(screen.getAllByText('33%').length).toBe(3)
  })

  it('marks the not-checked row as not a verdict', () => {
    render(<VideoScorecard scorecard={scorecard()} />)

    expect(screen.getByText('Not checked')).toBeInTheDocument()
    expect(screen.getByText('(not a verdict)')).toBeInTheDocument()
  })

  it('never renders a share for a row that has none', () => {
    // The not-checked row must not borrow a percentage, because a reader could
    // add it to the distribution and read a finding that was never measured.
    const { container } = render(
      <VideoScorecard
        scorecard={scorecard({ failed_claims: 2, true_ratio: null, false_ratio: null, ambiguous_ratio: null, unverifiable_ratio: null })}
      />,
    )

    const failureRow = container.querySelector('.vscore__row--failure')
    expect(failureRow).not.toBeNull()
    expect(failureRow?.textContent).not.toMatch(/\d+%/)
  })

  it('shows no percentages at all when nothing was checked', () => {
    const { container } = render(
      <VideoScorecard
        scorecard={scorecard({
          checked_claims: 0,
          failed_claims: 4,
          true_claims: 0,
          false_claims: 0,
          unverifiable_claims: 0,
          true_ratio: null,
          false_ratio: null,
          ambiguous_ratio: null,
          unverifiable_ratio: null,
          coverage_ratio: 0,
        })}
      />,
    )

    // "None could be checked" must not come with a distribution to read.
    expect(container.textContent).not.toMatch(/\d+%/)
  })

  it('renders a true zero share when something genuinely was checked', () => {
    render(<VideoScorecard scorecard={scorecard({ ambiguous_claims: 0, ambiguous_ratio: 0, true_claims: 0, true_ratio: 0 })} />)

    // A genuine zero is a measurement and is shown, unlike an absent one.
    expect(screen.getAllByText('0%').length).toBeGreaterThan(0)
  })
})

describe('VideoClaimList', () => {
  it('renders the claim, its speaker and its timestamp', () => {
    render(<VideoClaimList results={[result()]} />)

    expect(screen.getByText(/Water boils at 100 degrees/)).toBeInTheDocument()
    expect(screen.getByText('Host')).toBeInTheDocument()
    expect(screen.getByText('0:12.4')).toBeInTheDocument()
  })

  it('renders the supporting statement and the citation', () => {
    render(<VideoClaimList results={[result()]} />)

    expect(screen.getByText(/Water boils at 100 °C\./)).toBeInTheDocument()
    // The citation link is labelled with the source's host, not its title, so
    // the accessible name is the domain.
    expect(screen.getByRole('link', { name: /example\.com/ })).toHaveAttribute(
      'href',
      'https://example.com/water',
    )
  })

  it('shows the provider confidence when one was reported', () => {
    render(<VideoClaimList results={[result({ confidence: 0.9 })]} />)

    // formatConfidence renders the provider's own number verbatim rather than
    // padding it to a fixed precision, so 0.9 stays "0.9".
    expect(screen.getByText('0.9')).toBeInTheDocument()
  })

  it('shows N/A rather than inventing a confidence', () => {
    render(<VideoClaimList results={[result({ confidence: null })]} />)

    expect(screen.getByText('N/A')).toBeInTheDocument()
    expect(screen.queryByText('0.90')).not.toBeInTheDocument()
  })

  it('distinguishes a failed check from an unverifiable verdict', () => {
    const { container } = render(
      <VideoClaimList
        results={[
          result({
            claim_id: 'failed1',
            status: 'failed',
            verdict: null,
            reason: null,
            supporting_statement: null,
            source: null,
            sources: [],
            confidence: null,
            error: 'Verification did not complete; no verdict was reached for this claim.',
          }),
        ]}
      />,
    )

    // The label must not read as a verdict.
    expect(screen.getByText('NOT CHECKED')).toBeInTheDocument()
    expect(screen.queryByText('UNVERIFIABLE')).not.toBeInTheDocument()
    expect(screen.getByText(/Verification did not complete/)).toBeInTheDocument()

    const row = container.querySelector('.vclaim--unchecked')
    expect(row).not.toBeNull()
    expect(row?.getAttribute('data-status')).toBe('failed')
  })

  it('does not show a failure as if it had evidence', () => {
    render(
      <VideoClaimList
        results={[
          result({
            claim_id: 'failed1',
            status: 'failed',
            verdict: null,
            reason: null,
            supporting_statement: null,
            source: null,
            sources: [],
            confidence: null,
            error: 'Could not check this claim.',
          }),
        ]}
      />,
    )

    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.queryByText('N/A')).not.toBeInTheDocument()
  })

  it('lists false claims before the rest, each in timestamp order', () => {
    render(
      <VideoClaimList
        results={[
          result({ claim_id: 'a', verdict: 'TRUE' as Verdict, claim: 'True claim.', timestamp: 1 }),
          result({ claim_id: 'b', verdict: 'FALSE' as Verdict, claim: 'False claim one.', timestamp: 5 }),
          result({ claim_id: 'c', verdict: 'FALSE' as Verdict, claim: 'False claim two.', timestamp: 2 }),
        ]}
      />,
    )

    // `getAllByRole('listitem')` also returns the per-source <li>s nested in
    // each claim, so restrict to the claim rows themselves.
    const rendered = screen
      .getAllByRole('listitem')
      .map((node) => node.getAttribute('data-claim-id'))
      .filter((id): id is string => id !== null)
    // False claims lead, because they are the reason to read the report at all.
    expect(rendered).toEqual(['c', 'b', 'a'])
  })

  it('marks a replayed verdict as coming from cache', () => {
    render(<VideoClaimList results={[result({ from_cache: true })]} />)

    expect(screen.getByText('From cache')).toBeInTheDocument()
  })

  it('explains an empty result instead of rendering a blank panel', () => {
    render(<VideoClaimList results={[]} />)

    expect(screen.getByText(/No checkable claims were found/)).toBeInTheDocument()
  })
})

describe('completionMessage', () => {
  it('surfaces a failure count rather than reporting a clean run', () => {
    // "verified 3 of 4" reads as a clean result even when the shortfall was a
    // broken retrieval, so the failure is named in the sentence.
    const message = completionMessage({
      claims_extracted: 4,
      verifications_completed: 3,
      scorecard: scorecard({ failed_claims: 1 }),
    })

    expect(message).toContain('1 could not be checked')
  })

  it('omits the failure clause when nothing failed', () => {
    const message = completionMessage({
      claims_extracted: 2,
      verifications_completed: 2,
      scorecard: scorecard({ failed_claims: 0 }),
    })

    expect(message).toBe('Found 2 claims, verified 2.')
  })

  it('still reads correctly against an older backend with no scorecard', () => {
    const message = completionMessage({ claims_extracted: 2, verifications_completed: 2 })

    expect(message).toBe('Found 2 claims, verified 2.')
  })
})

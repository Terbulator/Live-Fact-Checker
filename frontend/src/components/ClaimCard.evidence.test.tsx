/**
 * Display of the three separate concepts on a resolved claim.
 *
 *   verdict              what the system concluded
 *   supporting statement why, in prose traceable to a source
 *   confidence           the search provider's own score, or "N/A"
 *
 * The tests that matter here are the negative ones. A null confidence must
 * render as an explicit absence, and no code path may substitute 100%, 90% or
 * any other number, because a displayed number is read as a measurement.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ClaimCard } from './ClaimCard'
import { formatConfidence, hasConfidence } from '../lib/format'
import type { VerificationEvent, Verdict } from '../types/events'
import type { ClaimCard as ClaimCardModel } from '../types/model'

function verification(overrides: Partial<VerificationEvent> = {}): VerificationEvent {
  return {
    type: 'verification',
    eventId: 'e1',
    claimId: 'c1',
    sessionId: 's1',
    speaker: 'Speaker 1',
    timestamp: 12.4,
    verdict: 'TRUE' as Verdict,
    reason: 'Authoritative sources corroborate the key facts.',
    source: 'https://nasa.gov/apollo',
    ...overrides,
  }
}

function renderCard(overrides: Partial<VerificationEvent> = {}) {
  const model: ClaimCardModel = {
    claimId: 'c1',
    speaker: 'Speaker 1',
    timestamp: 12.4,
    claim: 'Apollo 11 landed on the Moon in 1969.',
    claimType: 'historical_fact',
    pending: false,
    verification: verification(overrides),
    transcriptKey: 'Speaker 1@12.40',
  }
  return render(
    <ul>
      <ClaimCard card={model} selected={false} onSelect={() => {}} />
    </ul>,
  )
}

// ---------------------------------------------------------------------------
// Supporting statement
// ---------------------------------------------------------------------------

describe('supporting statement', () => {
  it('is shown alongside the reason and the sources', () => {
    renderCard({
      supportingStatement:
        'The retrieved evidence supports this claim. nasa.gov states: “Apollo 11 landed humans on the Moon.”',
    })

    expect(screen.getByText(/retrieved evidence supports this claim/i)).toBeInTheDocument()
    // The reason still renders: the two fields are additive, not a replacement.
    expect(screen.getByText('Authoritative sources corroborate the key facts.')).toBeInTheDocument()
    expect(screen.getByRole('link')).toBeInTheDocument()
  })

  it('is simply absent when the backend sent none', () => {
    const { container } = renderCard({ supportingStatement: null })

    expect(container.querySelector('.card__statement')).toBeNull()
    expect(screen.getByText('Authoritative sources corroborate the key facts.')).toBeInTheDocument()
  })

  it('is absent for an event that predates the field', () => {
    const { container } = renderCard({ supportingStatement: undefined })
    expect(container.querySelector('.card__statement')).toBeNull()
  })

  it('renders an ambiguous statement, conflict and all', () => {
    renderCard({
      verdict: 'AMBIGUOUS' as Verdict,
      supportingStatement:
        'The retrieved evidence supports more than one reading of this claim. one.example.com states: “Growth may vary by region.” Meanwhile two.example.com states: “Growth rose nationally.”',
    })

    expect(screen.getByText(/more than one reading/i)).toBeInTheDocument()
    expect(screen.getByText('AMBIGUOUS')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Confidence
// ---------------------------------------------------------------------------

describe('confidence display', () => {
  it('shows the provider score exactly as it was reported', () => {
    renderCard({ confidence: 0.73 })
    expect(screen.getByText('0.73')).toBeInTheDocument()
  })

  it('shows N/A rather than 100% when the provider reported nothing', () => {
    const { container } = renderCard({ confidence: null })

    expect(screen.getByText('N/A')).toBeInTheDocument()
    expect(container.textContent).not.toContain('100%')
    expect(container.textContent).not.toContain('1.00')
  })

  it('shows N/A for an event with no confidence field at all', () => {
    renderCard({ confidence: undefined })
    expect(screen.getByText('N/A')).toBeInTheDocument()
  })

  it('does not invent a score for a zero', () => {
    // 0.0 is a real measurement, so it is shown, not treated as missing.
    renderCard({ confidence: 0 })
    expect(screen.getByText('0')).toBeInTheDocument()
    expect(screen.queryByText('N/A')).not.toBeInTheDocument()
  })
})

describe('formatConfidence', () => {
  it('shows a reported score verbatim, with no rounding', () => {
    expect(formatConfidence(0.73)).toBe('0.73')
    expect(formatConfidence(1)).toBe('1')
    expect(formatConfidence(0.999)).toBe('0.999')
    expect(formatConfidence(0.05)).toBe('0.05')
  })

  it('never rounds a score up into perfect confidence', () => {
    // Displayed as 1.00, this would read as certainty the provider never gave.
    expect(formatConfidence(0.999)).not.toBe('1')
    expect(formatConfidence(0.999)).not.toBe('1.00')
  })

  it('reports every unusable value as absent', () => {
    for (const value of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(formatConfidence(value)).toBe('N/A')
      expect(hasConfidence(value)).toBe(false)
    }
  })

  it('never substitutes a number for an absent one', () => {
    expect(formatConfidence(null)).not.toMatch(/\d/)
    expect(formatConfidence(undefined)).not.toMatch(/\d/)
  })
})

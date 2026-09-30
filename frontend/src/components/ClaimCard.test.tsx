/**
 * ClaimCard evidence rendering, including the multi-source extension.
 *
 * The `source` string must keep working exactly as before for a backend that
 * sends no `sources` field; these tests pin that alongside the new list.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ClaimCard } from './ClaimCard'
import { collectSources } from '../lib/format'
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

function card(overrides: Partial<VerificationEvent> = {}): ClaimCardModel {
  return {
    claimId: 'c1',
    speaker: 'Speaker 1',
    timestamp: 12.4,
    claim: 'Apollo 11 landed on the Moon in 1969.',
    claimType: 'historical_fact',
    pending: false,
    verification: verification(overrides),
    transcriptKey: 'Speaker 1@12.40',
  }
}

function renderCard(overrides: Partial<VerificationEvent> = {}) {
  return render(
    <ul>
      <ClaimCard card={card(overrides)} selected={false} onSelect={() => {}} />
    </ul>,
  )
}

// ---------------------------------------------------------------------------
// collectSources
// ---------------------------------------------------------------------------

describe('collectSources', () => {
  it('treats an absent sources field as a single source', () => {
    const rows = collectSources(verification())
    expect(rows).toEqual([
      { url: 'https://nasa.gov/apollo', title: null, snippet: null, primary: true },
    ])
  })

  it('marks the source field as primary and the rest as supporting', () => {
    const rows = collectSources(
      verification({
        sources: [
          { url: 'https://icc-cricket.com/archive', title: 'ICC Archive', snippet: 'Yes.' },
        ],
      }),
    )
    expect(rows.map((row) => row.primary)).toEqual([true, false])
    expect(rows[1].title).toBe('ICC Archive')
  })

  it('does not repeat the primary url', () => {
    const rows = collectSources(
      verification({
        sources: [{ url: 'https://nasa.gov/apollo', title: 'Same page', snippet: null }],
      }),
    )
    expect(rows).toHaveLength(1)
  })

  it('skips entries with no usable url', () => {
    const rows = collectSources(
      verification({
        sources: [
          { url: '', title: 'No URL', snippet: 'x' },
          { url: 'https://ok.example.com/1', title: 'Fine', snippet: 'y' },
        ],
      }),
    )
    expect(rows.map((row) => row.url)).toEqual([
      'https://nasa.gov/apollo',
      'https://ok.example.com/1',
    ])
  })

  it('normalises blank titles and snippets to null', () => {
    const rows = collectSources(
      verification({
        sources: [{ url: 'https://ok.example.com/1', title: '   ', snippet: '  ' }],
      }),
    )
    expect(rows[1].title).toBeNull()
    expect(rows[1].snippet).toBeNull()
  })

  it('tolerates a malformed sources array', () => {
    const rows = collectSources(
      verification({ sources: [null, 'junk', { url: 'https://ok.example.com/1' }] as never }),
    )
    expect(rows.map((row) => row.url)).toEqual([
      'https://nasa.gov/apollo',
      'https://ok.example.com/1',
    ])
  })
})

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

describe('ClaimCard evidence area', () => {
  it('renders a single source as before, with no count heading', () => {
    renderCard()
    expect(screen.getByRole('link')).toHaveAttribute('href', 'https://nasa.gov/apollo')
    expect(screen.getByText('Source')).toBeInTheDocument()
    expect(screen.queryByText(/^Sources \(/)).not.toBeInTheDocument()
  })

  it('renders several sources, each with a title, domain and snippet', () => {
    renderCard({
      sources: [
        {
          url: 'https://icc-cricket.com/archive',
          title: 'ICC Archive',
          snippet: 'India defeated Sri Lanka to win the 2011 World Cup.',
        },
        {
          url: 'https://bbc.co.uk/sport/cricket',
          title: 'BBC Sport',
          snippet: 'A retrospective on the 2011 final.',
        },
      ],
    })

    expect(screen.getByText('Sources (3)')).toBeInTheDocument()
    expect(screen.getByText('Primary')).toBeInTheDocument()
    expect(screen.getAllByText('Also')).toHaveLength(2)
    expect(screen.getByText('ICC Archive')).toBeInTheDocument()
    expect(screen.getByText('BBC Sport')).toBeInTheDocument()
    expect(screen.getByText('icc-cricket.com')).toBeInTheDocument()
    expect(screen.getByText('bbc.co.uk')).toBeInTheDocument()
    expect(
      screen.getByText('India defeated Sri Lanka to win the 2011 World Cup.'),
    ).toBeInTheDocument()
  })

  it('links every source', () => {
    renderCard({
      sources: [{ url: 'https://icc-cricket.com/archive', title: 'ICC', snippet: 'Yes.' }],
    })
    const links = screen.getAllByRole('link')
    expect(links).toHaveLength(2)
    expect(links[0]).toHaveAttribute('href', 'https://nasa.gov/apollo')
    expect(links[1]).toHaveAttribute('href', 'https://icc-cricket.com/archive')
  })

  it('falls back to the domain when a source has no title', () => {
    renderCard({
      sources: [{ url: 'https://icc-cricket.com/archive', title: null, snippet: null }],
    })
    expect(screen.getByText('icc-cricket.com')).toBeInTheDocument()
  })

  it('renders an unverifiable verdict with its sources', () => {
    renderCard({
      verdict: 'UNVERIFIABLE' as Verdict,
      reason: 'Available sources provide conflicting information.',
      sources: [
        { url: 'https://a.example.com/report', title: 'A Report', snippet: 'Says November 15.' },
        { url: 'https://b.example.com/analysis', title: 'An Analysis', snippet: 'Says next year.' },
      ],
    })
    expect(screen.getByText('Sources (3)')).toBeInTheDocument()
    expect(screen.getByText('Says November 15.')).toBeInTheDocument()
    expect(screen.getByText('Says next year.')).toBeInTheDocument()
  })
})

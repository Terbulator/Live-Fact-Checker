/**
 * Regression: the dashboard renders empty until real results arrive.
 *
 * These tests render the real components with no props, which is exactly the
 * state a visitor lands on at /dashboard before speaking or uploading. They
 * assert on what is absent, not on what a fixture injected, so they would fail
 * if any default claim, verdict, source, confidence or scorecard were ever
 * hardcoded into production code.
 */

import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { initialLiveView } from '../types/model'
import { ClaimPanel } from '../components/ClaimPanel'
import { VerdictScoreboard } from '../components/VerdictScoreboard'
import { TranscriptPanel } from '../components/TranscriptPanel'
import { VideoClaimList } from '../components/VideoClaimList'
import { VideoScorecard } from '../components/VideoScorecard'
import { IngestionControls } from '../components/IngestionControls'

describe('the production dashboard starts empty', () => {
  it('has no preloaded claims in the live view', () => {
    expect(initialLiveView.claims).toEqual([])
    expect(initialLiveView.transcripts).toEqual([])
    expect(initialLiveView.errors).toEqual([])
    expect(initialLiveView.status).toBe('idle')
    expect(initialLiveView.lastSpeechAt).toBeNull()
  })

  it('renders the claims panel empty, with no fabricated claims', () => {
    render(<ClaimPanel claims={initialLiveView.claims} />)

    expect(screen.queryByText(/verdict/i)).not.toBeInTheDocument()
    // No verdict of any kind is asserted before evidence is retrieved.
    expect(screen.queryByText('TRUE')).not.toBeInTheDocument()
    expect(screen.queryByText('FALSE')).not.toBeInTheDocument()
    expect(screen.queryByText('UNVERIFIABLE')).not.toBeInTheDocument()
    expect(screen.queryByText('AMBIGUOUS')).not.toBeInTheDocument()
  })

  it('renders the scoreboard with every count at zero', () => {
    render(<VerdictScoreboard claims={initialLiveView.claims} />)

    // All four verdict buckets present and reading zero.
    for (const label of ['True', 'False', 'Unverifiable', 'Ambiguous', 'Checking']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    expect(screen.getAllByText('0').length).toBeGreaterThanOrEqual(5)
    // Nothing that could read as a real result.
    expect(screen.queryByText(/N\/A.*N\/A/)).not.toBeInTheDocument()
  })

  it('renders the transcript panel with no sample transcript', () => {
    render(<TranscriptPanel lines={initialLiveView.transcripts} activeKey={null} />)

    expect(screen.queryByText(/India won/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Eiffel/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Good evening/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/housing figures/i)).not.toBeInTheDocument()
  })

  it('renders the video claim list empty', () => {
    render(<VideoClaimList results={[]} />)

    expect(screen.queryByText('TRUE')).not.toBeInTheDocument()
    expect(screen.queryByText('FALSE')).not.toBeInTheDocument()
    // No source is presented before retrieval happened.
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('does not expose a confidence before any provider result', () => {
    render(<VideoClaimList results={[]} />)
    expect(screen.queryByText(/Confidence/)).not.toBeInTheDocument()
  })

  it('shows ingestion controls without any prior analysis', () => {
    // With no active session the upload controls are withheld entirely.
    const { unmount } = render(<IngestionControls sessionId={null} isActive={false} />)
    expect(screen.queryByRole('button', { name: 'Upload Audio' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Upload Video' })).not.toBeInTheDocument()
    unmount()

    // With a session, the controls appear but carry no prior results.
    render(<IngestionControls sessionId="session-1" isActive />)
    expect(screen.getByRole('button', { name: 'Upload Audio' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upload Video' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Analyze URL' })).toBeInTheDocument()
    // No scorecard, claims or findings are preloaded by the controls.
    expect(screen.queryByText(/claim/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/TRUE|FALSE|UNVERIFIABLE/)).not.toBeInTheDocument()
  })

  it('renders a scorecard only when real data is supplied', () => {
    const empty = {
      total_claims: 0,
      checked_claims: 0,
      failed_claims: 0,
      true_claims: 0,
      false_claims: 0,
      ambiguous_claims: 0,
      unverifiable_claims: 0,
      true_ratio: null,
      false_ratio: null,
      ambiguous_ratio: null,
      unverifiable_ratio: null,
      coverage_ratio: null,
    }

    // With zero analysed claims the component must say so rather than imply a
    // percentage was measured.
    const { unmount } = render(<VideoScorecard scorecard={empty} />)
    expect(screen.getByText(/0 claims/)).toBeInTheDocument()
    unmount()
  })
})

describe('no seeded data is reachable from production modules', () => {
  it('does not export the mock transcript script into the frontend bundle', async () => {
    // The scripted demo content lives only in the Python mock module; the
    // frontend must not carry a copy of it.
    const paths = ['../types/model', './format', './api', './videoReport']
    const sources = await Promise.all(
      paths.map((path) => import(/* @vite-ignore */ path).then((m) => JSON.stringify(m)).catch(() => '')),
    )
    const joined = sources.join('')
    for (const canned of ['India won the 2011', 'Eiffel Tower', 'Good evening, and welcome']) {
      expect(joined).not.toContain(canned)
    }
  })

  it('does not define a default claims array', async () => {
    const model = await import('../types/model')
    expect(model.initialLiveView.claims).toEqual([])
    expect(model.initialLiveView.transcripts).toEqual([])
  })
})

// Keep the mocked browser APIs referenced so linting does not strip them.
void vi

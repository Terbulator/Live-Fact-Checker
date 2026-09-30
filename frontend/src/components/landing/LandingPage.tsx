import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

import { Navigation } from './Navigation'
import { Hero } from './Hero'
import { ProblemSolution } from './ProblemSolution'
import { HowItWorks } from './HowItWorks'
import { LiveDemo } from './LiveDemo'
import { EvidenceSection } from './EvidenceSection'
import { Differentiator } from './Differentiator'
import { VerdictSystem } from './VerdictSystem'
import { UseCases } from './UseCases'
import { Technology } from './Technology'
import { Roadmap } from './Roadmap'
import { TrustSection } from './TrustSection'
import { FinalCTA } from './FinalCTA'
import { Footer } from './Footer'

/**
 * Scroll to the section named in the URL hash.
 *
 * Needed because the sections are on this route: a plain `#id` link only
 * scrolls on a full page load, not after a client-side navigation.
 */
function useHashScroll() {
  const { hash } = useLocation()

  useEffect(() => {
    if (!hash) return
    const target = document.getElementById(hash.slice(1))
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [hash])
}

export function LandingPage() {
  useHashScroll()

  return (
    <div className="landing-page">
      <Navigation />
      <main className="landing-main">
        <Hero />
        <ProblemSolution />
        <HowItWorks />
        <LiveDemo />
        <EvidenceSection />
        <Differentiator />
        <VerdictSystem />
        <UseCases />
        <Technology />
        <Roadmap />
        <TrustSection />
        <FinalCTA />
      </main>
      <Footer />
    </div>
  )
}

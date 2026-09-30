import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

import { Navigation } from './Navigation'
import { Hero } from './Hero'
import { VideoSection } from './VideoSection'
import { PipelineSection, InputTypes } from './PipelineSection'
import { AskListenVerify } from './AskListenVerify'
import { EvidenceFlow, SourcesSection } from './EvidenceFlow'
import { VideoAnalysis, Technology, Capabilities } from './VideoAnalysis'
import { VideoScorecardSection } from './VideoScorecardSection'
import { TrustSection, Faq, FinalCTA, Footer } from './TrustSection'

/**
 * Marketing landing page.
 *
 * COLOUR RHYTHM
 * The page alternates between light editorial bands and dark product bands so
 * the eye can tell "we are explaining" from "here is the product". Reading top
 * to bottom:
 *
 *   light hero · light video · light pipeline · DARK video · light inputs ·
 *   DARK product demo · light video · light evidence · light sources ·
 *   DARK video analysis · light video · DARK architecture · light capabilities ·
 *   light report · light trust · light faq · DARK call to action · DARK footer
 *
 * Product panels inside light bands (the hero preview, the transcript/verdict
 * split, the scorecard, the claim report) stay dark by design: the contrast is
 * the point, and it matches how the real interface looks.
 *
 * All four video slots pass an empty `videoSrc`, so each renders its designed
 * placeholder. To publish a recording, drop the file into
 * `frontend/public/videos/` and set the path — no other change is needed.
 */

/** Scroll to the section named in the URL hash. */
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
    <div className="lfp-root">
      <Navigation />

      <main className="lfp-main">
        <Hero />

        {/* VIDEO_01_HERO_DEMO — /videos/hero-demo.mp4 */}
        <VideoSection
          id="demo-hero"
          surface="warm"
          eyebrow="SEE IT IN ACTION"
          title="From speech to verified fact."
          description="The whole path in one recording: live capture, claim extraction, evidence retrieval, verdict."
          videoSrc=""
          poster=""
          placeholderLabel="Product demonstration"
        />

        <PipelineSection surface="beige" />

        {/* VIDEO_02_PIPELINE_DEMO — /videos/pipeline-demo.mp4 */}
        <VideoSection
          id="demo-pipeline"
          surface="black"
          title="Watch a claim move through the pipeline."
          description="Each stage shown end to end, with the transcript and the retrieved evidence side by side."
          videoSrc=""
          poster=""
          placeholderLabel="Pipeline walkthrough"
        />

        <InputTypes surface="white" />

        <AskListenVerify surface="mint" />

        {/* VIDEO_03_VERIFICATION_DEMO — /videos/verification-demo.mp4 */}
        <VideoSection
          id="demo-verification"
          surface="warm"
          title="See exactly how verification works."
          description="What happens between a sentence being spoken and a verdict being shown."
          videoSrc=""
          poster=""
          placeholderLabel="Verification walkthrough"
        />

        <EvidenceFlow surface="paper" />

        <SourcesSection surface="warm" />

        <VideoAnalysis surface="charcoal" />

        {/* VIDEO_04_VIDEO_ANALYSIS_DEMO — /videos/video-analysis-demo.mp4 */}
        <VideoSection
          id="demo-video"
          surface="warm"
          title="Watch an entire video become a fact-check report."
          description="Upload, transcription, per-claim verification and the resulting scorecard."
          videoSrc=""
          poster=""
          placeholderLabel="Video analysis walkthrough"
        />

        <Technology surface="black" />
        <Capabilities surface="beige" />
        <VideoScorecardSection surface="white" />
        <TrustSection surface="paper" />
        <Faq surface="warm" />
        <FinalCTA />
      </main>

      <Footer />
    </div>
  )
}

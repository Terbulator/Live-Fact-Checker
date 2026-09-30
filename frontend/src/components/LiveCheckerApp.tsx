/**
 * The live fact-checking surface.
 *
 * Extracted from the former application shell so it can be mounted inside the
 * dashboard route without importing the router (which would be circular). It is
 * otherwise unchanged: a read-only observer of the backend pipeline that starts
 * and stops sessions, streams the live transcript, and shows each claim's
 * verdict as it resolves. It never produces transcripts, claims or verdicts
 * itself.
 *
 * Layout is ordered by how quickly a judge needs each thing:
 *
 *   1. the pipeline flow, so the shape of the system reads immediately
 *   2. the live transcript, because speech comes first
 *   3. the claim cards and scoreboard, which are the answer
 *
 * Selecting a claim highlights the transcript line it came from; that single
 * piece of cross-linking is what makes the two columns read as one story.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'

import { ClaimPanel } from './ClaimPanel'
import { ErrorPanel } from './ErrorPanel'
import { PipelineFlow } from './PipelineFlow'
import { SessionControls } from './SessionControls'
import { StatusBar } from './StatusBar'
import { TranscriptPanel } from './TranscriptPanel'
import { VerdictScoreboard } from './VerdictScoreboard'
import { useNow } from '../hooks/useNow'
import { useSession } from '../hooks/useSession'
import { useVoiceSession } from '../hooks/useVoiceSession'
import { BACKEND_URL } from '../lib/config'

export default function LiveCheckerApp() {
  const {
    phase,
    connection,
    session,
    view,
    fault,
    start,
    stop,
    reconnect,
    dismissFault,
    clearErrors,
  } = useSession()

  const {
    status: voiceStatus,
    error: voiceError,
    start: startVoice,
    stop: stopVoice,
  } = useVoiceSession({
    externalSessionId: session?.sessionId ?? null,
  })

  const isLive = phase === 'active' || phase === 'stopping'
  const now = useNow(isLive)

  const [selectedClaimId, setSelectedClaimId] = useState<string | null>(null)
  const [isDemo, setIsDemo] = useState(false)

  // Start voice session when backend session becomes active (for Go Live)
  useEffect(() => {
    if (phase === 'active' && !isDemo && voiceStatus === 'idle') {
      void startVoice()
    }
  }, [phase, isDemo, voiceStatus, startVoice])

  // Stop voice session when backend session stops
  useEffect(() => {
    if (phase === 'idle' && voiceStatus !== 'idle' && voiceStatus !== 'stopping') {
      void stopVoice()
    }
  }, [phase, voiceStatus, stopVoice])

  // Resolve the selected claim to the transcript line it originated from, so
  // the transcript can scroll to and highlight it.
  const activeLineKey = useMemo(() => {
    if (selectedClaimId === null) return null
    const card = view.claims.find((claim) => claim.claimId === selectedClaimId)
    return card?.transcriptKey ?? null
  }, [selectedClaimId, view.claims])

  // Clicking a claim toggles it, so a second click returns to following the
  // live edge of the transcript.
  const handleSelect = useCallback((claimId: string) => {
    setSelectedClaimId((current) => (current === claimId ? null : claimId))
  }, [])

  const handleStart = useCallback(
    (options?: { demo?: boolean }) => {
      setSelectedClaimId(null)
      setIsDemo(options?.demo === true)
      void start(options)
    },
    [start],
  )

  const handleStop = useCallback(async () => {
    setSelectedClaimId(null)
    setIsDemo(false)
    await stopVoice()
    await stop()
  }, [stopVoice, stop])

  return (
    <div className="app">
      <StatusBar
        phase={phase}
        connection={connection}
        backendUrl={BACKEND_URL}
        sessionId={session?.sessionId ?? null}
        connectedClients={session?.connectedClients ?? null}
        now={now}
        lastSpeechAt={view.lastSpeechAt}
        lastSpeaker={view.lastSpeaker}
        isDemo={isDemo}
      />

      <main className="app__main">
        <PipelineFlow view={view} isLive={isLive} now={now} />

        <SessionControls
          phase={phase}
          onStart={handleStart}
          onStop={handleStop}
          onReconnect={reconnect}
        />

        <ErrorPanel
          fault={fault ?? voiceError}
          errors={view.errors}
          onDismissFault={dismissFault}
          onClearErrors={clearErrors}
        />

        <VerdictScoreboard claims={view.claims} isLive={isLive} />

        <div className="app__columns">
          <TranscriptPanel lines={view.transcripts} activeKey={activeLineKey} />
          <ClaimPanel
            claims={view.claims}
            selectedClaimId={selectedClaimId}
            onSelect={handleSelect}
          />
        </div>
      </main>
    </div>
  )
}

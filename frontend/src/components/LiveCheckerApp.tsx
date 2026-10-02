/**
 * The conversation.
 *
 * One thread, one composer, one Send. Everything the product can check arrives
 * here as a message and leaves here as an answer, so there is no mode to choose
 * and nothing to navigate between: a claim, a link, a file and the microphone
 * are four ways of sending the same kind of message.
 *
 * WHAT IS REAL
 * - Progress comes from `resolveStages`, which reads only what the backend has
 *   actually emitted.
 * - Results come from the live event stream or from the ingestion response.
 * - A verdict the pipeline never reached is never shown, and no count here is
 *   estimated.
 *
 * WHAT IS NOT RESTORED
 * Conversation history records what was run, when, and under what name.
 * Reopening an older entry shows its name and says plainly that its results
 * live on the server, because the backend exposes no endpoint for reading a
 * past session back. Inventing a transcript to fill that gap would be the one
 * thing on this page a reader could not trust.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CircleAlert } from 'lucide-react'

import { ErrorPanel } from './ErrorPanel'
import { PipelineFlow, resolveStages } from './PipelineFlow'
import type { Stage } from './PipelineFlow'
import { TechnicalDetails } from './TechnicalDetails'
import { VideoScorecard } from './VideoScorecard'
import { ChatHeader } from './dashboard/ChatHeader'
import { Composer } from './dashboard/Composer'
import {
  ClaimsSection,
  ProcessingSection,
  SourcesSection,
  TranscriptSection,
} from './dashboard/Details'
import { EmptyWorkspace } from './dashboard/EmptyWorkspace'
import { ResultSummary } from './dashboard/ResultSummary'
import { Sidebar } from './dashboard/Sidebar'
import { UserMessage } from './dashboard/UserMessage'
import { collectRunSources, createTurn, formatDuration, runClaimCount, tallyRun, transcriptDuration } from './dashboard/thread'
import type { Attachment, RunKind, RunResults, TurnOutcome, UserTurn } from './dashboard/thread'
import { useAuth, displayName } from '../hooks/useAuth'
import { useConversations } from '../hooks/useConversations'
import { useMediaIngestion } from '../hooks/useMediaIngestion'
import { useTicker } from '../hooks/useNow'
import { useSession } from '../hooks/useSession'
import { useVoiceSession } from '../hooks/useVoiceSession'
import { submitClaim } from '../lib/api'
import type { IngestionResponse } from '../lib/api'
import { BACKEND_URL } from '../lib/config'
import { isBareUrl } from '../lib/media'
import type { ErrorEvent } from '../types/events'
import type { TranscriptLine } from '../types/model'

/** A claim id the backend has not seen in this session. */
function mintClaimId(): string {
  return `claim_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

function describeFailure(error: unknown): string {
  if (error instanceof Error) return error.message
  return 'That did not go through.'
}

/** An empty thread view for a conversation whose results are not stored here. */
function ArchivedConversation({ title }: { title: string }) {
  return (
    <section className="welcome" aria-label="Past conversation">
      <h2 className="welcome__title">{title}</h2>
      <p className="welcome__lede">
        This conversation ran in this browser. Its name and date are kept here; the
        transcript and verdicts were written to the session on the server, and this
        build has no way to read a past session back.
      </p>
    </section>
  )
}

export default function LiveCheckerApp() {
  const {
    phase,
    connection,
    session,
    view,
    fault,
    start,
    stop,
    dismissFault,
    clearErrors,
  } = useSession()

  // The account card in the sidebar. Reading the one provider here is what keeps
  // it from ever disagreeing with what /login and /signup believe.
  const { user: authUser, signOut } = useAuth()

  const {
    status: voiceStatus,
    error: voiceError,
    isMicrophoneActive,
    start: startVoice,
    stop: stopVoice,
  } = useVoiceSession({ externalSessionId: session?.sessionId ?? null })

  const {
    conversations,
    activeId,
    active,
    beginTurn,
    recordOutcome,
    rename,
    select,
    startNew,
  } = useConversations()

  const [threads, setThreads] = useState<Record<string, UserTurn[]>>({})
  const [draft, setDraft] = useState('')
  const [attachment, setAttachment] = useState<Attachment | null>(null)
  /** The kind of the run in view, which decides the pipeline's stages. */
  const [runKind, setRunKind] = useState<RunKind | null>(null)
  /** The ingestion report, when the current run was recorded media. */
  const [mediaResult, setMediaResult] = useState<IngestionResponse | null>(null)
  /** A typed claim waiting for the session stream to be open. */
  const [pendingClaim, setPendingClaim] = useState<string | null>(null)
  const [localError, setLocalError] = useState<string | null>(null)
  const [selectedClaimId, setSelectedClaimId] = useState<string | null>(null)
  const [navOpen, setNavOpen] = useState(false)

  const clock = useTicker(30_000)

  const turns = useMemo(() => threads[activeId] ?? [], [activeId, threads])
  const threadRef = useRef<HTMLDivElement>(null)

  const appendTurn = useCallback(
    (turn: UserTurn) => {
      setThreads((current) => ({
        ...current,
        [activeId]: [...(current[activeId] ?? []), turn],
      }))
    },
    [activeId],
  )

  const patchLastTurn = useCallback(
    (patch: Partial<UserTurn>) => {
      setThreads((current) => {
        const existing = current[activeId] ?? []
        if (existing.length === 0) return current
        const last = existing[existing.length - 1] as UserTurn
        return { ...current, [activeId]: [...existing.slice(0, -1), { ...last, ...patch }] }
      })
    },
    [activeId],
  )

  // Release a staged preview when it is removed or replaced, so a file that is
  // no longer on screen does not keep its bytes alive in the tab.
  const clearAttachment = useCallback(() => {
    setAttachment((current) => {
      if (current?.previewUrl != null) URL.revokeObjectURL(current.previewUrl)
      return null
    })
  }, [])

  useEffect(() => clearAttachment, [clearAttachment])

  /**
   * A session to work in, created on demand.
   *
   * Ingestion and typed claims both refuse to run without one, so rather than
   * making the reader press start first, sending creates it.
   */
  const ensureSession = useCallback(async (): Promise<string | null> => {
    if (session !== null && phase === 'active') return session.sessionId
    const created = await start()
    return created?.sessionId ?? null
  }, [phase, session, start])

  const ingestion = useMediaIngestion({
    resolveSession: ensureSession,
    onStart: (target) => {
      setMediaResult(null)
      setRunKind(target.kind)
      setLocalError(null)
    },
    onComplete: (result) => setMediaResult(result),
  })

  /**
   * Post the typed claim for verification.
   *
   * It goes through the backend's existing claim ingress, which runs the same
   * pipeline a spoken claim goes through. Posting waits for the stream to be
   * open: a claim broadcast while this browser is not yet attached would be
   * verified and then lost, leaving an empty answer.
   */
  useEffect(() => {
    if (pendingClaim === null || session === null) return
    if (connection !== 'open') return

    const claim = pendingClaim
    setPendingClaim(null)
    const createdAt = Date.parse(session.createdAt)
    const elapsed = Number.isFinite(createdAt) ? Math.max(0, (Date.now() - createdAt) / 1000) : 0

    void (async () => {
      try {
        await submitClaim({
          claimId: mintClaimId(),
          sessionId: session.sessionId,
          claim,
          timestamp: elapsed,
        })
      } catch (error) {
        setLocalError(describeFailure(error))
      }
    })()
  }, [connection, pendingClaim, session])

  // Opening the microphone is a message in its own right.
  const voiceTurnOpen = useRef(false)
  useEffect(() => {
    if (voiceStatus === 'active' && !voiceTurnOpen.current) {
      voiceTurnOpen.current = true
      setRunKind('voice')
      setMediaResult(null)
      setLocalError(null)
      beginTurn({ text: '', attachment: null, kind: 'voice' })
      appendTurn(createTurn({ text: '', attachment: null, kind: 'voice' }))
    }
    if (voiceStatus === 'idle' || voiceStatus === 'error') {
      voiceTurnOpen.current = false
    }
  }, [appendTurn, beginTurn, voiceStatus])

  // Stop voice when the session goes away.
  useEffect(() => {
    if (phase === 'idle' && voiceStatus !== 'idle' && voiceStatus !== 'stopping') {
      void stopVoice()
    }
  }, [phase, voiceStatus, stopVoice])

  const handleToggleVoice = useCallback(() => {
    setLocalError(null)
    if (voiceStatus === 'active' || voiceStatus === 'starting') {
      void stopVoice()
      return
    }
    if (voiceStatus !== 'idle') return
    if (session === null) {
      // Opening the session is what lets the existing session -> voice effect
      // take over from here.
      void start()
      return
    }
    void startVoice()
  }, [session, start, startVoice, stopVoice, voiceStatus])

  const handleSend = useCallback(() => {
    const text = draft.trim()
    if (attachment === null && text === '') return

    // A link pasted as the whole message is an attachment, not a claim that
    // happens to contain a URL.
    const asUrl = attachment === null && isBareUrl(text)
    const submitted: Attachment | null =
      attachment ?? (asUrl ? { kind: 'url', label: text, previewUrl: null, file: null, size: null } : null)
    const kind: RunKind = submitted !== null ? submitted.kind : 'claim'

    setLocalError(null)
    setDraft('')
    clearAttachment()
    setRunKind(kind)
    setMediaResult(null)
    setSelectedClaimId(null)

    beginTurn({ text, attachment: submitted, kind })
    appendTurn(createTurn({ text, attachment: submitted, kind }))

    if (submitted !== null && submitted.file !== null) {
      const fileKind = submitted.kind === 'audio' ? 'audio' : 'video'
      void ingestion.submitFile(fileKind, submitted.file, submitted.previewUrl)
      return
    }

    if (kind === 'url') {
      void ingestion.submitUrl(text)
      return
    }

    // A typed claim can only be posted once the stream is attached.
    setPendingClaim(text)
    void ensureSession()
  }, [appendTurn, attachment, beginTurn, clearAttachment, draft, ensureSession, ingestion])

  const handleNewChat = useCallback(() => {
    // A new chat cannot inherit a running session's results, so the old session
    // is closed rather than left streaming into an empty thread.
    if (session !== null) {
      void stopVoice()
      void stop()
    }
    startNew()
    setRunKind(null)
    setMediaResult(null)
    setPendingClaim(null)
    setLocalError(null)
    setDraft('')
    setSelectedClaimId(null)
    clearAttachment()
  }, [clearAttachment, session, startNew, stop, stopVoice])

  const handleSelectConversation = useCallback(
    (id: string) => {
      select(id)
      setSelectedClaimId(null)
      setNavOpen(false)
    },
    [select],
  )

  // Results for the run in view: the ingestion report when there is one, the
  // live stream otherwise.
  const run: RunResults | null = useMemo(() => {
    if (runKind === null) return null
    if (mediaResult !== null) return { source: 'media', claims: null, result: mediaResult }
    if (view.claims.length > 0) return { source: 'live', claims: view.claims, result: null }
    return null
  }, [mediaResult, runKind, view.claims])

  const outcome: TurnOutcome | null = useMemo(() => tallyRun(run), [run])
  const pendingWork =
    ingestion.busy || view.claims.some((card) => card.pending) || pendingClaim !== null

  // Record the answer once it is final, so the thread and the sidebar carry the
  // real counts rather than a guess made while work was in flight.
  const lastTurnId = turns[turns.length - 1]?.id ?? null
  useEffect(() => {
    if (outcome === null || outcome.claims === 0 || pendingWork) return
    if (outcome.checked < outcome.claims) return
    const last = turns[turns.length - 1]
    if (last === undefined || last.outcome !== null) return
    patchLastTurn({ outcome })
    recordOutcome(outcome.claims)
  }, [outcome, patchLastTurn, pendingWork, recordOutcome, turns])

  const stages: Stage[] = useMemo(() => {
    if (runKind === null) return []
    return resolveStages({
      kind: runKind,
      submitted: session !== null,
      extracted: mediaResult !== null,
      transcribed:
        view.transcripts.length > 0 ||
        (mediaResult !== null && (mediaResult.transcript_segments?.length ?? 0) > 0),
      claims: runClaimCount(run),
      checking: view.claims.some((card) => card.pending) || ingestion.busy,
      evidence: collectRunSources(run).length > 0,
      complete: outcome !== null && outcome.claims > 0 && outcome.checked >= outcome.claims,
      failed: ingestion.state.status === 'error' || view.errors.length > 0,
      listening: voiceStatus === 'active',
    })
  }, [
    ingestion.busy,
    ingestion.state.status,
    mediaResult,
    outcome,
    run,
    runKind,
    session,
    view.claims,
    view.errors.length,
    view.transcripts.length,
    voiceStatus,
  ])

  // The transcript line a selected claim came from, so choosing a claim points
  // at the words it was extracted from.
  const activeLineKey = useMemo(() => {
    if (selectedClaimId === null || run?.source !== 'live') return null
    return run.claims.find((card) => card.claimId === selectedClaimId)?.transcriptKey ?? null
  }, [run, selectedClaimId])

  // Follow the newest message, the way a conversation scrolls itself.
  useEffect(() => {
    const node = threadRef.current
    if (node !== null) node.scrollTop = node.scrollHeight
  }, [lastTurnId, view.transcripts.length, view.claims.length, mediaResult, localError])

  const isArchived = active !== null && threads[activeId] === undefined
  const hasThread = turns.length > 0 || runKind !== null
  const busy = pendingWork || voiceStatus === 'active'

  const connected = connection === 'open' || connection === 'connecting'
  const connectionLabel =
    connection === 'open'
      ? 'Backend connected'
      : connection === 'connecting'
        ? 'Connecting…'
        : connection === 'error'
          ? 'Backend unreachable'
          : 'Backend ready'
  const connectionDetail =
    connection === 'open'
      ? 'All systems operational'
      : connection === 'error'
        ? `Cannot reach ${BACKEND_URL.replace(/^https?:\/\//, '')}`
        : 'Connects when you send something'

  const busyText = ingestion.busy
    ? ingestion.state.message
    : pendingClaim !== null
      ? 'Opening the session stream…'
      : view.claims.some((card) => card.pending)
        ? 'Checking claims…'
        : null

  const ingestionError = ingestion.state.status === 'error' ? ingestion.state.message : null
  const errorText = localError ?? ingestionError

  return (
    <div className="shell">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        onSelect={handleSelectConversation}
        onNewChat={handleNewChat}
        open={navOpen}
        onClose={() => setNavOpen(false)}
        status={{ connected, label: connectionLabel, detail: connectionDetail }}
        account={{
          // The name comes from Supabase's own user metadata, which is where
          // signup wrote it. A guest is the honest default: the fact-checker
          // works without an account, so nobody is asked to have one.
          name: displayName(authUser),
          email: authUser?.email ?? null,
          signedIn: authUser !== null,
          onSignOut: () => void signOut(),
        }}
      />

      <button
        type="button"
        className={`scrim${navOpen ? ' scrim--on' : ''}`}
        aria-label="Close navigation"
        tabIndex={navOpen ? 0 : -1}
        onClick={() => setNavOpen(false)}
      />

      <div className="shell__main">
        <ChatHeader
          title={active?.title ?? 'New chat'}
          createdAt={active?.createdAt ?? null}
          now={clock}
          busy={busy}
          onRename={(title) => rename(activeId, title)}
          onNewChat={handleNewChat}
          onMenu={() => setNavOpen(true)}
        />

        <div className="thread" ref={threadRef}>
          {!hasThread ? (
            isArchived && active !== null ? (
              <ArchivedConversation title={active.title} />
            ) : (
              <EmptyWorkspace />
            )
          ) : (
            <div className="thread__inner">
              {turns.map((turn, index) => (
                <div key={turn.id} className="thread__pair">
                  <UserMessage turn={turn} now={clock} />

                  {index === turns.length - 1 && runKind !== null && (
                    <AssistantTurn
                      stages={stages}
                      run={run}
                      outcome={outcome}
                      pending={pendingWork}
                      note={
                        ingestion.state.status === 'complete' ? ingestion.state.message : null
                      }
                      transcript={view.transcripts}
                      errors={view.errors}
                      fault={fault ?? voiceError}
                      onDismissFault={dismissFault}
                      onClearErrors={clearErrors}
                      subject={describeSubject(turn)}
                      media={
                        turn.attachment !== null && turn.attachment.kind !== 'url'
                          ? {
                              label: turn.attachment.label,
                              size: turn.attachment.size,
                            }
                          : null
                      }
                      activeKey={activeLineKey}
                      selectedClaimId={selectedClaimId}
                      onSelectClaim={setSelectedClaimId}
                    />
                  )}
                </div>
              ))}

              {errorText !== null && (
                <div className="alert" role="alert">
                  <CircleAlert size={16} aria-hidden="true" className="alert__icon" />
                  <div className="alert__body">
                    <p className="alert__message">{errorText}</p>
                    {errorText.length > 160 && (
                      <TechnicalDetails>{errorText}</TechnicalDetails>
                    )}
                  </div>
                  <button
                    type="button"
                    className="button button--small"
                    onClick={() => {
                      setLocalError(null)
                      ingestion.reset()
                    }}
                  >
                    Dismiss
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="dock">
          <Composer
            value={draft}
            onChange={setDraft}
            attachment={attachment}
            onAttach={(next) => (next === null ? clearAttachment() : setAttachment(next))}
            onSubmit={handleSend}
            canSubmit={attachment !== null || draft.trim() !== ''}
            busy={pendingWork}
            busyText={busyText}
            voiceStatus={voiceStatus}
            microphoneActive={isMicrophoneActive}
            onToggleVoice={handleToggleVoice}
          />
        </div>
      </div>
    </div>
  )
}

/** What the answer is about, named for the reader. */
function describeSubject(turn: UserTurn): string {
  if (turn.attachment !== null) {
    return turn.attachment.kind === 'audio' ? 'that audio' : 'that video'
  }
  if (turn.kind === 'voice') return 'what was said'
  return 'that claim'
}

interface AssistantTurnProps {
  stages: Stage[]
  run: RunResults | null
  outcome: TurnOutcome | null
  pending: boolean
  note: string | null
  transcript: TranscriptLine[]
  errors: ErrorEvent[]
  fault: string | null
  onDismissFault: () => void
  onClearErrors: () => void
  subject: string
  media: { label: string; size: number | null } | null
  activeKey: string | null
  selectedClaimId: string | null
  onSelectClaim: (claimId: string) => void
}

/**
 * Everything the product says back, in the order a reader wants it: what is
 * happening now, then the answer, then the detail behind it.
 */
function AssistantTurn({
  stages,
  run,
  outcome,
  pending,
  note,
  transcript,
  errors,
  fault,
  onDismissFault,
  onClearErrors,
  subject,
  media,
  activeKey,
  selectedClaimId,
  onSelectClaim,
}: AssistantTurnProps) {
  const scorecard = run?.source === 'media' ? run.result.scorecard : null
  const duration = transcriptDuration(run)
  // Once every stage has actually finished, the row has said all it needs to
  // say. The stages themselves stay one click away under Processing details, so
  // collapsing them costs the reader nothing and calms the finished message.
  const pipelineSettled = stages.length > 0 && stages.every((stage) => stage.state === 'done')

  return (
    <div className="turn turn--app">
      <p className="turn__who">
        <span className="turn__mark" aria-hidden="true" />
        Live Fact Checker
      </p>

      {stages.length > 0 && !pipelineSettled && <PipelineFlow stages={stages} />}

      <ErrorPanel
        fault={fault}
        errors={errors}
        onDismissFault={onDismissFault}
        onClearErrors={onClearErrors}
      />

      {outcome !== null ? (
        <>
          <ResultSummary
            outcome={outcome}
            pending={pending}
            subject={subject}
            duration={duration !== null ? formatDuration(duration) : null}
            note={note}
          />

          {scorecard != null && (
            <div className="scorecard">
              <VideoScorecard scorecard={scorecard} />
            </div>
          )}

          <div className="details">
            <ClaimsSection
              run={run}
              transcript={transcript}
              steps={stages}
              media={media}
              activeKey={activeKey}
              selectedClaimId={selectedClaimId}
              onSelectClaim={onSelectClaim}
            />
            <SourcesSection run={run} />
            <TranscriptSection transcript={transcript} run={run} activeKey={activeKey} />
            <ProcessingSection steps={stages} media={media} />
          </div>
        </>
      ) : (
        <p className="turn__waiting">
          {pending ? 'Working on it. The result appears here.' : 'Nothing to show yet.'}
        </p>
      )}
    </div>
  )
}

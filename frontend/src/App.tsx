/**
 * Application shell for the Live Fact-Checker frontend.
 *
 * The frontend is a read-only observer of the backend pipeline. It starts and
 * stops sessions, streams the live transcript, and shows each claim's verdict as
 * it resolves. It never produces transcripts, claims or verdicts itself.
 */

import { ClaimPanel } from './components/ClaimPanel'
import { ErrorPanel } from './components/ErrorPanel'
import { SessionControls } from './components/SessionControls'
import { StatusBar } from './components/StatusBar'
import { TranscriptPanel } from './components/TranscriptPanel'
import { VerdictLegend } from './components/VerdictLegend'
import { useSession } from './hooks/useSession'
import { BACKEND_URL } from './lib/config'

export default function App() {
  const { phase, connection, session, view, fault, start, stop, reconnect, dismissFault, clearErrors } =
    useSession()

  return (
    <div className="app">
      <StatusBar
        phase={phase}
        connection={connection}
        backendUrl={BACKEND_URL}
        sessionId={session?.sessionId ?? null}
        connectedClients={session?.connectedClients ?? null}
      />

      <main className="app__main">
        <SessionControls
          phase={phase}
          onStart={(options) => {
            void start(options)
          }}
          onStop={() => {
            void stop()
          }}
          onReconnect={reconnect}
        />

        <ErrorPanel
          fault={fault}
          errors={view.errors}
          onDismissFault={dismissFault}
          onClearErrors={clearErrors}
        />

        <div className="app__columns">
          <TranscriptPanel lines={view.transcripts} />
          <div className="app__side">
            <ClaimPanel claims={view.claims} />
            <VerdictLegend />
          </div>
        </div>
      </main>
    </div>
  )
}

/**
 * Error surfaces.
 *
 * Two distinct kinds of failure, kept visually separate because they need
 * different responses from the user:
 *
 * - a **fault** is this client failing to reach or stay on the backend
 * - an **error event** is the backend reporting a recoverable pipeline problem
 *
 * Both state the consequence in the user's own words -- what is broken and what
 * still works -- and keep the machine-readable code, the raw transport message
 * and any provider detail inside a "Technical details" disclosure. A stack-shaped
 * string is not something a reader can act on, and showing it by default trains
 * people to ignore the panel that matters.
 */

import { TechnicalDetails } from './TechnicalDetails'
import type { ErrorEvent } from '../types/events'

export interface ErrorPanelProps {
  fault: string | null
  errors: ErrorEvent[]
  onDismissFault: () => void
  onClearErrors: () => void
}

export function ErrorPanel({
  fault,
  errors,
  onDismissFault,
  onClearErrors,
}: ErrorPanelProps) {
  if (fault === null && errors.length === 0) return null

  return (
    <section className="panel panel--errors" aria-label="Errors" role="alert">
      <h2 className="panel__title">Errors</h2>

      {fault !== null && (
        <div className="alert alert--fault">
          <div className="alert__body">
            <strong className="alert__code">Connection</strong>
            <p className="alert__message">
              Lost contact with the backend, so results are not arriving. Checks
              resume on their own once the connection is back.
            </p>
            <TechnicalDetails>{fault}</TechnicalDetails>
          </div>
          <button
            type="button"
            className="button button--small"
            onClick={onDismissFault}
          >
            Dismiss
          </button>
        </div>
      )}

      {errors.length > 0 && (
        <>
          <ul className="errors">
            {[...errors].reverse().map((error, index) => (
              <li
                className={`alert${error.recoverable ? '' : ' alert--fatal'}`}
                key={`${error.code}-${error.claimId ?? 'none'}-${index}`}
              >
                <div className="alert__body">
                  <strong className="alert__code">{error.code}</strong>
                  <p className="alert__message">
                    {error.recoverable
                      ? 'The check for one claim did not complete. The rest of the session is unaffected.'
                      : 'The session stopped because of this error. Start a new check to continue.'}
                  </p>
                  <TechnicalDetails>
                    {[
                      error.message,
                      error.detail ?? null,
                    ]
                      .filter((part): part is string => part !== null && part !== '')
                      .join('\n')}
                  </TechnicalDetails>
                </div>
              </li>
            ))}
          </ul>
          <button type="button" className="button button--small" onClick={onClearErrors}>
            Clear errors
          </button>
        </>
      )}
    </section>
  )
}
/**
 * Error surfaces.
 *
 * Two distinct kinds of failure, kept visually separate because they need
 * different responses from the user:
 *
 * - a **fault** is this client failing to reach or stay on the backend
 * - an **error event** is the backend reporting a recoverable pipeline problem
 */

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
          <div>
            <strong className="alert__code">Connection</strong>
            <p className="alert__message">{fault}</p>
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
                <div>
                  <strong className="alert__code">{error.code}</strong>
                  <p className="alert__message">{error.message}</p>
                  {error.detail !== null && error.detail !== undefined && (
                    <p className="alert__detail">{error.detail}</p>
                  )}
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

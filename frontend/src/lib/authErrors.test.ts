/**
 * Error sanitisation.
 *
 * The property under test is that nothing developer-shaped reaches the screen.
 * Every input here is something the SDK or a browser can genuinely produce,
 * and the assertion is always the same: a sentence a reader can act on, and
 * never the raw message.
 */

import { describe, expect, it } from 'vitest'

import { friendlyAuthError } from './authErrors'

/** The shape the Supabase SDK throws. */
function authError(code: string, message: string): unknown {
  return { name: 'AuthApiError', code, message, status: 400 }
}

describe('friendlyAuthError', () => {
  it('maps a known code to something actionable', () => {
    const error = friendlyAuthError(authError('user_already_exists', 'User already registered'))
    expect(error.title).toMatch(/already registered/i)
    expect(error.message).toMatch(/log in/i)
  })

  it('never passes a raw SDK message through, even for an unmapped code', () => {
    const raw = 'Database error: relation auth.internal_secret does not exist'
    const error = friendlyAuthError(authError('some_new_code', raw))
    expect(error.message).not.toContain(raw)
    expect(error.message).not.toMatch(/relation|database/i)
  })

  it('says nothing was submitted when the request never left the browser', () => {
    const error = friendlyAuthError(new TypeError('Failed to fetch'))
    expect(error.message).toMatch(/nothing was submitted/i)
  })

  it('has a message for a value that is not an error at all', () => {
    // A thrown non-Error must still produce a renderable string rather than
    // crashing the form.
    const error = friendlyAuthError('something odd')
    expect(typeof error.message).toBe('string')
    expect(error.message.length).toBeGreaterThan(0)
  })

  it('treats a rate limit as something to wait out, not to retry', () => {
    const error = friendlyAuthError(authError('over_request_rate_limit', 'Rate limit exceeded'))
    expect(error.message).toMatch(/wait/i)
  })

  it('recognises an already-registered message even without a code', () => {
    const error = friendlyAuthError(authError('', 'User already registered'))
    expect(error.title).toMatch(/already registered/i)
  })
})

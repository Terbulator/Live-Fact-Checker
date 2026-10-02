/**
 * Turning an auth failure into something a reader can act on.
 *
 * Supabase errors are written for developers: they carry a machine code, a
 * status, and occasionally a raw message that can name internal identifiers.
 * A signup form is the worst possible place to show a developer sentence, and
 * the worst possible place to leak one.
 *
 * So nothing from the SDK reaches the screen unfiltered. Every known code maps
 * to a sentence that tells the reader what to do next, and anything
 * unrecognised becomes a single generic line. The raw message is never
 * rendered: an unmapped code means we did not anticipate this failure, not that
 * the reader needs its internals.
 *
 * The mapping is by `code` where one exists, because codes are the stable
 * contract and messages are not — they get reworded between SDK releases. The
 * message is only pattern-matched as a fallback, and only to catch the handful
 * of conditions that legitimately ship without a code.
 */

export interface FriendlyAuthError {
  /** One or two sentences, safe to render as text. */
  message: string
  /** A short heading, for the error panel. */
  title: string
}

const BY_CODE: Record<string, FriendlyAuthError> = {
  // Already registered. The most common signup failure, and the one most likely
  // to be discovered by a real person with a real address.
  user_already_exists: {
    title: 'That email is already registered',
    message: 'An account already uses this email address. Log in instead, or reset the password if you have forgotten it.',
  },
  email_exists: {
    title: 'That email is already registered',
    message: 'An account already uses this email address. Log in instead, or reset the password if you have forgotten it.',
  },
  // Validation failures Supabase raises before it ever contacts a provider.
  weak_password: {
    title: 'Password too weak',
    message: 'This password is not strong enough yet. Use at least 8 characters and avoid the most common passwords.',
  },
  over_request_rate_limit: {
    title: 'Too many attempts',
    message: 'That has been tried too many times. Wait a minute and try again.',
  },
  over_email_send_rate_limit: {
    title: 'Too many emails sent',
    message: 'A confirmation email has already been sent to this address a few times. Wait a few minutes before asking for another.',
  },
  // Supabase returns these when the provider rejects the signup, and they carry
  // no provider detail by design.
  email_address_invalid: {
    title: 'Check the email address',
    message: 'That email address was not accepted. Check for a typo and try again.',
  },
  email_not_confirmed: {
    title: 'Confirm your email first',
    message: 'Open the confirmation email we sent, then come back and log in.',
  },
  invalid_credentials: {
    title: 'Email or password is wrong',
    message: 'That email and password do not match an account. Check both and try again.',
  },
  signups_not_allowed: {
    title: 'Signup is closed',
    message: 'New accounts cannot be created on this project at the moment.',
  },
}

/**
 * The catch-all. Deliberately says the request failed and that the details were
 * withheld, rather than inventing a cause.
 */
const GENERIC: FriendlyAuthError = {
  title: 'Something went wrong',
  message: 'We could not complete that request. Please try again in a moment.',
}

/**
 * A short, safe message for a transport failure: the SDK could not reach
 * Supabase at all, so nothing was sent and nothing was created.
 */
export const NETWORK_ERROR: FriendlyAuthError = {
  title: 'Cannot reach the authentication service',
  message: 'Check your connection and try again. Nothing was submitted.',
}

/**
 * Map any thrown value to something displayable.
 *
 * Accepts `unknown` deliberately: a network failure and a bug both arrive here
 * as exceptions, and neither should be able to crash the form.
 */
export function friendlyAuthError(error: unknown): FriendlyAuthError {
  if (isAuthApiError(error)) {
    const mapped = BY_CODE[error.code]
    if (mapped !== undefined) return mapped
    if (/already registered|already exists/i.test(error.message)) {
      return BY_CODE.user_already_exists as FriendlyAuthError
    }
    if (/rate limit|too many/i.test(error.message)) {
      return BY_CODE.over_request_rate_limit as FriendlyAuthError
    }
    if (/password/i.test(error.message)) {
      return BY_CODE.weak_password as FriendlyAuthError
    }
    return GENERIC
  }

  // `fetch failed` is what a browser throws when the request never lands. It
  // says something different from a rejection, and the reader can act on it.
  if (error instanceof TypeError || isNetworkFailure(error)) return NETWORK_ERROR

  return GENERIC
}

/** The shape of an `AuthError` without importing Supabase's class. */
interface AuthApiError {
  code: string
  message: string
  status?: number
}

function isAuthApiError(error: unknown): error is AuthApiError {
  if (typeof error !== 'object' || error === null) return false
  const candidate = error as Partial<AuthApiError>
  return typeof candidate.message === 'string' && typeof candidate.code === 'string'
}

function isNetworkFailure(error: unknown): boolean {
  if (!(error instanceof Error)) return false
  return /failed to fetch|networkerror|load failed/i.test(error.message)
}

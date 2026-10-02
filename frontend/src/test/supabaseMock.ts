/**
 * Test double for `@supabase/supabase-js`.
 *
 * Aliased in `vite.config.ts` under `test` only, so the real package never ships
 * in a test bundle and never touches the network. It exists because the real SDK
 * is a large dependency graph that has to be transformed once per test file,
 * which added tens of seconds to the suite for no extra coverage — every test in
 * this repository mocks the auth call at this boundary anyway, and the real
 * network behaviour is Supabase's to test, not ours.
 *
 * The shape is deliberately minimal: `createClient` returns an object with an
 * `auth` namespace whose methods are spies a test can override, and `resetAuth`
 * clears them between tests.
 */

import { vi } from 'vitest'

/** The surface the app actually calls. Everything else is unused. */
export const authMock = {
  signUp: vi.fn(),
  signInWithPassword: vi.fn(),
  signOut: vi.fn(),
  getSession: vi.fn(),
  onAuthStateChange: vi.fn(),
}

export function resetAuthMock(): void {
  authMock.signUp.mockReset()
  authMock.signInWithPassword.mockReset()
  authMock.signOut.mockReset()
  authMock.getSession.mockReset()
  authMock.onAuthStateChange.mockReset()

  // Safe defaults: no session, and a subscription that can be torn down.
  authMock.getSession.mockResolvedValue({ data: { session: null }, error: null })
  authMock.onAuthStateChange.mockReturnValue({
    data: { subscription: { unsubscribe: vi.fn() } },
  })
}

resetAuthMock()

export function createClient(): unknown {
  return { auth: authMock }
}

/**
 * A stand-in for Supabase's `AuthError`. The app never `instanceof`s it — it
 * checks `code` and `message` — so a plain object with those two fields is a
 * faithful double and is what production will actually be handed.
 */
export function authApiError(code: string, message: string, status = 400): unknown {
  return { name: 'AuthApiError', code, message, status }
}

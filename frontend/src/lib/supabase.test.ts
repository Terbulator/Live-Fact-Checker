/**
 * The Supabase client's guard rails.
 *
 * The important assertion here is a negative one: that a service-role key is
 * refused. That key bypasses row level security, so shipping one to a browser is
 * a full database compromise, and the most likely way it happens is somebody
 * copying the wrong credential out of the dashboard — which is exactly why it
 * is rejected at start-up instead of being used.
 *
 * No network and no real project: the module is re-imported with a stubbed
 * environment for each case, which is the same boundary the app uses.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'

/** Build a JWT-shaped string whose payload carries the given claims. */
function fakeJwt(claims: Record<string, unknown>): string {
  const encode = (value: unknown) =>
    btoa(JSON.stringify(value)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  return `${encode({ alg: 'HS256' })}.${encode(claims)}.signature`
}

const URL = 'https://abcdefghijklm.supabase.co'
const ANON = fakeJwt({ role: 'anon' })

/** Re-import the module with a given environment. */
async function loadWith(env: { url?: string; key?: string }) {
  vi.resetModules()
  vi.stubEnv('VITE_SUPABASE_URL', env.url ?? URL)
  vi.stubEnv('VITE_SUPABASE_ANON_KEY', env.key ?? ANON)
  return await import('./supabase')
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
})

describe('isSupabaseConfigured', () => {
  it('is false when the project URL is missing', async () => {
    const { isSupabaseConfigured } = await loadWith({ url: '' })
    expect(isSupabaseConfigured).toBe(false)
  })

  it('is false when the anon key is missing', async () => {
    const { isSupabaseConfigured } = await loadWith({ key: '' })
    expect(isSupabaseConfigured).toBe(false)
  })

  it('is true when both are present', async () => {
    const { isSupabaseConfigured } = await loadWith({})
    expect(isSupabaseConfigured).toBe(true)
  })
})

describe('getSupabase', () => {
  it('returns null rather than failing when nothing is configured', async () => {
    const { getSupabase } = await loadWith({ url: '', key: '' })
    // The fact-checker must keep working on a deployment with no auth project,
    // so this is a null and not a throw.
    expect(getSupabase()).toBeNull()
  })

  it('refuses a legacy service-role key', async () => {
    const { getSupabase, SupabaseKeyError } = await loadWith({
      key: fakeJwt({ role: 'service_role' }),
    })
    expect(() => getSupabase()).toThrow(SupabaseKeyError)
    expect(() => getSupabase()).toThrow(/row level security/i)
  })

  it('refuses a modern sb_secret_ key', async () => {
    const { getSupabase, SupabaseKeyError } = await loadWith({ key: 'sb_secret_abc123' })
    expect(() => getSupabase()).toThrow(SupabaseKeyError)
  })

  it('accepts a publishable key and returns the same client every time', async () => {
    const { getSupabase } = await loadWith({ key: 'sb_publishable_abc123' })
    const first = getSupabase()
    expect(first).not.toBeNull()
    // One client, so one session and one storage listener for the whole app.
    expect(getSupabase()).toBe(first)
  })
})

import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      /**
       * The Supabase SDK is replaced with a test double, and only for tests.
       *
       * Two reasons, one practical and one about what a test is allowed to do.
       * Practically, the real SDK is a large dependency graph that vitest
       * transforms once per test file, which added tens of seconds to a suite
       * whose actual coverage never touches it. And it makes the boundary
       * explicit: every test here mocks authentication at `createClient`, so no
       * test can reach a real Supabase project or a real account, and none can
       * accidentally start doing so later.
       *
       * The alias lives in this file, so the production bundle is untouched.
       * `vite.config.ts` is not involved in tests and has no such alias.
       */
      '@supabase/supabase-js': fileURLToPath(
        new URL('./src/test/supabaseMock.ts', import.meta.url),
      ),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    // Generous, for the same reason as `asyncUtilTimeout`: this suite runs
    // `framer-motion` pages and a jsdom environment, and a loaded machine can
    // take seconds on a cold transform. A timeout here should mean the code
    // hung, not that the disk was busy.
    testTimeout: 30000,
    hookTimeout: 30000,
  },
})

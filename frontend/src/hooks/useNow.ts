/**
 * A wall clock that ticks on an interval.
 *
 * The "speaker is talking" state is a function of elapsed time since the last
 * transcript event, so something has to re-render for that to decay. This hook
 * supplies that clock without any component subscribing to a timer itself, and
 * it pauses entirely when the app is hidden or the session is not live, so an
 * idle demo does not spin a timer forever.
 */

import { useEffect, useState } from 'react'

/** How often the clock advances. */
const TICK_MS = 400

export function useNow(enabled: boolean): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!enabled) return

    setNow(Date.now())
    const timer = window.setInterval(() => setNow(Date.now()), TICK_MS)

    const onVisibility = () => {
      // Resync on return so a backgrounded tab does not show a stale clock.
      if (document.visibilityState === 'visible') setNow(Date.now())
    }
    document.addEventListener('visibilitychange', onVisibility)

    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [enabled])

  return now
}

/**
 * A slow clock, for wording that ages in minutes rather than milliseconds.
 *
 * "Started 2 minutes ago" must stay true without re-rendering the conversation
 * twice a second to achieve it, so this ticks on a coarse interval and stops
 * entirely when the page is hidden.
 */
export function useTicker(intervalMs: number, enabled = true): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!enabled) return

    setNow(Date.now())
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs)

    const onVisibility = () => {
      if (document.visibilityState === 'visible') setNow(Date.now())
    }
    document.addEventListener('visibilitychange', onVisibility)

    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [enabled, intervalMs])

  return now
}

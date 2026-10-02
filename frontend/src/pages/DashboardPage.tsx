import LiveCheckerApp from '../components/LiveCheckerApp'

/**
 * The dashboard route.
 *
 * Deliberately thin: it supplies the two roots the workspace needs and mounts
 * the surface. `lfp-root` carries the product's colour tokens -- the same ones
 * the landing page is built from -- and `lfp-dash` adds the workspace's own
 * surfaces, so this reads as the same product rather than a second design
 * system.
 *
 * Routing is unchanged: there is one dashboard route, and the sections inside
 * it are modes of the workspace, not pages.
 */
export function DashboardPage() {
  return (
    <div className="lfp-root lfp-dash">
      <LiveCheckerApp />
    </div>
  )
}
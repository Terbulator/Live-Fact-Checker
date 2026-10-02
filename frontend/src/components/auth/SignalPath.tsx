import { useEffect, useRef } from 'react'

/**
 * The verification signal behind signup.
 *
 * Not a variation on `EnergyField`. That field is fluid: ribbons chase a
 * pointer, motes are shed by velocity, and the whole thing is about following
 * the cursor. Signup asks a different question, and the answer is a circuit, not
 * a current.
 *
 * A single closed trace is routed around the card. A bright segment travels it
 * continuously. Small particles are carried along behind. Nodes sit at fixed
 * points on the route and light individually, the way a junction lights when
 * traffic passes. The form is wired into it: focusing a field wakes the nearest
 * node, the form becoming valid runs the loop once end to end, and a successful
 * signup fires a verification pulse outward before the page navigates away.
 *
 * The form is the subject and the signal is the mood, so the rules that keep it
 * honest are the same ones `EnergyField` follows.
 *
 *   Tokens, not colours. Every fill is `--lfp-lime` / `--lfp-green` /
 *   `--lfp-black` read off the canvas at start-up, so no hex appears here and
 *   the field cannot drift away from the landing page's palette.
 *
 *   Almost no per-frame geometry. The route is a closed superellipse, sampled
 *   once per resize into a fixed array. A frame then costs one faint stroke for
 *   the route, one short stroke for the travelling segment, and a couple of
 *   dozen tiny circles. That is orders of magnitude less than a fill-rate
 *   bound effect, which matters because this runs *behind a form the reader is
 *   typing into* — an animation that costs frames costs keystrokes.
 *
 *   Reactive values arrive through refs, not props in the dependency array, so
 *   focusing a field does not tear down and rebuild the loop.
 *
 * `prefers-reduced-motion` paints one still frame: route, nodes, no travel, no
 * pulse. The page is never empty, and no loop is ever started. The loop also
 * stops whenever the tab is hidden.
 */

type RGB = [number, number, number]
type Tint = 'lime' | 'green'

interface SignalPathProps {
  /** 0–1. Scales particle budget and overall brightness. */
  quality: number
  /** Vertical centre of the focused field, in CSS px. `null` when nothing has focus. */
  focusY: number | null
  /** True while a field holds focus. */
  focused: boolean
  /** Increment to run the route once, end to end. */
  sweepToken: number
  /** True to fire the expanding verification pulse. */
  pulse: boolean
}

interface Point {
  x: number
  y: number
}

interface Node {
  /** Position along the route, 0–1. */
  at: number
  phase: number
  /** How much extra this node flares when traffic passes it. */
  weight: number
}

interface Particle {
  /** Position along the route, 0–1. */
  at: number
  speed: number
  size: number
  tint: Tint
}

interface Ring {
  age: number
  life: number
}

/** Read an `--lfp-*` custom property off the canvas and split it into channels. */
function readToken(el: Element, name: string): RGB {
  const raw = getComputedStyle(el).getPropertyValue(name).trim()
  const hex = raw.startsWith('#') ? raw.slice(1) : ''
  const wide =
    hex.length === 3
      ? [...hex].map((c) => c + c).join('')
      : hex.padEnd(6, '0').slice(0, 6)
  return [
    parseInt(wide.slice(0, 2), 16) || 0,
    parseInt(wide.slice(2, 4), 16) || 0,
    parseInt(wide.slice(4, 6), 16) || 0,
  ]
}

const rgba = ([r, g, b]: RGB, a: number) => `rgba(${r},${g},${b},${a})`
const clamp = (v: number, lo: number, hi: number) => (v < lo ? lo : v > hi ? hi : v)

/**
 * The route.
 *
 * A superellipse, not a rectangle and not a circle: the exponent is what gives
 * the trace a circuit's flat runs and rounded corners, and it is a closed curve
 * in one line, which is why the travelling segment can be drawn as a slice of
 * an array rather than a recomputed path. Two slow sines then push it off true,
 * because a mathematically perfect loop reads as a diagram and this has to read
 * as a signal that happens to be routed.
 *
 * The exponent rises on narrow viewports so the route keeps its horizontal
 * character on a phone instead of collapsing into a circle.
 */
const ROUTE_SAMPLES = 360
function buildRoute(width: number, height: number): Point[] {
  const cx = width / 2
  const cy = height / 2
  const reach = Math.min(width, height)
  const a = Math.max(120, width * 0.42)
  const b = Math.max(120, height * 0.4)
  const exponent = width < 760 ? 3 : 4.2
  const power = 2 / exponent

  const points: Point[] = []
  for (let i = 0; i < ROUTE_SAMPLES; i += 1) {
    const theta = (i / ROUTE_SAMPLES) * Math.PI * 2
    const cos = Math.cos(theta)
    const sin = Math.sin(theta)
    const x = cx + a * Math.sign(cos) * Math.pow(Math.abs(cos), power)
    const y = cy + b * Math.sign(sin) * Math.pow(Math.abs(sin), power)
    // A few pixels of waver, scaled to the viewport so it stays a texture rather
    // than becoming visible wobble.
    const waver = reach * 0.012
    points.push({
      x: x + Math.sin(theta * 3 + 0.7) * waver,
      y: y + Math.sin(theta * 2 + 2.1) * waver,
    })
  }
  return points
}

/**
 * Junction positions.
 *
 * Sixteen is enough to read as a routed circuit and few enough that none of
 * them is individually distracting. They are evenly spaced with a fixed offset
 * so the eye never finds a regular repeating beat, and the weights vary so the
 * route does not flare all at once.
 */
const NODE_COUNT = 16
function buildNodes(): Node[] {
  return Array.from({ length: NODE_COUNT }, (_unused, index) => ({
    at: (index / NODE_COUNT + 0.031) % 1,
    phase: index * 0.73,
    weight: 0.55 + ((index * 7919) % 11) / 22,
  }))
}

export function SignalPath({ quality, focusY, focused, sweepToken, pulse }: SignalPathProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  // Reactive inputs, read from inside the loop so that focusing a field or
  // completing validation never restarts the effect.
  const focusYRef = useRef(focusY)
  const focusedRef = useRef(focused)
  const sweepTokenRef = useRef(sweepToken)
  const pulseRef = useRef(pulse)
  focusYRef.current = focusY
  focusedRef.current = focused
  sweepTokenRef.current = sweepToken
  pulseRef.current = pulse

  useEffect(() => {
    const canvas = canvasRef.current
    if (canvas === null) return undefined
    const context = canvas.getContext('2d')
    if (context === null) return undefined
    const ctx: CanvasRenderingContext2D = context

    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')

    const lime = readToken(canvas, '--lfp-lime')
    const green = readToken(canvas, '--lfp-green')
    const black = readToken(canvas, '--lfp-black')
    const tint = (t: Tint) => (t === 'lime' ? lime : green)

    let width = 1
    let height = 1
    let dpr = 1
    let raf = 0

    let route: Point[] = []
    const nodes = buildNodes()
    const particles: Particle[] = []
    const rings: Ring[] = []

    /** Position along the route, 0–1, wrapped. */
    const pointAt = (t: number): Point => {
      const index = ((Math.floor(t * ROUTE_SAMPLES) % ROUTE_SAMPLES) + ROUTE_SAMPLES) % ROUTE_SAMPLES
      return route[index] ?? { x: width / 2, y: height / 2 }
    }

    /**
     * The travelling segment: 0–1 along the route. It only ever moves forward,
     * so the signal always reads as travelling a loop rather than seeking.
     */
    let head = 0

    /**
     * A completed validation. While this counts down the segment runs the whole
     * route at speed, which is the visual form of "that check passed".
     */
    let sweep = 0
    let lastSweepToken = 0

    /** The focus node, remembered so it can decay rather than snap off. */
    let focusNode = -1
    let focusGlow = 0

    const particleBudget = () => Math.round(clamp((width * height) / 46_000, 5, 14) * quality)

    const seedParticles = () => {
      particles.length = 0
      for (let i = 0; i < particleBudget(); i += 1) {
        particles.push({
          at: Math.random(),
          // Negative is legal and intentional: most particles travel against
          // the head, so the route reads as carrying traffic in both
          // directions rather than being towed along by one thing.
          speed: (0.012 + Math.random() * 0.03) * (Math.random() < 0.4 ? -1 : 1),
          size: 0.9 + Math.random() * 1.5,
          tint: Math.random() < 0.5 ? 'lime' : 'green',
        })
      }
    }

    /**
     * The backdrop never changes, so it is painted once and blitted each frame.
     * The parent is a near-black surface, so this is also what clears the canvas.
     */
    const backdrop = document.createElement('canvas')
    const paintBackdrop = () => {
      backdrop.width = Math.max(1, Math.round(width * dpr))
      backdrop.height = Math.max(1, Math.round(height * dpr))
      const b = backdrop.getContext('2d')
      if (b === null) return
      b.setTransform(dpr, 0, 0, dpr, 0, 0)
      b.globalCompositeOperation = 'source-over'
      b.fillStyle = rgba(black, 1)
      b.fillRect(0, 0, width, height)
      b.globalCompositeOperation = 'lighter'
      // Lime from above and behind the card, green from below: the landing
      // page's own rhythm, at a fraction of its strength. The card is the
      // subject, so the field has to stay behind it.
      const glow = b.createRadialGradient(
        width * 0.5,
        height * 0.42,
        0,
        width * 0.5,
        height * 0.42,
        Math.max(width, height) * 0.62,
      )
      glow.addColorStop(0, rgba(green, 0.075))
      glow.addColorStop(0.5, rgba(green, 0.022))
      glow.addColorStop(1, rgba(green, 0))
      b.fillStyle = glow
      b.fillRect(0, 0, width, height)
    }

    const resize = () => {
      width = Math.max(1, window.innerWidth)
      height = Math.max(1, window.innerHeight)
      const pixels = width * height
      // Capped hard: this field is decorative and sits behind a form, so a
      // retina panel gets the same treatment as a laptop rather than four
      // times the fill cost.
      dpr = pixels > 1_200_000 ? 1 : Math.min(window.devicePixelRatio || 1, 1.5)
      canvas.width = Math.max(1, Math.round(width * dpr))
      canvas.height = Math.max(1, Math.round(height * dpr))
      canvas.style.width = `${width}px`
      canvas.style.height = `${height}px`
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.lineJoin = 'round'
      ctx.lineCap = 'round'
      route = buildRoute(width, height)
      seedParticles()
      paintBackdrop()
      if (motionQuery.matches) paintStatic()
    }

    /** The route itself: one faint stroke, the constant the rest plays against. */
    const drawRoute = (alpha: number) => {
      if (route.length === 0) return
      ctx.beginPath()
      const first = route[0]
      if (first === undefined) return
      ctx.moveTo(first.x, first.y)
      for (let i = 1; i < route.length; i += 1) {
        const p = route[i]
        if (p !== undefined) ctx.lineTo(p.x, p.y)
      }
      ctx.closePath()
      ctx.strokeStyle = rgba(green, 0.16 * alpha * quality)
      ctx.lineWidth = 1
      ctx.stroke()
    }

    /**
     * The travelling segment, drawn as a slice of the sampled route.
     *
     * Two strokes stand in for a glow: a wide dim one and the filament itself.
     * A blur filter here would be far more expensive than the effect is worth,
     * and at this opacity the pair is indistinguishable.
     */
    const drawHead = (brightness: number) => {
      const span = 0.085
      const steps = 26
      ctx.globalCompositeOperation = 'lighter'

      ctx.beginPath()
      for (let i = 0; i <= steps; i += 1) {
        const t = head - span + (span * i) / steps
        const p = pointAt(t)
        if (i === 0) ctx.moveTo(p.x, p.y)
        else ctx.lineTo(p.x, p.y)
      }
      ctx.strokeStyle = rgba(lime, 0.1 * brightness * quality)
      ctx.lineWidth = 9
      ctx.stroke()
      ctx.strokeStyle = rgba(lime, 0.5 * brightness * quality)
      ctx.lineWidth = 1.6
      ctx.stroke()

      // The leading mark: small, hard, and the only saturated thing here.
      const tip = pointAt(head)
      const dot = ctx.createRadialGradient(tip.x, tip.y, 0, tip.x, tip.y, 11)
      dot.addColorStop(0, rgba(lime, 0.6 * brightness * quality))
      dot.addColorStop(0.4, rgba(green, 0.22 * brightness * quality))
      dot.addColorStop(1, rgba(green, 0))
      ctx.fillStyle = dot
      ctx.beginPath()
      ctx.arc(tip.x, tip.y, 11, 0, Math.PI * 2)
      ctx.fill()

      ctx.globalCompositeOperation = 'source-over'
    }

    /**
     * Junctions. Each lights on its own schedule, and brightens sharply as the
     * travelling segment passes over it, so the route reads as carrying the
     * signal rather than as a line with decoration stuck to it.
     */
    const drawNodes = (t: number) => {
      ctx.globalCompositeOperation = 'lighter'
      for (let i = 0; i < nodes.length; i += 1) {
        const node = nodes[i]
        if (node === undefined) continue
        const p = pointAt(node.at)

        // Standing light: a slow narrow pulse, so junctions breathe.
        const idle = Math.pow(Math.max(0, Math.sin(t * 0.00042 + node.phase)), 6) * 0.5
        // Traffic: distance from the head along the route, in either direction.
        const gap = Math.min(Math.abs(node.at - head), 1 - Math.abs(node.at - head))
        const pass = Math.max(0, 1 - gap / 0.05)
        const lit = clamp(idle + pass * 0.9, 0, 1)

        // The nearest node to the focused field stays lit while it has focus.
        const isFocus = i === focusNode ? focusGlow : 0
        const brightness = clamp(lit + isFocus * 0.75, 0, 1)
        if (brightness < 0.02) continue

        const radius = 2 + brightness * 1.6
        ctx.fillStyle = rgba(i % 4 === 0 ? lime : green, 0.5 * brightness * quality)
        ctx.beginPath()
        ctx.arc(p.x, p.y, radius, 0, Math.PI * 2)
        ctx.fill()

        if (brightness > 0.4) {
          const halo = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, 18)
          halo.addColorStop(0, rgba(lime, 0.2 * brightness * quality))
          halo.addColorStop(1, rgba(lime, 0))
          ctx.fillStyle = halo
          ctx.beginPath()
          ctx.arc(p.x, p.y, 18, 0, Math.PI * 2)
          ctx.fill()
        }
      }
      ctx.globalCompositeOperation = 'source-over'
    }

    const drawParticles = (delta: number) => {
      ctx.globalCompositeOperation = 'lighter'
      for (const particle of particles) {
        const before = particle.at
        particle.at = ((particle.at + particle.speed * delta * 0.06) % 1 + 1) % 1
        const from = pointAt(before)
        const to = pointAt(particle.at)
        ctx.strokeStyle = rgba(tint(particle.tint), 0.34 * quality)
        ctx.lineWidth = particle.size
        ctx.beginPath()
        ctx.moveTo(from.x, from.y)
        ctx.lineTo(to.x, to.y)
        ctx.stroke()
      }
      ctx.globalCompositeOperation = 'source-over'
    }

    /**
     * The verification pulse: an expanding ring, fired once on success.
     *
     * A ring rather than a flash, because a flash is a strobe and this page is
     * not a strobe. Two of them, slightly offset, is the minimum that reads as
     * a confirmation rather than a single expanding circle.
     */
    const drawRings = (delta: number) => {
      if (rings.length === 0) return
      ctx.globalCompositeOperation = 'lighter'
      const cx = width * 0.5
      const cy = height * 0.5
      for (let i = rings.length - 1; i >= 0; i -= 1) {
        const ring = rings[i]
        if (ring === undefined) continue
        ring.age += delta
        const progress = ring.age / ring.life
        if (progress >= 1) {
          rings.splice(i, 1)
          continue
        }
        const eased = 1 - Math.pow(1 - progress, 3)
        const radius = eased * Math.max(width, height) * 0.62
        const alpha = (1 - progress) * 0.3
        ctx.strokeStyle = rgba(lime, alpha * quality)
        ctx.lineWidth = 2.5 * (1 - progress) + 0.5
        ctx.beginPath()
        ctx.arc(cx, cy, radius, 0, Math.PI * 2)
        ctx.stroke()
      }
      ctx.globalCompositeOperation = 'source-over'
    }

    /**
     * Reduced motion: one frame, then nothing. The route and the junctions are
     * still there, so the page keeps its depth, but no loop is ever started and
     * no battery is spent.
     */
    function paintStatic() {
      ctx.globalCompositeOperation = 'source-over'
      ctx.drawImage(backdrop, 0, 0, width, height)
      ctx.globalCompositeOperation = 'lighter'
      drawRoute(1)
      for (const node of nodes) {
        const p = pointAt(node.at)
        ctx.fillStyle = rgba(node.weight > 0.8 ? lime : green, 0.28 * quality)
        ctx.beginPath()
        ctx.arc(p.x, p.y, 2, 0, Math.PI * 2)
        ctx.fill()
      }
      ctx.globalCompositeOperation = 'source-over'
    }

    let previous = 0
    const frame = (now: number) => {
      const delta = previous === 0 ? 1 : clamp((now - previous) / 16.67, 0, 3)
      previous = now

      // Focus: find the nearest junction to the focused field, once per frame,
      // and let its glow decay rather than switching off instantly.
      const y = focusYRef.current
      if (focusedRef.current && y !== null && route.length > 0) {
        let best = -1
        let bestDistance = Infinity
        for (let i = 0; i < nodes.length; i += 1) {
          const node = nodes[i]
          if (node === undefined) continue
          const p = pointAt(node.at)
          const distance = Math.hypot(p.x - width * 0.5, p.y - y)
          if (distance < bestDistance) {
            bestDistance = distance
            best = i
          }
        }
        if (best !== focusNode) focusNode = best
        focusGlow = Math.min(1, focusGlow + 0.14 * delta)
      } else {
        focusGlow = Math.max(0, focusGlow - 0.06 * delta)
        if (focusGlow === 0) focusNode = -1
      }

      // A validation pass runs the loop once, briskly.
      if (sweepTokenRef.current !== lastSweepToken) {
        lastSweepToken = sweepTokenRef.current
        sweep = 1
      }
      if (sweep > 0) {
        sweep = Math.max(0, sweep - 0.008 * delta)
        head = (head + 0.028 * delta) % 1
      } else {
        head = (head + 0.0035 * delta) % 1
      }

      // Success: two rings, offset so they read as one event.
      if (pulseRef.current) {
        pulseRef.current = false
        rings.length = 0
        rings.push({ age: 0, life: 78 }, { age: -14, life: 78 })
      }

      ctx.globalCompositeOperation = 'source-over'
      ctx.drawImage(backdrop, 0, 0, width, height)
      ctx.globalCompositeOperation = 'lighter'

      drawRoute(1)
      drawParticles(delta)
      drawNodes(now)
      drawHead(sweep > 0 ? 1 + sweep * 0.8 : 1)
      drawRings(delta)

      raf = requestAnimationFrame(frame)
    }

    const start = () => {
      if (raf !== 0) return
      previous = 0
      raf = requestAnimationFrame(frame)
    }
    const stop = () => {
      if (raf === 0) return
      cancelAnimationFrame(raf)
      raf = 0
    }

    const onVisibility = () => {
      if (document.hidden) stop()
      else if (!motionQuery.matches) start()
    }
    document.addEventListener('visibilitychange', onVisibility)

    // Honour a mid-session change to the motion preference, not just the value
    // at mount.
    const onMotionChange = () => {
      stop()
      if (motionQuery.matches) paintStatic()
      else start()
    }
    motionQuery.addEventListener('change', onMotionChange)

    resize()
    if (motionQuery.matches) paintStatic()
    else start()

    return () => {
      stop()
      window.removeEventListener('resize', resize)
      document.removeEventListener('visibilitychange', onVisibility)
      motionQuery.removeEventListener('change', onMotionChange)
    }
  }, [quality])

  return <canvas ref={canvasRef} className="lfp-auth__signal" aria-hidden="true" />
}

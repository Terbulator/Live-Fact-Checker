import { useEffect, useRef } from 'react'

/**
 * The energy field behind the login screen.
 *
 * A single 2D canvas, one rAF loop, zero React state. The pointer is not a
 * spotlight that follows the cursor — it is an *attractor* inside a system that
 * keeps running without it:
 *
 *   head     a spring that chases the pointer. It never arrives instantly, so a
 *            change of direction leaves the energy briefly behind on the old
 *            heading before the new ribbons bend toward the cursor.
 *   trail    the head's own recent path, kept as a ring buffer. Every ribbon
 *            and every particle is read out of this, and that is what makes the
 *            field lag, stretch and decay rather than track.
 *   ribbons  five passes over the trail, each starting further back and wobbling
 *            on its own phase, stroked three times (wide/dim → medium → core)
 *            rather than blurred.
 *   motes    advected by the head's velocity, so they are carried by the flow
 *            instead of chasing it. Some detach and die on their own.
 *   haze     three large soft washes that follow the head at different rates:
 *            the volumetric illumination.
 *
 * Two rules shaped the implementation.
 *
 *   Tokens, not colours. Every fill comes from `--lfp-lime` / `--lfp-green` /
 *   `--lfp-black` read off the canvas at start-up. No hex appears in this file,
 *   so the field cannot drift away from the landing page's palette.
 *
 *   Fill rate, not draw calls. A full-viewport canvas repainting sixty times a
 *   second is entirely fill-rate bound, so the static backdrop is baked once
 *   into an offscreen canvas, the device pixel ratio is capped, and nothing
 *   per-frame uses a blur filter.
 *
 * `prefers-reduced-motion` drops to a single painted frame: no loop, no motes,
 * no pointer. Touch devices run the same field with an autonomous target
 * instead of a cursor.
 */

type RGB = [number, number, number]
type Tint = 'lime' | 'green'

interface EnergyFieldProps {
  /** 0–1. Scales the mote budget, ribbon reach and overall brightness. */
  quality: number
}

interface Ribbon {
  /** How far back into the trail this layer starts reading: the parallax. */
  lag: number
  step: number
  width: number
  alpha: number
  wobble: number
  speed: number
  phase: number
  /** Trail samples exposed at a full-speed sweep. */
  span: number
  tint: Tint
}

interface Mote {
  x: number
  y: number
  ox: number
  oy: number
  vx: number
  vy: number
  life: number
  max: number
  size: number
  tint: RGB
  seed: number
}

/**
 * Ribbon layers, widest and faintest last. `lag` is how far back into the trail
 * this layer starts reading, which is the parallax: the thin bright filament
 * hugs the head while the wide atmospheric ribbon is well behind it. `wobble`
 * grows with width, because a thick ribbon needs a much larger excursion to
 * read as bent rather than as a straight smear.
 *
 * `step` is the important performance field. A stroke's cost is dominated by its
 * vertices, not its length, because every one costs a round join the width of the
 * line — on a 96px-wide stroke that is a large arc fill, and a hundred of them
 * is what turns a soft atmospheric band into a dropped frame. So the thin
 * filaments sample every point and the wide bands step wider and reach less
 * far, which is also all they need to read as atmosphere.
 */
const RIBBONS: Ribbon[] = [
  { lag: 0, step: 1, width: 1.2, alpha: 0.95, wobble: 5, speed: 1.6, phase: 0.0, span: 120, tint: 'lime' },
  { lag: 4, step: 1, width: 2.8, alpha: 0.4, wobble: 18, speed: 1.1, phase: 1.9, span: 96, tint: 'lime' },
  { lag: 11, step: 2, width: 7, alpha: 0.17, wobble: 38, speed: 0.82, phase: 3.4, span: 64, tint: 'green' },
  { lag: 22, step: 3, width: 16, alpha: 0.085, wobble: 62, speed: 0.56, phase: 5.1, span: 46, tint: 'green' },
  { lag: 32, step: 5, width: 30, alpha: 0.045, wobble: 92, speed: 0.36, phase: 0.7, span: 32, tint: 'green' },
]

/** Trail samples exposed at a crawl, as a fraction of a full-speed sweep. */
const SLOW_SPAN = 0.4
/** Pointer speed in CSS px/frame that counts as a full-tilt sweep. */
const FAST_SPEED = 16
const TRAIL_MAX = 130

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
const lerp = (a: number, b: number, t: number) => a + (b - a) * t

export function EnergyField({ quality }: EnergyFieldProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (canvas === null) return undefined
    const context = canvas.getContext('2d')
    if (context === null) return undefined
    // Annotated non-null so the hoisted helpers below, which TypeScript assumes
    // may run before the guard above, still get a definite context.
    const ctx: CanvasRenderingContext2D = context

    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    const pointerQuery = window.matchMedia('(pointer: fine)')

    const lime = readToken(canvas, '--lfp-lime')
    const green = readToken(canvas, '--lfp-green')
    const black = readToken(canvas, '--lfp-black')
    const tint = (t: Tint) => (t === 'lime' ? lime : green)

    let width = 1
    let height = 1
    let dpr = 1
    let raf = 0
    let boost = 0
    let spawnDebt = 0

    const trail: { x: number; y: number }[] = []
    const motes: Mote[] = []
    const ambient: Mote[] = []

    const head = { x: 0, y: 0, vx: 0, vy: 0 }
    const pointer = { x: 0, y: 0, seen: false }
    const haze = [
      { x: 0, y: 0, r: 420, a: 0.085, ease: 0.055 },
      { x: 0, y: 0, r: 280, a: 0.075, ease: 0.09 },
      { x: 0, y: 0, r: 175, a: 0.1, ease: 0.15 },
    ]

    const moteBudget = () => Math.round(clamp((width * height) / 9000, 40, 190) * quality)
    const ambientBudget = () => Math.round(moteBudget() * 0.4)

    /**
     * A mote is shed *onto a ribbon*, not into a disc around the head: it picks
     * a point somewhere along the trail, offset a little sideways. That is what
     * makes them read as carried by the flow rather than as sparks around a dot.
     * Farther along the trail means further from the head, so a share of them are
     * born already detached.
     */
    const newMote = (): Mote => {
      const index = Math.floor(Math.pow(Math.random(), 2.2) * Math.min(trail.length, 70))
      const p = trail[index] ?? head
      const q = trail[Math.max(0, index - 1)] ?? head
      const len = Math.hypot(p.x - q.x, p.y - q.y) || 1
      const side = (Math.random() - 0.5) * 15
      return {
        x: p.x + (-(p.y - q.y) / len) * side,
        y: p.y + ((p.x - q.x) / len) * side,
        ox: 0,
        oy: 0,
        vx: (Math.random() - 0.5) * 0.7,
        vy: (Math.random() - 0.5) * 0.7,
        life: 0,
        max: 40 + Math.random() * 110,
        size: 0.7 + Math.random() * 2.2,
        tint: Math.random() < 0.55 ? lime : green,
        seed: Math.random() * 1000,
      }
    }

    /**
     * Cap a mote's speed. Advection is an accumulating term, so without a cap a
     * mote handed a lot of momentum keeps accelerating and eventually crosses the
     * viewport as a hard streak — a laser, not a spark.
     */
    const capMote = (m: Mote, limit: number) => {
      const speed = Math.hypot(m.vx, m.vy)
      if (speed <= limit) return
      m.vx = (m.vx / speed) * limit
      m.vy = (m.vy / speed) * limit
    }

    /**
     * The backdrop never changes, so it is painted once into a second canvas and
     * blitted in. Re-deriving three large gradients every frame is the single
     * most expensive thing this effect could do.
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
      // Lime from above, green from below: the landing page's own rhythm, at a
      // tenth of the landing page's strength.
      const top = b.createRadialGradient(width / 2, -height * 0.18, 0, width / 2, -height * 0.18, height * 0.95)
      top.addColorStop(0, rgba(lime, 0.1))
      top.addColorStop(0.45, rgba(lime, 0.028))
      top.addColorStop(1, rgba(lime, 0))
      b.fillStyle = top
      b.fillRect(0, 0, width, height)
      const floor = b.createRadialGradient(width * 0.5, height * 1.05, 0, width * 0.5, height * 1.05, height * 0.85)
      floor.addColorStop(0, rgba(green, 0.09))
      floor.addColorStop(0.5, rgba(green, 0.025))
      floor.addColorStop(1, rgba(green, 0))
      b.fillStyle = floor
      b.fillRect(0, 0, width, height)
    }

    const resize = () => {
      width = Math.max(1, window.innerWidth)
      height = Math.max(1, window.innerHeight)
      // Adaptive resolution. A full-viewport repaint is fill-rate bound, so the
      // pixel count matters far more than the stroke count: past about a
      // megapixel the extra device pixels buy almost nothing on a field this
      // soft, and cost 2.25x. Below that, take whatever the screen gives.
      const pixels = width * height
      dpr = pixels > 900_000 ? 1 : Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.max(1, Math.round(width * dpr))
      canvas.height = Math.max(1, Math.round(height * dpr))
      canvas.style.width = `${width}px`
      canvas.style.height = `${height}px`
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.lineJoin = 'round'
      ctx.lineCap = 'round'
      if (trail.length === 0) {
        head.x = width / 2
        head.y = height * 0.46
        for (const h of haze) {
          h.x = head.x
          h.y = head.y
        }
        while (ambient.length < ambientBudget()) ambient.push(newMote())
      }
      paintBackdrop()
      hazeBuffer.width = Math.max(1, Math.round(width * HAZE_SCALE))
      hazeBuffer.height = Math.max(1, Math.round(height * HAZE_SCALE))
      if (motionQuery.matches) paintStatic()
    }

    /** Slow organic drift, so the field is alive even when the cursor is not. */
    const wander = (t: number, amount: number) => ({
      x: (Math.sin(t * 0.00061) * 52 + Math.sin(t * 0.00023 + 2.1) * 34) * amount,
      y: (Math.cos(t * 0.00047 + 0.9) * 40 + Math.sin(t * 0.00031 + 4.2) * 22) * amount,
    })

    const onPointerMove = (event: PointerEvent) => {
      pointer.x = event.clientX
      pointer.y = event.clientY
      pointer.seen = true
    }
    window.addEventListener('pointermove', onPointerMove, { passive: true })

    /**
     * The haze is the volumetric illumination, and it is also three large radial
     * gradients over most of the canvas — the single most expensive thing the
     * effect draws. It is soft by definition, so it is rendered into a
     * quarter-resolution buffer and blitted up. Gradient fill drops sixteenfold
     * and nothing visible is lost, because there are no edges to resolve.
     */
    const HAZE_SCALE = 0.25
    const hazeBuffer = document.createElement('canvas')
    const hazeContext = hazeBuffer.getContext('2d')

    const drawHaze = (t: number) => {
      if (hazeContext === null) return
      const hctx = hazeContext
      // Below full quality the widest wash is dropped: it is the largest single
      // fill on the page and the least load-bearing of the three.
      const layers = quality < 0.75 ? haze.slice(1) : haze

      hctx.setTransform(1, 0, 0, 1, 0, 0)
      hctx.clearRect(0, 0, hazeBuffer.width, hazeBuffer.height)
      hctx.setTransform(HAZE_SCALE, 0, 0, HAZE_SCALE, 0, 0)
      hctx.globalCompositeOperation = 'lighter'

      for (const h of layers) {
        h.x = lerp(h.x, head.x, h.ease)
        h.y = lerp(h.y, head.y, h.ease)
        const drift = wander(t * 0.5, 0.4)
        const cx = h.x + drift.x
        const cy = h.y + drift.y
        const g = hctx.createRadialGradient(cx, cy, 0, cx, cy, h.r)
        g.addColorStop(0, rgba(green, h.a))
        g.addColorStop(0.42, rgba(green, h.a * 0.34))
        g.addColorStop(1, rgba(green, 0))
        hctx.fillStyle = g
        hctx.beginPath()
        hctx.arc(cx, cy, h.r, 0, Math.PI * 2)
        hctx.fill()
      }

      ctx.globalCompositeOperation = 'lighter'
      ctx.drawImage(hazeBuffer, 0, 0, width, height)
    }

    const drawRibbons = (t: number, span: number) => {
      if (trail.length < 4) return
      const pointAt = (i: number) => trail[i] ?? head
      // Below full quality the two widest bands go first: they are the most
      // expensive strokes and the least load-bearing ones visually.
      const layers = quality < 0.75 ? RIBBONS.slice(0, 3) : RIBBONS
      for (const ribbon of layers) {
        const reach = Math.min(Math.round(ribbon.span * span), trail.length - ribbon.lag)
        if (reach < 3) continue

        ctx.beginPath()
        for (let i = 0; i < reach; i += ribbon.step) {
          const at = i + ribbon.lag
          const p = pointAt(at)
          const q = pointAt(Math.max(0, at - 1))
          // Bend the ribbon off its own tangent, with an envelope that pins it
          // to the head and lets it bow through the middle. Two frequencies, so
          // the curve is a slow snake rather than a jitter. Each layer runs its
          // own phase and rate, which is what stops the five layers from
          // collapsing into one thick line tracking the cursor exactly.
          const tx = p.x - q.x
          const ty = p.y - q.y
          const len = Math.hypot(tx, ty) || 1
          const progress = i / reach
          const envelope = Math.sin(Math.PI * progress) ** 0.55
          const wave =
            Math.sin(t * 0.0009 * ribbon.speed + i * 0.05 + ribbon.phase) * 0.75 +
            Math.sin(t * 0.0017 * ribbon.speed + i * 0.13 + ribbon.phase * 2.3) * 0.25
          const offset = wave * ribbon.wobble * envelope
          const x = p.x + (-ty / len) * offset
          const y = p.y + (tx / len) * offset
          if (i === 0) ctx.moveTo(x, y)
          else ctx.lineTo(x, y)
        }

        const end = pointAt(Math.min(reach - 1 + ribbon.lag, trail.length - 1))
        const colour = tint(ribbon.tint)
        const fade = ctx.createLinearGradient(head.x, head.y, end.x, end.y)
        fade.addColorStop(0, rgba(colour, ribbon.alpha))
        fade.addColorStop(0.45, rgba(colour, ribbon.alpha * 0.42))
        fade.addColorStop(1, rgba(colour, 0))
        ctx.strokeStyle = fade
        // Three strokes stand in for a blur: wide and dim, then medium, then the
        // filament itself. The wide pass is by far the most expensive thing here
        // — its area is reach × width — so the multiplier is kept small.
        ctx.globalAlpha = 0.22
        ctx.lineWidth = ribbon.width * 3
        ctx.stroke()
        ctx.globalAlpha = 0.5
        ctx.lineWidth = ribbon.width * 1.9
        ctx.stroke()
        ctx.globalAlpha = 1
        ctx.lineWidth = ribbon.width
        ctx.stroke()
      }
      ctx.globalAlpha = 1
    }

    const drawMotes = (t: number) => {
      for (const m of motes) {
        // Advection: the head's momentum is handed to the mote, so it is carried
        // along the stream and keeps travelling when the head slows.
        m.vx += head.vx * 0.13 + Math.sin(m.y * 0.008 + t * 0.0007 + m.seed) * 0.05
        m.vy += head.vy * 0.13 + Math.cos(m.x * 0.008 + t * 0.0006 + m.seed) * 0.05
        m.vx *= 0.955
        m.vy *= 0.955
        capMote(m, 5)
        m.life += 1
        m.ox = m.x
        m.oy = m.y
        m.x += m.vx
        m.y += m.vy

        // Retire on distance as well as on age: a mote left behind by a fast
        // sweep fades out instead of orbiting the page indefinitely.
        if (m.life > m.max || Math.hypot(m.x - head.x, m.y - head.y) > 460) {
          m.life = 0
          continue
        }

        // A sine envelope: a mote fades in as it is shed and out as it dies.
        // The smallest ones stay faint so the field reads as dust in a stream
        // rather than as scattered confetti.
        const weight = 0.45 + Math.min(1, m.size / 2.2) * 0.55
        const a = Math.sin((Math.PI * m.life) / m.max) * 0.8 * weight * quality
        if (a <= 0.005) continue

        // The motion streak is the mote's own fading trail.
        ctx.strokeStyle = rgba(m.tint, a)
        ctx.lineWidth = m.size
        ctx.beginPath()
        ctx.moveTo(m.ox, m.oy)
        ctx.lineTo(m.x, m.y)
        ctx.stroke()
        if (m.size > 1.4) {
          ctx.fillStyle = rgba(lime, a * 0.85)
          ctx.beginPath()
          ctx.arc(m.x, m.y, m.size * 0.7, 0, Math.PI * 2)
          ctx.fill()
        }
      }

      for (const m of ambient) {
        // Ambient motes ride the same curl field as the flow motes, which is what
        // stops them reading as a starfield. They never die, so the page keeps a
        // faint drift around it however still the cursor is.
        m.vx += Math.sin(m.y * 0.006 + t * 0.0004 + m.seed) * 0.028
        m.vy += Math.cos(m.x * 0.006 + t * 0.00035 + m.seed) * 0.028
        m.vx *= 0.985
        m.vy *= 0.985
        m.ox = m.x
        m.oy = m.y
        m.x += m.vx
        m.y += m.vy
        if (m.x < -40 || m.x > width + 40 || m.y < -40 || m.y > height + 40) {
          m.x = head.x + (Math.random() - 0.5) * 200
          m.y = head.y + (Math.random() - 0.5) * 200
        }
        ctx.strokeStyle = rgba(m.tint, 0.16 * quality)
        ctx.lineWidth = m.size
        ctx.beginPath()
        ctx.moveTo(m.ox, m.oy)
        ctx.lineTo(m.x, m.y)
        ctx.stroke()
      }
    }

    const drawCore = () => {
      const r = 74 + boost * 46
      const g = ctx.createRadialGradient(head.x, head.y, 0, head.x, head.y, r)
      g.addColorStop(0, rgba(lime, 0.4))
      g.addColorStop(0.18, rgba(lime, 0.2))
      g.addColorStop(0.45, rgba(green, 0.1))
      g.addColorStop(1, rgba(green, 0))
      ctx.fillStyle = g
      ctx.beginPath()
      ctx.arc(head.x, head.y, r, 0, Math.PI * 2)
      ctx.fill()

      // The bright lime source: small, hard, and the one genuinely saturated
      // mark anywhere on the page.
      const dot = ctx.createRadialGradient(head.x, head.y, 0, head.x, head.y, 16)
      dot.addColorStop(0, rgba(lime, 0.9))
      dot.addColorStop(0.5, rgba(lime, 0.35))
      dot.addColorStop(1, rgba(lime, 0))
      ctx.fillStyle = dot
      ctx.beginPath()
      ctx.arc(head.x, head.y, 16, 0, Math.PI * 2)
      ctx.fill()
    }

    function paintStatic() {
      ctx.globalCompositeOperation = 'source-over'
      ctx.drawImage(backdrop, 0, 0, width, height)
      // Reduced motion keeps one still wash behind the card. Nothing here moves,
      // so there is no loop to run and no battery to spend.
      ctx.globalCompositeOperation = 'lighter'
      const cx = width * 0.5
      const cy = height * 0.4
      const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(width, height) * 0.55)
      g.addColorStop(0, rgba(green, 0.07))
      g.addColorStop(0.5, rgba(green, 0.022))
      g.addColorStop(1, rgba(green, 0))
      ctx.fillStyle = g
      ctx.fillRect(0, 0, width, height)
      ctx.globalCompositeOperation = 'source-over'
    }

    const frame = () => {
      const t = performance.now()
      const autonomous = motionQuery.matches || !pointerQuery.matches || !pointer.seen

      let targetX: number
      let targetY: number
      if (autonomous) {
        // No cursor to follow, so the field crosses the viewport on its own. The
        // periods here are deliberately short enough to keep ribbons visibly
        // stretched on a touch device, where `quality` also scales the mote
        // budget down.
        targetX = width * 0.5 + Math.sin(t * 0.00042) * width * 0.32
        targetY = height * 0.46 + Math.sin(t * 0.00031 + 1.7) * height * 0.28
      } else {
        // Pointer mode, but never frozen: the more the cursor settles, the more
        // the target wanders, so there is always something flowing.
        const drift = wander(t, 0.55 + boost * 0.85)
        targetX = pointer.x + drift.x
        targetY = pointer.y + drift.y
      }

      // Spring chase. The lag *is* the effect: the energy arrives late, never
      // overshoots, and bends through corners instead of snapping.
      const chase = autonomous ? 0.06 : 0.11
      const previousX = head.x
      const previousY = head.y
      head.vx = (head.vx + (targetX - head.x) * chase) * 0.86
      head.vy = (head.vy + (targetY - head.y) * chase) * 0.86
      head.x += head.vx
      head.y += head.vy
      boost = clamp(Math.hypot(head.x - previousX, head.y - previousY) / FAST_SPEED, 0, 1)

      trail.unshift({ x: head.x, y: head.y })
      if (trail.length > TRAIL_MAX) trail.pop()

      ctx.globalCompositeOperation = 'source-over'
      // The backdrop is opaque and covers the full canvas, so it both clears and
      // paints — an extra clearRect here would be a second full-surface op for
      // nothing.
      ctx.drawImage(backdrop, 0, 0, width, height)
      ctx.globalCompositeOperation = 'lighter'

      // Slow pointer means a short, faint wake; a fast sweep exposes the whole
      // trail and brightens it. This is the energy stretching with velocity.
      // Reach is deliberately *not* scaled by quality — quality buys motes and
      // brightness, and a phone should still show visibly flowing ribbons.
      drawHaze(t)
      drawRibbons(t, lerp(SLOW_SPAN, 1.05, boost))
      drawMotes(t)

      // Motes are shed by motion, not by a timer: the spawn rate follows speed.
      spawnDebt += (0.25 + boost * 2.6) * quality
      while (spawnDebt >= 1 && motes.length < moteBudget()) {
        spawnDebt -= 1
        motes.push(newMote())
      }

      drawCore()
      ctx.globalCompositeOperation = 'source-over'

      raf = requestAnimationFrame(frame)
    }

    const start = () => {
      if (raf !== 0) return
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
      window.removeEventListener('pointermove', onPointerMove)
      document.removeEventListener('visibilitychange', onVisibility)
      motionQuery.removeEventListener('change', onMotionChange)
    }
  }, [quality])

  return <canvas ref={canvasRef} className="lfp-auth__energy" aria-hidden="true" />
}

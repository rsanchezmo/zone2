import { useEffect, useMemo, useRef } from 'react'
import polyline from '@mapbox/polyline'
import { usePolylines } from '../../api/hooks'
import { useBackdrop } from '../../hooks/useBackdrop'
import { useTheme } from '../../hooks/useTheme'
import type { BackdropCity } from '../../hooks/backdropContext'

interface Bounds {
  minX: number
  maxX: number
  minY: number
  maxY: number
}

const DEG_TO_RAD = Math.PI / 180

/** Web-Mercator, both axes in radians so a single scale keeps the aspect true. */
function mercatorX(lon: number): number {
  return lon * DEG_TO_RAD
}

function mercatorY(lat: number): number {
  const clamped = Math.max(-85.05, Math.min(85.05, lat))
  return Math.log(Math.tan(Math.PI / 4 + (clamped * DEG_TO_RAD) / 2))
}

/** ~55 km — wide enough to hold a city and its outskirts in one cell. */
const CLUSTER_CELL = 0.5 * DEG_TO_RAD

function quantile(sorted: number[], q: number): number {
  return sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * q))]
}

/**
 * Frame on the single region the routes cluster in. Total bounds would span
 * every country ever visited, and covering that puts the empty land between
 * clusters on screen — so bucket the points into regions and keep the busiest
 * one's neighbourhood. Trips elsewhere still draw, just off-frame.
 */
function clusterBounds(routes: Float64Array[]): Bounds | null {
  const counts = new Map<string, number>()
  let best = ''
  let bestCount = 0
  for (const flat of routes) {
    for (let i = 0; i < flat.length; i += 2) {
      const key = `${Math.round(flat[i] / CLUSTER_CELL)}:${Math.round(flat[i + 1] / CLUSTER_CELL)}`
      const next = (counts.get(key) ?? 0) + 1
      counts.set(key, next)
      if (next > bestCount) {
        bestCount = next
        best = key
      }
    }
  }
  if (!best) return null

  const [cellX, cellY] = best.split(':').map(Number)
  const xs: number[] = []
  const ys: number[] = []
  for (const flat of routes) {
    for (let i = 0; i < flat.length; i += 2) {
      const x = flat[i]
      const y = flat[i + 1]
      if (Math.abs(x / CLUSTER_CELL - cellX) > 1.5 || Math.abs(y / CLUSTER_CELL - cellY) > 1.5) continue
      xs.push(x)
      ys.push(y)
    }
  }
  if (!xs.length) return null

  // Percentiles, not extremes: a single ride out to the mountains would
  // otherwise shrink the whole street network into a corner.
  const asc = (a: number, b: number) => a - b
  xs.sort(asc)
  ys.sort(asc)
  return {
    minX: quantile(xs, 0.02),
    maxX: quantile(xs, 0.98),
    minY: quantile(ys, 0.02),
    maxY: quantile(ys, 0.98),
  }
}

/** Projected routes as flat [x0, y0, x1, y1, …] pairs, plus the frame to fit. */
function project(
  encoded: { polyline: string }[] | undefined,
  city: BackdropCity | null,
): { routes: Float64Array[]; bounds: Bounds | null } {
  if (!encoded?.length) return { routes: [], bounds: null }

  const routes: Float64Array[] = []
  for (const { polyline: encodedPath } of encoded) {
    let points: [number, number][]
    try {
      points = polyline.decode(encodedPath) as [number, number][]
    } catch {
      continue
    }
    if (points.length < 2) continue
    if (city && !points.some(([lat, lon]) =>
      lat >= city.south && lat <= city.north && lon >= city.west && lon <= city.east)) {
      continue
    }

    const flat = new Float64Array(points.length * 2)
    for (let i = 0; i < points.length; i++) {
      flat[i * 2] = mercatorX(points[i][1])
      flat[i * 2 + 1] = mercatorY(points[i][0])
    }
    routes.push(flat)
  }

  if (!routes.length) return { routes: [], bounds: null }
  return { routes, bounds: clusterBounds(routes) }
}

function paint(
  canvas: HTMLCanvasElement,
  routes: Float64Array[],
  bounds: Bounds,
  color: string,
  core: string,
) {
  const ctx = canvas.getContext('2d')
  const width = canvas.clientWidth
  const height = canvas.clientHeight
  if (!ctx || width === 0 || height === 0) return

  // Cap the backing store at 2× — the backdrop is faint enough that retina
  // beyond that only costs fill rate.
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  canvas.width = Math.round(width * dpr)
  canvas.height = Math.round(height * dpr)
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, width, height)

  // Cover, not contain: the routes should bleed off-screen rather than float
  // in a letterboxed island.
  const scale = Math.max(
    width / Math.max(bounds.maxX - bounds.minX, 1e-9),
    height / Math.max(bounds.maxY - bounds.minY, 1e-9),
  )
  const cx = (bounds.minX + bounds.maxX) / 2
  const cy = (bounds.minY + bounds.maxY) / 2

  const path = new Path2D()
  for (const flat of routes) {
    let lastX = 0
    let lastY = 0
    for (let i = 0; i < flat.length; i += 2) {
      const px = (flat[i] - cx) * scale + width / 2
      const py = height / 2 - (flat[i + 1] - cy) * scale
      if (i === 0) {
        path.moveTo(px, py)
      } else if (Math.abs(px - lastX) + Math.abs(py - lastY) >= 0.4) {
        path.lineTo(px, py)
      } else {
        continue
      }
      lastX = px
      lastY = py
    }
  }

  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  // Three passes mirror the neon PNG export: wide atmosphere, soft glow, bright core.
  const passes: [number, number, string][] = [
    [5, 0.05, color],
    [1.8, 0.2, color],
    [0.6, 0.85, core],
  ]
  for (const [lineWidth, alpha, stroke] of passes) {
    ctx.lineWidth = lineWidth
    ctx.globalAlpha = alpha
    ctx.strokeStyle = stroke
    ctx.stroke(path)
  }
  ctx.globalAlpha = 1
}

/** Full-viewport neon route wallpaper sitting behind the whole app. */
export default function RouteBackdrop() {
  const { settings } = useBackdrop()
  const { theme } = useTheme()
  const canvasRef = useRef<HTMLCanvasElement>(null)

  const { data } = usePolylines(settings.sport || undefined, undefined, settings.enabled)

  const { routes, bounds } = useMemo(() => project(data, settings.city), [data, settings.city])

  // The white core is what makes the glow read as neon; on a light surface it
  // would vanish, so the accent carries the core there instead.
  const core = theme === 'light' ? settings.color : '#ffffff'

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !bounds) return

    let frame = 0
    const render = () => paint(canvas, routes, bounds, settings.color, core)
    const onResize = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(render)
    }

    render()
    window.addEventListener('resize', onResize)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('resize', onResize)
    }
  }, [routes, bounds, settings.color, core])

  if (!bounds) return null

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className="fixed inset-0 h-full w-full pointer-events-none"
      // Below the body noise texture (z-index -1) but above the body background.
      style={{ zIndex: -2, opacity: settings.opacity }}
    />
  )
}

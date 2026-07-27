import polyline from '@mapbox/polyline'
import type { ActivityPolyline } from '../../api/hooks'

export interface DecodedRoute {
  id: number | string
  sport_type: string
  name: string
  positions: [number, number][]
}

/** Leaflet corner pair: [[south, west], [north, east]]. */
export type CornerBounds = [[number, number], [number, number]]

export function decodeRoutes(raw: ActivityPolyline[] | undefined): DecodedRoute[] {
  if (!raw) return []
  const routes: DecodedRoute[] = []
  for (const activity of raw) {
    let positions: [number, number][]
    try {
      positions = polyline.decode(activity.polyline) as [number, number][]
    } catch {
      continue
    }
    if (positions.length === 0) continue
    routes.push({
      id: activity.id,
      sport_type: activity.sport_type,
      name: activity.name,
      positions,
    })
  }
  return routes
}

/** Bounding corners over every route point — endpoints alone collapse loops. */
export function routeBounds(routes: DecodedRoute[]): CornerBounds | null {
  let south = Infinity
  let west = Infinity
  let north = -Infinity
  let east = -Infinity
  for (const route of routes) {
    for (const [lat, lng] of route.positions) {
      if (lat < south) south = lat
      if (lat > north) north = lat
      if (lng < west) west = lng
      if (lng > east) east = lng
    }
  }
  if (south === Infinity) return null
  return [[south, west], [north, east]]
}

function quantile(sorted: number[], q: number): number {
  return sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * q))]
}

/**
 * Bounds around the interquartile core of the points, widened by `spread`.
 *
 * Total bounds open on a continent as soon as one trip left town, shrinking
 * the streets actually run into a knot. The IQR tracks where the bulk of the
 * points sit however far the strays reach — the outliers still render, they
 * are just off the initial view.
 */
export function homeBounds(routes: DecodedRoute[], spread = 2): CornerBounds | null {
  const lats: number[] = []
  const lngs: number[] = []
  for (const route of routes) {
    for (const [lat, lng] of route.positions) {
      lats.push(lat)
      lngs.push(lng)
    }
  }
  if (!lats.length) return null

  const asc = (a: number, b: number) => a - b
  lats.sort(asc)
  lngs.sort(asc)

  // ~500 m, so a single repeated loop still gets room around it.
  const MIN_PAD = 0.005
  const axis = (sorted: number[]): [number, number] => {
    const lo = quantile(sorted, 0.25)
    const hi = quantile(sorted, 0.75)
    const pad = Math.max((hi - lo) * spread, MIN_PAD)
    return [lo - pad, hi + pad]
  }

  const [south, north] = axis(lats)
  const [west, east] = axis(lngs)
  return [[south, west], [north, east]]
}

/** Stable key for a route set, so a map refits only when the set changes. */
export function routesSignature(routes: DecodedRoute[]): string {
  return `${routes.length}:${routes[0]?.id ?? ''}:${routes[routes.length - 1]?.id ?? ''}`
}

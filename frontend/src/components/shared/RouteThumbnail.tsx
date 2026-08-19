import { useMemo } from 'react'
import polyline from '@mapbox/polyline'
import clsx from 'clsx'
import { useTheme } from '../../hooks/useTheme'

const PADDING = 10
const MAX_POINTS = 100

interface RouteShape {
  d: string
  start: [number, number]
  end: [number, number]
}

/**
 * Decode a summary polyline and fit it into a size×size tile. Equirectangular
 * projection with a cos(mid-latitude) longitude correction is enough at
 * thumbnail scale — the route keeps its real aspect without a Mercator dep.
 */
function buildRouteShape(encoded: string, size: number): RouteShape | null {
  let points: [number, number][]
  try {
    points = polyline.decode(encoded) as [number, number][]
  } catch {
    return null
  }
  if (points.length < 2) return null

  const step = Math.max(1, Math.ceil(points.length / MAX_POINTS))
  const sampled = points.filter((_, i) => i % step === 0 || i === points.length - 1)

  let minLat = Infinity
  let maxLat = -Infinity
  let minLng = Infinity
  let maxLng = -Infinity
  for (const [lat, lng] of sampled) {
    if (lat < minLat) minLat = lat
    if (lat > maxLat) maxLat = lat
    if (lng < minLng) minLng = lng
    if (lng > maxLng) maxLng = lng
  }

  const cosLat = Math.cos(((minLat + maxLat) / 2) * Math.PI / 180)
  const spanX = (maxLng - minLng) * cosLat
  const spanY = maxLat - minLat
  if (spanX <= 0 && spanY <= 0) return null

  const inner = size - PADDING * 2
  const scale = Math.min(spanX > 0 ? inner / spanX : Infinity, spanY > 0 ? inner / spanY : Infinity)
  const offsetX = (size - spanX * scale) / 2
  const offsetY = (size - spanY * scale) / 2
  const px = (lng: number) => offsetX + (lng - minLng) * cosLat * scale
  const py = (lat: number) => offsetY + (maxLat - lat) * scale

  const d = sampled
    .map(([lat, lng], i) => `${i === 0 ? 'M' : 'L'}${px(lng).toFixed(1)} ${py(lat).toFixed(1)}`)
    .join(' ')
  const first = sampled[0]
  const last = sampled[sampled.length - 1]
  return {
    d,
    start: [px(first[1]), py(first[0])],
    end: [px(last[1]), py(last[0])],
  }
}

interface RouteThumbnailProps {
  encodedPolyline?: string | null
  /** Sport accent color for the route stroke and the fallback icon. */
  color: string
  size?: number
}

export default function RouteThumbnail({ encodedPolyline, color, size = 88 }: RouteThumbnailProps) {
  const { theme } = useTheme()
  const isLight = theme === 'light'

  const route = useMemo(
    () => (encodedPolyline ? buildRouteShape(encodedPolyline, size) : null),
    [encodedPolyline, size],
  )

  return (
    <div
      className={clsx(
        'shrink-0 rounded-lg border overflow-hidden flex items-center justify-center',
        isLight ? 'bg-gray-50 border-gray-200' : 'bg-surface-700 border-surface-600',
      )}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      {route ? (
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} fill="none">
          <path d={route.d} stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" opacity={0.9} />
          <circle cx={route.start[0]} cy={route.start[1]} r={2.5} fill={isLight ? '#16a34a' : '#4ade80'} />
          <circle cx={route.end[0]} cy={route.end[1]} r={2.5} fill={color} />
        </svg>
      ) : (
        // Sport-neutral "no recorded track" mark — the sport itself is already
        // carried by the card's pill and accent border.
        <svg width={30} height={30} viewBox="0 0 30 30" fill="none" style={{ color, opacity: 0.55 }}>
          <path d="M7 22C11 18 13 12 17 8" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeDasharray="3 3" />
          <circle cx="6.5" cy="22.5" r="2.5" stroke="currentColor" strokeWidth={1.5} />
          <circle cx="18" cy="7" r="2.5" stroke="currentColor" strokeWidth={1.5} />
        </svg>
      )}
    </div>
  )
}

import { MapContainer, TileLayer, Polyline, Marker, Tooltip, CircleMarker, useMap } from 'react-leaflet'
import { useState, useEffect, useMemo } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { LatLngBoundsExpression } from 'leaflet'
import { useTheme } from '../../hooks/useTheme'
import clsx from 'clsx'

function FitBounds({ positions }: { positions: [number, number][] }) {
  const map = useMap()
  useEffect(() => {
    if (positions.length > 0) {
      map.fitBounds(positions as LatLngBoundsExpression, { padding: [30, 30] })
    }
  }, [map, positions])
  return null
}

function InvalidateSize({ expanded }: { expanded: boolean }) {
  const map = useMap()
  useEffect(() => {
    setTimeout(() => {
      map.invalidateSize()
      // Re-fit bounds after resize so the route stays centered
      const container = map.getContainer()
      if (container) map.invalidateSize()
    }, 150)
  }, [map, expanded])
  return null
}

function createStartIcon() {
  return L.divIcon({
    className: '',
    iconSize: [22, 22],
    iconAnchor: [11, 11],
    html: `<svg width="22" height="22" viewBox="0 0 22 22" xmlns="http://www.w3.org/2000/svg">
      <circle cx="11" cy="11" r="10" fill="#16a34a" stroke="#fff" stroke-width="2"/>
      <polygon points="9,6 17,11 9,16" fill="#fff"/>
    </svg>`,
  })
}

function createEndIcon() {
  return L.divIcon({
    className: '',
    iconSize: [22, 22],
    iconAnchor: [11, 11],
    html: `<svg width="22" height="22" viewBox="0 0 22 22" xmlns="http://www.w3.org/2000/svg">
      <circle cx="11" cy="11" r="10" fill="#dc2626" stroke="#fff" stroke-width="2"/>
      <rect x="7" y="7" width="8" height="8" rx="1" fill="#fff"/>
    </svg>`,
  })
}

export interface KmMarker {
  position: [number, number]
  km: number
  tooltip: string // HTML or plain text for tooltip
}

/** Interpolate between two hex colors. t in [0,1] */
function lerpColor(a: string, b: string, t: number): string {
  const parse = (hex: string) => [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ]
  const [r1, g1, b1] = parse(a)
  const [r2, g2, b2] = parse(b)
  const r = Math.round(r1 + (r2 - r1) * t)
  const g = Math.round(g1 + (g2 - g1) * t)
  const bl = Math.round(b1 + (b2 - b1) * t)
  return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${bl.toString(16).padStart(2, '0')}`
}

/** Map a normalized value [0,1] to a green→yellow→red gradient */
function velocityToColor(normalized: number): string {
  const t = Math.max(0, Math.min(1, normalized))
  if (t < 0.5) {
    // green → yellow
    return lerpColor('#22c55e', '#eab308', t * 2)
  }
  // yellow → red
  return lerpColor('#eab308', '#ef4444', (t - 0.5) * 2)
}

interface MapViewProps {
  positions: [number, number][]
  color?: string
  showMarkers?: boolean
  kmMarkers?: KmMarker[]
  /** velocity_smooth values aligned with positions, for gradient coloring */
  velocities?: number[]
  /** If true, slower = green (pace sports). If false, faster = green (speed sports). Default true. */
  invertGradient?: boolean
  /** Formatted fast pace/speed label for legend, e.g. "3:45 min/km" */
  gradientFastLabel?: string
  /** Formatted slow pace/speed label for legend, e.g. "6:20 min/km" */
  gradientSlowLabel?: string
}

export default function MapView({ positions, color = '#fc0101', showMarkers = true, kmMarkers, velocities, invertGradient = true, gradientFastLabel, gradientSlowLabel }: MapViewProps) {
  const { theme, colors } = useTheme()
  const isLight = theme === 'light'
  const [expanded, setExpanded] = useState(false)
  const [gradientMode, setGradientMode] = useState(false)
  const hasVelocities = velocities && velocities.length === positions.length

  const startIcon = useMemo(() => createStartIcon(), [])
  const endIcon = useMemo(() => createEndIcon(), [])

  // Close fullscreen on Escape key
  useEffect(() => {
    if (!expanded) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setExpanded(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expanded])

  // Pre-compute gradient segments
  const gradientSegments = useMemo(() => {
    if (!hasVelocities || !velocities) return []
    // Filter out zero/near-zero velocities for percentile calc
    const valid = velocities.filter(v => v > 0.3)
    if (valid.length === 0) return []
    const sorted = [...valid].sort((a, b) => a - b)
    const p5 = sorted[Math.floor(sorted.length * 0.05)]
    const p95 = sorted[Math.floor(sorted.length * 0.95)]
    const range = p95 - p5
    if (range <= 0) return []

    const segments: { positions: [number, number][]; color: string }[] = []
    // Sample every N points based on total count to keep segment count reasonable
    const step = Math.max(1, Math.floor(positions.length / 800))
    for (let i = 0; i < positions.length - step; i += step) {
      const end = Math.min(i + step, positions.length - 1)
      const vel = velocities[i]
      // Normalize: 0 = slowest, 1 = fastest
      let normalized = vel > 0.3 ? (vel - p5) / range : 0
      normalized = Math.max(0, Math.min(1, normalized))
      // For pace sports (running), invert so slow=red, fast=green
      const colorVal = invertGradient ? 1 - normalized : normalized
      segments.push({
        positions: [positions[i], positions[end]],
        color: velocityToColor(colorVal),
      })
    }
    return segments
  }, [hasVelocities, velocities, positions, invertGradient])

  if (positions.length === 0) return null

  const center = positions[Math.floor(positions.length / 2)]
  const startPos = positions[0]
  const endPos = positions[positions.length - 1]
  const tileUrl = theme === 'light'
    ? 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'
    : 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'

  return (
    <div className={expanded ? 'fixed inset-0 z-50 w-screen h-screen' : 'relative h-full w-full'}>
      <MapContainer
        center={center}
        zoom={13}
        style={{ height: '100%', width: '100%', background: colors.mapBg }}
        zoomControl={false}
      >
        <TileLayer
          attribution='&copy; CartoDB'
          url={tileUrl}
        />
        {gradientMode && gradientSegments.length > 0 ? (
          <>
            {/* Glow layer for gradient */}
            <Polyline
              positions={positions}
              pathOptions={{
                color: '#888',
                weight: 8,
                opacity: 0.1,
              }}
            />
            {gradientSegments.map((seg, i) => (
              <Polyline
                key={i}
                positions={seg.positions}
                pathOptions={{
                  color: seg.color,
                  weight: 3,
                  opacity: 0.9,
                }}
              />
            ))}
          </>
        ) : (
          <>
            <Polyline
              positions={positions}
              pathOptions={{
                color,
                weight: 3,
                opacity: 0.9,
              }}
            />
            {/* Glow layer */}
            <Polyline
              positions={positions}
              pathOptions={{
                color,
                weight: 8,
                opacity: 0.2,
              }}
            />
          </>
        )}
        <FitBounds positions={positions} />
        <InvalidateSize expanded={expanded} />
        {/* Km markers rendered after polylines so they sit on top */}
        {kmMarkers && kmMarkers.map((m) => (
          <CircleMarker
            key={m.km}
            center={m.position}
            radius={4}
            pathOptions={{
              color: isLight ? '#374151' : '#d1d5db',
              fillColor: isLight ? '#fff' : '#1f2937',
              fillOpacity: 0.9,
              weight: 1.5,
            }}
          >
            <Tooltip
              direction="top"
              offset={[0, -8]}
              className="km-marker-tooltip"
            >
              <div dangerouslySetInnerHTML={{ __html: m.tooltip }} />
            </Tooltip>
          </CircleMarker>
        ))}
        {showMarkers && (
          <>
            <Marker position={startPos} icon={startIcon} />
            <Marker position={endPos} icon={endIcon} />
          </>
        )}
      </MapContainer>

      {/* Km marker tooltip styles */}
      <style>{`
        .km-marker-tooltip {
          background: ${isLight ? '#fff' : '#1e293b'} !important;
          border: 1px solid ${isLight ? '#e5e7eb' : '#334155'} !important;
          border-radius: 8px !important;
          padding: 6px 10px !important;
          font-size: 11px !important;
          font-family: ui-monospace, monospace !important;
          color: ${isLight ? '#111827' : '#e5e7eb'} !important;
          box-shadow: 0 4px 12px rgba(0,0,0,0.3) !important;
          line-height: 1.5 !important;
        }
        .km-marker-tooltip::before {
          border-top-color: ${isLight ? '#fff' : '#1e293b'} !important;
        }
      `}</style>

      {/* Map controls */}
      <div className="absolute top-3 right-3 z-[1000] flex flex-col gap-2">
        {/* Gradient toggle */}
        {hasVelocities && (
          <button
            onClick={() => setGradientMode(g => !g)}
            className={clsx(
              'bg-surface-800/90 border rounded-lg p-2 transition-colors backdrop-blur-sm',
              gradientMode
                ? 'border-green-500/50 text-green-400 hover:bg-surface-700'
                : 'border-surface-600 text-gray-400 hover:bg-surface-700',
              isLight ? 'hover:text-gray-900' : 'hover:text-white'
            )}
            title={gradientMode ? 'Switch to solid color' : 'Switch to speed gradient'}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <defs>
                <linearGradient id="speedGrad" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor="#22c55e" />
                  <stop offset="50%" stopColor="#eab308" />
                  <stop offset="100%" stopColor="#ef4444" />
                </linearGradient>
              </defs>
              <rect x="2" y="6" width="12" height="4" rx="2" fill={gradientMode ? 'url(#speedGrad)' : 'currentColor'} opacity={gradientMode ? 1 : 0.5} />
            </svg>
          </button>
        )}

        {/* Fullscreen toggle */}
        <button
          onClick={() => setExpanded(e => !e)}
          className={clsx(
            'bg-surface-800/90 border border-surface-600 rounded-lg p-2 text-gray-400 hover:bg-surface-700 transition-colors backdrop-blur-sm',
            isLight ? 'hover:text-gray-900' : 'hover:text-white'
          )}
          title={expanded ? 'Exit fullscreen (Esc)' : 'Fullscreen'}
        >
          {expanded ? (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M6 2v4H2M10 14v-4h4M14 2l-4 4M2 14l4-4" />
            </svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M2 6V2h4M14 10v4h-4M2 2l4 4M14 14l-4-4" />
            </svg>
          )}
        </button>
      </div>

      {/* Gradient legend */}
      {gradientMode && hasVelocities && (
        <div className="absolute bottom-3 left-3 z-[1000] bg-surface-800/90 border border-surface-600 rounded-lg px-3 py-2 backdrop-blur-sm">
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-green-400 font-medium whitespace-nowrap">
              {invertGradient ? 'Fast' : 'Slow'}
              {(invertGradient ? gradientFastLabel : gradientSlowLabel) && (
                <span className="font-mono opacity-75"> ({invertGradient ? gradientFastLabel : gradientSlowLabel})</span>
              )}
            </span>
            <div className="w-16 h-2 rounded-full shrink-0" style={{ background: 'linear-gradient(to right, #22c55e, #eab308, #ef4444)' }} />
            <span className="text-[10px] text-red-400 font-medium whitespace-nowrap">
              {invertGradient ? 'Slow' : 'Fast'}
              {(invertGradient ? gradientSlowLabel : gradientFastLabel) && (
                <span className="font-mono opacity-75"> ({invertGradient ? gradientSlowLabel : gradientFastLabel})</span>
              )}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

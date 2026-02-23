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

interface MapViewProps {
  positions: [number, number][]
  color?: string
  showMarkers?: boolean
  kmMarkers?: KmMarker[]
}

export default function MapView({ positions, color = '#fc0101', showMarkers = true, kmMarkers }: MapViewProps) {
  const { theme, colors } = useTheme()
  const isLight = theme === 'light'
  const [expanded, setExpanded] = useState(false)

  const startIcon = useMemo(() => createStartIcon(), [])
  const endIcon = useMemo(() => createEndIcon(), [])

  // Close fullscreen on Escape key
  useEffect(() => {
    if (!expanded) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setExpanded(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expanded])

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
        {showMarkers && (
          <>
            <Marker position={startPos} icon={startIcon} />
            <Marker position={endPos} icon={endIcon} />
          </>
        )}
        {/* Km markers */}
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
        <FitBounds positions={positions} />
        <InvalidateSize expanded={expanded} />
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

      {/* Fullscreen toggle */}
      <button
        onClick={() => setExpanded(e => !e)}
        className={clsx(
          'absolute top-3 right-3 z-[1000] bg-surface-800/90 border border-surface-600 rounded-lg p-2 text-gray-400 hover:bg-surface-700 transition-colors backdrop-blur-sm',
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
  )
}

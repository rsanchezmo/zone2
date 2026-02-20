import { MapContainer, TileLayer, Polyline, useMap } from 'react-leaflet'
import { useEffect } from 'react'
import 'leaflet/dist/leaflet.css'
import type { LatLngBoundsExpression } from 'leaflet'
import { useTheme } from '../../hooks/useTheme'

function FitBounds({ positions }: { positions: [number, number][] }) {
  const map = useMap()
  useEffect(() => {
    if (positions.length > 0) {
      map.fitBounds(positions as LatLngBoundsExpression, { padding: [30, 30] })
    }
  }, [map, positions])
  return null
}

interface MapViewProps {
  positions: [number, number][]
  color?: string
}

export default function MapView({ positions, color = '#fc0101' }: MapViewProps) {
  const { theme, colors } = useTheme()
  if (positions.length === 0) return null

  const center = positions[Math.floor(positions.length / 2)]
  const tileUrl = theme === 'light'
    ? 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'
    : 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'

  return (
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
      <FitBounds positions={positions} />
    </MapContainer>
  )
}

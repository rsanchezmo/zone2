import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { usePolylines, useSportTypes, useYears } from '../api/hooks'
import { getSportColor } from '../constants/sportColors'
import { MapContainer, TileLayer, Polyline, useMap } from 'react-leaflet'
import { useEffect } from 'react'
import polyline from '@mapbox/polyline'
import 'leaflet/dist/leaflet.css'
import type { LatLngBoundsExpression } from 'leaflet'
import ExportButton from '../components/shared/ExportButton'
import { useTheme } from '../hooks/useTheme'
import clsx from 'clsx'

function FitAll({ bounds }: { bounds: [number, number][] }) {
  const map = useMap()
  useEffect(() => {
    if (bounds.length > 0) {
      map.fitBounds(bounds as LatLngBoundsExpression, { padding: [30, 30] })
    }
  }, [map, bounds])
  return null
}

function InvalidateSize({ expanded }: { expanded: boolean }) {
  const map = useMap()
  useEffect(() => {
    setTimeout(() => map.invalidateSize(), 100)
  }, [map, expanded])
  return null
}

interface DecodedActivity {
  id: number | string
  sport_type: string
  name: string
  positions: [number, number][]
}

export default function AggregationsPage() {
  const { theme, colors } = useTheme()
  const isLight = theme === 'light'
  const { data: sportTypes } = useSportTypes()
  const { data: years } = useYears()
  const [sport, setSport] = useState<string>('')
  const [year, setYear] = useState<string>('')
  const [heatmapCity, setHeatmapCity] = useState('')
  const [expanded, setExpanded] = useState(false)
  const navigate = useNavigate()

  const { data: rawPolylines, isLoading } = usePolylines(
    sport || undefined,
    year ? Number(year) : undefined,
  )

  const activities: DecodedActivity[] = useMemo(() => {
    if (!rawPolylines) return []
    return rawPolylines
      .map((a: { id: number | string; sport_type: string; name: string; polyline: string }) => {
        try {
          const decoded = polyline.decode(a.polyline)
          if (decoded.length === 0) return null
          return {
            id: a.id,
            sport_type: a.sport_type,
            name: a.name,
            positions: decoded as [number, number][],
          }
        } catch {
          return null
        }
      })
      .filter(Boolean) as DecodedActivity[]
  }, [rawPolylines])

  // Compute bounds from all positions
  const allBounds = useMemo(() => {
    const pts: [number, number][] = []
    for (const a of activities) {
      if (a.positions.length > 0) {
        pts.push(a.positions[0])
        pts.push(a.positions[a.positions.length - 1])
      }
    }
    return pts
  }, [activities])

  // Build heatmap export URL with all active filters
  const heatmapUrl = useMemo(() => {
    const params = new URLSearchParams()
    if (heatmapCity) params.set('location', heatmapCity)
    if (sport) params.set('sport_types', sport)
    if (year) params.set('year', year)
    return `/api/exports/thunderstorm-heatmap?${params.toString()}`
  }, [heatmapCity, sport, year])

  return (
    <div className={expanded ? '' : 'max-w-6xl mx-auto'}>
      {/* Map */}
      <div className={expanded
        ? 'fixed inset-0 z-50 w-screen h-screen'
        : 'relative h-[calc(100vh-6rem)] rounded-xl overflow-hidden border border-surface-600'
      }>
        {isLoading ? (
          <div className="flex items-center justify-center h-full text-gray-500 bg-surface-900">Loading routes...</div>
        ) : activities.length === 0 ? (
          <div className="flex items-center justify-center h-full text-gray-500 bg-surface-900">No routes found</div>
        ) : (
          <MapContainer
            center={[0, 0]}
            zoom={2}
            style={{ height: '100%', width: '100%', background: colors.mapBg }}
            zoomControl={false}
          >
            <TileLayer
              attribution='&copy; CartoDB'
              url={theme === 'light'
                ? 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'
                : 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'}
            />
            {activities.map(a => {
              const color = getSportColor(a.sport_type)
              return (
                <Polyline
                  key={String(a.id)}
                  positions={a.positions}
                  pathOptions={{ color, weight: 2, opacity: 0.6 }}
                  eventHandlers={{
                    click: () => navigate(`/activities/${a.id}`),
                    mouseover: (e) => {
                      e.target.setStyle({ weight: 4, opacity: 1 })
                      e.target.bindTooltip(`${a.sport_type}: ${a.name}`, { sticky: true }).openTooltip()
                    },
                    mouseout: (e) => {
                      e.target.setStyle({ weight: 2, opacity: 0.6 })
                      e.target.closeTooltip()
                    },
                  }}
                />
              )
            })}
            <FitAll bounds={allBounds} />
            <InvalidateSize expanded={expanded} />
          </MapContainer>
        )}

        {/* Controls overlay — top left */}
        <div className="absolute top-3 left-3 z-[1000] flex items-center gap-2 flex-wrap">
          <select
            value={sport}
            onChange={e => setSport(e.target.value)}
            className="bg-surface-800/90 border border-surface-600 rounded px-2 py-1 text-sm backdrop-blur-sm"
          >
            <option value="">All Sports</option>
            {(sportTypes ?? []).map((s: string) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <select
            value={year}
            onChange={e => setYear(e.target.value)}
            className="bg-surface-800/90 border border-surface-600 rounded px-2 py-1 text-sm backdrop-blur-sm"
          >
            <option value="">All Years</option>
            {(years ?? []).map((y: number) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
          <span className="text-xs text-gray-400 bg-surface-800/90 border border-surface-600 rounded px-2 py-1 backdrop-blur-sm">
            {activities.length} routes
          </span>
        </div>

        {/* Heatmap export overlay — bottom left */}
        <div className="absolute bottom-3 left-3 z-[1000] flex items-center gap-2">
          <input
            placeholder="City (e.g. Paris)"
            value={heatmapCity}
            onChange={e => setHeatmapCity(e.target.value)}
            className="bg-surface-800/90 border border-surface-600 rounded px-2 py-1 text-sm backdrop-blur-sm w-40"
          />
          <ExportButton
            url={heatmapUrl}
            label="Export Heatmap"
            filename={`heatmap_${heatmapCity || 'all'}.png`}
          />
        </div>

        {/* Fullscreen toggle — top right */}
        <button
          onClick={() => setExpanded(e => !e)}
          className={clsx(
            'absolute top-3 right-3 z-[1000] bg-surface-800/90 border border-surface-600 rounded-lg p-2 text-gray-400 hover:bg-surface-700 transition-colors backdrop-blur-sm',
            isLight ? 'hover:text-gray-900' : 'hover:text-white'
          )}
          title={expanded ? 'Exit fullscreen' : 'Fullscreen'}
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
    </div>
  )
}

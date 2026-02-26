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

  const overlayClass = clsx(
    'rounded-lg border backdrop-blur-md',
    isLight
      ? 'bg-white/85 border-gray-200/80 shadow-sm'
      : 'bg-surface-800/85 border-surface-600/80',
  )

  const selectClass = clsx(
    'border rounded px-1.5 py-1 text-xs transition-colors appearance-none cursor-pointer',
    isLight
      ? 'bg-white/90 border-gray-200 text-gray-700'
      : 'bg-surface-700/90 border-surface-600 text-gray-300',
  )

  return (
    <div className={expanded ? '' : 'max-w-6xl mx-auto'}>
      {/* Map */}
      <div className={expanded
        ? 'fixed inset-0 z-50 w-screen h-screen'
        : clsx('relative h-[calc(100vh-3rem)] rounded-xl overflow-hidden border', isLight ? 'border-gray-200' : 'border-surface-600')
      }>
        {isLoading ? (
          <div className={clsx('flex flex-col items-center justify-center h-full gap-3', isLight ? 'bg-gray-50' : 'bg-surface-900')}>
            <svg className="w-8 h-8 text-gray-500 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <span className="text-sm text-gray-500">Loading routes...</span>
          </div>
        ) : activities.length === 0 ? (
          <div className={clsx('flex flex-col items-center justify-center h-full gap-2', isLight ? 'bg-gray-50' : 'bg-surface-900')}>
            <svg className="w-12 h-12 text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 6.75V15m6-6v8.25m.503 3.498l4.875-2.437c.381-.19.622-.58.622-1.006V4.82c0-.836-.88-1.38-1.628-1.006l-3.869 1.934c-.317.159-.69.159-1.006 0L9.503 3.252a1.125 1.125 0 00-1.006 0L3.622 5.689C3.24 5.88 3 6.27 3 6.695V19.18c0 .836.88 1.38 1.628 1.006l3.869-1.934c.317-.159.69-.159 1.006 0l4.994 2.497c.317.158.69.158 1.006 0z" />
            </svg>
            <p className="text-sm text-gray-500">No routes found</p>
            <p className="text-xs text-gray-600">Try adjusting your filters</p>
          </div>
        ) : (
          <MapContainer
            center={[0, 0]}
            zoom={2}
            style={{ height: '100%', width: '100%', background: colors.mapBg }}
            zoomControl={false}
          >
            <TileLayer
              attribution='&copy; CartoDB'
              url={isLight
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
        <div className={clsx('absolute top-3 left-3 z-[1000]', overlayClass, 'px-2 py-1.5 flex items-center gap-1.5')}>
          <select value={sport} onChange={e => setSport(e.target.value)} className={selectClass}>
            <option value="">All Sports</option>
            {(sportTypes ?? []).map((s: string) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <select value={year} onChange={e => setYear(e.target.value)} className={selectClass}>
            <option value="">All Years</option>
            {(years ?? []).map((y: number) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
          <span className={clsx('text-xs font-mono tabular-nums', isLight ? 'text-gray-500' : 'text-gray-400')}>
            {activities.length} routes
          </span>
        </div>

        {/* Heatmap export overlay — bottom left */}
        <div className={clsx('absolute bottom-3 left-3 z-[1000]', overlayClass, 'p-2 flex items-center gap-2')}>
          <svg className={clsx('w-4 h-4 shrink-0', isLight ? 'text-gray-400' : 'text-gray-500')} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
          <input
            placeholder="City (e.g. Paris)"
            value={heatmapCity}
            onChange={e => setHeatmapCity(e.target.value)}
            className={clsx(
              'border rounded px-2 py-1 text-sm w-36 placeholder-gray-500 focus:outline-none',
              isLight
                ? 'bg-white/90 border-gray-200 focus:border-gray-300'
                : 'bg-surface-700/90 border-surface-600 focus:border-surface-500',
            )}
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
            'absolute top-3 right-3 z-[1000] rounded-lg p-2 transition-colors',
            overlayClass,
            isLight ? 'text-gray-500 hover:text-gray-900' : 'text-gray-400 hover:text-white'
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

import { useState, useMemo, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { usePolylines, useSportTypes, useYears, useGeocodeCity, type GeocodeResult } from '../api/hooks'
import { getSportColor } from '../constants/sportColors'
import { MapContainer, TileLayer, Polyline, useMap } from 'react-leaflet'
import polyline from '@mapbox/polyline'
import 'leaflet/dist/leaflet.css'
import type { LatLngBoundsExpression } from 'leaflet'
import ExportButton from '../components/shared/ExportButton'
import { useTheme } from '../hooks/useTheme'
import clsx from 'clsx'
import { InvalidateSize } from '../components/shared/leafletHelpers'
import { FullscreenIcon } from '../components/shared/mapChrome'
import { tileLayerUrl } from '../utils/mapTiles'
import { useExitFullscreenOnEscape } from '../hooks/useExitFullscreenOnEscape'
import { MapStyleToggle, SATELLITE_ATTR, SATELLITE_TILES, type MapStyle } from '../components/shared/MapStyleToggle'

/** Fit the map once per distinct route set, so filter changes refit. */
function FitAll({ bounds, signature }: { bounds: [number, number][]; signature: string }) {
  const map = useMap()
  const fittedFor = useRef<string | null>(null)
  useEffect(() => {
    if (bounds.length === 0 || fittedFor.current === signature) return
    fittedFor.current = signature
    map.fitBounds(bounds as LatLngBoundsExpression, { padding: [30, 30] })
  }, [map, bounds, signature])
  return null
}

function FlyToCity({ target }: { target: GeocodeResult['bbox'] | null }) {
  const map = useMap()
  useEffect(() => {
    if (target) {
      map.flyToBounds(
        [[target.south, target.west], [target.north, target.east]],
        { padding: [30, 30], duration: 1.5 }
      )
    }
  }, [map, target])
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
  const [flyTarget, setFlyTarget] = useState<GeocodeResult['bbox'] | null>(null)
  const geocodeMutation = useGeocodeCity()
  const [expanded, setExpanded] = useState(false)
  const [mapStyle, setMapStyle] = useState<MapStyle>('street')
  const navigate = useNavigate()

  useExitFullscreenOnEscape(expanded, () => setExpanded(false))

  const tileUrl = mapStyle === 'satellite' ? SATELLITE_TILES : tileLayerUrl(isLight)

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

  // Bounding corners over every route point — endpoints alone collapse loops.
  const allBounds = useMemo<[number, number][]>(() => {
    let south = Infinity
    let west = Infinity
    let north = -Infinity
    let east = -Infinity
    for (const a of activities) {
      for (const [lat, lng] of a.positions) {
        if (lat < south) south = lat
        if (lat > north) north = lat
        if (lng < west) west = lng
        if (lng > east) east = lng
      }
    }
    if (south === Infinity) return []
    return [[south, west], [north, east]]
  }, [activities])

  const routesSignature = useMemo(
    () => `${activities.length}:${activities[0]?.id ?? ''}:${activities[activities.length - 1]?.id ?? ''}`,
    [activities],
  )

  const heatmapUrl = useMemo(() => {
    const params = new URLSearchParams()
    if (heatmapCity) params.set('location', heatmapCity)
    if (sport) params.set('sport_types', sport)
    if (year) params.set('year', year)
    return `/api/exports/thunderstorm-heatmap?${params.toString()}`
  }, [heatmapCity, sport, year])

  const handleGoToCity = () => {
    if (!heatmapCity.trim()) return
    geocodeMutation.mutate(heatmapCity, {
      onSuccess: (result) => setFlyTarget(result.bbox),
    })
  }

  const overlayClass = clsx(
    'rounded-lg border backdrop-blur-md',
    isLight ? 'bg-white/85 border-gray-200/80 shadow-sm' : 'bg-surface-800/85 border-surface-600/80',
  )
  const selectClass = 'select !text-xs !py-1 !px-1.5'

  // Compute sport breakdown for the overlay badge (top N)
  const sportBreakdown = useMemo(() => {
    const counts = new Map<string, number>()
    for (const a of activities) counts.set(a.sport_type, (counts.get(a.sport_type) ?? 0) + 1)
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 4)
  }, [activities])

  return (
    <div className={expanded ? '' : 'max-w-6xl mx-auto space-y-6 pb-6'}>
      {/* ── Breadcrumb header (hidden in fullscreen) ──── */}
      {!expanded && (
        <header className="flex items-baseline gap-2 flex-wrap">
          <span className="eyebrow">Aggregations</span>
          <span className={clsx('text-[11px]', isLight ? 'text-gray-300' : 'text-gray-700')}>·</span>
          <span className="text-[11px] text-gray-500 normal-case tracking-normal">every route you've recorded, on one map</span>
        </header>
      )}

      {/* ── Map ────────────────────────────────────── */}
      <div
        className={expanded
          ? 'fixed inset-0 z-50 w-screen h-screen'
          : clsx('relative h-[calc(100vh-8rem)] rounded-xl overflow-hidden border', isLight ? 'border-gray-200' : 'border-surface-600')}
      >
        {isLoading ? (
          <div className={clsx('flex flex-col items-center justify-center h-full gap-3', isLight ? 'bg-gray-50' : 'bg-surface-900')}>
            <svg className="w-8 h-8 text-gray-500 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <span className="eyebrow">Loading routes</span>
          </div>
        ) : activities.length === 0 ? (
          <div className={clsx('flex flex-col items-center justify-center h-full gap-3', isLight ? 'bg-gray-50' : 'bg-surface-900')}>
            <svg className={clsx('w-10 h-10', isLight ? 'text-gray-300' : 'text-gray-600')} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 6.75V15m6-6v8.25m.503 3.498l4.875-2.437c.381-.19.622-.58.622-1.006V4.82c0-.836-.88-1.38-1.628-1.006l-3.869 1.934c-.317.159-.69.159-1.006 0L9.503 3.252a1.125 1.125 0 00-1.006 0L3.622 5.689C3.24 5.88 3 6.27 3 6.695V19.18c0 .836.88 1.38 1.628 1.006l3.869-1.934c.317-.159.69-.159 1.006 0l4.994 2.497c.317.158.69.158 1.006 0z" />
            </svg>
            <p className={clsx('text-sm', isLight ? 'text-gray-500' : 'text-gray-500')}>No routes found</p>
            <p className={clsx('text-[11px]', isLight ? 'text-gray-400' : 'text-gray-600')}>Try adjusting your filters</p>
          </div>
        ) : (
          <MapContainer
            center={[0, 0]}
            zoom={2}
            preferCanvas
            style={{ height: '100%', width: '100%', background: colors.mapBg }}
            zoomControl={false}
          >
            <TileLayer
              key={tileUrl}
              attribution={mapStyle === 'satellite' ? SATELLITE_ATTR : '&copy; CartoDB'}
              url={tileUrl}
              className={mapStyle === 'satellite' ? 'satellite-tiles' : undefined}
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
                    mouseover: e => {
                      e.target.setStyle({ weight: 4, opacity: 1 })
                      e.target.bindTooltip(`${a.sport_type}: ${a.name}`, { sticky: true }).openTooltip()
                    },
                    mouseout: e => {
                      e.target.setStyle({ weight: 2, opacity: 0.6 })
                      e.target.closeTooltip()
                    },
                  }}
                />
              )
            })}
            <FitAll bounds={allBounds} signature={routesSignature} />
            <FlyToCity target={flyTarget} />
            <InvalidateSize expanded={expanded} />
          </MapContainer>
        )}

        {/* ── Filter overlay — top left ────────────── */}
        <div className={clsx('absolute top-3 left-3 z-[1000] px-3 py-2 flex items-center gap-3', overlayClass)}>
          <div className="flex flex-col gap-0.5">
            <span className="eyebrow text-[9px]">Sport</span>
            <select value={sport} onChange={e => setSport(e.target.value)} className={selectClass} aria-label="Sport">
              <option value="">All</option>
              {(sportTypes ?? []).map((s: string) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="eyebrow text-[9px]">Year</span>
            <select value={year} onChange={e => setYear(e.target.value)} className={selectClass} aria-label="Year">
              <option value="">All</option>
              {(years ?? []).map((y: number) => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>
          </div>
          <div className={clsx('w-px h-8 self-center', isLight ? 'bg-gray-200' : 'bg-surface-600')} aria-hidden="true" />
          <div className="flex flex-col gap-0.5">
            <span className="eyebrow text-[9px]">Routes</span>
            <span className={clsx('text-sm font-mono tabular-nums font-semibold', isLight ? 'text-gray-900' : 'text-gray-100')}>
              {activities.length.toLocaleString()}
            </span>
          </div>
        </div>

        {/* ── Sport breakdown overlay — top right (only when we have enough data) ── */}
        {sportBreakdown.length > 1 && (
          <div className={clsx('absolute top-3 right-[3.5rem] z-[1000] px-3 py-2 hidden md:flex items-center gap-3', overlayClass)}>
            {sportBreakdown.map(([name, count]) => (
              <div key={name} className="flex items-center gap-1.5">
                <span
                  className="w-1.5 h-1.5 rounded-full"
                  style={{ backgroundColor: getSportColor(name) }}
                  aria-hidden="true"
                />
                <span className={clsx('text-[10px] uppercase tracking-[0.1em]', isLight ? 'text-gray-600' : 'text-gray-400')}>{name}</span>
                <span className="text-[10px] font-mono tabular-nums text-gray-500">{count}</span>
              </div>
            ))}
          </div>
        )}

        {/* ── Heatmap export overlay — bottom left ── */}
        <div className={clsx('absolute bottom-3 left-3 z-[1000] p-2.5 flex items-center gap-2 flex-wrap', overlayClass)}>
          <div className="flex items-center gap-1.5">
            <svg className={clsx('w-3.5 h-3.5 shrink-0', isLight ? 'text-gray-400' : 'text-gray-500')} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            <span className="eyebrow text-[9px]">Heatmap</span>
          </div>
          <input
            placeholder="City (e.g. Paris)"
            value={heatmapCity}
            onChange={e => setHeatmapCity(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleGoToCity() }}
            className="input !py-1 !px-2 !text-xs w-40"
          />
          <button
            onClick={handleGoToCity}
            disabled={!heatmapCity.trim() || geocodeMutation.isPending}
            className="btn !text-[11px] !py-1 !px-2.5"
            title="Zoom map to this city"
          >
            {geocodeMutation.isPending ? '…' : 'Go'}
          </button>
          <ExportButton
            url={heatmapUrl}
            label="PNG"
            filename={`heatmap_${heatmapCity || 'all'}.png`}
            exportType="thunderstorm-heatmap"
          />
        </div>

        {/* ── Map controls — top right ─────────────── */}
        <div className="absolute top-3 right-3 z-[1000] flex flex-col gap-2">
          <button
            onClick={() => setExpanded(e => !e)}
            className={clsx(
              'rounded-lg p-2 transition-colors',
              overlayClass,
              isLight ? 'text-gray-500 hover:text-gray-900' : 'text-gray-400 hover:text-gray-100',
            )}
            title={expanded ? 'Exit fullscreen' : 'Fullscreen'}
            aria-label={expanded ? 'Exit fullscreen' : 'Enter fullscreen'}
          >
            <FullscreenIcon expanded={expanded} />
          </button>
          <MapStyleToggle
            mapStyle={mapStyle}
            onToggle={() => setMapStyle(s => (s === 'satellite' ? 'street' : 'satellite'))}
            className={clsx(
              'rounded-lg p-2 transition-colors',
              overlayClass,
              isLight ? 'text-gray-500 hover:text-gray-900' : 'text-gray-400 hover:text-gray-100',
            )}
          />
        </div>
      </div>
    </div>
  )
}

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { MapContainer, TileLayer, GeoJSON, Rectangle, useMap, useMapEvents } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import clsx from 'clsx'
import { useQueryClient } from '@tanstack/react-query'
import {
  useCoverageCities, useCoverageEdges, useCoverageDistricts, useCoverageArea,
  useCoverageSyncStatus, useTriggerCoverageSync, useUncoveredEdges,
  type AreaCoverage, type DistrictCoverage,
} from '../api/hooks'
import { useTheme } from '../hooks/useTheme'
import { MapStyleToggle, SATELLITE_ACCENT, SATELLITE_ATTR, SATELLITE_TILES, type MapStyle } from '../components/shared/MapStyleToggle'

const COVERED_ACCENT = '#fb2c36'

function FitToLayer({ data }: { data: unknown }) {
  const map = useMap()
  const fitted = useRef(false)
  useEffect(() => {
    if (!data || fitted.current) return
    const layer = L.geoJSON(data as GeoJSON.GeoJsonObject)
    const bounds = layer.getBounds()
    if (bounds.isValid()) {
      map.fitBounds(bounds, { padding: [30, 30] })
      fitted.current = true
    }
  }, [map, data])
  return null
}

function FlyToBbox({ bbox }: { bbox: [number, number, number, number] | null }) {
  const map = useMap()
  useEffect(() => {
    if (!bbox) return
    map.flyToBounds([[bbox[0], bbox[1]], [bbox[2], bbox[3]]], { padding: [30, 30], duration: 1.0 })
  }, [map, bbox])
  return null
}

/** Report the viewport bbox (south,west,north,east) when zoomed in enough for
 *  the uncovered-streets layer; payloads at city zoom would be the whole map. */
const MISSING_MIN_ZOOM = 14

function ViewportTracker({ onChange }: { onChange: (bbox: string | undefined) => void }) {
  const map = useMap()
  const report = useCallback(() => {
    if (map.getZoom() < MISSING_MIN_ZOOM) {
      onChange(undefined)
      return
    }
    const b = map.getBounds()
    const r = (x: number) => x.toFixed(4)
    onChange(`${r(b.getSouth())},${r(b.getWest())},${r(b.getNorth())},${r(b.getEast())}`)
  }, [map, onChange])
  useMapEvents({ moveend: report, zoomend: report })
  useEffect(report, [report])
  return null
}

function InvalidateSize({ expanded }: { expanded: boolean }) {
  const map = useMap()
  useEffect(() => {
    const id = setTimeout(() => map.invalidateSize(), 100)
    return () => clearTimeout(id)
  }, [map, expanded])
  return null
}

/** Drag-a-rectangle selection. While active, map dragging is disabled and a
 *  mousedown→mouseup drag defines the area; the callback gets its corners. */
function AreaSelect({
  active,
  onSelect,
}: {
  active: boolean
  onSelect: (bounds: L.LatLngBounds) => void
}) {
  const [rect, setRect] = useState<L.LatLngBounds | null>(null)
  const startRef = useRef<L.LatLng | null>(null)
  const map = useMap()

  useEffect(() => {
    if (active) map.dragging.disable()
    else map.dragging.enable()
    startRef.current = null
    return () => { map.dragging.enable() }
  }, [active, map])

  useMapEvents({
    mousedown(e) {
      if (!active) return
      startRef.current = e.latlng
      setRect(L.latLngBounds(e.latlng, e.latlng))
    },
    mousemove(e) {
      if (!active || !startRef.current) return
      setRect(L.latLngBounds(startRef.current, e.latlng))
    },
    mouseup(e) {
      if (!active || !startRef.current) return
      const bounds = L.latLngBounds(startRef.current, e.latlng)
      startRef.current = null
      setRect(null)
      if (bounds.getSouthWest().distanceTo(bounds.getNorthEast()) > 50) {
        onSelect(bounds)
      }
    },
  })

  if (active && rect) {
    return <Rectangle bounds={rect} pathOptions={{ color: '#22d3ee', weight: 1.5, dashArray: '4 4', fillOpacity: 0.08 }} />
  }
  return null
}

export default function CoveragePage() {
  const { theme, colors } = useTheme()
  const isLight = theme === 'light'
  const qc = useQueryClient()

  const { data: cities, isLoading: citiesLoading } = useCoverageCities()
  const [slug, setSlug] = useState<string | undefined>(undefined)
  const activeSlug = slug ?? cities?.[0]?.slug
  const city = cities?.find(c => c.slug === activeSlug)

  const { data: edges, isLoading: edgesLoading } = useCoverageEdges(activeSlug)
  const [adminLevel, setAdminLevel] = useState(9)
  const { data: districts } = useCoverageDistricts(activeSlug, adminLevel)
  const [showDistricts, setShowDistricts] = useState(true)
  const [flyBbox, setFlyBbox] = useState<[number, number, number, number] | null>(null)

  const [expanded, setExpanded] = useState(false)
  const [mapStyle, setMapStyle] = useState<MapStyle>('street')
  const [selectMode, setSelectMode] = useState(false)
  const [areaRect, setAreaRect] = useState<L.LatLngBounds | null>(null)
  const [areaStats, setAreaStats] = useState<AreaCoverage | null>(null)
  const areaMutation = useCoverageArea(activeSlug)

  const [showMissing, setShowMissing] = useState(false)
  const [viewportBbox, setViewportBbox] = useState<string | undefined>(undefined)
  const { data: uncovered } = useUncoveredEdges(activeSlug, showMissing ? viewportBbox : undefined)

  const syncMutation = useTriggerCoverageSync(activeSlug)
  const { data: syncStatus } = useCoverageSyncStatus(activeSlug, syncMutation.isSuccess)
  const syncRunning = !!syncStatus?.running
  const prevRunning = useRef(false)
  useEffect(() => {
    if (prevRunning.current && !syncRunning) {
      qc.invalidateQueries({ queryKey: ['coverage-cities'] })
      qc.invalidateQueries({ queryKey: ['coverage-edges'] })
      qc.invalidateQueries({ queryKey: ['coverage-districts'] })
    }
    prevRunning.current = syncRunning
  }, [syncRunning, qc])

  // Close fullscreen on Escape
  useEffect(() => {
    if (!expanded) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setExpanded(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expanded])

  const accent = mapStyle === 'satellite' ? SATELLITE_ACCENT : COVERED_ACCENT
  const tileUrl = mapStyle === 'satellite'
    ? SATELLITE_TILES
    : isLight
      ? 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'
      : 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'

  const overlayClass = clsx(
    'rounded-lg border backdrop-blur-md',
    isLight ? 'bg-white/85 border-gray-200/80 shadow-sm' : 'bg-surface-800/85 border-surface-600/80',
  )
  const buttonClass = clsx(
    'rounded-lg p-2 transition-colors',
    overlayClass,
    isLight ? 'text-gray-500 hover:text-gray-900' : 'text-gray-400 hover:text-gray-100',
  )

  const handleAreaSelect = (bounds: L.LatLngBounds) => {
    setAreaRect(bounds)
    setSelectMode(false)
    const sw = bounds.getSouthWest()
    const ne = bounds.getNorthEast()
    const points: [number, number][] = [
      [sw.lat, sw.lng], [sw.lat, ne.lng], [ne.lat, ne.lng], [ne.lat, sw.lng],
    ]
    areaMutation.mutate(points, { onSuccess: setAreaStats })
  }

  const clearArea = () => {
    setAreaRect(null)
    setAreaStats(null)
  }

  const edgesKey = useMemo(
    () => `${activeSlug}-${(edges as { features?: unknown[] } | undefined)?.features?.length ?? 0}-${accent}`,
    [activeSlug, edges, accent],
  )

  if (!citiesLoading && (cities?.length ?? 0) === 0) {
    return (
      <div className="max-w-6xl mx-auto pb-6 space-y-4">
        <header className="flex items-baseline gap-2">
          <span className="eyebrow">Coverage</span>
        </header>
        <div className={clsx('panel p-10 text-center text-sm', isLight ? 'text-gray-500' : 'text-gray-400')}>
          No coverage maps yet. Build one with <code className="font-mono text-xs">StravaMapMatcher(city_name=..., workdir=...)</code> — it downloads and stores the runnable street network, then sync your activities here.
        </div>
      </div>
    )
  }

  return (
    <div className={expanded ? '' : 'max-w-6xl mx-auto space-y-6 pb-6'}>
      {!expanded && (
        <header className="flex items-baseline gap-2 flex-wrap">
          <span className="eyebrow">Coverage</span>
          <span className={clsx('text-[11px]', isLight ? 'text-gray-300' : 'text-gray-700')}>·</span>
          <span className="text-[11px] text-gray-500 normal-case tracking-normal">every street you've conquered — and the ones you haven't</span>
        </header>
      )}

      <div
        className={expanded
          ? 'fixed inset-0 z-50 w-screen h-screen'
          : clsx('relative h-[calc(100vh-8rem)] rounded-xl overflow-hidden border', isLight ? 'border-gray-200' : 'border-surface-600')}
      >
        <MapContainer
          center={[0, 0]}
          zoom={12}
          preferCanvas
          zoomControl={false}
          style={{ height: '100%', width: '100%', background: colors.mapBg, cursor: selectMode ? 'crosshair' : undefined }}
        >
          <TileLayer
            key={tileUrl}
            attribution={mapStyle === 'satellite' ? SATELLITE_ATTR : '&copy; CartoDB'}
            url={tileUrl}
            className={mapStyle === 'satellite' ? 'satellite-tiles' : undefined}
          />
          {showMissing && uncovered && viewportBbox && (
            <GeoJSON
              key={`missing-${activeSlug}-${viewportBbox}`}
              data={uncovered}
              style={{
                color: mapStyle === 'satellite' ? '#cbd5e1' : isLight ? '#94a3b8' : '#64748b',
                weight: 1.2,
                opacity: 0.55,
                dashArray: '3 4',
              }}
            />
          )}
          {edges && (
            <>
              {/* Glow underlay + bright core */}
              <GeoJSON key={`${edgesKey}-glow`} data={edges} style={{ color: accent, weight: 5, opacity: 0.18 }} />
              <GeoJSON key={`${edgesKey}-core`} data={edges} style={{ color: accent, weight: 1.6, opacity: 0.95 }} />
              <FitToLayer data={edges} />
            </>
          )}
          <ViewportTracker onChange={setViewportBbox} />
          {areaRect && (
            <Rectangle bounds={areaRect} pathOptions={{ color: '#22d3ee', weight: 1.5, fillOpacity: 0.06 }} />
          )}
          <AreaSelect active={selectMode} onSelect={handleAreaSelect} />
          <FlyToBbox bbox={flyBbox} />
          <InvalidateSize expanded={expanded} />
        </MapContainer>

        {/* ── Summary overlay — top left ───────────── */}
        <div className={clsx('absolute top-3 left-3 z-[1000] px-3 py-2 flex items-center gap-3 flex-wrap max-w-[calc(100%-8rem)]', overlayClass)}>
          {(cities?.length ?? 0) > 1 && (
            <select
              value={activeSlug}
              onChange={e => { setSlug(e.target.value); clearArea() }}
              className="select !text-xs !py-1 !px-1.5"
              aria-label="City"
            >
              {cities?.map(c => <option key={c.slug} value={c.slug}>{c.city_name}</option>)}
            </select>
          )}
          {(cities?.length ?? 0) === 1 && (
            <span className={clsx('text-xs font-semibold', isLight ? 'text-gray-900' : 'text-gray-100')}>{city?.city_name}</span>
          )}
          <div className="flex flex-col gap-0.5">
            <span className="eyebrow text-[9px]">Covered</span>
            <span className={clsx('text-sm font-mono tabular-nums font-semibold', isLight ? 'text-gray-900' : 'text-gray-100')}>
              {city?.traversed_km.toLocaleString(undefined, { maximumFractionDigits: 0 })}
              <span className="text-[10px] text-gray-500"> / {city?.total_network_km.toLocaleString(undefined, { maximumFractionDigits: 0 })} km</span>
            </span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="eyebrow text-[9px]">City</span>
            <span className="text-sm font-mono tabular-nums font-semibold" style={{ color: COVERED_ACCENT }}>
              {city?.coverage_pct}%
            </span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="eyebrow text-[9px]">Streets</span>
            <span className={clsx('text-sm font-mono tabular-nums font-semibold', isLight ? 'text-gray-900' : 'text-gray-100')}>
              {city?.num_unique_streets.toLocaleString()}
            </span>
          </div>
          <button
            onClick={() => syncMutation.mutate()}
            disabled={syncRunning}
            className="btn !text-[11px] !py-1 !px-2.5"
            title="Match new activities against this city"
          >
            {syncRunning ? 'Matching…' : 'Sync'}
          </button>
        </div>

        {/* ── Controls — top right ─────────────────── */}
        <div className="absolute top-3 right-3 z-[1000] flex flex-col gap-2">
          <button
            onClick={() => setExpanded(e => !e)}
            className={buttonClass}
            title={expanded ? 'Exit fullscreen' : 'Fullscreen'}
            aria-label={expanded ? 'Exit fullscreen' : 'Enter fullscreen'}
          >
            {expanded ? (
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M6 2v4H2M10 14v-4h4M14 2l-4 4M2 14l4-4" />
              </svg>
            ) : (
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M2 6V2h4M14 10v4h-4M2 2l4 4M14 14l-4-4" />
              </svg>
            )}
          </button>
          <MapStyleToggle
            mapStyle={mapStyle}
            onToggle={() => setMapStyle(s => (s === 'satellite' ? 'street' : 'satellite'))}
            className={buttonClass}
          />
          <button
            onClick={() => { setSelectMode(m => !m); if (areaRect) clearArea() }}
            className={clsx(buttonClass, selectMode && '!text-cyan-400 !border-cyan-500/50')}
            title={selectMode ? 'Cancel area selection' : 'Select an area to compute coverage'}
            aria-label="Select area"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <rect x="3" y="3" width="10" height="10" rx="1" strokeDasharray="3 2" />
              <path d="M8 6v4M6 8h4" />
            </svg>
          </button>
          <button
            onClick={() => setShowMissing(m => !m)}
            className={clsx(buttonClass, showMissing && '!text-slate-300 !border-slate-400/50')}
            title={showMissing ? 'Hide missing streets' : 'Show missing streets (zoom in)'}
            aria-label="Toggle missing streets"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M2 12c2-6 4 2 6-4s4 2 6-4" strokeDasharray="2.5 2" />
            </svg>
          </button>
          <button
            onClick={() => setShowDistricts(s => !s)}
            className={clsx(buttonClass, showDistricts && (isLight ? '!text-gray-900' : '!text-gray-100'))}
            title={showDistricts ? 'Hide districts' : 'Show districts'}
            aria-label="Toggle district panel"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M2 3h12M2 8h12M2 13h8" />
            </svg>
          </button>
        </div>

        {/* ── Districts panel — right ──────────────── */}
        {showDistricts && (districts?.length ?? 0) > 0 && (
          <div className={clsx('absolute top-[13rem] md:top-16 right-3 bottom-3 z-[1000] w-60 flex flex-col overflow-hidden', overlayClass)}>
            <div className="flex items-center justify-between px-3 pt-2.5 pb-1.5">
              <span className="eyebrow text-[9px]">By district</span>
              <div className="flex gap-1">
                {[[9, 'Districts'], [10, 'Barrios']].map(([lvl, label]) => (
                  <button
                    key={lvl}
                    onClick={() => setAdminLevel(lvl as number)}
                    className={clsx(
                      'text-[9px] uppercase tracking-[0.1em] px-1.5 py-0.5 rounded border transition-colors',
                      adminLevel === lvl
                        ? 'border-current text-cyan-400'
                        : isLight ? 'border-gray-200 text-gray-400 hover:text-gray-600' : 'border-surface-600 text-gray-500 hover:text-gray-300',
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-1.5">
              {districts?.map((d: DistrictCoverage) => (
                <button
                  key={d.name}
                  onClick={() => setFlyBbox([...d.bbox])}
                  className={clsx(
                    'w-full text-left rounded-md px-2 py-1.5 transition-colors',
                    isLight ? 'hover:bg-gray-50' : 'hover:bg-surface-700',
                  )}
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className={clsx('text-[11px] font-medium truncate', isLight ? 'text-gray-800' : 'text-gray-200')}>{d.name}</span>
                    <span className="text-[11px] font-mono tabular-nums shrink-0" style={{ color: d.coverage_pct > 0 ? COVERED_ACCENT : undefined }}>
                      {d.coverage_pct.toFixed(0)}%
                    </span>
                  </div>
                  <div className={clsx('h-1 rounded-full mt-1 overflow-hidden', isLight ? 'bg-gray-100' : 'bg-surface-700')}>
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${Math.min(100, d.coverage_pct)}%`, backgroundColor: COVERED_ACCENT }}
                    />
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* ── Area result — bottom left ────────────── */}
        {(areaStats || areaMutation.isPending) && (
          <div className={clsx('absolute bottom-3 left-3 z-[1000] px-3 py-2 flex items-center gap-3', overlayClass)}>
            <span className="eyebrow text-[9px]">Selected area</span>
            {areaMutation.isPending ? (
              <span className="text-xs text-gray-500">computing…</span>
            ) : areaStats && (
              <>
                <span className="text-sm font-mono tabular-nums font-semibold" style={{ color: '#22d3ee' }}>
                  {areaStats.coverage_pct}%
                </span>
                <span className={clsx('text-xs font-mono tabular-nums', isLight ? 'text-gray-700' : 'text-gray-300')}>
                  {areaStats.covered_km} / {areaStats.total_km} km
                </span>
                <span className="text-[11px] text-gray-500">
                  {areaStats.num_covered_streets}/{areaStats.num_streets} streets
                </span>
              </>
            )}
            <button onClick={clearArea} className={clsx('text-[11px]', isLight ? 'text-gray-400 hover:text-gray-700' : 'text-gray-500 hover:text-gray-200')} aria-label="Clear selection">
              ✕
            </button>
          </div>
        )}

        {/* ── Hints ────────────────────────────────── */}
        {selectMode && (
          <div className={clsx('absolute bottom-3 left-1/2 -translate-x-1/2 z-[1000] px-3 py-1.5 text-[11px]', overlayClass, isLight ? 'text-gray-600' : 'text-gray-300')}>
            Drag to select an area
          </div>
        )}
        {showMissing && !viewportBbox && !selectMode && (
          <div className={clsx('absolute bottom-3 left-1/2 -translate-x-1/2 z-[1000] px-3 py-1.5 text-[11px]', overlayClass, isLight ? 'text-gray-600' : 'text-gray-300')}>
            Zoom in to reveal missing streets
          </div>
        )}

        {edgesLoading && (
          <div className={clsx('absolute inset-x-0 top-1/2 z-[999] flex justify-center pointer-events-none')}>
            <span className={clsx('px-3 py-1.5 text-[11px] rounded-lg', overlayClass, 'text-gray-400')}>Loading covered streets…</span>
          </div>
        )}
      </div>
    </div>
  )
}

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { MapContainer, TileLayer, GeoJSON, Rectangle, useMap, useMapEvents } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import clsx from 'clsx'
import { useQueryClient } from '@tanstack/react-query'
import {
  useCoverageCities, useCoverageEdges, useCoverageDistricts, useCoverageArea,
  useCoverageSyncStatus, useTriggerCoverageSync, useUncoveredEdges,
  useAddCity, useAddCityStatus, useGeocodeCity, useDeleteCity, type GeocodeSuggestion,
  useAppConfig,
  type AreaCoverage, type CoverageSummary, type DistrictCoverage,
} from '../api/hooks'
import { useNow } from '../hooks/useNow'
import { useTheme } from '../hooks/useTheme'
import { InvalidateSize } from '../components/shared/leafletHelpers'
import { FullscreenIcon } from '../components/shared/mapChrome'
import { tileLayerAttribution, tileLayerClass, tileLayerUrl } from '../utils/mapTiles'
import { useExitFullscreenOnEscape } from '../hooks/useExitFullscreenOnEscape'
import { MapStyleToggle, SATELLITE_ACCENT, SATELLITE_ATTR, SATELLITE_TILES, type MapStyle } from '../components/shared/MapStyleToggle'

const COVERED_ACCENT = '#fb2c36'

// Magma stops for the traversal-frequency heatmap: streets run once stay cool
// and dim, the daily loops glow hot.
const HEAT_STOPS = ['#3b0f70', '#8c2981', '#de4968', '#fe9f6d', '#fcfdbf'] as const

/** Map a normalised [0,1] frequency to a magma colour by interpolating stops. */
function heatColor(t: number): string {
  const x = Math.min(1, Math.max(0, t)) * (HEAT_STOPS.length - 1)
  const i = Math.min(HEAT_STOPS.length - 2, Math.floor(x))
  const f = x - i
  const c1 = parseInt(HEAT_STOPS[i].slice(1), 16)
  const c2 = parseInt(HEAT_STOPS[i + 1].slice(1), 16)
  const mix = (shift: number) => {
    const a = (c1 >> shift) & 255
    const b = (c2 >> shift) & 255
    return Math.round(a + f * (b - a))
  }
  return `rgb(${mix(16)},${mix(8)},${mix(0)})`
}

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

/** Fly to a city when it becomes active. On first load the covered-edges fit
 *  positions the map instead, unless the city has nothing matched yet. */
function FlyToActiveCity({ city }: { city: CoverageSummary | undefined }) {
  const map = useMap()
  const flownSlug = useRef<string | undefined>(undefined)
  useEffect(() => {
    if (!city?.bbox || flownSlug.current === city.slug) return
    const first = flownSlug.current === undefined
    flownSlug.current = city.slug
    if (first && city.num_matched_activities !== 0) return
    const [south, west, north, east] = city.bbox
    map.flyToBounds([[south, west], [north, east]], { padding: [30, 30], duration: 1.0 })
  }, [map, city])
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

/** Map control button with an instant hover tip to its left. */
function TipButton({ tip, onClick, className, isLight, children }: {
  tip: string
  onClick: () => void
  className: string
  isLight: boolean
  children: React.ReactNode
}) {
  return (
    <div className="relative group">
      <button onClick={onClick} className={className} aria-label={tip} type="button">
        {children}
      </button>
      <span
        className={clsx(
          'absolute right-full mr-2 top-1/2 -translate-y-1/2 px-2 py-1 rounded-md text-[10px] whitespace-nowrap',
          'opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity',
          isLight ? 'bg-white/95 text-gray-700 border border-gray-200 shadow-sm' : 'bg-surface-800/95 text-gray-200 border border-surface-600',
        )}
      >
        {tip}
      </span>
    </div>
  )
}

/** Ticking "elapsed since start" label; mounted only while a download runs. */
function ElapsedSince({ startedAt }: { startedAt: number }) {
  const now = useNow(1000)
  const elapsed = Math.max(0, Math.round(now / 1000 - startedAt))
  const txt = elapsed >= 60 ? `${Math.floor(elapsed / 60)}m ${elapsed % 60}s` : `${elapsed}s`
  return <span className="font-mono tabular-nums"> · {txt}</span>
}

/** "+ City" button → inline input → geocode preview to confirm the resolved
 *  place → background download with status polling. The preview matters:
 *  bare "Amsterdam" resolves to New York City (née New Amsterdam). */
function AddCityForm({ onAdded }: { onAdded: (slug: string) => void }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState('')
  const [resolved, setResolved] = useState<string | null>(null)
  // A village mapped only as a point has no boundary; the area around it is offered instead
  const [suggestion, setSuggestion] = useState<GeocodeSuggestion | null>(null)
  const [noArea, setNoArea] = useState(false)
  const geocodeMutation = useGeocodeCity()
  const addMutation = useAddCity()
  // The hook keeps polling on its own while a download reports running.
  const { data: status } = useAddCityStatus(addMutation.isPending)
  const running = !!status?.running
  const prevRunning = useRef(false)

  // Completion resets the form via the parent: onAdded switches the active
  // city, and the mount sites key this component by that slug.
  useEffect(() => {
    if (prevRunning.current && !running) {
      qc.invalidateQueries({ queryKey: ['coverage-cities'] })
      if (status?.slug && !status.error) {
        onAdded(status.slug)
      }
    }
    prevRunning.current = running
  }, [running, status, qc, onAdded])

  if (running) {
    return (
      <span className="text-[11px] text-gray-500 animate-pulse whitespace-nowrap" title="Downloads the street network from OSM — takes a few minutes for a big city">
        adding {status?.city_name} — {status?.progress ?? 'working'}
        {status?.started_at != null && <ElapsedSince startedAt={status.started_at} />}
      </span>
    )
  }
  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className="btn !text-[11px] !py-1 !px-2.5" title="Download a new city's street network">
        + City
      </button>
    )
  }
  return (
    <form
      className="flex items-center gap-1.5"
      onSubmit={e => {
        e.preventDefault()
        const name = value.trim()
        if (!name) return
        if (resolved) addMutation.mutate(name)
        else geocodeMutation.mutate(name, {
          onSuccess: d => {
            if (!d.point_only) setResolved(d.display_name)
            else if (d.suggestion) setSuggestion(d.suggestion)
            else setNoArea(true)
          },
        })
      }}
    >
      <input
        autoFocus
        value={value}
        onChange={e => { setValue(e.target.value); setResolved(null); setSuggestion(null); setNoArea(false) }}
        onKeyDown={e => { if (e.key === 'Escape') setOpen(false) }}
        placeholder="Amsterdam, Netherlands"
        className="input !text-xs !py-1 !px-2 w-44"
        aria-label="City name"
      />
      <button
        type="submit"
        disabled={!value.trim() || geocodeMutation.isPending}
        className={clsx('btn !text-[11px] !py-1 !px-2', resolved && '!text-emerald-400 !border-emerald-500/50')}
      >
        {geocodeMutation.isPending ? 'Resolving…' : resolved ? 'Confirm' : 'Add'}
      </button>
      {resolved && (
        <span className="text-[10px] text-gray-400 max-w-52 truncate" title={resolved}>→ {resolved}</span>
      )}
      {suggestion && !resolved && (
        <span className="flex items-center gap-1.5 text-[10px] text-gray-400">
          <span className="max-w-64 truncate" title={suggestion.display_name}>
            not an area in OSM — it lies in {suggestion.display_name.split(',')[0]} ({Math.round(suggestion.area_km2)} km²)
          </span>
          <button
            type="button"
            className="btn !text-[10px] !py-0.5 !px-1.5"
            onClick={() => { setValue(suggestion.query); setResolved(suggestion.display_name); setSuggestion(null) }}
          >
            Use it
          </button>
        </span>
      )}
      {noArea && (
        <span className="text-[10px] text-red-400">not an area in OSM, and nothing around it to add</span>
      )}
      {geocodeMutation.isError && !resolved && (
        <span className="text-[10px] text-red-400">place not found</span>
      )}
      {status?.error && (
        <span className="text-[10px] text-red-400 max-w-44 truncate" title={status.error}>{status.error}</span>
      )}
    </form>
  )
}

export default function CoveragePage() {
  const { theme, colors } = useTheme()
  const isLight = theme === 'light'
  const qc = useQueryClient()

  const { data: cities, isLoading: citiesLoading } = useCoverageCities()
  const [slug, setSlug] = useState<string | undefined>(undefined)
  const activeSlug = slug ?? cities?.[0]?.slug
  const city = cities?.find(c => c.slug === activeSlug)

  // Leaflet layers read their GeoJSON once at mount, so every layer below is
  // keyed by dataUpdatedAt: it moves the moment a fetch resolves, which is what
  // forces the redraw — a key built from the request inputs alone would change
  // while the previous payload is still the one being held.
  const { data: edges, isLoading: edgesLoading, dataUpdatedAt: edgesAt } = useCoverageEdges(activeSlug)
  // 9 = administrative districts, 10 = neighbourhoods (finer). Cities OSM
  // doesn't subdivide at the chosen level collapse to a whole-city district.
  const [adminLevel, setAdminLevel] = useState<9 | 10>(9)
  const { data: districts, dataUpdatedAt: districtsAt } = useCoverageDistricts(activeSlug, adminLevel)
  const [showDistricts, setShowDistricts] = useState(true)
  const [flyBbox, setFlyBbox] = useState<[number, number, number, number] | null>(null)

  const [expanded, setExpanded] = useState(false)
  const [mapStyle, setMapStyle] = useState<MapStyle>('street')
  const [heatmapMode, setHeatmapMode] = useState(false)
  const [selectMode, setSelectMode] = useState(false)
  const [areaRect, setAreaRect] = useState<L.LatLngBounds | null>(null)
  const [areaStats, setAreaStats] = useState<AreaCoverage | null>(null)
  const areaMutation = useCoverageArea(activeSlug)

  const [showMissing, setShowMissing] = useState(false)
  const [viewportBbox, setViewportBbox] = useState<string | undefined>(undefined)
  const { data: uncovered, dataUpdatedAt: uncoveredAt } = useUncoveredEdges(activeSlug, showMissing ? viewportBbox : undefined)

  const deleteMutation = useDeleteCity()
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const syncMutation = useTriggerCoverageSync(activeSlug)
  const { data: syncStatus } = useCoverageSyncStatus(activeSlug, syncMutation.isSuccess)
  const syncRunning = !!syncStatus?.running
  const prevRunning = useRef(false)
  const resetSyncMutation = syncMutation.reset
  useEffect(() => {
    if (prevRunning.current && !syncRunning) {
      // Drop the mutation's success flag so the status poll stops with the sync.
      resetSyncMutation()
      qc.invalidateQueries({ queryKey: ['coverage-cities'] })
      qc.invalidateQueries({ queryKey: ['coverage-edges'] })
      qc.invalidateQueries({ queryKey: ['coverage-districts'] })
    }
    prevRunning.current = syncRunning
  }, [syncRunning, qc, resetSyncMutation])

  useExitFullscreenOnEscape(expanded, () => setExpanded(false))

  const accent = mapStyle === 'satellite' ? SATELLITE_ACCENT : COVERED_ACCENT
  const districtColor = mapStyle === 'satellite' ? '#c4b5fd' : isLight ? '#7c3aed' : '#8b5cf6'

  const districtFC = useMemo(() => {
    const features = (districts ?? [])
      .filter((d: DistrictCoverage) => d.geometry)
      .map((d: DistrictCoverage) => ({
        type: 'Feature' as const,
        geometry: d.geometry!,
        properties: {
          name: d.name, pct: d.coverage_pct,
          covered_km: d.covered_km, total_km: d.total_km, bbox: d.bbox,
        },
      }))
    return features.length ? { type: 'FeatureCollection' as const, features } : null
  }, [districts])

  // Shaded relative to the best-covered district (square root, so the low end
  // still differs): every district is far from complete, and the tooltip has
  // the real percentage.
  const maxDistrictPct = useMemo(
    () => (districts ?? []).reduce((m: number, d: DistrictCoverage) => Math.max(m, d.coverage_pct), 0),
    [districts],
  )

  const districtStyle = useCallback((feature?: GeoJSON.Feature): L.PathOptions => {
    const pct = (feature?.properties as { pct?: number } | null)?.pct ?? 0
    return {
      color: districtColor,
      weight: 1,
      opacity: 0.35,
      fillColor: districtColor,
      fillOpacity: 0.04 + 0.42 * (maxDistrictPct > 0 ? Math.sqrt(Math.min(1, pct / maxDistrictPct)) : 0),
    }
  }, [districtColor, maxDistrictPct])

  const onDistrictFeature = useCallback((feature: GeoJSON.Feature, layer: L.Layer) => {
    const p = feature.properties as {
      name: string; pct: number; covered_km: number; total_km: number
      bbox: [number, number, number, number]
    }
    const path = layer as L.Path
    path.bindTooltip(
      `<span class="district-tip-name">${p.name}</span>` +
      `<span class="district-tip-pct" style="color:${districtColor}">${p.pct.toFixed(1)}%</span>` +
      `<span class="district-tip-km">${p.covered_km.toFixed(1)} / ${p.total_km.toFixed(1)} km</span>`,
      { sticky: true, className: 'district-tip', direction: 'top', opacity: 1 },
    )
    path.on({
      mouseover: () => path.setStyle({ weight: 2, opacity: 0.9, fillOpacity: (districtStyle(feature).fillOpacity ?? 0) + 0.12 }),
      mouseout: () => path.setStyle(districtStyle(feature)),
      click: () => setFlyBbox([...p.bbox]),
    })
  }, [districtColor, districtStyle])

  const { cartoApiKey, pending: configPending } = useAppConfig()
  const isSatellite = mapStyle === 'satellite'
  const tileUrl = isSatellite ? SATELLITE_TILES : tileLayerUrl(isLight, cartoApiKey)

  const overlayClass = clsx(
    'rounded-lg border backdrop-blur-md',
    isLight ? 'bg-white/85 border-gray-200/80 shadow-sm' : 'bg-surface-800/85 border-surface-600/80',
  )
  const buttonClass = clsx(
    'rounded-lg p-2 transition-colors',
    overlayClass,
    isLight ? 'text-gray-500 hover:text-gray-900' : 'text-gray-400 hover:text-gray-100',
  )

  const rectPoints = (bounds: L.LatLngBounds): [number, number][] => {
    const sw = bounds.getSouthWest()
    const ne = bounds.getNorthEast()
    return [[sw.lat, sw.lng], [sw.lat, ne.lng], [ne.lat, ne.lng], [ne.lat, sw.lng]]
  }

  const handleAreaSelect = (bounds: L.LatLngBounds) => {
    setAreaRect(bounds)
    setSelectMode(false)
    areaMutation.mutate(rectPoints(bounds), { onSuccess: setAreaStats })
  }

  const clearArea = () => {
    setAreaRect(null)
    setAreaStats(null)
  }

  // Per-city UI state (delete confirmation, area selection) resets on switch.
  const switchCity = (next: string | undefined) => {
    setSlug(next)
    setConfirmingDelete(false)
    clearArea()
  }

  // Highest traversal count in view — the hot end of the heatmap's log scale.
  const maxTimes = useMemo(() => {
    if (!heatmapMode || !edges) return 1
    let m = 1
    for (const f of edges.features) m = Math.max(m, f.properties.times ?? 0)
    return m
  }, [heatmapMode, edges])

  const heatNorm = useCallback(
    (t: number) => (maxTimes <= 1 ? 0 : Math.log(Math.max(1, t)) / Math.log(maxTimes)),
    [maxTimes],
  )

  const edgesKey = useMemo(
    () => `${activeSlug}-${edgesAt}-${heatmapMode ? `heat${maxTimes}` : accent}`,
    [activeSlug, edgesAt, accent, heatmapMode, maxTimes],
  )

  if (!citiesLoading && (cities?.length ?? 0) === 0) {
    return (
      <div className="max-w-6xl mx-auto pb-6 space-y-4">
        <header className="flex items-baseline gap-2">
          <span className="eyebrow">Coverage</span>
        </header>
        <div className={clsx('panel p-10 text-center text-sm space-y-4', isLight ? 'text-gray-500' : 'text-gray-400')}>
          <p>No coverage maps yet. Add a city to download its runnable street network, then sync your activities against it.</p>
          <div className="flex justify-center">
            <AddCityForm key={activeSlug ?? 'no-city'} onAdded={switchCity} />
          </div>
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
          center={[40.42, -3.7]}
          zoom={12}
          preferCanvas
          zoomControl={false}
          style={{ height: '100%', width: '100%', background: colors.mapBg, cursor: selectMode ? 'crosshair' : undefined }}
        >
          {!configPending && (
            <TileLayer
              key={tileUrl}
              attribution={isSatellite ? SATELLITE_ATTR : tileLayerAttribution(cartoApiKey)}
              url={tileUrl}
              className={isSatellite ? 'satellite-tiles' : tileLayerClass(cartoApiKey)}
            />
          )}
          {showDistricts && districtFC && (
            <GeoJSON
              key={`districts-${activeSlug}-${districtsAt}-${districtColor}-${selectMode}`}
              data={districtFC}
              interactive={!selectMode}
              style={districtStyle}
              onEachFeature={onDistrictFeature}
            />
          )}
          {showMissing && uncovered && viewportBbox && (
            <GeoJSON
              key={`missing-${activeSlug}-${uncoveredAt}`}
              data={uncovered}
              style={{
                color: mapStyle === 'satellite' ? '#cbd5e1' : isLight ? '#94a3b8' : '#64748b',
                weight: 1.2,
                opacity: 0.55,
                dashArray: '3 4',
              }}
            />
          )}
          {edges && heatmapMode && (
            <>
              {/* Frequency heatmap: colour + weight scale with how often each
                  street was run (log scale, glow underlay + brighter core). */}
              <GeoJSON
                key={`${edgesKey}-hglow`}
                data={edges}
                style={(f?: GeoJSON.Feature) => {
                  const n = heatNorm((f?.properties as { times?: number } | null)?.times ?? 1)
                  return { color: heatColor(n), weight: 3 + 4 * n, opacity: 0.16 }
                }}
              />
              <GeoJSON
                key={`${edgesKey}-hcore`}
                data={edges}
                style={(f?: GeoJSON.Feature) => {
                  const n = heatNorm((f?.properties as { times?: number } | null)?.times ?? 1)
                  return { color: heatColor(n), weight: 1.2 + 2.2 * n, opacity: 0.95 }
                }}
              />
              <FitToLayer data={edges} />
            </>
          )}
          {edges && !heatmapMode && (
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
          <FlyToActiveCity city={city} />
          <InvalidateSize expanded={expanded} />
        </MapContainer>

        {/* ── Summary overlay — top left ───────────── */}
        <div className={clsx('absolute top-3 left-3 z-[1000] px-3 py-2 flex items-center gap-3 flex-wrap max-w-[calc(100%-8rem)]', overlayClass)}>
          {(cities?.length ?? 0) > 1 && (
            <select
              value={activeSlug}
              onChange={e => switchCity(e.target.value)}
              className="select !text-xs !py-1 !px-1.5"
              aria-label="City"
            >
              {cities?.map(c => <option key={c.slug} value={c.slug}>{c.city_name}</option>)}
            </select>
          )}
          {(cities?.length ?? 0) === 1 && (
            <span className={clsx('text-xs font-semibold', isLight ? 'text-gray-900' : 'text-gray-100')}>{city?.city_name}</span>
          )}
          {city && !confirmingDelete && (
            <button
              onClick={() => setConfirmingDelete(true)}
              className={clsx('transition-colors', isLight ? 'text-gray-300 hover:text-red-500' : 'text-gray-600 hover:text-red-400')}
              title={`Delete ${city.city_name}`}
              aria-label={`Delete ${city.city_name}`}
            >
              <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M2.5 4.5h11M6.5 4.5v-2h3v2M4 4.5l.8 9h6.4l.8-9M6.7 7.5v3.5M9.3 7.5v3.5" />
              </svg>
            </button>
          )}
          {city && confirmingDelete && (
            <span className="flex items-center gap-1.5">
              <span className="text-[11px] text-red-400">delete {city.city_name} and its matched state?</span>
              <button
                onClick={() => deleteMutation.mutate(city.slug, {
                  onSuccess: () => switchCity(undefined),
                })}
                disabled={deleteMutation.isPending}
                className="btn !text-[10px] !py-0.5 !px-2 !text-red-400 !border-red-500/50"
              >
                {deleteMutation.isPending ? 'Deleting…' : 'Delete'}
              </button>
              <button onClick={() => setConfirmingDelete(false)} className="btn !text-[10px] !py-0.5 !px-2">
                Cancel
              </button>
            </span>
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
            <span className="eyebrow text-[9px]">Segments</span>
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
          <AddCityForm key={activeSlug ?? 'no-city'} onAdded={switchCity} />
        </div>

        {/* ── Controls — top right ─────────────────── */}
        <div className="absolute top-3 right-3 z-[1000] flex flex-col gap-2 items-end">
          <TipButton
            tip={expanded ? 'Exit fullscreen' : 'Fullscreen'}
            onClick={() => setExpanded(e => !e)}
            className={buttonClass}
            isLight={isLight}
          >
            <FullscreenIcon expanded={expanded} />
          </TipButton>
          <div className="relative group">
            <MapStyleToggle
              mapStyle={mapStyle}
              onToggle={() => setMapStyle(s => (s === 'satellite' ? 'street' : 'satellite'))}
              className={buttonClass}
              hideTitle
            />
            <span
              className={clsx(
                'absolute right-full mr-2 top-1/2 -translate-y-1/2 px-2 py-1 rounded-md text-[10px] whitespace-nowrap',
                'opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity',
                isLight ? 'bg-white/95 text-gray-700 border border-gray-200 shadow-sm' : 'bg-surface-800/95 text-gray-200 border border-surface-600',
              )}
            >
              {mapStyle === 'satellite' ? 'Switch to street map' : 'Switch to satellite imagery'}
            </span>
          </div>
          <TipButton
            tip={heatmapMode ? 'Show solid coverage' : 'Frequency heatmap — colour streets by how often you’ve run them'}
            onClick={() => setHeatmapMode(m => !m)}
            className={clsx(buttonClass, heatmapMode && '!text-orange-400 !border-orange-500/50')}
            isLight={isLight}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M8 1.8c.6 2 2 2.7 2 4.7a2 2 0 0 1-4 0M8 1.8C6.2 3.8 4 5.4 4 9a4 4 0 0 0 8 0c0-1.8-.8-2.9-1.6-3.8" />
            </svg>
          </TipButton>
          <TipButton
            tip={selectMode ? 'Cancel area selection' : 'Measure an area — drag a rectangle to get its coverage'}
            onClick={() => { setSelectMode(m => !m); if (areaRect) clearArea() }}
            className={clsx(buttonClass, selectMode && '!text-cyan-400 !border-cyan-500/50')}
            isLight={isLight}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <rect x="3" y="3" width="10" height="10" rx="1" strokeDasharray="3 2" />
              <path d="M8 6v4M6 8h4" />
            </svg>
          </TipButton>
          <TipButton
            tip={showMissing ? 'Hide missing streets' : 'Missing streets — streets you haven’t run yet, zoom in to see them'}
            onClick={() => setShowMissing(m => !m)}
            className={clsx(buttonClass, showMissing && '!text-slate-300 !border-slate-400/50')}
            isLight={isLight}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M2 12c2-6 4 2 6-4s4 2 6-4" strokeDasharray="2.5 2" />
            </svg>
          </TipButton>
          <TipButton
            tip={showDistricts ? 'Hide district overlay' : 'District overlay — hover a district for its coverage'}
            onClick={() => setShowDistricts(s => !s)}
            className={clsx(buttonClass, showDistricts && '!text-violet-400 !border-violet-500/50')}
            isLight={isLight}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M8 2.2 13.5 6l-2 7H4.5l-2-7z" />
            </svg>
          </TipButton>
        </div>

        {/* ── Bottom left: area result + district granularity ──── */}
        <div className="absolute bottom-3 left-3 z-[1000] flex flex-col gap-2 items-start">
          {heatmapMode && edges && (
            <div className={clsx('px-3 py-2 flex items-center gap-2', overlayClass)}>
              <span className="eyebrow text-[9px]">Runs</span>
              <span className="text-[10px] text-gray-500">1</span>
              <span
                className="h-2 w-24 rounded-full"
                style={{ background: `linear-gradient(to right, ${HEAT_STOPS.join(', ')})` }}
              />
              <span className="text-[10px] text-gray-500">{maxTimes}×</span>
            </div>
          )}
          {(areaStats || areaMutation.isPending) && (
            <div className={clsx('px-3 py-2 flex items-center gap-3', overlayClass)}>
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
                    {areaStats.num_covered_streets}/{areaStats.num_streets} segments
                  </span>
                </>
              )}
              <button onClick={clearArea} className={clsx('text-[11px]', isLight ? 'text-gray-400 hover:text-gray-700' : 'text-gray-500 hover:text-gray-200')} aria-label="Clear selection">
                ✕
              </button>
            </div>
          )}
          {showDistricts && (
            <div className={clsx('flex items-center gap-0.5 px-1 py-0.5', overlayClass)}>
              {([[9, 'Districts'], [10, 'Neighborhoods']] as const).map(([lvl, label]) => (
                <button key={lvl} onClick={() => setAdminLevel(lvl)} className="chip whitespace-nowrap" data-active={adminLevel === lvl}>
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>

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
        {city && city.num_matched_activities === 0 && !syncRunning && !selectMode && !showMissing && (
          <div className={clsx('absolute bottom-3 left-1/2 -translate-x-1/2 z-[1000] px-3 py-1.5 text-[11px]', overlayClass, isLight ? 'text-gray-600' : 'text-gray-300')}>
            Nothing matched yet for {city.city_name} — press Sync to match your activities
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

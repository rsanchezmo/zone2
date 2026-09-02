import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { MapContainer, Polyline, TileLayer, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import type { LatLngBoundsExpression } from 'leaflet'
import clsx from 'clsx'

import { getSportColor } from '../../constants/sportColors'
import { useAppConfig } from '../../api/hooks'
import { useTheme } from '../../hooks/useTheme'
import { useExitFullscreenOnEscape } from '../../hooks/useExitFullscreenOnEscape'
import { tileLayerAttribution, tileLayerClass, tileLayerUrl } from '../../utils/mapTiles'
import { InvalidateSize } from './leafletHelpers'
import { FullscreenIcon } from './mapChrome'
import { MapStyleToggle, SATELLITE_ATTR, SATELLITE_TILES, type MapStyle } from './MapStyleToggle'
import { routeBounds, routesSignature, type CornerBounds, type DecodedRoute } from './routes'

/** Fit the map once per distinct route set, so filter changes refit. */
function FitAll({ bounds, signature }: { bounds: CornerBounds | null; signature: string }) {
  const map = useMap()
  const fittedFor = useRef<string | null>(null)
  useEffect(() => {
    if (!bounds || fittedFor.current === signature) return
    fittedFor.current = signature
    map.fitBounds(bounds as LatLngBoundsExpression, { padding: [30, 30] })
  }, [map, bounds, signature])
  return null
}

interface RoutesMapProps {
  routes: DecodedRoute[]
  /** Initial frame. Defaults to every route point. */
  fitTo?: CornerBounds | null
  /** Stroke per route. Defaults to the sport colour. */
  colorFor?: (route: DecodedRoute) => string
  /** Layers mounted inside the Leaflet container (fly-to helpers, extra shapes). */
  children?: ReactNode
  /** Chrome drawn over the map — filter panels, legends, badges. */
  overlay?: ReactNode
  /** Container classes while not fullscreen. */
  className?: string
  loading?: boolean
  emptyState?: ReactNode
  /** Fullscreen is owned here; pages that restyle around it get told. */
  onExpandedChange?: (expanded: boolean) => void
}

/**
 * Many activity routes on one zoomable Leaflet map.
 *
 * Canvas-rendered: with hundreds of polylines the default SVG renderer buries
 * the page in DOM nodes.
 */
export default function RoutesMap({
  routes,
  fitTo,
  colorFor,
  children,
  overlay,
  className,
  loading = false,
  emptyState,
  onExpandedChange,
}: RoutesMapProps) {
  const { theme, colors } = useTheme()
  const isLight = theme === 'light'
  const navigate = useNavigate()
  const [expanded, setExpanded] = useState(false)
  const [mapStyle, setMapStyle] = useState<MapStyle>('street')

  const setFullscreen = (next: boolean) => {
    setExpanded(next)
    onExpandedChange?.(next)
  }

  useExitFullscreenOnEscape(expanded, () => setFullscreen(false))

  const cartoApiKey = useAppConfig().data?.carto_api_key
  const isSatellite = mapStyle === 'satellite'
  const tileUrl = isSatellite ? SATELLITE_TILES : tileLayerUrl(isLight, cartoApiKey)
  const allBounds = useMemo(() => routeBounds(routes), [routes])
  const signature = useMemo(() => routesSignature(routes), [routes])

  const placeholder = clsx(
    'flex flex-col items-center justify-center h-full gap-3',
    isLight ? 'bg-gray-50' : 'bg-surface-900',
  )

  return (
    <div className={expanded ? 'fixed inset-0 z-50 w-screen h-screen' : clsx('relative', className)}>
      {loading ? (
        <div className={placeholder}>
          <svg className="w-8 h-8 text-gray-500 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <span className="eyebrow">Loading routes</span>
        </div>
      ) : routes.length === 0 ? (
        <div className={placeholder}>{emptyState}</div>
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
            attribution={isSatellite ? SATELLITE_ATTR : tileLayerAttribution(cartoApiKey)}
            url={tileUrl}
            className={isSatellite ? 'satellite-tiles' : tileLayerClass(cartoApiKey)}
          />
          {routes.map(route => {
            const color = colorFor ? colorFor(route) : getSportColor(route.sport_type)
            return (
              <Polyline
                key={String(route.id)}
                positions={route.positions}
                pathOptions={{ color, weight: 2, opacity: 0.6 }}
                eventHandlers={{
                  click: () => navigate(`/activities/${route.id}`),
                  mouseover: e => {
                    e.target.setStyle({ weight: 4, opacity: 1 })
                    e.target.bindTooltip(`${route.sport_type}: ${route.name}`, { sticky: true }).openTooltip()
                  },
                  mouseout: e => {
                    e.target.setStyle({ weight: 2, opacity: 0.6 })
                    e.target.closeTooltip()
                  },
                }}
              />
            )
          })}
          <FitAll bounds={fitTo ?? allBounds} signature={signature} />
          <InvalidateSize expanded={expanded} />
          {children}
        </MapContainer>
      )}

      {overlay}

      <div className="absolute top-3 right-3 z-[1000] flex flex-col gap-2">
        <button
          onClick={() => setFullscreen(!expanded)}
          className={clsx(
            'map-overlay p-2 transition-colors',
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
            'map-overlay p-2 transition-colors',
            isLight ? 'text-gray-500 hover:text-gray-900' : 'text-gray-400 hover:text-gray-100',
          )}
        />
      </div>
    </div>
  )
}

import { useEffect, useMemo, useState } from 'react'
import { Marker, useMap, useMapEvents } from 'react-leaflet'
import { createArrowIcon, routeArrows } from './mapIcons'

/** Re-measures the map after a layout change (e.g. fullscreen toggle) so
 *  Leaflet doesn't render stale tile bounds. */
export function InvalidateSize({ expanded }: { expanded?: boolean }) {
  const map = useMap()
  useEffect(() => {
    const id = setTimeout(() => map.invalidateSize(), 100)
    return () => clearTimeout(id)
  }, [map, expanded])
  return null
}

const ARROW_SPACING_PX = 80

/** Direction arrows along a route, spaced by screen distance so they stay
 *  readable at any zoom. */
export function RouteArrows({ lines }: { lines: [number, number][][] }) {
  const map = useMap()
  const [zoom, setZoom] = useState(() => map.getZoom())
  const [bounds, setBounds] = useState(() => map.getBounds())
  useMapEvents({
    zoomend: () => setZoom(map.getZoom()),
    moveend: () => setBounds(map.getBounds()),
  })
  const arrows = useMemo(() => {
    let px = 0
    for (const line of lines) {
      for (let i = 1; i < line.length; i++) {
        px += map.project(line[i - 1], zoom).distanceTo(map.project(line[i], zoom))
      }
    }
    return routeArrows(lines, Math.max(2, Math.round(px / ARROW_SPACING_PX)))
  }, [lines, map, zoom])
  // Only the arrows around the viewport are rendered, so zooming in on a long run stays light
  const nearView = bounds.pad(0.5)
  return (
    <>
      {arrows.map((a, i) => nearView.contains(a.position) && (
        <Marker key={`${zoom}-${i}`} position={a.position} icon={createArrowIcon(a.heading)} interactive={false} />
      ))}
    </>
  )
}

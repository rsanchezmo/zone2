import { useEffect } from 'react'
import { useMap } from 'react-leaflet'

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

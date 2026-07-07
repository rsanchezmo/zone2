export type MapStyle = 'street' | 'satellite'

export const SATELLITE_TILES = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
export const SATELLITE_ATTR = 'Imagery &copy; <a href="https://www.esri.com/">Esri</a>'

/** Override accent for overlays in satellite mode. Per-sport accents can
 *  disappear into terrain; cyan reads cleanly against dimmed imagery. */
export const SATELLITE_ACCENT = '#22d3ee'

interface Props {
  mapStyle: MapStyle
  onToggle: () => void
  className: string
  /** Suppress the native title when the caller renders its own tooltip. */
  hideTitle?: boolean
}

/** Street/satellite toggle button. Place inside the map wrapper div, NOT
 *  inside `<MapContainer>` (which mounts to a Leaflet pane and would
 *  capture pointer events differently). */
export function MapStyleToggle({ mapStyle, onToggle, className, hideTitle = false }: Props) {
  const label = mapStyle === 'satellite' ? 'Switch to street map' : 'Switch to satellite'
  return (
    <button onClick={onToggle} className={className} title={hideTitle ? undefined : label} aria-label={label} type="button">
      {mapStyle === 'satellite' ? (
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M2 4l4-2 4 2 4-2v10l-4 2-4-2-4 2z" />
          <path d="M6 2v12M10 4v12" />
        </svg>
      ) : (
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="8" cy="8" r="6" />
          <ellipse cx="8" cy="8" rx="2.5" ry="6" />
          <path d="M2 8h12" />
        </svg>
      )}
    </button>
  )
}

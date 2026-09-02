/** CARTO stamps an "API KEY REQUIRED" watermark on unkeyed tiles, so without
 *  a key we serve plain OSM instead of a defaced basemap. Grab a free key
 *  (no account needed) at https://carto.com/basemaps/apikey and set
 *  STRAVA_WEB_CARTO_API_KEY. */
const OSM_TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const OSM_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
const CARTO_ATTR = `${OSM_ATTR}, &copy; <a href="https://carto.com/attributions">CARTO</a>`

export function tileLayerUrl(light: boolean, cartoApiKey?: string | null): string {
  if (!cartoApiKey) return OSM_TILES
  const style = light ? 'light_all' : 'dark_all'
  return `https://{s}.basemaps.cartocdn.com/${style}/{z}/{x}/{y}{r}.png?key=${cartoApiKey}`
}

export function tileLayerAttribution(cartoApiKey?: string | null): string {
  return cartoApiKey ? CARTO_ATTR : OSM_ATTR
}

/** OSM's single style has no dark variant; dim it to sit under neon overlays
 *  the way CARTO's dark_all does. Paired with `tileLayerUrl`'s fallback. */
export function tileLayerClass(cartoApiKey?: string | null): string | undefined {
  return cartoApiKey ? undefined : 'osm-fallback-tiles'
}

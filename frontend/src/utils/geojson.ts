/** [south, west, north, east] of every coordinate in a GeoJSON object, or null when it has none. */
export function geojsonBounds(data: GeoJSON.GeoJsonObject): [number, number, number, number] | null {
  let south = Infinity, west = Infinity, north = -Infinity, east = -Infinity
  const visit = (coords: unknown): void => {
    if (!Array.isArray(coords)) return
    if (typeof coords[0] === 'number') {
      const [lng, lat] = coords as number[]
      if (lat < south) south = lat
      if (lat > north) north = lat
      if (lng < west) west = lng
      if (lng > east) east = lng
      return
    }
    for (const c of coords) visit(c)
  }
  const walk = (obj: GeoJSON.GeoJsonObject | null | undefined): void => {
    if (!obj) return
    if (obj.type === 'FeatureCollection') (obj as GeoJSON.FeatureCollection).features.forEach(walk)
    else if (obj.type === 'Feature') walk((obj as GeoJSON.Feature).geometry)
    else if (obj.type === 'GeometryCollection') (obj as GeoJSON.GeometryCollection).geometries.forEach(walk)
    else visit((obj as GeoJSON.LineString).coordinates)
  }
  walk(data)
  return south <= north ? [south, west, north, east] : null
}

const identities = new WeakMap<object, number>()
let nextIdentity = 0

/** A stable number per object: a React key that changes only when the data object does. */
export function identityOf(obj: object): number {
  let id = identities.get(obj)
  if (id === undefined) {
    id = ++nextIdentity
    identities.set(obj, id)
  }
  return id
}

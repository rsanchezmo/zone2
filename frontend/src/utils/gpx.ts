/** A GPX 1.1 track of `coords` ([lon, lat], GeoJSON order), for importing as a course on a watch. */
export function gpxTrack(name: string, coords: number[][]): string {
  const escaped = name.replace(/&/g, '&amp;').replace(/</g, '&lt;')
  const points = coords.map(([lon, lat]) => `<trkpt lat="${lat}" lon="${lon}"/>`).join('\n      ')
  return `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="z2" xmlns="http://www.topografix.com/GPX/1/1">
  <metadata><name>${escaped}</name></metadata>
  <trk>
    <name>${escaped}</name>
    <trkseg>
      ${points}
    </trkseg>
  </trk>
</gpx>
`
}

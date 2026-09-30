import L from 'leaflet'

export function createStartIcon() {
  return L.divIcon({
    className: '',
    iconSize: [22, 22],
    iconAnchor: [11, 11],
    html: `<svg width="22" height="22" viewBox="0 0 22 22" xmlns="http://www.w3.org/2000/svg">
      <circle cx="11" cy="11" r="10" fill="#16a34a" stroke="#fff" stroke-width="2"/>
      <polygon points="9,6 17,11 9,16" fill="#fff"/>
    </svg>`,
  })
}

/** Numbered via point of a planned loop. */
export function createViaIcon(n: number) {
  return L.divIcon({
    className: '',
    iconSize: [20, 20],
    iconAnchor: [10, 10],
    html: `<svg width="20" height="20" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">
      <circle cx="10" cy="10" r="9" fill="#0e7490" stroke="#fff" stroke-width="2"/>
      <text x="10" y="14" text-anchor="middle" font-size="11" font-weight="700" fill="#fff" font-family="system-ui, sans-serif">${n}</text>
    </svg>`,
  })
}

export function createEndIcon() {
  return L.divIcon({
    className: '',
    iconSize: [22, 22],
    iconAnchor: [11, 11],
    html: `<svg width="22" height="22" viewBox="0 0 22 22" xmlns="http://www.w3.org/2000/svg">
      <circle cx="11" cy="11" r="10" fill="#dc2626" stroke="#fff" stroke-width="2"/>
      <rect x="7" y="7" width="8" height="8" rx="1" fill="#fff"/>
    </svg>`,
  })
}

/** Evenly spaced arrows along the lines, each with its heading of travel in
 *  degrees clockwise from north. */
export function routeArrows(lines: [number, number][][], count: number): { position: [number, number]; heading: number }[] {
  const step = (a: [number, number], b: [number, number]) => {
    const dLat = b[0] - a[0]
    const dLon = (b[1] - a[1]) * Math.cos((a[0] * Math.PI) / 180)
    return { dLat, dLon, len: Math.hypot(dLat, dLon) }
  }
  let total = 0
  for (const line of lines) for (let i = 1; i < line.length; i++) total += step(line[i - 1], line[i]).len
  if (total === 0) return []
  const spacing = total / count
  const arrows: { position: [number, number]; heading: number }[] = []
  let next = spacing / 2
  let walked = 0
  for (const line of lines) {
    for (let i = 1; i < line.length; i++) {
      const { dLat, dLon, len } = step(line[i - 1], line[i])
      while (len > 0 && walked + len >= next) {
        const t = (next - walked) / len
        arrows.push({
          position: [line[i - 1][0] + t * (line[i][0] - line[i - 1][0]), line[i - 1][1] + t * (line[i][1] - line[i - 1][1])],
          heading: (Math.atan2(dLon, dLat) * 180) / Math.PI,
        })
        next += spacing
      }
      walked += len
    }
  }
  return arrows
}

/** White heads with a dark edge read as annotation on top of any route colour or basemap. */
export function createArrowIcon(heading: number) {
  return L.divIcon({
    className: '',
    iconSize: [16, 16],
    iconAnchor: [8, 8],
    html: `<svg width="16" height="16" viewBox="0 0 14 14" style="transform: rotate(${heading}deg)" xmlns="http://www.w3.org/2000/svg">
      <path d="M7 1 L12.5 12 L7 9 L1.5 12 Z" fill="#fff" stroke="rgba(13,17,23,0.85)" stroke-width="1.2" stroke-linejoin="round"/>
    </svg>`,
  })
}

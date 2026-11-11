export interface TooltipLine {
  text: string
  className?: string
  color?: string
}

/** A Leaflet tooltip built from nodes, so a name from Strava or OSM is always text, never markup. */
export function tooltipContent(...lines: TooltipLine[]): HTMLElement {
  const tip = document.createElement('div')
  for (const { text, className, color } of lines) {
    const span = tip.appendChild(document.createElement('span'))
    span.textContent = text
    if (className) span.className = className
    if (color) span.style.color = color
  }
  return tip
}

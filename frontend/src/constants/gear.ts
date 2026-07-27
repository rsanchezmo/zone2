/** Distance a pair of running shoes is expected to last before the midsole is
 *  spent. Bikes have no comparable ceiling, so they are gauged against the
 *  rest of the collection instead. */
export const SHOE_LIFE_KM = 700

/** Amber rather than red — the running accent is already red, so a red "spent"
 *  bar would read as ordinary fill. */
export const WEAR_SPENT_COLOR = '#f59e0b'

export interface GearWear {
  /** Bar fill, clamped to the track. */
  fill: number
  /** Uncapped distance / target — above 1 the pair has outlived its budget. */
  ratio: number
  caption: string
  spent: boolean
}

export function shoeWear(distanceKm: number): GearWear {
  const ratio = distanceKm / SHOE_LIFE_KM
  const caption = ratio >= 1.1
    ? `${ratio.toFixed(1)}× a ${SHOE_LIFE_KM} km life`
    : `${Math.round(ratio * 100)}% of a ${SHOE_LIFE_KM} km life`
  return { fill: Math.min(1, ratio), ratio, caption, spent: ratio >= 1 }
}

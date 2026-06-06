export type HrHistogram = { minBpm: number; counts: number[] }

/** Build a histogram (1 bpm bins) from raw HR samples. */
export function buildHrHistogram(samples: number[]): HrHistogram | null {
  if (samples.length === 0) return null
  let lo = Infinity
  let hi = -Infinity
  for (const v of samples) {
    if (v < lo) lo = v
    if (v > hi) hi = v
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return null
  const minBpm = Math.floor(lo) - 2
  const maxBpm = Math.ceil(hi) + 2
  const n = maxBpm - minBpm
  if (n <= 0) return null
  const counts = new Array<number>(n).fill(0)
  for (const v of samples) {
    const idx = Math.floor(v) - minBpm
    if (idx >= 0 && idx < n) counts[idx] += 1
  }
  return { minBpm, counts }
}

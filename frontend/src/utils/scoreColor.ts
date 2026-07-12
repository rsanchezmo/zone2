/** Traffic-light hex color for a 0–100 execution/session score. */
export function scoreColor(score: number): string {
  if (score >= 80) return '#22c55e'
  if (score >= 50) return '#eab308'
  return '#ef4444'
}

// Form as a share of fitness. The usual form zones apply to it whatever the
// load scale, which matters because z2's load is TRIMP, not TSS.
export const FORM_ZONES = [
  { from: 20, to: 60, label: 'Transition', hint: 'fitness is fading', color: '#f59e0b' },
  { from: 5, to: 20, label: 'Fresh', hint: 'ready to race', color: '#38bdf8' },
  { from: -10, to: 5, label: 'Neutral', hint: 'holding steady', color: '#9ca3af' },
  { from: -30, to: -10, label: 'Optimal', hint: 'building fitness', color: '#22c55e' },
  { from: -80, to: -30, label: 'Overreaching', hint: 'time to back off', color: '#ef4444' },
] as const

export type FormZone = (typeof FORM_ZONES)[number]

export function formZone(pct: number): FormZone {
  return FORM_ZONES.find(z => pct >= z.from) ?? FORM_ZONES[FORM_ZONES.length - 1]
}

export function formatFormPct(pct: number): string {
  return `${pct > 0 ? '+' : ''}${Math.round(pct)}%`
}

export interface Segment {
  type: 'warmup' | 'work' | 'recovery' | 'cooldown' | 'rest'
  distance_km?: number | null
  duration_mins?: number | null
  target_pace_min?: number | null
  target_pace_max?: number | null
  target_hr_zone?: number | null
  target_zone_pct?: number | null
  repetitions?: number | null
  recovery_duration_mins?: number | null
  recovery_distance_km?: number | null
  label?: string | null
}

export const SEGMENT_TYPES = [
  { value: 'warmup', label: 'Warmup', color: '#22d3ee' },
  { value: 'work', label: 'Work', color: '#f97316' },
  { value: 'recovery', label: 'Recovery', color: '#6b7280' },
  { value: 'cooldown', label: 'Cooldown', color: '#22d3ee' },
  { value: 'rest', label: 'Rest', color: '#4b5563' },
] as const

export function getSegmentColor(type: string): string {
  return SEGMENT_TYPES.find(t => t.value === type)?.color ?? '#6b7280'
}

export function getSegmentLabel(type: string): string {
  return SEGMENT_TYPES.find(t => t.value === type)?.label ?? type
}

import { getSportCategory, isSpeedSport, type SportCategory } from '../../utils/formatSpeed'

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

/** A segment's planned amount as a compact label: "2km", "400m" or "15'". */
export function formatSegmentAmount(km: number | null | undefined, mins: number | null | undefined): string {
  if (km) return km >= 1 ? `${km}km` : `${Math.round(km * 1000)}m`
  if (mins) return `${mins}'`
  return ''
}

/** One step of a workout as the watch runs it, with reps unrolled. */
export interface WorkoutBlock {
  segment: Segment
  km: number | null
  mins: number | null
  /** Estimated, from the target pace or an assumed one; a step with no end condition gets a nominal 5'. */
  seconds: number
  /** km/h, the block's intensity; 0 standing still. */
  speed: number
  rep: number | null
  reps: number
}

// km/h for a step with no pace target, and the ceiling an easy pace is anchored to
const ASSUMED_SPEED: Record<SportCategory, { easy: number; hard: number }> = {
  running: { easy: 10, hard: 13.3 },
  swimming: { easy: 2.7, hard: 3.4 },
  cycling: { easy: 24, hard: 32 },
  water: { easy: 7, hard: 10 },
  speed: { easy: 8, hard: 12 },
}

function targetSpeed(seg: Segment, sportType: string): number | null {
  const values = [seg.target_pace_min, seg.target_pace_max].filter((v): v is number => v != null && v > 0)
  if (values.length === 0) return null
  const mid = values.reduce((a, b) => a + b, 0) / values.length
  if (isSpeedSport(sportType)) return mid
  return (getSportCategory(sportType) === 'swimming' ? 6 : 60) / mid
}

/** Unrolls segments into blocks the way the Garmin export repeats them: recovery
 *  between reps, none after the last. Untargeted steps get an easy pace scaled to
 *  the workout's fastest target, so a slow runner's warmup doesn't look like work. */
export function workoutBlocks(segments: Segment[], sportType: string): WorkoutBlock[] {
  const assumed = ASSUMED_SPEED[getSportCategory(sportType)]
  const fastest = Math.max(0, ...segments.map(s => targetSpeed(s, sportType) ?? 0))
  const hard = fastest || assumed.hard
  const easy = fastest ? Math.min(assumed.easy, 0.8 * fastest) : assumed.easy
  const recovery = 0.85 * easy

  const speedOf = (seg: Segment): number => {
    const target = targetSpeed(seg, sportType)
    if (target) return target
    if (seg.type === 'rest') return 0
    if (seg.target_hr_zone) return easy + (hard - easy) * (seg.target_hr_zone - 2) / 3
    if (seg.type === 'work') return hard
    return seg.type === 'recovery' ? recovery : easy
  }
  const block = (segment: Segment, rep: number | null, reps: number): WorkoutBlock => {
    const speed = speedOf(segment)
    const km = segment.distance_km || null
    const mins = km ? null : segment.duration_mins || null
    const seconds = km ? km / (speed || recovery) * 3600 : mins ? mins * 60 : 300
    return { segment, km, mins, seconds, speed, rep, reps }
  }

  return segments.flatMap(seg => {
    const reps = Math.max(1, seg.repetitions ?? 1)
    if (reps === 1) return [block(seg, null, 1)]
    const between: Segment | null = seg.recovery_distance_km || seg.recovery_duration_mins
      ? { type: 'recovery', distance_km: seg.recovery_distance_km, duration_mins: seg.recovery_duration_mins }
      : null
    return Array.from({ length: reps }, (_, i) => [
      block(seg, i + 1, reps),
      ...(between && i < reps - 1 ? [block(between, null, reps)] : []),
    ]).flat()
  })
}

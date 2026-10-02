import type { ComponentType, DragEvent as ReactDragEvent } from 'react'
import { addDays, format, isSameMonth, parseISO } from 'date-fns'
import type {
  Activity, ExecutionScore, Goal, GoalMetric, RaceEvent, SessionScoresResponse, TrainingSession,
} from '../../api/hooks'
import { SESSION_GOALS, type SessionGoalKey } from '../../constants/sessionGoals'
import { formatDist, formatDurationHM, formatPace, getPaceUnit, isSpeedSport } from '../../utils/formatSpeed'
import type { IconProps } from '../icons'

/** Label a Monday-anchored week, dropping the repeated month when it doesn't change. */
export function formatWeekRange(weekStart: string): string {
  const start = parseISO(weekStart)
  const end = addDays(start, 6)
  return isSameMonth(start, end)
    ? `${format(start, 'MMM d')} – ${format(end, 'd')}`
    : `${format(start, 'MMM d')} – ${format(end, 'MMM d')}`
}

/** Whether a day's planned sessions were all covered by logged activities.
 *  Null for future days, where "missed" would be premature. */
export function dayPlanStatus(
  sessions: TrainingSession[],
  activities: Activity[],
  isPastOrToday: boolean,
): 'done' | 'missed' | null {
  if (sessions.length === 0 || !isPastOrToday) return null
  const activitySports = new Set(activities.map(a => a.sport_type))
  const allMatched = sessions.every(s => {
    if (s.sport_type.toLowerCase() === 'rest') return activities.length === 0
    return activitySports.has(s.sport_type)
  })
  return allMatched ? 'done' : 'missed'
}

export function dayAvgScore(
  sessions: TrainingSession[],
  scores: SessionScoresResponse | undefined,
): number | null {
  const scored = sessions
    .map(s => scores?.[String(s.id)])
    .filter((sc): sc is ExecutionScore => sc != null && sc.overall_score != null)
  if (scored.length === 0) return null
  return Math.round(scored.reduce((sum, sc) => sum + sc.overall_score, 0) / scored.length)
}

export interface GoalChip {
  Icon: ComponentType<IconProps> | null
  color: string
  label: string
}

const GOAL_METRIC_VALUE: Record<GoalMetric, (a: Activity) => number> = {
  distance_km: a => a.distance_km ?? 0,
  time_hours: a => (a.moving_time ?? 0) / 3600,
  activities: () => 1,
  elevation_m: a => a.total_elevation_gain ?? 0,
}

export interface WeekSummary {
  totalKm: number
  timeStr: string
  plannedKm: number
  /** False for a week with nothing logged or planned — its totals row is noise. */
  hasContent: boolean
  goals: (Goal & { current_value: number; percentage: number })[]
}

export interface WeekRow {
  monday: string
  days: Date[]
  summary: WeekSummary | undefined
}

/** A planned session's targets, in the same order and colors as the goal cards
 *  in the session modal. */
export function sessionGoalChips(s: TrainingSession): GoalChip[] {
  const chips: GoalChip[] = []
  const hasSegments = Array.isArray(s.segments) && s.segments.length > 0
  // Distance auto-derived from segments would just restate the workout below it.
  const add = (goal: SessionGoalKey, label: string) => {
    const { color, Icon } = SESSION_GOALS[goal]
    chips.push({ Icon, color, label })
  }
  if (s.planned_distance_km != null && !hasSegments) add('distance', formatDist(s.planned_distance_km, s.sport_type))
  if (s.planned_duration_mins != null) add('duration', `${s.planned_duration_mins} min`)
  const useSpeed = isSpeedSport(s.sport_type)
  const paceUnit = getPaceUnit(s.sport_type)
  if (s.target_avg_pace != null) add('avg_pace', `${formatPace(s.target_avg_pace, useSpeed)} ${paceUnit}`)
  if (s.target_pace_min != null || s.target_pace_max != null) {
    const isPace = paceUnit === 'min/km'
    const parts: string[] = []
    if (s.target_pace_min != null) parts.push(`${isPace ? 'fastest' : 'min'} ${formatPace(s.target_pace_min, useSpeed)}`)
    if (s.target_pace_max != null) parts.push(`${isPace ? 'slowest' : 'max'} ${formatPace(s.target_pace_max, useSpeed)}`)
    add('pace_range', `${parts.join(' – ')} ${paceUnit}`)
  }
  if (s.target_hr_zone != null) add('hr_zone', `Zone ${s.target_hr_zone} @ ${s.target_zone_pct ?? 80}%`)
  return chips
}

/** Totals and weekly-goal progress for each week row of `days`, keyed by the index of its Monday. */
export function buildWeekSummaries(
  days: Date[],
  activityMap: Record<string, Activity[]>,
  sessionMap: Record<string, TrainingSession[]>,
  yearGoals: Goal[] | undefined,
  showSport: (sport: string) => boolean,
): Record<number, WeekSummary> {
  const summaries: Record<number, WeekSummary> = {}
  // A filtered-out sport's goal would sit at a permanent 0% — drop it rather
  // than report progress against activities the grid is hiding.
  const weeklyGoals = (yearGoals ?? []).filter(
    g => g.period === 'weekly' && (g.sport_type === '__all__' || showSport(g.sport_type)),
  )
  for (let idx = 0; idx < days.length; idx += 7) {
    const weekDays = days.slice(idx, idx + 7)
    let totalKm = 0
    let totalSec = 0
    let plannedKm = 0
    for (const wd of weekDays) {
      const dateStr = format(wd, 'yyyy-MM-dd')
      const acts = activityMap[dateStr] || []
      for (const a of acts) {
        totalKm += a.distance_km ?? 0
        totalSec += a.moving_time ?? 0
      }
      for (const s of sessionMap[dateStr] || []) {
        plannedKm += s.planned_distance_km ?? 0
      }
    }
    const goals = weeklyGoals.map(g => {
      let current = 0
      for (const wd of weekDays) {
        const acts = activityMap[format(wd, 'yyyy-MM-dd')] || []
        for (const a of acts) {
          if (g.sport_type !== '__all__' && a.sport_type !== g.sport_type) continue
          current += GOAL_METRIC_VALUE[g.metric](a)
        }
      }
      const target = g.target_value
      const pct = target > 0 ? (current / target) * 100 : 0
      return { ...g, current_value: current, percentage: pct }
    })
    summaries[idx] = {
      totalKm,
      timeStr: formatDurationHM(totalSec),
      plannedKm,
      hasContent: totalSec > 0 || totalKm > 0 || plannedKm > 0,
      goals,
    }
  }
  return summaries
}

export interface DayDropProps {
  onDragOver: (e: ReactDragEvent) => void
  onDragLeave: () => void
  onDrop: (e: ReactDragEvent) => void
}

/** What the month grid and the week view share: the range's items by day, and drag & drop. */
export interface CalendarGridProps {
  activityMap: Record<string, Activity[]>
  sessionMap: Record<string, TrainingSession[]>
  raceMap: Record<string, RaceEvent[]>
  scores: SessionScoresResponse | undefined
  dragOverDate: string | null
  draggingSessionId: number | null
  dayDropProps: (dateStr: string, day: Date) => DayDropProps
  onOpenDay: (dateStr: string) => void
  onSessionDragStart: (e: ReactDragEvent, session: TrainingSession) => void
  onSessionDragEnd: () => void
  onRaceDragStart: (e: ReactDragEvent, race: RaceEvent) => void
}

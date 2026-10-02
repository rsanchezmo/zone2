import type { ComponentType } from 'react'
import { BoltIcon, DistanceIcon, HeartIcon, RangeIcon, TimerIcon, type IconProps } from '../components/icons'

export type SessionGoalKey = 'distance' | 'duration' | 'avg_pace' | 'pace_range' | 'hr_zone' | 'segments'

/** The targets a planned session can carry, in display order: the session
 *  editor's goal cards, the calendar's goal chips and the activity page's
 *  score breakdown all show them this way. */
export const SESSION_GOALS: Record<SessionGoalKey, { label: string; color: string; Icon: ComponentType<IconProps> | null }> = {
  distance: { label: 'Distance', color: '#3b82f6', Icon: DistanceIcon },
  duration: { label: 'Duration', color: '#22c55e', Icon: TimerIcon },
  avg_pace: { label: 'Avg Pace', color: '#f97316', Icon: BoltIcon },
  pace_range: { label: 'Pace Range', color: '#a855f7', Icon: RangeIcon },
  hr_zone: { label: 'HR Zone', color: '#ef4444', Icon: HeartIcon },
  segments: { label: 'Structured Workout', color: '#22d3ee', Icon: null },
}

export const SESSION_GOAL_KEYS = Object.keys(SESSION_GOALS) as SessionGoalKey[]

import type { Goal } from '../api/hooks'
import { getSportCategory } from './formatSpeed'

/** A goal bar's colour once the goal is met. */
export const GOAL_DONE_COLOR = '#22c55e'

/** A goal value in the unit it reads in: swim distances in metres, the rest rounded for display. */
export function goalAmount(goal: Pick<Goal, 'metric' | 'sport_type'>, value: number): { value: number; unit: string } {
  switch (goal.metric) {
    case 'distance_km':
      return getSportCategory(goal.sport_type) === 'swimming'
        ? { value: Math.round(value * 1000), unit: 'm' }
        : { value: Math.round(value * 10) / 10, unit: 'km' }
    case 'time_hours':
      return { value: Math.round(value * 10) / 10, unit: 'hrs' }
    case 'elevation_m':
      return { value: Math.round(value), unit: 'm' }
    case 'activities':
      return { value: Math.round(value), unit: '' }
  }
}

/** "45 / 100 m": progress towards a goal in its unit. */
export function formatGoalProgress(goal: Pick<Goal, 'metric' | 'sport_type' | 'target_value'>, current: number): string {
  const { unit } = goalAmount(goal, goal.target_value)
  return `${goalAmount(goal, current).value} / ${goalAmount(goal, goal.target_value).value}${unit ? ` ${unit}` : ''}`
}

import clsx from 'clsx'
import { getSportColor } from '../../constants/sportColors'
import { formatGoalProgress, GOAL_DONE_COLOR } from '../../utils/goals'
import GoalProgressBar from '../shared/GoalProgressBar'
import type { WeekSummary } from './calendar'

/** Week totals and weekly-goal progress, shared by the month grid's per-week
 *  divider and the week view's panel header. */
export default function WeekTotals({ summary, className }: { summary: WeekSummary; className?: string }) {
  return (
    <div className={clsx('flex items-center flex-wrap gap-x-3 gap-y-1', className)}>
      {summary.goals.map(g => {
        const color = getSportColor(g.sport_type)
        const complete = g.percentage >= 100
        return (
          <div
            key={g.id}
            className="flex items-center gap-1"
            title={`${g.sport_type === '__all__' ? 'All' : g.sport_type} ${g.metric.replace('_', ' ')}: ${formatGoalProgress(g, g.current_value)} (${g.percentage.toFixed(0)}%)`}
          >
            <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
            <GoalProgressBar percentage={g.percentage} color={color} className="w-16 h-1.5" />
            <span className="text-[9px] font-mono" style={{ color: complete ? GOAL_DONE_COLOR : '#6b7280' }}>
              {g.percentage.toFixed(0)}%
            </span>
          </div>
        )
      })}
      <span className="text-[10px] text-gray-500 font-mono tabular-nums">{summary.totalKm.toFixed(1)} km</span>
      <span className="text-[10px] text-gray-500 font-mono tabular-nums">{summary.timeStr}</span>
      {summary.plannedKm > 0 && (
        <span className="text-[10px] text-gray-500 font-mono tabular-nums opacity-70">
          plan {summary.plannedKm.toFixed(1)} km
        </span>
      )}
    </div>
  )
}

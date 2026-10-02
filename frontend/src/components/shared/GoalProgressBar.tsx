import clsx from 'clsx'
import { useTheme } from '../../hooks/useTheme'
import { GOAL_DONE_COLOR } from '../../utils/goals'

/** A goal's progress bar: its sport colour until the goal is met, green after.
 *  `className` sets the track's size. */
export default function GoalProgressBar({ percentage, color, className }: {
  percentage: number
  color: string
  className?: string
}) {
  const { theme } = useTheme()
  return (
    <div className={clsx('rounded-full overflow-hidden', theme === 'light' ? 'bg-gray-200' : 'bg-surface-700', className)}>
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{ width: `${Math.min(percentage, 100)}%`, backgroundColor: percentage >= 100 ? GOAL_DONE_COLOR : color }}
      />
    </div>
  )
}

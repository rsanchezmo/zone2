import clsx from 'clsx'
import { useTheme } from '../../hooks/useTheme'
import { COACH } from './colors'

/** The plan's first word ("Sub-50" for "Sub-50 10K"), for a tag in a month cell. */
function shortName(name: string): string {
  return name.trim().split(/\s+/)[0].slice(0, 10)
}

/** Marks a planned session that belongs to one of the coach's plans, in the coach's teal. */
export default function PlanTag({ name, short = false, className }: { name: string; short?: boolean; className?: string }) {
  const { theme } = useTheme()
  const color = theme === 'light' ? COACH.light : COACH.dark
  return (
    <span
      className={clsx('shrink-0 rounded font-medium leading-none whitespace-nowrap',
        short ? 'text-[9px] px-1 py-[2px]' : 'text-[10px] px-1.5 py-[3px]', className)}
      style={{ color, backgroundColor: `${color}1f` }}
      title={`Part of the ${name} plan`}
    >
      {short ? shortName(name) : name}
    </span>
  )
}

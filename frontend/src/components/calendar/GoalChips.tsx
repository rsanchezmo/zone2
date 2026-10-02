import clsx from 'clsx'
import type { GoalChip } from './calendar'

export default function GoalChips({ chips, className }: { chips: GoalChip[]; className?: string }) {
  if (chips.length === 0) return null
  return (
    <div className={clsx('flex flex-wrap gap-1.5', className)}>
      {chips.map((g, i) => (
        <span
          key={i}
          className="text-[11px] rounded-full px-2 py-0.5 border font-mono tabular-nums inline-flex items-center gap-1.5"
          style={{ color: g.color, borderColor: `${g.color}40`, backgroundColor: `${g.color}10` }}
        >
          {g.Icon && <g.Icon size={10} />} {g.label}
        </span>
      ))}
    </div>
  )
}

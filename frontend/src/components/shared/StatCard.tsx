import clsx from 'clsx'
import { useTheme } from '../../hooks/useTheme'

interface StatCardProps {
  label: string
  value: string | number
  unit?: string
  delta?: number | string | null
  sublabel?: string
  color?: string
}

export default function StatCard({ label, value, unit, delta, sublabel, color }: StatCardProps) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  return (
    <div className={clsx('rounded-xl p-4 border', isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600')}>
      <div className={clsx('text-xs uppercase tracking-wider mb-1', isLight ? 'text-gray-500' : 'text-gray-500')}>{label}</div>
      <div className={clsx('text-2xl font-bold', color ?? (isLight ? 'text-gray-900' : 'text-gray-100'))}>
        {value}
        {unit && <span className={clsx('text-sm ml-1', isLight ? 'text-gray-400' : 'text-gray-400')}>{unit}</span>}
      </div>
      {delta !== undefined && delta !== null && (
        <div className={clsx('text-xs mt-1',
          delta === 'new' ? 'text-green-400' : (delta as number) >= 0 ? 'text-green-400' : 'text-red-400'
        )}>
          {delta === 'new' ? <span className="inline-block w-2 h-2 rounded-full bg-green-400" /> : `${(delta as number) >= 0 ? '+' : ''}${(delta as number).toFixed(1)}%`}
        </div>
      )}
      {sublabel && <div className="text-[11px] text-gray-500 mt-1">{sublabel}</div>}
    </div>
  )
}

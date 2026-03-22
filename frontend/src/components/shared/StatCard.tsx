import clsx from 'clsx'
import { useTheme } from '../../hooks/useTheme'

interface StatCardProps {
  label: string
  value: string | number
  unit?: string
  delta?: number | string | null
  sublabel?: string
  color?: string
  tooltip?: string
  loading?: boolean
  accent?: string
}

export default function StatCard({ label, value, unit, delta, sublabel, color, tooltip, loading, accent }: StatCardProps) {
  const { theme } = useTheme()
  const isLight = theme === 'light'

  if (loading) {
    return (
      <div className={clsx(
        'rounded-xl p-4 border animate-pulse',
        isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
      )}>
        <div className={clsx('h-3 w-16 rounded mb-3', isLight ? 'bg-gray-200' : 'bg-surface-700')} />
        <div className={clsx('h-7 w-24 rounded', isLight ? 'bg-gray-200' : 'bg-surface-700')} />
      </div>
    )
  }

  return (
    <div
      className={clsx(
        'rounded-xl p-4 border group relative overflow-hidden transition-all duration-200',
        isLight
          ? 'bg-white border-gray-200 hover:border-gray-300'
          : 'bg-surface-800 border-surface-600 hover:border-surface-500',
      )}
      style={accent ? {
        '--card-accent': accent,
        borderLeftWidth: 2,
        borderLeftColor: accent,
      } as React.CSSProperties : undefined}
      title={tooltip}
    >
      {/* Subtle accent glow on hover */}
      {accent && (
        <div
          className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none"
          style={{ background: `radial-gradient(ellipse at top left, ${accent}08, transparent 70%)` }}
        />
      )}
      <div className={clsx('text-[11px] uppercase tracking-wider mb-1.5 relative', isLight ? 'text-gray-500' : 'text-gray-500')}>{label}</div>
      <div className="flex items-baseline gap-2 relative">
        <div className={clsx('text-2xl font-bold tabular-nums tracking-tight', color ?? (isLight ? 'text-gray-900' : 'text-gray-100'))}>
          {value}
          {unit && <span className={clsx('text-sm ml-1 font-medium tracking-normal', isLight ? 'text-gray-400' : 'text-gray-500')}>{unit}</span>}
        </div>
        {delta !== undefined && delta !== null && (
          <span className={clsx(
            'text-[11px] font-semibold px-1.5 py-0.5 rounded-md',
            delta === 'new'
              ? (isLight ? 'bg-green-100 text-green-700' : 'bg-green-500/15 text-green-400')
              : (delta as number) >= 0
                ? (isLight ? 'bg-green-100 text-green-700' : 'bg-green-500/15 text-green-400')
                : (isLight ? 'bg-red-100 text-red-700' : 'bg-red-500/15 text-red-400'),
          )}>
            {delta === 'new' ? 'new' : `${(delta as number) >= 0 ? '+' : ''}${(delta as number).toFixed(1)}%`}
          </span>
        )}
      </div>
      {sublabel && <div className="text-[11px] text-gray-500 mt-1.5 relative">{sublabel}</div>}
    </div>
  )
}
